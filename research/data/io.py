"""Deterministic JSON and streaming file helpers."""

import gzip
import hashlib
import json
from pathlib import Path


def canonical(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def file_hash(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(4 * 1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def read_jsonl(path):
    path = Path(path)
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as source:
        for number, line in enumerate(source, 1):
            if line.strip():
                try:
                    value = json.loads(line)
                    if not isinstance(value, dict):
                        raise ValueError("expected JSON object")
                    yield value
                except (ValueError, TypeError) as error:
                    raise ValueError(f"Invalid JSON record at {path.name}:{number}") from error


def write_json(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def write_jsonl(path, records):
    with Path(path).open("w", encoding="utf-8", newline="\n") as output:
        for record in records:
            output.write(canonical(record) + "\n")
