"""Local-feature rerank: ALIKED keypoints + LightGlue matching over the top-N.

The addendum calls this the highest-value trick available, for one reason: it
needs no labels. It matches keypoints between the query and each shortlisted
template and rewards geometric agreement — coat patterns are keypoint-rich.
It is too slow for the whole gallery, so it only ever reranks the embedding's
top-N templates.

Two guards are built in, because local features are *more* exposed to the
background trap than global embeddings are, not less:

* **Only matches with both endpoints on the animal count** (`foreground_only`).
  Rock and grass are texture-rich; white fur is nearly featureless. Without the
  guard, two crops of one enclosure match each other far better than two crops
  of one animal do.

* **An image with no detected animal contributes no countable matches.** It
  cannot be verified, so it cannot promote a candidate.

Scores are fused, not replaced. The match count is squashed into [0, 1) and
blended with cosine similarity, and the threshold is recalibrated on the fused
score — so an embedding that is already confident is not overruled by a
handful of keypoints, and the open-set floor still holds.

The ranking and fusion functions are pure and tested without torch; only
`LocalMatcher` needs the stack.
"""

import logging
from dataclasses import dataclass

import numpy as np

from catreid.metrics import rank_identities

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RerankConfig:
    # Templates reranked per query — the addendum's "ANN top-50".
    top_n: int = 50
    # Share of the fused score given to local-feature evidence.
    weight: float = 0.5
    # Matches at which the match score reaches 0.5. Cross-session matches on
    # white fur run in single digits, so this is set where they live.
    saturation: float = 10.0
    foreground_only: bool = True

    def describe(self):
        guard = "animal-only matches" if self.foreground_only else "all matches"
        return (
            f"top-{self.top_n}, weight {self.weight}, "
            f"saturation {self.saturation:g}, {guard}"
        )


# --- pure ---------------------------------------------------------------------


def match_score(matches, saturation):
    """Squash a match count into [0, 1): n / (n + saturation).

    Saturating rather than linear, so ten extra matches matter a lot at the low
    end and little at the high end — where the extra matches are usually one
    textured patch matched many times over.
    """
    if saturation <= 0:
        raise ValueError("saturation must be positive")
    matches = max(0.0, float(matches))
    return matches / (matches + saturation)


def fuse(cosine, local, weight):
    if not 0.0 <= weight <= 1.0:
        raise ValueError(f"weight must be in [0, 1], got {weight}")
    return (1.0 - weight) * float(cosine) + weight * float(local)


def top_templates(similarities, n):
    """Indices of the n most similar templates, best first; ties by index."""
    similarities = np.asarray(similarities, dtype=float)
    n = min(n, len(similarities))
    # lexsort sorts by the last key first: descending score, then index.
    order = np.lexsort((np.arange(len(similarities)), -similarities))
    return order[:n].tolist()


def rerank_ranking(similarities, gallery_identities, match_counts, config):
    """Fused, identity-level ranking for one query.

    `match_counts` maps template index -> countable matches for the templates
    that were reranked. Every other template is fused with zero local evidence,
    which keeps all fused scores on one scale.
    """
    if len(similarities) != len(gallery_identities):
        raise ValueError("one similarity per gallery template is required")

    fused = [
        fuse(
            cosine,
            match_score(match_counts.get(index, 0), config.saturation),
            config.weight,
        )
        for index, cosine in enumerate(similarities)
    ]
    ranked, scores = rank_identities(gallery_identities, fused)
    return ranked, scores, fused


# --- needs torch --------------------------------------------------------------


@dataclass
class LocalFeatures:
    keypoints: np.ndarray  # (K, 2) x, y in pixels
    descriptors: object  # torch tensor (K, D)
    hw: tuple
    on_animal: np.ndarray  # (K,) bool


class LocalMatcher:
    """ALIKED + LightGlue, with per-image features computed once and kept."""

    def __init__(self, device="cpu"):
        import kornia.feature as KF

        self.device = device
        self._kf = KF
        self.extractor = KF.ALIKED.from_pretrained("aliked-n16", device=device).eval()
        self.matcher = KF.LightGlueMatcher("aliked").eval().to(device)
        self._cache = {}

    def features(self, path, mask):
        if path in self._cache:
            return self._cache[path]

        import torch
        import torchvision.transforms.functional as TF
        from PIL import Image

        from catreid.foreground import keypoints_on_mask

        image = TF.to_tensor(Image.open(path).convert("RGB"))[None].to(self.device)
        with torch.inference_mode():
            found = self.extractor(image)[0]
        keypoints = found.keypoints.cpu().numpy()
        features = LocalFeatures(
            keypoints=keypoints,
            descriptors=found.descriptors,
            hw=tuple(image.shape[-2:]),
            on_animal=keypoints_on_mask(keypoints, mask),
        )
        self._cache[path] = features
        return features

    def match(self, a, b):
        """(M, 2) array of matched keypoint index pairs."""
        import torch

        if len(a.keypoints) == 0 or len(b.keypoints) == 0:
            return np.zeros((0, 2), dtype=int)

        def lafs(features):
            centers = torch.as_tensor(features.keypoints, device=self.device)[None]
            scales = torch.ones(1, len(features.keypoints), 1, 1, device=self.device)
            return self._kf.laf_from_center_scale_ori(centers, scales)

        with torch.inference_mode():
            _, pairs = self.matcher(
                a.descriptors, b.descriptors, lafs(a), lafs(b), hw1=a.hw, hw2=b.hw
            )
        return pairs.cpu().numpy().astype(int)

    def count(self, a, b, foreground_only):
        """(all matches, matches with both endpoints on the animal, pairs)."""
        pairs = self.match(a, b)
        if len(pairs) == 0:
            return 0, 0, pairs
        on_both = a.on_animal[pairs[:, 0]] & b.on_animal[pairs[:, 1]]
        total, animal = len(pairs), int(on_both.sum())
        return total, (animal if foreground_only else total), pairs
