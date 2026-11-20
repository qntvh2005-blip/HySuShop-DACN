"""Download official category raw files, resume only against unchanged HTTP validators."""

import argparse
import json
import shutil
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from research.data.io import file_hash, write_json

BASE = "https://mcauleylab.ucsd.edu/public_datasets/data/amazon_2023/raw/"
SOURCES = {
    "metadata": (
        BASE + "meta_categories/meta_Cell_Phones_and_Accessories.jsonl.gz",
        "meta_Cell_Phones_and_Accessories.jsonl.gz",
    ),
    "reviews": (
        BASE + "review_categories/Cell_Phones_and_Accessories.jsonl.gz",
        "Cell_Phones_and_Accessories.jsonl.gz",
    ),
}
HF_REVISION = "2b6d039ed471f2ba5fd2acb718bf33b0a7e5598e"
HF_BASE = (
    f"https://huggingface.co/datasets/McAuley-Lab/Amazon-Reviews-2023/resolve/{HF_REVISION}/raw/"
)
HF_SOURCES = {
    "metadata": (
        HF_BASE + "meta_categories/meta_Cell_Phones_and_Accessories.jsonl",
        "meta_Cell_Phones_and_Accessories.jsonl",
    ),
    "reviews": (
        HF_BASE + "review_categories/Cell_Phones_and_Accessories.jsonl",
        "Cell_Phones_and_Accessories.jsonl",
    ),
}
HF_SHA256 = {
    "metadata": "f8f411a2e3a90560de4b18a0c2c885a4ba410bb26f965a8e7290080898d22688",
    "reviews": "bda42ca8d28a1e57db970c78703b7aaac9c9beb6595e1be00364a0a55a682cd5",
}
CHUNK_SIZE = 32 * 1024 * 1024


def download(kind, output_dir, workers=4, mirror="ucsd"):
    url, filename = (HF_SOURCES if mirror == "huggingface" else SOURCES)[kind]
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / filename
    part = target.with_suffix(target.suffix + ".part")
    receipt = target.with_suffix(target.suffix + ".source.json")
    with urllib.request.urlopen(urllib.request.Request(url, method="HEAD"), timeout=60) as response:
        headers = response.headers
        expected = int(headers["Content-Length"])
        validator = {
            "etag": headers.get("ETag"),
            "last_modified": headers.get("Last-Modified"),
            "bytes": expected,
        }
    if target.exists():
        if not receipt.exists():
            raise ValueError(f"{target.name} exists without receipt; refusing to overwrite")
        saved = json.loads(receipt.read_text(encoding="utf-8"))
        if target.stat().st_size != saved["bytes"] or file_hash(target) != saved["sha256"]:
            raise ValueError(f"Checksum mismatch: {target.name}")
        print(f"{kind}: verified existing file", flush=True)
        return saved
    chunks_directory = output_dir / (filename + ".chunks")
    if part.exists() or chunks_directory.exists():
        if not receipt.exists():
            raise ValueError("Partial file without source validators; use a new output directory")
        saved = json.loads(receipt.read_text(encoding="utf-8"))
        if any(saved.get(k) != v for k, v in validator.items()) or saved.get("url", url) != url:
            raise ValueError("Remote file changed; use a new output directory")
    record = {
        "dataset": "Amazon Reviews 2023",
        "category": "Cell_Phones_and_Accessories",
        "kind": kind,
        "url": url,
        "project_url": "https://amazon-reviews-2023.github.io/",
        "accessed_at": datetime.now(timezone.utc).isoformat(),
        "status": "downloading",
        "mirror": mirror,
        "revision": HF_REVISION if mirror == "huggingface" else None,
        **validator,
    }
    write_json(receipt, record)
    offset = part.stat().st_size if part.exists() else 0
    if offset > expected:
        raise ValueError("Partial file exceeds remote size")
    if workers > 1:
        parts = output_dir / (filename + ".chunks")
        parts.mkdir(exist_ok=True)
        chunk_size = CHUNK_SIZE
        segments = [
            (start, min(expected, start + chunk_size)) for start in range(0, expected, chunk_size)
        ]

        def transfer(segment):
            start, end = segment
            chunk_path = parts / f"{start:012d}.part"
            if not chunk_path.exists() and offset >= end:
                with part.open("rb") as old, chunk_path.open("wb") as destination:
                    old.seek(start)
                    destination.write(old.read(end - start))
            have = chunk_path.stat().st_size if chunk_path.exists() else 0
            if have > end - start:
                raise ValueError("Chunk larger than requested range")
            for attempt in range(4):
                if have == end - start:
                    break
                try:
                    first = start + have
                    request = urllib.request.Request(
                        url,
                        headers={
                            "Range": f"bytes={first}-{end - 1}",
                            "If-Range": validator["etag"],
                        },
                    )
                    with urllib.request.urlopen(request, timeout=90) as response:
                        if (
                            response.status != 206
                            or response.headers.get("Content-Range")
                            != f"bytes {first}-{end - 1}/{expected}"
                        ):
                            raise ValueError("Server did not honor exact chunk range")
                        with chunk_path.open("ab") as destination:
                            while payload := response.read(min(1024 * 1024, end - start - have)):
                                destination.write(payload)
                                have += len(payload)
                    if have != end - start:
                        raise OSError("Incomplete range response")
                except (OSError, TimeoutError):
                    have = chunk_path.stat().st_size if chunk_path.exists() else 0
                    if attempt == 3:
                        raise
                    time.sleep(min(2**attempt, 8))
            print(
                f"{kind}: chunk {start // chunk_size + 1}/{len(segments)} verified length",
                flush=True,
            )
            return chunk_path

        with ThreadPoolExecutor(max_workers=workers) as pool:
            chunks = list(pool.map(transfer, segments))
        assembled = target.with_suffix(target.suffix + ".assembled")
        with assembled.open("wb") as destination:
            for chunk_path in chunks:
                with chunk_path.open("rb") as source:
                    shutil.copyfileobj(source, destination, length=4 * 1024 * 1024)
        record["sha256"] = file_hash(assembled)
        if mirror == "huggingface" and record["sha256"] != HF_SHA256[kind]:
            raise ValueError("Official Hugging Face LFS SHA-256 mismatch")
        record["status"] = "complete"
        record["completed_at"] = datetime.now(timezone.utc).isoformat()
        if assembled.stat().st_size != expected:
            raise ValueError("Assembled file has wrong size")
        write_json(receipt, record)
        assembled.rename(target)
        for chunk_path in chunks:
            chunk_path.unlink()
        parts.rmdir()
        part.unlink(missing_ok=True)
        print(f"{kind}: completed and SHA-256 recorded", flush=True)
        return record
    if offset < expected:
        request_headers = (
            {"Range": f"bytes={offset}-", "If-Range": validator["etag"]} if offset else {}
        )
        request = urllib.request.Request(url, headers=request_headers)
        with urllib.request.urlopen(request, timeout=90) as response:
            if offset and (
                response.status != 206
                or not response.headers.get("Content-Range", "").startswith(f"bytes {offset}-")
            ):
                raise ValueError("Server did not honor byte-range resume")
            last_print = 0.0
            with part.open("ab" if offset else "wb") as output:
                while chunk := response.read(4 * 1024 * 1024):
                    output.write(chunk)
                    offset += len(chunk)
                    if time.monotonic() - last_print > 20:
                        print(
                            f"{kind}: {offset / expected:.1%} ({offset / 2**20:.0f} MiB)",
                            flush=True,
                        )
                        last_print = time.monotonic()
    if part.stat().st_size != expected:
        raise ValueError("Download incomplete; rerun to resume")
    record["sha256"] = file_hash(part)
    if mirror == "huggingface" and record["sha256"] != HF_SHA256[kind]:
        raise ValueError("Official Hugging Face LFS SHA-256 mismatch")
    record["status"] = "complete"
    record["completed_at"] = datetime.now(timezone.utc).isoformat()
    write_json(receipt, record)
    part.rename(target)
    print(f"{kind}: completed and SHA-256 recorded", flush=True)
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", choices=["all", *SOURCES], default="all")
    parser.add_argument("--output-dir", type=Path, default=Path("data/raw/amazon-2023"))
    parser.add_argument("--workers-per-file", type=int, choices=range(1, 9), default=4)
    parser.add_argument("--mirror", choices=["ucsd", "huggingface"], default="ucsd")
    args = parser.parse_args()
    kinds = list(SOURCES) if args.kind == "all" else [args.kind]
    with ThreadPoolExecutor(max_workers=len(kinds)) as pool:
        results = list(
            pool.map(
                lambda kind: download(kind, args.output_dir, args.workers_per_file, args.mirror),
                kinds,
            )
        )
    write_json(
        args.output_dir / "source_manifest.json",
        {"files": results, "kind": "official_raw_download"},
    )


if __name__ == "__main__":
    main()
