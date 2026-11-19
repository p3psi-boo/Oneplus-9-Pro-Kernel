"""Run the stock qualification and TWRP packager for the ColorOS Actions job."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile

from project import ROOT, device, run


def package(built, stock, output, run_id):
    rom = "coloros"
    firmware = device("oneplus-9-pro")["firmware"][rom]
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    with tempfile.TemporaryDirectory(prefix="coloros-package-") as tmp:
        work = Path(tmp)
        qualified, upstream = work / "qualified", work / "AnyKernel3"
        run(sys.executable, ROOT / "scripts/repack.py", "--device", "oneplus-9-pro", "--os", rom,
            "--layout", "a/b", "--firmware", firmware["build_id"], "--stock", stock.resolve(),
            "--stock-sha256", firmware["stock_boot_sha256"], "--built", built.resolve(),
            "--output", qualified)
        lock = json.loads((ROOT / "anykernel3.lock.json").read_text())
        run("git", "init", "--quiet", upstream)
        run("git", "-C", upstream, "fetch", "--depth=1", lock["repository"], lock["commit"])
        run("git", "-C", upstream, "checkout", "--detach", lock["commit"])
        run(sys.executable, ROOT / "scripts/package_twrp.py", "--built", built.resolve(),
            "--qualified", qualified, "--os", rom, "--anykernel3", upstream,
            "--output", output.resolve(), "--source-commit", commit, "--ci-run", run_id)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ("built", "stock", "output"):
        parser.add_argument("--" + arg, type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    package(args.built, args.stock, args.output, args.run_id)
