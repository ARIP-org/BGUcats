"""Demo exporter tests.

The page re-implements the decision policy in JavaScript so it can recompute
outcomes live. A mirror that drifts would show the user a policy the research
code does not use, so `TestJavaScriptMirror` runs both implementations on the
same randomised cases and requires them to agree exactly.
"""

import json
import random
import re
import shutil
import subprocess

import pytest

from catreid.decision import classify
from catreid.demo import TEMPLATE, default_thresholds, select_samples
from catreid.metrics import QueryOutcome


class TestTemplate:
    def test_has_exactly_one_data_placeholder(self):
        assert TEMPLATE.read_text().count("/*__DEMO_DATA__*/null") == 1

    def test_has_a_title_for_the_gallery(self):
        assert "<title>" in TEMPLATE.read_text()[:8192]


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
class TestJavaScriptMirror:
    def extract(self):
        source = TEMPLATE.read_text()
        decide = re.search(r"function decide\(.*?\n", source).group(0)
        start = source.index("function classify(")
        end = source.index("function scoreRange(")
        return decide + source[start:end]

    def test_classify_agrees_with_python(self):
        rng = random.Random(0)
        names = ["a", "b", "c", "d", "e", "f"]
        cases = []
        for _ in range(500):
            ranked = rng.sample(names, 5)
            truth = rng.choice(names)
            known = rng.random() < 0.7
            score = round(rng.random(), 3)
            accept = round(rng.uniform(0.3, 0.9), 3)
            new = round(rng.uniform(0.0, accept), 3)
            cases.append((truth, known, ranked, score, accept, new))

        js_rows = [
            {
                "t": truth,
                "k": known,
                "top": [[names.index(n), score] for n in ranked],
                "a": accept,
                "n": new,
            }
            for truth, known, ranked, score, accept, new in cases
        ]
        program = (
            f"const NAMES = {json.dumps(names)}; const K = 3;\n"
            + self.extract()
            + f"\nconst rows = {json.dumps(js_rows)};\n"
            "console.log(JSON.stringify(rows.map(r => classify(r, r.a, r.n))));"
        )
        result = subprocess.run(
            ["node", "-e", program], capture_output=True, text=True, check=True
        )
        js = json.loads(result.stdout)

        py = [
            classify(QueryOutcome(truth, known, tuple(ranked), score), accept, new)
            for truth, known, ranked, score, accept, new in cases
        ]
        mismatches = [
            (c, j, p) for c, j, p in zip(cases, js, py, strict=True) if j != p
        ]
        assert not mismatches, f"{len(mismatches)} disagreements, e.g. {mismatches[:3]}"


def row(truth, known, top_name, names):
    return {
        "t": truth,
        "k": known,
        "top": [[names.index(top_name), 0.5]],
        "_names": top_name,
    }


class TestSelectSamples:
    names = ("a", "b", "c", "d")

    def rows(self):
        emb, rr = [], []
        # known queries: fixed, broke, both right, both wrong — for each identity
        for name in ["a", "b", "c"]:
            other = "d"
            emb.append(row(name, True, other, self.names))
            rr.append(row(name, True, name, self.names))  # rerank fixed it
            emb.append(row(name, True, name, self.names))
            rr.append(row(name, True, other, self.names))  # rerank broke it
            emb.append(row(name, True, name, self.names))
            rr.append(row(name, True, name, self.names))  # both right
        emb.append(row("ghost", False, "a", self.names))
        rr.append(row("ghost", False, "a", self.names))
        return emb, rr

    def test_fixed_cases_come_first(self):
        emb, rr = self.rows()
        chosen = select_samples(emb, rr, n=40, seed=0)
        assert chosen[0][1] == "rerank fixed it"

    def test_every_bucket_is_labelled(self):
        emb, rr = self.rows()
        buckets = {b for _, b in select_samples(emb, rr, n=40, seed=0)}
        assert {
            "rerank fixed it",
            "rerank broke it",
            "both right",
            "new animal",
        } <= buckets

    def test_spreads_across_identities(self):
        emb, rr = self.rows()
        chosen = select_samples(emb, rr, n=40, seed=0)
        fixed = [emb[q]["t"] for q, b in chosen if b == "rerank fixed it"]
        assert len(set(fixed)) == len(fixed)

    def test_respects_the_limit(self):
        emb, rr = self.rows()
        assert len(select_samples(emb, rr, n=3, seed=0)) == 3

    def test_deterministic(self):
        emb, rr = self.rows()
        assert select_samples(emb, rr, seed=4) == select_samples(emb, rr, seed=4)


class TestDefaultThresholds:
    def test_new_sits_at_or_below_accept(self):
        outcomes = [QueryOutcome("a", True, ("a",), 0.9)] + [
            QueryOutcome(f"g{i}", False, ("a",), 0.1 + i * 0.05) for i in range(6)
        ]
        t = default_thresholds(outcomes, min_baus=0.9)
        assert t["new"] <= t["accept"]

    def test_new_is_the_median_stranger_score(self):
        outcomes = [QueryOutcome("a", True, ("a",), 0.99)] + [
            QueryOutcome(f"g{i}", False, ("a",), s)
            for i, s in enumerate([0.1, 0.2, 0.3])
        ]
        t = default_thresholds(outcomes, min_baus=0.5)
        assert t["new"] == pytest.approx(0.2)
