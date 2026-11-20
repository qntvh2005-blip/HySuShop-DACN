import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from research.data.io import file_hash, write_json
from research.download import download


class Response(io.BytesIO):
    def __init__(self, payload, status, headers):
        super().__init__(payload)
        self.status = status
        self.headers = headers


class DownloadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.payload = bytes(range(256)) * 41

    def tearDown(self):
        self.temp.cleanup()

    def open(self, request, timeout):
        headers = {
            "Content-Length": str(len(self.payload)),
            "ETag": '"test-version"',
            "Last-Modified": "test-date",
        }
        if request.get_method() == "HEAD":
            return Response(b"", 200, headers)
        value = request.get_header("Range")
        if value:
            start, end = value.removeprefix("bytes=").split("-")
            first, last = int(start), int(end) if end else len(self.payload) - 1
            headers["Content-Range"] = f"bytes {first}-{last}/{len(self.payload)}"
            return Response(self.payload[first : last + 1], 206, headers)
        return Response(self.payload, 200, headers)

    @patch("research.download.CHUNK_SIZE", 4096)
    def test_parallel_download_checksum_and_existing_verification(self):
        with patch("research.download.urllib.request.urlopen", self.open):
            result = download("reviews", self.root, workers=2)
            target = self.root / "Cell_Phones_and_Accessories.jsonl.gz"
            self.assertEqual(target.read_bytes(), self.payload)
            self.assertEqual(result["sha256"], file_hash(target))
            self.assertEqual(download("reviews", self.root, workers=2)["sha256"], result["sha256"])
            target.write_bytes(b"tampered")
            with self.assertRaisesRegex(ValueError, "Checksum"):
                download("reviews", self.root, workers=2)

    @patch("research.download.CHUNK_SIZE", 4096)
    def test_resume_contiguous_partial_into_chunks(self):
        target = self.root / "Cell_Phones_and_Accessories.jsonl.gz"
        target.with_suffix(".gz.part").write_bytes(self.payload[:5000])
        write_json(
            target.with_suffix(".gz.source.json"),
            {"etag": '"test-version"', "last_modified": "test-date", "bytes": len(self.payload)},
        )
        with patch("research.download.urllib.request.urlopen", self.open):
            download("reviews", self.root, workers=2)
        self.assertEqual(target.read_bytes(), self.payload)

    def test_changed_source_validator_refuses_resume(self):
        target = self.root / "Cell_Phones_and_Accessories.jsonl.gz"
        target.with_suffix(".gz.part").write_bytes(b"partial")
        write_json(
            target.with_suffix(".gz.source.json"),
            {"etag": "old", "last_modified": "old", "bytes": len(self.payload)},
        )
        with patch("research.download.urllib.request.urlopen", self.open):
            with self.assertRaisesRegex(ValueError, "changed"):
                download("reviews", self.root, workers=1)

    def test_range_not_honored_does_not_append(self):
        target = self.root / "Cell_Phones_and_Accessories.jsonl.gz"
        partial = target.with_suffix(".gz.part")
        partial.write_bytes(self.payload[:10])
        write_json(
            target.with_suffix(".gz.source.json"),
            {"etag": '"test-version"', "last_modified": "test-date", "bytes": len(self.payload)},
        )

        def incorrect(request, timeout):
            if request.get_method() == "HEAD":
                return self.open(request, timeout)
            return Response(self.payload, 200, {})

        with patch("research.download.urllib.request.urlopen", incorrect):
            with self.assertRaisesRegex(ValueError, "honor"):
                download("reviews", self.root, workers=1)
        self.assertEqual(partial.read_bytes(), self.payload[:10])
