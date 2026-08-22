"""Holds src/process/phash.py bit-identical to the ImageHash reference.

This is the test that justifies not shipping ImageHash (and its 148MB of
scipy + PyWavelets) into the Lambda package. If the numpy DCT ever drifts
from scipy's, CI says so here.
"""

import imagehash
import numpy as np
import pytest
from PIL import Image

from process.phash import hamming_distance, phash


def _noise(seed, size=(400, 300)):
    rng = np.random.default_rng(seed)
    return Image.fromarray(rng.integers(0, 256, (*size[::-1], 3), dtype=np.uint8))


def _gradient(size=(320, 240)):
    w, h = size
    x = np.linspace(0, 255, w, dtype=np.uint8)
    return Image.fromarray(np.tile(x, (h, 1)))


def _photo_like(seed):
    """Smooth blobs — closer to a real photo's spectrum than pure noise."""
    rng = np.random.default_rng(seed)
    small = rng.integers(0, 256, (12, 16, 3), dtype=np.uint8)
    return Image.fromarray(small).resize((640, 480), Image.Resampling.BICUBIC)


IMAGES = [
    ("noise-1", _noise(1)),
    ("noise-2", _noise(2)),
    ("gradient", _gradient()),
    ("photo-like-1", _photo_like(10)),
    ("photo-like-2", _photo_like(11)),
    ("photo-like-3", _photo_like(12)),
    ("tiny", _noise(3, size=(40, 40))),
    ("wide", _noise(4, size=(800, 100))),
    ("tall", _noise(5, size=(100, 800))),
    ("solid", Image.new("RGB", (200, 200), (128, 128, 128))),
]


@pytest.mark.parametrize("name,image", IMAGES, ids=[n for n, _ in IMAGES])
def test_matches_imagehash_exactly(name, image):
    assert phash(image) == str(imagehash.phash(image))


@pytest.mark.parametrize("hash_size", [4, 8, 16])
def test_matches_imagehash_at_other_hash_sizes(hash_size):
    image = _photo_like(20)
    assert phash(image, hash_size=hash_size) == str(
        imagehash.phash(image, hash_size=hash_size)
    )


def test_hash_is_64_bits_as_16_hex_chars():
    assert len(phash(_photo_like(30))) == 16


def test_identical_images_have_distance_zero():
    image = _photo_like(40)
    assert hamming_distance(phash(image), phash(image.copy())) == 0


def test_recompression_is_a_near_duplicate_not_a_stranger():
    import io

    image = _photo_like(50)
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=60)
    recompressed = Image.open(io.BytesIO(buffer.getvalue()))
    assert hamming_distance(phash(image), phash(recompressed)) <= 5


def test_unrelated_images_are_far_apart():
    assert hamming_distance(phash(_noise(60)), phash(_noise(61))) > 5


# --- degenerate images -------------------------------------------------
# Flat and purely-linear images have exactly-zero AC coefficients, so the
# median sits on top of most of the values and the tiniest float residue
# decides every bit. The matrix-multiply DCT originally failed here while
# passing on all real photos; see _snap_near_zero in src/process/phash.py.


@pytest.mark.parametrize("value", [0, 64, 128, 200, 255])
def test_solid_colours_match_imagehash(value):
    image = Image.new("RGB", (200, 200), (value, value, value))
    assert phash(image) == str(imagehash.phash(image))


@pytest.mark.parametrize("size", [(32, 32), (200, 200), (641, 477), (1000, 50)])
def test_solid_colour_hashes_the_same_at_any_size(size):
    # Not just "matches the reference" — the hash must be stable, or two
    # photos of the same blank wall would look like different images.
    assert phash(Image.new("RGB", size, (128, 128, 128))) == "8000000000000000"


def test_gradients_match_imagehash():
    horizontal = _gradient()
    vertical = Image.fromarray(np.asarray(horizontal).T.copy())
    assert phash(horizontal) == str(imagehash.phash(horizontal))
    assert phash(vertical) == str(imagehash.phash(vertical))
