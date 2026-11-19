"""Fingerprint a clean Nix kernel output before it can enter the Actions cache."""
import argparse
import json
from pathlib import Path
import re

from project import sha256

CACHE_RECORD = "cache-provenance.json"
FILES = ("Image", "Module.symvers", "System.map", "build.json", "kernel.config")


def fingerprint(built, source_commit):
    if re.fullmatch(r"[a-f0-9]{40}", source_commit) is None:
        raise ValueError("Full project commit SHA required")
    digests = {}
    for name in FILES:
        path = built / name
        if path.is_symlink() or not path.is_file() or not path.stat().st_size:
            raise ValueError("Missing regular nonempty kernel output: " + name)
        digests[name] = sha256(path)
    manifest = json.loads((built / "build.json").read_text(encoding="utf-8"))
    if (manifest.get("source_commit") != source_commit
            or manifest.get("device") != "oneplus-9-pro"
            or manifest.get("os") != "coloros"
            or manifest.get("source_mode") != "offline-locked-trees"
            or manifest.get("compile_verified") is not True
            or manifest.get("image_sha256") != digests["Image"]
            or manifest.get("config_sha256") != digests["kernel.config"]):
        raise ValueError("Kernel output does not match this ColorOS Nix build")
    return {"schema": 1, "source_commit": source_commit, "files": digests}


def run(mode, built, source_commit):
    if built.is_symlink() or not built.is_dir():
        raise ValueError("Kernel output directory is missing or a symlink")
    expected = set(FILES)
    if mode == "check":
        expected.add(CACHE_RECORD)
    if {p.name for p in built.iterdir()} != expected:
        raise ValueError("Unexpected kernel cache file inventory")
    record = fingerprint(built, source_commit)
    path = built / CACHE_RECORD
    if mode == "record":
        with path.open("x", encoding="utf-8") as stream:
            json.dump(record, stream, sort_keys=True)
            stream.write("\n")
    elif path.is_symlink() or not path.is_file() or json.loads(path.read_text(encoding="utf-8")) != record:
        raise ValueError("Cached kernel file digest or provenance mismatch")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("record", "check"))
    parser.add_argument("--built", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    args = parser.parse_args()
    run(args.mode, args.built, args.source_commit)
