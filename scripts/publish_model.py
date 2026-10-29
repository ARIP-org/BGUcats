"""Publish the recognition model to the admin app, where the browser runs it.

    python scripts/publish_model.py \
        --model research/runs/browser/megadescriptor-t-224-int8.onnx \
        --bucket bgucats-admin-web-<account>

The model is built by `catreid.export` (research/), never committed, so
Terraform cannot own these objects: a fresh checkout without the file would
plan to delete them. They live next to the Terraform-managed app files in the
web bucket, under a prefix nothing in Terraform touches:

    model/{version}/model.onnx            the int8 graph
    model/{version}/ort.wasm.min.js       ONNX Runtime Web, self-hosted
    model/{version}/ort-wasm-simd.wasm    ... its WebAssembly (SIMD)
    model/{version}/ort-wasm.wasm         ... and the non-SIMD fallback
    model/manifest.json                   which version the app loads

The version is content-addressed (a hash of the model file), so a path never
changes meaning and the service worker may cache it forever. The manifest is
written last — the same "payload first, then the pointer to it" order as the
ingest path — so the app can never be pointed at a half-uploaded version.

ONNX Runtime Web comes from the npm registry, pinned and checked against
the registry's sha512, rather than from a CDN at runtime: the admin page
holds sign-in tokens, and a script loaded from someone else's server could
read them.

--out writes the same tree to a local folder instead of S3, for testing.
Nothing here imports research/ or src/.
"""

import argparse
import base64
import hashlib
import io
import json
import mimetypes
import shutil
import subprocess
import tarfile
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ORT_VERSION = "1.17.3"  # web/recognition.js is written against this API
ORT_TARBALL = (
    f"https://registry.npmjs.org/onnxruntime-web/-/onnxruntime-web-{ORT_VERSION}.tgz"
)
ORT_SHA512 = (
    "MSDrNUWgc1biP0YzY488OJ9n/jTMS9EXysgm9Aw4CUj2A836ALbO2J1sgzguWJeVUHTlM6p7"
    "tRzo8IGAgaXWKw=="
)
ORT_FILES = ("ort.wasm.min.js", "ort-wasm-simd.wasm", "ort-wasm.wasm")

MODEL_NAME = "MegaDescriptor-T-224, int8, zero-shot"
VERSION_PREFIX = "mega-t224-int8"
INPUT_SIZE = 224

CONTENT_TYPES = {
    ".onnx": "application/octet-stream",
    ".wasm": "application/wasm",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json",
}

CACHE = Path(__file__).resolve().parent.parent / "research" / ".cache"


def fetch_runtime():
    """The three runtime files, from a verified npm tarball (cached)."""
    folder = CACHE / f"onnxruntime-web-{ORT_VERSION}"
    if all((folder / name).exists() for name in ORT_FILES):
        return {name: folder / name for name in ORT_FILES}
    with urllib.request.urlopen(ORT_TARBALL) as response:
        data = response.read()
    digest = base64.b64encode(hashlib.sha512(data).digest()).decode()
    if digest != ORT_SHA512:
        raise SystemExit(f"onnxruntime-web {ORT_VERSION}: tarball sha512 mismatch")
    folder.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        for name in ORT_FILES:
            member = tar.extractfile(f"package/dist/{name}")
            (folder / name).write_bytes(member.read())
    return {name: folder / name for name in ORT_FILES}


def build(model_path):
    """{published key: local path}, and the manifest that points at them."""
    data = model_path.read_bytes()
    sha256 = hashlib.sha256(data).hexdigest()
    version = f"{VERSION_PREFIX}-{sha256[:12]}"
    files = {f"model/{version}/model.onnx": model_path}
    for name, path in fetch_runtime().items():
        files[f"model/{version}/{name}"] = path
    manifest = {
        "version": version,
        "model": MODEL_NAME,
        "inputSize": INPUT_SIZE,
        "file": f"/model/{version}/model.onnx",
        "bytes": len(data),
        "sha256": sha256,
        "runtime": {
            "name": "onnxruntime-web",
            "version": ORT_VERSION,
            "script": f"/model/{version}/ort.wasm.min.js",
            "wasmPath": f"/model/{version}/",
        },
        # Deliberately no thresholds. The only calibration this model has
        # is on polar bears; on BGU cats the scores of right guesses, wrong
        # guesses and never-seen cats overlap. Until the labeling tool has
        # measured enough sessions, the app ranks and never decides.
        "thresholds": None,
        "publishedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    return files, manifest


def content_type(key):
    return CONTENT_TYPES.get(Path(key).suffix) or mimetypes.guess_type(key)[0]


def publish_local(files, manifest, out):
    for key, path in files.items():
        target = out / key
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(path, target)
    (out / "model" / "manifest.json").write_text(json.dumps(manifest, indent=2))


def publish_s3(files, manifest, bucket):
    for key, path in files.items():
        subprocess.run(
            [
                "aws", "s3", "cp", str(path), f"s3://{bucket}/{key}",
                "--content-type", content_type(key), "--only-show-errors",
            ],
            check=True,
        )  # fmt: skip
    subprocess.run(
        [
            "aws", "s3", "cp", "-", f"s3://{bucket}/model/manifest.json",
            "--content-type", CONTENT_TYPES[".json"], "--only-show-errors",
        ],
        input=json.dumps(manifest, indent=2).encode(),
        check=True,
    )  # fmt: skip


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--model",
        type=Path,
        default=Path("research/runs/browser/megadescriptor-t-224-int8.onnx"),
    )
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--bucket", help="the admin web bucket")
    target.add_argument("--out", type=Path, help="a local folder instead of S3")
    args = parser.parse_args()

    if not args.model.exists():
        raise SystemExit(
            f"{args.model} not found — build it first: "
            "PYTHONPATH=research python -m catreid.export (see research/README.md)"
        )
    files, manifest = build(args.model)
    if args.out:
        publish_local(files, manifest, args.out)
    else:
        publish_s3(files, manifest, args.bucket)
    total = sum(p.stat().st_size for k, p in files.items() if "ort-wasm.wasm" not in k)
    print(json.dumps(manifest, indent=2))
    print(f"a device downloads about {total / 2**20:.1f} MB, once per version")


if __name__ == "__main__":
    main()
