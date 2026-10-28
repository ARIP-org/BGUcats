"""Export the recognition backbone for in-browser use, and prove it still works.

The phase-1b results are what make this possible at all: MegaDescriptor-T-224
(204 MB) recognised as well as L-384 (1.9 GB), so the small one is the one to
ship, and it is small enough to run on a phone.

What goes into the file, so the browser has as little to get wrong as possible:

* Normalisation is inside the graph. The page passes RGB in [0, 1]; a page that
  subtracted the wrong mean would produce embeddings that look fine and
  silently match nothing.
* L2-normalisation is inside the graph. A dot product in the page is then a
  cosine similarity, on the same scale the threshold was calibrated on.

Then it is shrunk with dynamic int8 quantisation (weights to 8 bits, ~4x
smaller) and checked twice: embedding agreement with the original PyTorch
model, and — the check that matters — recognition accuracy on the phase-1b
evaluation split, so "smaller" is not quietly "worse".

    PYTHONPATH=research python -m catreid.export --out research/runs/browser
"""

import argparse
import json
import logging
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

INPUT_SIZE = 224


class BrowserModel:
    """Built lazily so importing this module needs no torch."""

    @staticmethod
    def build(variant="T-224"):
        import timm
        import torch
        from torch import nn

        from catreid.embed import VARIANTS

        backbone = timm.create_model(VARIANTS[variant], pretrained=True, num_classes=0)
        config = timm.data.resolve_model_data_config(backbone)

        class Wrapped(nn.Module):
            def __init__(self):
                super().__init__()
                self.backbone = backbone
                self.register_buffer(
                    "mean", torch.tensor(config["mean"]).view(1, 3, 1, 1)
                )
                self.register_buffer(
                    "std", torch.tensor(config["std"]).view(1, 3, 1, 1)
                )

            def forward(self, image):
                features = self.backbone((image - self.mean) / self.std)
                return features / features.norm(dim=1, keepdim=True).clamp_min(1e-12)

        return Wrapped().eval(), config


def preprocess(path):
    """The exact pixels the page will produce: centre square, 224x224, [0,1].

    Deliberately what a browser canvas does (centre-crop the short side,
    bilinear resize), not timm's bicubic resize-then-crop. The model is checked
    against *this*, so the numbers below describe what the phone will see.
    """
    from PIL import Image

    image = Image.open(path).convert("RGB")
    w, h = image.size
    side = min(w, h)
    left, top = (w - side) // 2, (h - side) // 2
    image = image.crop((left, top, left + side, top + side)).resize(
        (INPUT_SIZE, INPUT_SIZE), Image.Resampling.BILINEAR
    )
    array = np.asarray(image, dtype=np.float32) / 255.0
    return array.transpose(2, 0, 1)[None]


def export(out_dir, variant="T-224", opset=17):
    import torch

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    model, _ = BrowserModel.build(variant)
    fp32 = out_dir / f"megadescriptor-{variant.lower()}-fp32.onnx"

    dummy = torch.rand(1, 3, INPUT_SIZE, INPUT_SIZE)
    torch.onnx.export(
        model,
        dummy,
        str(fp32),
        input_names=["image"],
        output_names=["embedding"],
        opset_version=opset,
        do_constant_folding=True,
        dynamo=False,
    )
    logger.info("exported %s (%.1f MB)", fp32.name, fp32.stat().st_size / 2**20)

    from onnxruntime.quantization import QuantType, quantize_dynamic

    int8 = out_dir / f"megadescriptor-{variant.lower()}-int8.onnx"
    # MatMul only. Quantising the patch-embedding Conv as well produces a
    # ConvInteger node, which the browser (WebAssembly) build of ONNX Runtime
    # does not implement — the session fails to load on the phone. That one
    # layer is tiny (4x4x3x96); every weight that matters for size is a MatMul.
    quantize_dynamic(
        str(fp32),
        str(int8),
        weight_type=QuantType.QInt8,
        op_types_to_quantize=["MatMul"],
    )
    logger.info("quantised %s (%.1f MB)", int8.name, int8.stat().st_size / 2**20)
    return model, fp32, int8


def onnx_embed(session, paths, batch=1):
    vectors = []
    for path in paths:
        out = session.run(["embedding"], {"image": preprocess(path)})[0]
        vectors.append(out[0])
    return np.stack(vectors).astype(np.float32)


def torch_embed(model, paths):
    import torch

    with torch.inference_mode():
        return np.stack(
            [model(torch.from_numpy(preprocess(p)))[0].numpy() for p in paths]
        ).astype(np.float32)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default="research/runs/browser")
    parser.add_argument("--variant", default="T-224")
    parser.add_argument("--dataset", default="PolarBearVidID")
    parser.add_argument("--root", default="research/data/PolarBearVidID")
    parser.add_argument("--agreement-images", type=int, default=40)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    import onnxruntime as ort

    from catreid.datasets import cap_sessions_per_identity, thin_frames_per_session
    from catreid.evaluate import build_outcomes, load_source
    from catreid.metrics import choose_threshold, evaluate_at_threshold
    from catreid.splits import open_set_split

    model, fp32, int8 = export(args.out, args.variant)
    sessions = {
        name: ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
        for name, path in (("fp32", fp32), ("int8", int8))
    }

    # The same split as the phase-1b diversity result (FINDINGS.md §2).
    source = thin_frames_per_session(
        cap_sessions_per_identity(load_source(args.dataset, args.root), 10, seed=0), 10
    )
    split = open_set_split(
        source.for_evaluation(),
        unknown_fraction=0.3,
        gallery_sessions_per_identity=3,
        seed=0,
    )
    gallery = list(split.gallery)
    queries = list(split.query_known) + list(split.query_unknown)

    sample = [r.path for r in queries[: args.agreement_images]]
    reference = torch_embed(model, sample)
    report = {"model": args.variant, "files": {}, "agreement": {}, "recognition": {}}
    for name, path in (("fp32", fp32), ("int8", int8)):
        report["files"][name] = {
            "file": path.name,
            "mb": round(path.stat().st_size / 2**20, 1),
        }
        got = onnx_embed(sessions[name], sample)
        cos = (got * reference).sum(axis=1)
        report["agreement"][name] = {
            "mean_cosine_vs_pytorch": round(float(cos.mean()), 5),
            "min_cosine_vs_pytorch": round(float(cos.min()), 5),
        }

    paths_g = [r.path for r in gallery]
    paths_q = [r.path for r in queries]
    for name in ("pytorch", "int8"):
        if name == "pytorch":
            g, q = torch_embed(model, paths_g), torch_embed(model, paths_q)
        else:
            g, q = (
                onnx_embed(sessions["int8"], paths_g),
                onnx_embed(sessions["int8"], paths_q),
            )
        outcomes = build_outcomes(gallery, g, queries, q, split.known_identities)
        threshold = choose_threshold(outcomes, min_baus=0.9)
        s = evaluate_at_threshold(outcomes, threshold)
        if name == "int8":
            # What the page ships with: accept at the open-set floor, and call
            # it a new animal below the median stranger score (catreid.demo).
            from catreid.demo import default_thresholds

            report["suggested_thresholds"] = default_thresholds(outcomes, min_baus=0.9)
        report["recognition"][name] = {
            "top1": round(s.top1_known, 4),
            "top5": round(s.top5_known, 4),
            "baks": round(s.baks, 4),
            "baus": round(s.baus, 4),
            "threshold": round(s.threshold, 4),
        }
        logger.info("%s: %s", name, report["recognition"][name])

    (Path(args.out) / "export-report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
