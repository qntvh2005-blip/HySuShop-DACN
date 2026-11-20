"""Report real-data job status and actual downloaded bytes without reading credentials."""

import json
from pathlib import Path

from research.data.pipeline import ROOT


def status():
    path = ROOT / "reports/data-job/status.json"
    result = (
        json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"stage": "not_started"}
    )
    downloads = []
    raw_dir = Path(result.get("raw_dir", ROOT / "data/raw/amazon-2023-hf"))
    for receipt_path in sorted(raw_dir.glob("*.source.json")):
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        target = receipt_path.with_name(receipt_path.name.removesuffix(".source.json"))
        chunks = target.with_name(target.name + ".chunks")
        downloaded = (
            target.stat().st_size
            if target.exists()
            else sum(p.stat().st_size for p in chunks.glob("*.part"))
        )
        downloads.append(
            {
                "kind": receipt["kind"],
                "downloaded_bytes": downloaded,
                "total_bytes": receipt["bytes"],
                "percent": round(100 * downloaded / receipt["bytes"], 1),
                "receipt_status": receipt["status"],
            }
        )
    result["downloads"] = downloads
    return result


if __name__ == "__main__":
    print(json.dumps(status(), ensure_ascii=False, indent=2))
