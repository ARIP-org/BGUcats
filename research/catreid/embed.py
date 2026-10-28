"""MegaDescriptor feature extraction.

The addendum's reasoning for this backbone over the spec's "zero-shot DINOv2":
MegaDescriptor is trained across ~30 animal re-ID datasets for individual
discrimination specifically, and its training mix already includes a cat
identity dataset. Published comparisons put a triplet head at +0.13 on
MegaDescriptor against +0.03 on DINOv2 — domain-specific pretraining matters
more than our own head does, and someone else already paid for it.

This is the only module in the package that needs torch, which is why the pure
evaluation logic lives elsewhere: splits and metrics are testable without
downloading a single weight.
"""

import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

# Variants trade accuracy for iteration speed. L-384 is the AnimalCLEF
# baseline and the one to quote; the smaller two exist so a pipeline change
# can be checked in minutes instead of hours.
VARIANTS = {
    "L-384": "hf-hub:BVRA/MegaDescriptor-L-384",
    "B-224": "hf-hub:BVRA/MegaDescriptor-B-224",
    "T-224": "hf-hub:BVRA/MegaDescriptor-T-224",
}
DEFAULT_VARIANT = "L-384"


@dataclass
class Embedder:
    name: str
    model: object
    transform: object
    device: str
    dim: int


def load_megadescriptor(variant=DEFAULT_VARIANT, device=None):
    """Load a MegaDescriptor backbone as a frozen feature extractor.

    `num_classes=0` in the published config means the classifier head is
    already removed and the model returns pooled features — there is no
    softmax over anyone else's animals to strip off, which is the shape we
    want permanently (CLAUDE.md: no softmax classifier, ever).
    """
    import timm
    import torch

    if variant not in VARIANTS:
        raise ValueError(f"unknown variant {variant!r}; try one of {sorted(VARIANTS)}")

    device = device or ("cuda" if torch.cuda.is_available() else "cpu")
    logger.info("loading MegaDescriptor-%s on %s", variant, device)

    model = timm.create_model(VARIANTS[variant], pretrained=True, num_classes=0)
    model = model.eval().to(device)

    config = timm.data.resolve_model_data_config(model)
    transform = timm.data.create_transform(**config, is_training=False)

    with torch.no_grad():
        probe = torch.zeros(1, *config["input_size"], device=device)
        dim = int(model(probe).shape[1])

    return Embedder(
        name=f"MegaDescriptor-{variant}",
        model=model,
        transform=transform,
        device=device,
        dim=dim,
    )


def embed_paths(embedder, paths, batch_size=16, progress_every=200, masks=None):
    """Embed images and L2-normalise, so a dot product is cosine similarity.

    Normalising here rather than at scoring time means every downstream
    similarity is directly comparable, which is what lets one threshold be
    calibrated and reused.

    With `masks` (path -> boolean mask or None), everything off the animal is
    filled with neutral grey before embedding. That is the ablation that asks
    whether the model recognises the animal or its enclosure.
    """
    import torch
    from PIL import Image

    from catreid.foreground import mask_background

    paths = list(paths)
    if not paths:
        raise ValueError("no paths to embed")

    vectors = []
    with torch.no_grad():
        for start in range(0, len(paths), batch_size):
            batch_paths = paths[start : start + batch_size]
            tensors = []
            for path in batch_paths:
                # Converted to RGB because a greyscale or palettised source
                # would otherwise arrive with the wrong channel count.
                image = Image.open(path).convert("RGB")
                if masks is not None:
                    image = Image.fromarray(
                        mask_background(np.asarray(image), masks.get(path))
                    )
                tensors.append(embedder.transform(image))
            batch = torch.stack(tensors).to(embedder.device)
            features = embedder.model(batch)
            features = torch.nn.functional.normalize(features, dim=1)
            vectors.append(features.cpu().numpy().astype(np.float32))

            done = start + len(batch_paths)
            if progress_every and done % progress_every < batch_size:
                logger.info("embedded %d/%d", done, len(paths))

    return np.concatenate(vectors, axis=0)


def embed_records(embedder, records, cache_dir=None, masks=None, **kwargs):
    """Embed records, reusing a cached matrix when the inputs are unchanged.

    Keyed on the model name, whether background was masked, and the exact
    ordered path list, so a cache hit cannot silently correspond to a different
    split, backbone, or preprocessing.
    """
    paths = [record.path for record in records]
    if cache_dir is None:
        return embed_paths(embedder, paths, masks=masks, **kwargs)

    tag = f"{embedder.name}-bgmasked" if masks is not None else embedder.name
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(("\n".join([tag, *paths])).encode("utf-8")).hexdigest()[:16]
    cache_path = cache_dir / f"{tag}-{len(paths)}-{digest}.npy"

    if cache_path.exists():
        logger.info("reusing cached embeddings %s", cache_path.name)
        return np.load(cache_path)

    vectors = embed_paths(embedder, paths, masks=masks, **kwargs)
    np.save(cache_path, vectors)
    logger.info("cached embeddings to %s", cache_path.name)
    return vectors


def cosine_similarity(queries, gallery):
    """(M, D) x (N, D) -> (M, N), assuming both are L2-normalised."""
    if queries.shape[1] != gallery.shape[1]:
        raise ValueError(
            f"dimension mismatch: queries {queries.shape}, gallery {gallery.shape}"
        )
    return queries @ gallery.T
