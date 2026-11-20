import json
from pathlib import Path

import joblib
import sklearn

from research.data.io import file_hash, write_json


def save_bundle(bundle, directory, metadata):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    path = directory / "bundle.joblib"
    joblib.dump(bundle, path, compress=3)
    manifest = {
        **metadata,
        "sklearn_version": sklearn.__version__,
        "item_ids": bundle.item_ids,
        "bundle_sha256": file_hash(path),
        "status": "complete",
    }
    write_json(directory / "manifest.json", manifest)
    return manifest


def load_bundle(directory):
    """Only load this project's trusted local artifacts, never user uploads."""
    directory = Path(directory)
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    path = directory / "bundle.joblib"
    if manifest.get("status") != "complete" or manifest["sklearn_version"] != sklearn.__version__:
        raise ValueError("Incomplete/incompatible model artifact")
    if file_hash(path) != manifest["bundle_sha256"]:
        raise ValueError("Model artifact checksum mismatch")
    bundle = joblib.load(path)
    if bundle.item_ids != manifest["item_ids"]:
        raise ValueError("Model item mapping mismatch")
    return bundle, manifest
