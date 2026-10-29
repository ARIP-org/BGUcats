"""Foreground helpers.

The behaviour that matters is conservatism: when there is no mask, nothing is
counted as being on the animal, because an unverifiable keypoint must never be
able to promote a candidate.
"""

import numpy as np
import pytest

from catreid.foreground import (
    BACKGROUND_FILL,
    _unpack,
    coverage,
    keypoints_on_mask,
    mask_background,
    masks_for_paths,
)


def square_mask(height=10, width=20, box=(2, 5, 8, 15)):
    """True inside rows box[0]:box[1], cols box[2]:box[3]."""
    mask = np.zeros((height, width), dtype=bool)
    mask[box[0] : box[1], box[2] : box[3]] = True
    return mask


class TestKeypointsOnMask:
    def test_inside_and_outside(self):
        mask = square_mask()
        # (x, y): x is the column, y the row
        on = keypoints_on_mask([[10, 3], [1, 1], [14, 4]], mask)
        assert on.tolist() == [True, False, True]

    def test_no_mask_counts_nothing(self):
        assert keypoints_on_mask([[1, 1], [5, 5]], None).tolist() == [False, False]

    def test_out_of_bounds_is_clipped_not_an_error(self):
        mask = np.ones((4, 4), dtype=bool)
        assert keypoints_on_mask([[-3, 99]], mask).tolist() == [True]

    def test_subpixel_coordinates_round(self):
        mask = square_mask()
        assert keypoints_on_mask([[7.6, 2.4]], mask).tolist() == [True]

    def test_empty_keypoints(self):
        assert keypoints_on_mask(np.zeros((0, 2)), square_mask()).size == 0


class TestMaskBackground:
    def test_fills_only_the_background(self):
        image = np.full((10, 20, 3), 200, dtype=np.uint8)
        out = mask_background(image, square_mask())
        assert tuple(out[0, 0]) == BACKGROUND_FILL
        assert tuple(out[3, 10]) == (200, 200, 200)

    def test_does_not_mutate_its_input(self):
        image = np.full((10, 20, 3), 200, dtype=np.uint8)
        mask_background(image, square_mask())
        assert (image == 200).all()

    def test_no_mask_returns_the_image_unchanged(self):
        image = np.full((4, 4, 3), 9, dtype=np.uint8)
        assert (mask_background(image, None) == image).all()

    def test_shape_mismatch_is_an_error(self):
        with pytest.raises(ValueError, match="does not match"):
            mask_background(np.zeros((5, 5, 3)), np.ones((4, 4), dtype=bool))


class TestCoverage:
    def test_fraction_of_animal(self):
        assert coverage(np.array([[True, False], [False, False]])) == 0.25

    def test_no_mask_is_zero(self):
        assert coverage(None) == 0.0


class TestMaskCache:
    def test_round_trips_masks_and_misses(self, tmp_path):
        mask = square_mask()
        np.savez_compressed(
            tmp_path / "x.npz", packed=np.packbits(mask), shape=np.array(mask.shape)
        )
        np.savez_compressed(
            tmp_path / "y.npz", packed=np.zeros(0, np.uint8), shape=np.zeros(2)
        )
        assert (_unpack(np.load(tmp_path / "x.npz")) == mask).all()
        assert _unpack(np.load(tmp_path / "y.npz")) is None

    def test_uncached_path_without_a_segmenter_is_an_error(self, tmp_path):
        with pytest.raises(ValueError, match="no cached mask"):
            masks_for_paths(None, ["/nope.jpg"], tmp_path)
