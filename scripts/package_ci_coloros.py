"""Qualify a locked ColorOS kernel once, then package that exact qualification."""
import argparse
import json
from pathlib import Path
import re
import sys
import tempfile

import package_twrp
from fetch_oneplus9pro_stock_boot import fetch
from project import ROOT, device, run, save, sha256

ROM = "coloros"


def require_locked_build(built, source_commit):
    if not re.fullmatch(r"[0-9a-f]{40}", source_commit):
        raise ValueError("Full source commit required")
    manifest_path = built / "build.json"
    manifest = json.loads(manifest_path.read_text())
    tools = json.loads((ROOT / "tools.lock.json").read_text())
    if (manifest.get("source_mode") != "offline-locked-trees"
            or manifest.get("offline_source_trees") != tools["offline_source_trees"]
            or manifest.get("compiler_lock") != tools["android_clang"]):
        raise ValueError("Missing exact locked Nix source provenance")
    if manifest.get("source_commit") != source_commit:
        raise ValueError("Compiled build belongs to another source commit")
    return sha256(manifest_path)


def qualify(built, stock, output, source_commit):
    firmware = device("oneplus-9-pro")["firmware"][ROM]
    digest = require_locked_build(built, source_commit)
    if output.exists():
        raise ValueError("Refusing to overwrite an existing qualification directory")
    if not stock.exists():
        fetch(firmware, stock)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".coloros-qualification-", dir=output.parent) as tmp:
        staged = Path(tmp) / "qualified"
        run(sys.executable, ROOT / "scripts/repack.py", "--device", "oneplus-9-pro", "--os", ROM,
            "--layout", "a/b", "--firmware", firmware["build_id"], "--stock", stock.resolve(),
            "--stock-sha256", firmware["stock_boot_sha256"], "--built", built.resolve(),
            "--output", staged)
        _, manifest = package_twrp.qualify(built, staged, ROM, source_commit)
        if require_locked_build(built, source_commit) != digest:
            raise ValueError("Compiled manifest changed during qualification")
        manifest["qualification_origin"] = {"source_commit": source_commit, "build_manifest_sha256": digest}
        save(staged / "build.json", manifest)
        if output.exists():
            raise ValueError("Refusing to overwrite an existing qualification directory")
        staged.rename(output)


def package(built, qualified, output, source_commit, run_id, anykernel3=None):
    digest = require_locked_build(built, source_commit)
    if not re.fullmatch(r"[0-9]+", run_id):
        raise ValueError("Numeric CI run required")
    origin = {"source_commit": source_commit, "build_manifest_sha256": digest}

    def assemble(upstream):
        return package_twrp.package(built, qualified, ROM, upstream, output, source_commit,
                                    run_id, required_origin=origin)

    if anykernel3 is not None:
        return assemble(anykernel3)
    lock = json.loads((ROOT / "anykernel3.lock.json").read_text())
    with tempfile.TemporaryDirectory(prefix="coloros-package-") as tmp:
        upstream = Path(tmp) / "AnyKernel3"
        run("git", "init", "--quiet", upstream)
        run("git", "-C", upstream, "fetch", "--depth=1", lock["repository"], lock["commit"])
        run("git", "-C", upstream, "checkout", "--detach", lock["commit"])
        return assemble(upstream)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("qualify", "package"):
        command = commands.add_parser(name)
        for flag in ("built", "output", "stock" if name == "qualify" else "qualified"):
            command.add_argument("--" + flag, type=Path, required=True)
        command.add_argument("--source-commit", required=True)
        if name == "package":
            command.add_argument("--run-id", required=True)
            command.add_argument("--anykernel3", type=Path)
    args = vars(parser.parse_args())
    command = args.pop("command")
    (qualify if command == "qualify" else package)(**args)


if __name__ == "__main__":
    main()
