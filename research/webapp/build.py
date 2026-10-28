"""Assemble the Spotter web MVP into a folder that any static host can serve.

    python research/webapp/build.py \
        --model research/runs/browser/megadescriptor-t-224-int8.onnx \
        --report research/runs/browser/export-report.json \
        --out research/runs/webapp

Output (gitignored — it holds model weights):

    index.html            the page as an artifact fragment (title + body)
    standalone.html       the same page wrapped in a full document, for S3/Pages
    ort-wasm-simd.wasm    ONNX Runtime Web, pinned to the version the page loads
    ort-wasm.wasm         non-SIMD fallback for old browsers
    model/part-N.bin      the int8 ONNX graph in chunks (hosts cap single files);
                          with --base64, model/part-N.txt instead, for hosts
                          that refuse arbitrary binary types (claude.ai artifacts)
    model/manifest.json   parts, byte count, sha256, open-set thresholds

Nothing here talks to AWS. The two wasm files are fetched once from jsdelivr
and cached under research/.cache/.
"""

import argparse
import base64
import hashlib
import json
import shutil
import urllib.request
from pathlib import Path

ORT_VERSION = "1.17.3"  # must match the <script src> in index.html
ORT_FILES = ("ort-wasm-simd.wasm", "ort-wasm.wasm")
PART_BYTES = 12 * 1024 * 1024
# base64 grows data by 4/3; 9 MiB of model stays under a 16 MB text-file cap
BASE64_PART_BYTES = 9 * 1024 * 1024

HERE = Path(__file__).resolve().parent
CACHE = HERE.parent / ".cache" / f"onnxruntime-web-{ORT_VERSION}"

STANDALONE_HEAD = (
    "<!doctype html><html><head><meta charset=utf-8>"
    '<meta name=viewport content="width=device-width,initial-scale=1,viewport-fit=cover">'
    "<style>*,*::before,*::after{box-sizing:border-box}body{margin:0}</style>"
    "</head><body>"
)


def fetch_runtime(name):
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / name
    if not path.exists():
        url = f"https://cdn.jsdelivr.net/npm/onnxruntime-web@{ORT_VERSION}/dist/{name}"
        with urllib.request.urlopen(url) as response:
            path.write_bytes(response.read())
    return path


def split_model(model, out_dir, as_base64):
    data = model.read_bytes()
    size = BASE64_PART_BYTES if as_base64 else PART_BYTES
    parts = []
    for i, start in enumerate(range(0, len(data), size)):
        chunk = data[start : start + size]
        if as_base64:
            name = f"part-{i}.txt"
            (out_dir / name).write_bytes(base64.b64encode(chunk))
        else:
            name = f"part-{i}.bin"
            (out_dir / name).write_bytes(chunk)
        parts.append(f"model/{name}")
    return data, parts


def build(model, report, out, as_base64=False):
    if out.exists():
        shutil.rmtree(out)
    (out / "model").mkdir(parents=True)

    page = (HERE / "index.html").read_text()
    (out / "index.html").write_text(page)
    (out / "standalone.html").write_text(STANDALONE_HEAD + page + "</body></html>")

    for name in ORT_FILES:
        shutil.copy(fetch_runtime(name), out / name)

    data, parts = split_model(model, out / "model", as_base64)
    exported = json.loads(report.read_text())
    recognition = exported["recognition"]["int8"]
    manifest = {
        "model": f"MegaDescriptor-{exported['model']} (int8, zero-shot)",
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "parts": parts,
        "encoding": "base64" if as_base64 else "binary",
        "thresholds": exported["suggested_thresholds"],
        "thresholdsNote": (
            "Calibrated on held-out polar bear identities (PolarBearVidID), "
            f"BAUS {recognition['baus']:.2f}. Public-data numbers, not BGU accuracy."
        ),
    }
    (out / "model" / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=Path("research/runs/webapp"))
    parser.add_argument(
        "--base64", action="store_true", help="ship model chunks as base64 text"
    )
    args = parser.parse_args()

    manifest = build(args.model, args.report, args.out, args.base64)
    print(json.dumps({k: v for k, v in manifest.items() if k != "parts"}, indent=2))
    for path in sorted(args.out.rglob("*")):
        if path.is_file():
            print(f"{path.stat().st_size / 1e6:8.2f} MB  {path.relative_to(args.out)}")


if __name__ == "__main__":
    main()
