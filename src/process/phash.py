"""Perceptual hash, numpy-only.

This is the same construction as `imagehash.phash`, which follows
https://www.hackerfactor.com/blog/index.php?/archives/432-Looks-Like-It.html
— resize to 32x32 grayscale, 2D DCT-II, keep the low-frequency 8x8 corner,
threshold at its median, read out 64 bits.

Why reimplemented rather than imported: ImageHash reaches for
`scipy.fftpack.dct` to do that one DCT, and scipy plus PyWavelets add
~148MB to the deployment package — 239MB total against Lambda's hard
250MB limit. A DCT-II is a matrix multiply, so numpy does it in a few
lines and the package drops to ~91MB.

`tests/process/test_phash.py` asserts bit-identical output against
`imagehash.phash` (kept as a dev-only dependency) so this can't silently
drift from the reference.
"""

import numpy as np
from PIL import Image

HASH_SIZE = 8
HIGHFREQ_FACTOR = 4


def _dct_matrix(n):
    """Unnormalized DCT-II basis, matching scipy.fftpack.dct(..., norm=None).

    scipy computes y[k] = 2 * sum_n x[n] * cos(pi*k*(2n+1) / 2N), so the
    2D transform scipy.fftpack.dct(dct(x, axis=0), axis=1) is D @ x @ D.T.
    """
    k = np.arange(n).reshape(-1, 1)
    i = np.arange(n).reshape(1, -1)
    return 2.0 * np.cos(np.pi * k * (2 * i + 1) / (2 * n))


def phash(image, hash_size=HASH_SIZE, highfreq_factor=HIGHFREQ_FACTOR):
    """Return the 64-bit perceptual hash of a PIL image as a hex string."""
    size = hash_size * highfreq_factor
    grayscale = image.convert("L").resize((size, size), Image.Resampling.LANCZOS)
    pixels = np.asarray(grayscale, dtype=np.float64)

    basis = _dct_matrix(size)
    lowfreq = (basis @ pixels @ basis.T)[:hash_size, :hash_size]
    lowfreq = _snap_near_zero(lowfreq)

    bits = lowfreq > np.median(lowfreq)
    return _bits_to_hex(bits)


def _snap_near_zero(coefficients):
    """Zero out floating-point dust left by the matrix multiply.

    A flat image has exactly-zero AC coefficients in theory, and scipy's
    FFT-based DCT returns exactly zero. This matrix formulation instead
    leaves ~1e-11 residue. That is irrelevant to the values but decisive
    for the hash: the median is then also ~0, so `> median` reads pure
    noise and a plain grey image hashes differently every time its
    dimensions change.

    The threshold is relative to the largest coefficient, so it scales
    with image brightness. Real DCT coefficients are within a few orders
    of magnitude of the DC term; 1e-9 of it is far below any real signal
    and far above the residue.
    """
    scale = np.abs(coefficients).max()
    if scale == 0:
        return coefficients
    snapped = coefficients.copy()
    snapped[np.abs(snapped) < scale * 1e-9] = 0.0
    return snapped


def _bits_to_hex(bits):
    value = 0
    for bit in bits.flatten():
        value = (value << 1) | int(bit)
    width = bits.size // 4
    return f"{value:0{width}x}"


def hamming_distance(hex_a, hex_b):
    """Number of differing bits between two hex-encoded hashes."""
    return (int(hex_a, 16) ^ int(hex_b, 16)).bit_count()
