"""Ensure the Nix-injected repacking tool cannot bypass the pinned hash."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from project import sha256
import repack


class PinnedRepackToolTests(unittest.TestCase):
    def test_nix_apk_used_without_network_and_mismatch_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            source = base / "supplied.apk"
            with ZipFile(source, "w") as archive:
                archive.writestr("lib/fake/magiskboot", b"not an executable fixture")
            tools = {"sha256": sha256(source), "member": "lib/fake/magiskboot"}
            work = base / "work"
            work.mkdir()
            with patch.dict(os.environ, {"COLOROS_MAGISK_APK": str(source)}):
                with patch.object(repack.urllib.request, "urlretrieve", side_effect=AssertionError("Unexpected network")):
                    binary = repack.stock_unpacker(work, tools)
                    self.assertEqual(binary.read_bytes(), b"not an executable fixture")
                    source.write_bytes(b"tampered")
                    with self.assertRaisesRegex(ValueError, "checksum mismatch"):
                        repack.stock_unpacker(work, tools)


if __name__ == "__main__":
    unittest.main()
