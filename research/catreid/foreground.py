"""Animal foreground masks — the "cat detector" stage of the pipeline.

Public re-ID crops are mostly not animal. On PolarBearVidID the bear covers
under half of a typical crop; the rest is rock, grass, water and enclosure
wall. That matters twice:

* **Local-feature matching finds texture, and rocks are texture-rich while
  white fur is nearly featureless.** Unguarded, the rerank step would match the
  enclosure and call it the animal — the "matching the wall, not the cat" trap
  from CLAUDE.md in a new form.

* **A global embedding can exploit background too.** If two clips of one
  animal share an enclosure, a model can score them as similar for reasons that
  have nothing to do with the animal. Masking the background and re-scoring is
  how we find out.

Segmentation uses torchvision's COCO Mask R-CNN. Any COCO animal class counts
as the subject, not only the expected one: a white bear is regularly read as
"sheep", and a campus cat will sometimes be read as "dog". The mask is still the
animal, which is all this stage needs. Crops are already one animal each, so the
single highest-scoring animal detection is taken.

The pure helpers at the bottom are numpy-only and tested without torch.
"""

import hashlib
import logging
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

ANIMAL_CLASSES = (
    "bird",
    "cat",
    "dog",
    "horse",
    "sheep",
    "cow",
    "elephant",
    "bear",
    "zebra",
    "giraffe",
)

# Low on purpose: missing the animal entirely is worse than a loose mask, and
# a detection is only ever used for its mask, never for its class label.
MIN_DETECTION_SCORE = 0.3

# Mask R-CNN upscales its input to min_size. The default (800) turns a
# 256x128 crop into a 1600x800 image and costs 3.5s per crop on CPU; 256
# keeps detection the same on this data at ~1.3s.
SEGMENTER_MIN_SIZE = 256

# Neutral fill for masked-out background — a mid grey, so it carries no
# texture or colour a model could latch onto.
BACKGROUND_FILL = (124, 124, 124)


def load_segmenter(device=None):
    import torch
    import torchvision

    device = device or ("cuda" if torch.cuda.is_available() else "cpu")
    weights = torchvision.models.detection.MaskRCNN_ResNet50_FPN_V2_Weights.DEFAULT
    model = torchvision.models.detection.maskrcnn_resnet50_fpn_v2(
        weights=weights,
        min_size=SEGMENTER_MIN_SIZE,
        max_size=SEGMENTER_MIN_SIZE * 2,
    )
    categories = weights.meta["categories"]
    animal_ids = {categories.index(name) for name in ANIMAL_CLASSES}
    model.eval().to(device)
    return {"model": model, "animal_ids": animal_ids, "device": device}


def segment(segmenter, path):
    """Boolean HxW mask of the animal in an image, or None if none was found."""
    import torch
    import torchvision.transforms.functional as TF
    from PIL import Image

    image = TF.to_tensor(Image.open(path).convert("RGB")).to(segmenter["device"])
    with torch.inference_mode():
        output = segmenter["model"]([image])[0]

    best = None
    for index, (label, score) in enumerate(
        zip(output["labels"].tolist(), output["scores"].tolist(), strict=True)
    ):
        is_animal = label in segmenter["animal_ids"] and score >= MIN_DETECTION_SCORE
        if is_animal and (best is None or score > best[1]):
            best = (index, score)
    if best is None:
        return None
    return (output["masks"][best[0], 0] > 0.5).cpu().numpy()


def _cache_path(cache_dir, path):
    digest = hashlib.sha256(str(path).encode("utf-8")).hexdigest()[:20]
    return Path(cache_dir) / f"{digest}.npz"


def masks_for_paths(segmenter, paths, cache_dir, progress_every=100):
    """path -> mask (or None), cached per image so any split can reuse it.

    Per-image rather than per-split caching because the segmenter is the
    slowest stage by far, and a new split or subsample should never pay for it
    twice. A "no animal found" result is cached too, as an empty array.
    """
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)

    masks, computed = {}, 0
    for index, path in enumerate(paths):
        cached = _cache_path(cache_dir, path)
        if cached.exists():
            data = np.load(cached)
            masks[path] = _unpack(data)
            continue

        if segmenter is None:
            raise ValueError(
                f"no cached mask for {path} and no segmenter to compute it"
            )
        mask = segment(segmenter, path)
        if mask is None:
            np.savez_compressed(cached, packed=np.zeros(0, np.uint8), shape=np.zeros(2))
        else:
            np.savez_compressed(
                cached, packed=np.packbits(mask), shape=np.array(mask.shape)
            )
        masks[path] = mask
        computed += 1
        if progress_every and computed % progress_every == 0:
            logger.info("segmented %d new (%d/%d)", computed, index + 1, len(paths))

    return masks


def _unpack(data):
    packed = data["packed"]
    if packed.size == 0:
        return None
    shape = tuple(int(v) for v in data["shape"])
    return np.unpackbits(packed)[: shape[0] * shape[1]].reshape(shape).astype(bool)


# --- pure helpers -----------------------------------------------------------


def keypoints_on_mask(keypoints_xy, mask):
    """Which (x, y) keypoints fall on the foreground. All False if no mask.

    No mask means we cannot verify that a keypoint is on the animal, so it is
    not counted. Conservative on purpose: an unverifiable match must not be
    able to promote a candidate.
    """
    keypoints_xy = np.asarray(keypoints_xy, dtype=float).reshape(-1, 2)
    if mask is None or keypoints_xy.size == 0:
        return np.zeros(len(keypoints_xy), dtype=bool)
    height, width = mask.shape
    xs = np.clip(np.round(keypoints_xy[:, 0]).astype(int), 0, width - 1)
    ys = np.clip(np.round(keypoints_xy[:, 1]).astype(int), 0, height - 1)
    return mask[ys, xs]


def mask_background(image_array, mask, fill=BACKGROUND_FILL):
    """Return a copy of an HxWx3 image with everything off the animal filled.

    If no animal was found the image is returned unchanged — and the caller is
    expected to count how often that happened, because an unmasked image in a
    "masked" run is a leak of exactly what the run is trying to remove.
    """
    image_array = np.asarray(image_array)
    if mask is None:
        return image_array.copy()
    if mask.shape != image_array.shape[:2]:
        raise ValueError(
            f"mask {mask.shape} does not match image {image_array.shape[:2]}"
        )
    out = image_array.copy()
    out[~mask] = fill
    return out


def coverage(mask):
    """Fraction of the image that is animal, or 0.0 when none was found."""
    if mask is None or mask.size == 0:
        return 0.0
    return float(mask.mean())
