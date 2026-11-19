import bz2
import hashlib
import io
import lzma
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import fetch_oneplus9pro_stock_boot as stock


def var(n):
    result = bytearray()
    while n >= 128:
        result.append((n & 127) | 128)
        n >>= 7
    return bytes(result) + bytes([n])


def field(num, data):
    if isinstance(data, int):
        return var(num * 8) + var(data)
    return var(num * 8 + 2) + var(len(data)) + data


def ota(behavior=None):
    chunks = [(0, b"A" * 4096), (1, b"B" * 4096), (8, b"C" * 4096), (6, b"\0" * 4096)]
    body = b""
    plan = []
    image = b"".join(data for _, data in chunks)
    digest = hashlib.sha256(image).hexdigest()
    for block, (mode, data) in enumerate(chunks):
        raw = data if mode == 0 else bz2.compress(data) if mode == 1 else lzma.compress(data) if mode == 8 else b""
        position = 0 if behavior == "overlap" and block == 1 else block
        kind = 4 if behavior == "delta" and block == 0 else mode
        op = field(1, kind) + field(6, field(1, position) + field(2, 1))
        if raw:
            hash_bytes = hashlib.sha256(raw).digest()
            if behavior == "corrupt_op" and block == 1:
                hash_bytes = b"\0" * 32
            op += field(2, len(body)) + field(3, len(raw)) + field(8, hash_bytes)
            body += raw
        plan.append(field(8, op))
    partition = (field(1, b"boot") + field(7, field(1, len(image)) + field(2, bytes.fromhex(digest))) + b"".join(plan))
    manifest = field(3, 4096) + field(13, partition)
    payload = struct.pack(">4sQQI", b"CrAU", 2, len(manifest), 0) + manifest + body
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("payload.bin", payload, compress_type=zipfile.ZIP_DEFLATED if behavior == "compressed_zip" else zipfile.ZIP_STORED)
    firmware = {"stock_boot_size":len(image), "stock_boot_sha256":digest,
                "source_url":"https://gauss-componentotamanual.allawnofs.com/pinned.zip", "build_id":"test"}
    if behavior == "wrong_image":
        firmware["stock_boot_sha256"] = "0" * 64
    return archive.getvalue(), firmware, image


class MemoryRemote(io.BytesIO):
    def get(self, start, length):
        return self.getvalue()[start:start + length]


class StockBootTests(unittest.TestCase):
    def test_reconstructs_full_boot_and_never_overwrites(self):
        blob, firmware, image = ota()
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "new" / "boot.img"
            stock.fetch(firmware, output, lambda _: MemoryRemote(blob))
            self.assertEqual(output.read_bytes(), image)
            with self.assertRaises(FileExistsError):
                stock.fetch(firmware, output, lambda _: self.fail("should not access source"))

    def test_bad_ota_is_never_published(self):
        for behavior in ("overlap", "delta", "corrupt_op", "wrong_image", "compressed_zip"):
            with self.subTest(behavior=behavior), tempfile.TemporaryDirectory() as tmp:
                blob, firmware, _ = ota(behavior)
                output = Path(tmp) / "boot.img"
                with self.assertRaises(ValueError):
                    stock.fetch(firmware, output, lambda _: MemoryRemote(blob))
                self.assertFalse(output.exists())

    def test_rejects_untrusted_or_unpinned_url(self):
        for url in ("http://gauss-componentotamanual.allawnofs.com/ota.zip", "https://evil.invalid/ota.zip",
                    "https://gauss-componentotamanual.allawnofs.com/ota.zip?a=1"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                stock.RemoteZip(url)

    def test_rejects_mismatched_http_range(self):
        class FakeReply(io.BytesIO):
            status = 206
            headers = {"Content-Range": "bytes 4-4/50"}
            def geturl(self):
                return "https://gauss-componentotamanual.allawnofs.com/ota.zip"
        with patch.object(stock.request, "urlopen", return_value=FakeReply(b"x")), self.assertRaisesRegex(ValueError,"range"):
            stock.RemoteZip("https://gauss-componentotamanual.allawnofs.com/ota.zip")

    def test_rejects_short_or_noncanonical_manifest(self):
        for data in (b"\0", b"\x0a\x04abc", b"\x08\xff", b"\x08"+b"\xff"*9+b"\x7f"):
            with self.subTest(data=data), self.assertRaises(ValueError):
                stock.message(data)


if __name__ == "__main__":
    unittest.main()
