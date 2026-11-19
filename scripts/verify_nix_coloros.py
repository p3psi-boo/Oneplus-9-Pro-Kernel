"""Verify Nix/native parity using the exact official OnePlus 9 Pro ColorOS boot."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile

from project import ROOT, device, run, sha256
from repack import boot_header, stock_unpacker


def verify(stock, native_dir, nix_dir, report):
    registered = device("oneplus-9-pro")["firmware"]["coloros"]
    if (stock.stat().st_size != registered["stock_boot_size"]
            or sha256(stock) != registered["stock_boot_sha256"] or boot_header(stock) != 3):
        raise ValueError("Use the exact registered ColorOS stock boot image")
    with tempfile.TemporaryDirectory(prefix="nix-stock-") as temp:
        work = Path(temp)
        tools = json.loads((ROOT / "tools.lock.json").read_text())["magiskboot"]
        binary = stock_unpacker(work, tools)
        run(binary, "unpack", "-h", stock.resolve(), cwd=work)
        stock_map = work / "stock.map"
        with stock_map.open("wb") as stream:
            subprocess.run([sys.executable, ROOT / "scripts/recover_symbols.py", work / "kernel"],
                           stdout=stream, check=True)
        run(sys.executable, ROOT / "scripts/check_nix_parity.py",
            "--native-dir", native_dir, "--nix-dir", nix_dir,
            "--stock-kernel", work / "kernel", "--stock-map", stock_map, "--report", report)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("stock", "native-dir", "nix-dir", "report"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    verify(args.stock, args.native_dir, args.nix_dir, args.report)
