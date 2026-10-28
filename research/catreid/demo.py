"""Export an interactive "watch it decide" page from an experiment.

Writes one self-contained HTML file — data, thumbnails and match drawings
inlined — so it opens in any browser with no server, and can be regenerated
after any run. The page replays stored evidence; no model runs in it.

What it shows, per query: the candidates the system ranked, the score behind
each, the keypoint matches between the query and its top candidate (counted
matches on the animal drawn bright, ignored background matches drawn dim), and
the decision under the current thresholds. Two sliders move the accept and
new-animal thresholds, and the outcome counts across *every* query update
live — the decision policy from `catreid.decision`, mirrored in JavaScript.
"""

import base64
import io
import json
import logging
import random
from collections import defaultdict
from pathlib import Path

import numpy as np

from catreid.decision import PICK_K
from catreid.metrics import choose_threshold, rank_identities
from catreid.rerank import rerank_ranking

logger = logging.getLogger(__name__)

TEMPLATE = Path(__file__).with_name("demo_template.html")
TOP_K = 5
SKELETON = (
    '<!doctype html><html lang="en"><head><meta charset="utf-8">'
    '<meta name="viewport" content="width=device-width,initial-scale=1,'
    'viewport-fit=cover"></head><body>{body}</body></html>'
)


def _template_scores(evidence, q, config):
    """Per-template score for one query in one mode."""
    row = evidence.sims[q]
    if config is None:
        return np.asarray(row, dtype=float)
    source = evidence.animal if config.foreground_only else evidence.total
    limit = min(config.top_n, evidence.top.shape[1])
    counts = {int(evidence.top[q, j]): int(source[q, j]) for j in range(limit)}
    _, _, fused = rerank_ranking(row, [None] * len(row), counts, config)
    return np.asarray(fused, dtype=float)


def mode_view(evidence, identities, queries, known, config):
    """Ranking, best template per identity, and outcome for every query."""
    index_of = {name: i for i, name in enumerate(sorted(set(identities)))}
    rows, outcomes, best_templates = [], [], []
    from catreid.metrics import QueryOutcome

    for q, record in enumerate(queries):
        scores = _template_scores(evidence, q, config)
        ranked, ranked_scores = rank_identities(identities, scores)
        best = {}
        for t, name in enumerate(identities):
            if name not in best or scores[t] > scores[best[name]]:
                best[name] = t
        rows.append(
            {
                "t": record.identity,
                "k": record.identity in known,
                "top": [
                    [index_of[name], round(float(score), 4)]
                    for name, score in zip(
                        ranked[:TOP_K], ranked_scores[:TOP_K], strict=True
                    )
                ],
            }
        )
        best_templates.append(best)
        outcomes.append(
            QueryOutcome(
                record.identity, record.identity in known, ranked, ranked_scores[0]
            )
        )
    return rows, outcomes, best_templates, index_of


def default_thresholds(outcomes, min_baus):
    """Accept at the calibrated open-set floor; flag 'new' below the median
    stranger score, so half of unseen animals are called new outright and the
    rest go to a human as "none of these"."""
    accept = choose_threshold(outcomes, min_baus=min_baus)
    strangers = sorted(o.top_score for o in outcomes if not o.is_known)
    new = min(float(np.median(strangers)), accept) if strangers else accept
    return {"accept": round(float(accept), 4), "new": round(float(new), 4)}


def select_samples(embedding_rows, rerank_rows, n=40, seed=0):
    """A spread of instructive queries, varied across identities.

    The cases where local matching changed the answer — fixed or broke it —
    are the most informative, so they are taken first; then correct and wrong
    answers from both modes, then new animals.
    """
    buckets = defaultdict(list)
    for q, (e, r) in enumerate(zip(embedding_rows, rerank_rows, strict=True)):
        if not e["k"]:
            buckets["new animal"].append(q)
            continue
        buckets[_known_bucket(e["t"], e["_names"], r["_names"])].append(q)

    quota = [
        ("rerank fixed it", 8),
        ("rerank broke it", 4),
        ("both right", 10),
        ("both wrong", 6),
        ("new animal", 12),
    ]
    rng = random.Random(seed)
    chosen = []
    for bucket, count in quota:
        pool = buckets.get(bucket, [])
        rng.shuffle(pool)
        # Round-robin over identities so one animal does not fill the bucket.
        by_identity = defaultdict(list)
        for q in pool:
            by_identity[embedding_rows[q]["t"]].append(q)
        picked = []
        while len(picked) < count and any(by_identity.values()):
            for name in sorted(by_identity):
                if by_identity[name] and len(picked) < count:
                    picked.append(by_identity[name].pop())
        chosen += [(q, bucket) for q in picked]
    return chosen[:n]


def _known_bucket(truth, embedding_top, rerank_top):
    right = (embedding_top == truth, rerank_top == truth)
    if not right[0] and right[1]:
        return "rerank fixed it"
    if right[0] and not right[1]:
        return "rerank broke it"
    return "both right" if all(right) else "both wrong"


def _jpeg(image, quality=80):
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=quality)
    return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode()


def draw_matches(
    query_path, template_path, query_mask, template_mask, matcher, scale=1.5
):
    """Side-by-side query|template with matches drawn.

    Off-animal regions are darkened so the reader can see what counts.
    Matches with both ends on the animal are drawn bright and counted;
    the rest are drawn dim and ignored.
    """
    from PIL import Image, ImageDraw

    def prepared(path, mask):
        image = np.asarray(Image.open(path).convert("RGB")).astype(float)
        if mask is None:
            image *= 0.45
        else:
            image[~mask] *= 0.45
        return Image.fromarray(image.clip(0, 255).astype(np.uint8))

    left, right = (
        prepared(query_path, query_mask),
        prepared(template_path, template_mask),
    )
    width, height = left.width + 8 + right.width, max(left.height, right.height)
    canvas = Image.new("RGB", (width, height), (18, 22, 28))
    canvas.paste(left, (0, 0))
    offset = left.width + 8
    canvas.paste(right, (offset, 0))
    canvas = canvas.resize((int(width * scale), int(height * scale)))
    draw = ImageDraw.Draw(canvas)

    qf = matcher.features(query_path, query_mask)
    tf = matcher.features(template_path, template_mask)
    pairs = matcher.match(qf, tf)
    counted = 0
    for a, b in pairs:
        on_animal = bool(qf.on_animal[a] and tf.on_animal[b])
        x1, y1 = qf.keypoints[a] * scale
        x2, y2 = (tf.keypoints[b] + [offset, 0]) * scale
        if on_animal:
            counted += 1
            draw.line([(x1, y1), (x2, y2)], fill=(255, 196, 64), width=2)
            for x, y in ((x1, y1), (x2, y2)):
                draw.ellipse([x - 3, y - 3, x + 3, y + 3], fill=(255, 196, 64))
        else:
            draw.line([(x1, y1), (x2, y2)], fill=(120, 130, 140), width=1)
    return _jpeg(canvas, quality=78), len(pairs), counted


def export(
    path,
    *,
    gallery,
    queries,
    known,
    evidence,
    masks,
    matcher,
    config,
    min_baus,
    meta,
    n_samples=40,
    seed=0,
    standalone=False,
):
    identities = [r.identity for r in gallery]
    modes = {}
    for name, cfg in (("embedding", None), ("rerank", config)):
        rows, outcomes, best, index_of = mode_view(
            evidence, identities, queries, known, cfg
        )
        names = sorted(index_of, key=index_of.get)
        for row in rows:
            row["_names"] = names[row["top"][0][0]]
        modes[name] = {
            "rows": rows,
            "best": best,
            "thresholds": default_thresholds(outcomes, min_baus),
        }
    names = sorted(set(identities))

    images = {}

    def image_key(p):
        if p not in images:
            from PIL import Image

            images[p] = _jpeg(Image.open(p).convert("RGB"), quality=80)
        return p

    samples = []
    for q, bucket in select_samples(
        modes["embedding"]["rows"], modes["rerank"]["rows"], n_samples, seed
    ):
        query = queries[q]
        sample = {"q": q, "img": image_key(query.path), "bucket": bucket, "modes": {}}
        for mode_name, mode in modes.items():
            row = mode["rows"][q]
            cands = []
            for name_index, score in row["top"]:
                name = names[name_index]
                t = mode["best"][q][name]
                j = np.where(evidence.top[q] == t)[0]
                shortlisted = len(j) > 0
                cands.append(
                    {
                        "i": name_index,
                        "s": score,
                        "img": image_key(gallery[t].path),
                        "cos": round(float(evidence.sims[q, t]), 4),
                        "m_all": int(evidence.total[q, j[0]]) if shortlisted else None,
                        "m_animal": int(evidence.animal[q, j[0]])
                        if shortlisted
                        else None,
                    }
                )
            top_template = mode["best"][q][names[row["top"][0][0]]]
            viz, n_all, n_counted = draw_matches(
                query.path,
                gallery[top_template].path,
                masks.get(query.path),
                masks.get(gallery[top_template].path),
                matcher,
            )
            sample["modes"][mode_name] = {
                "cands": cands,
                "viz": viz,
                "viz_all": n_all,
                "viz_counted": n_counted,
            }
        samples.append(sample)
        logger.info("demo sample %d/%d", len(samples), n_samples)

    for mode in modes.values():
        mode.pop("best")
        for row in mode["rows"]:
            row.pop("_names")

    data = {
        "meta": {**meta, "pick_k": PICK_K},
        "names": names,
        "images": images,
        "modes": modes,
        "samples": samples,
    }
    page = TEMPLATE.read_text().replace(
        "/*__DEMO_DATA__*/null", json.dumps(data, separators=(",", ":"))
    )
    if standalone:
        page = SKELETON.format(body=page)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(page)
    size_mb = len(page.encode()) / 2**20
    logger.info("wrote demo %s (%.1f MB, %d samples)", path, size_mb, len(samples))
    return path
