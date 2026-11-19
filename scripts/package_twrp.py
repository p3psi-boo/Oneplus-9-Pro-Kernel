#!/usr/bin/env python3
"""Reproducible, exact-stock-only TWRP ZIP. Never touches a device.

Requires repack.py's successful independent qualification, not just a raw Image.
Uses pinned official AnyKernel3 BusyBox with a restricted custom AK3-format entrypoint.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import zipfile
import droidspaces
from kernel_release import validate_release
from project import ROOT, device, sha256

PIN = "41f04bdb4ee30a44e429c2c1131d5e8bb32b15f1"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def qualify(built, qualified, rom):
    data = device("oneplus-9-pro")
    droidspaces.require_device(data)
    fw = data["firmware"][rom]
    original = json.loads((built / "build.json").read_text())
    manifest = json.loads((qualified / "build.json").read_text())
    require(fw["layout"] == "a/b" and fw["verified_from_stock_image"] is True, "Unsupported firmware layout")
    require(manifest.get("device") == "oneplus-9-pro" and manifest.get("os") == rom
            and manifest.get("firmware") == fw["build_id"], "Wrong exact model/OS/firmware")
    require(all(manifest.get(k) == v for k, v in original.items()), "Qualification differs from compiled manifest")
    require(manifest.get("compile_verified") is True and manifest.get("abi_compatible") is True,
            "Build/ABI qualification missing")
    require(manifest.get("partition_layout") == "a/b", "Qualification not A/B")
    require(manifest.get("droidspaces") == droidspaces.profile(), "Stale Droidspaces/ranet3 inputs")
    require(manifest.get("kernel") == data["kernel"] and manifest.get("vendor") == data["vendor"]
            and manifest.get("resukisu") == data["resukisu"], "Wrong pinned sources")
    require(manifest.get("stock_boot_sha256") == fw["stock_boot_sha256"], "Wrong stock boot fingerprint")
    require(manifest.get("image_sha256") == sha256(built / "Image"), "Compiled kernel changed")
    require(manifest.get("config_sha256") == sha256(built / "kernel.config"), "Compiled configuration changed")
    require(manifest.get("boot_sha256") == sha256(qualified / "boot.img"), "Qualified boot changed")
    require((qualified / "boot.img").stat().st_size == fw["stock_boot_size"], "Qualified boot is not full partition size")
    abi = manifest.get("export_crc_check") or {}
    require(abi.get("passed") is True and not abi.get("missing") and not abi.get("mismatch"), "Stock export CRC mismatch")
    require(abi.get("image_sha256") == manifest["image_sha256"]
            and abi.get("system_map_sha256") == sha256(built / "System.map"), "ABI report belongs to another kernel/map")
    require((manifest.get("module_signature_check") or {}).get("passed") is True, "Module trust checks missing")
    stock_config = ROOT / fw["config"]
    require(sha256(stock_config) == fw["config_sha256"], "Stock config changed")
    droidspaces.verify_config(built / "kernel.config", stock_config)
    validate_release(manifest, fw["kernel_release"], built / "kernel.config")
    return fw, manifest


def upstream_files(upstream):
    lock = json.loads((ROOT / "anykernel3.lock.json").read_text())
    require(lock["commit"] == PIN and lock["repository"] == "https://github.com/osm0sis/AnyKernel3.git", "Unexpected upstream pin")
    head = subprocess.check_output(["git", "-C", str(upstream), "rev-parse", "HEAD"], text=True).strip()
    require(head == PIN, "AnyKernel3 checkout is not the pinned upstream revision")
    files = {}
    for name, digest in lock["files"].items():
        path = upstream / name
        require(path.is_file() and not path.is_symlink() and sha256(path) == digest, "Upstream content changed: " + name)
        files["ANYKERNEL3-LICENSE" if name == "LICENSE" else ("upstream/ak3-core.sh" if name == "tools/ak3-core.sh" else name)] = path.read_bytes()
    require(set(files) == {"upstream/ak3-core.sh", "tools/busybox", "ANYKERNEL3-LICENSE"}, "Unexpected upstream file inventory")
    return files, lock


def package(built, qualified, rom, upstream, output, source_commit, ci_run):
    require(rom in ("coloros", "oxygenos"), "Unknown ROM")
    require(re.fullmatch(r"[0-9a-f]{40}", source_commit) is not None, "Full source commit required")
    require(re.fullmatch(r"[0-9]+", ci_run) is not None, "Numeric CI run required")
    fw, manifest = qualify(built, qualified, rom)
    files, lock = upstream_files(upstream)
    for name, target in (("update-binary", "META-INF/com/google/android/update-binary"),
                         ("anykernel.sh", "anykernel.sh"), ("guard.sh", "guard.sh")):
        files[target] = (ROOT / "scripts/twrp" / name).read_bytes()
    files["META-INF/com/google/android/updater-script"] = b"#AK3\n"
    files["boot.img"] = (qualified / "boot.img").read_bytes()
    # All values originate in the reviewed local device profile / hash-checked manifest.
    for value in (fw["build_id"], rom):
        require(re.fullmatch(r"[A-Za-z0-9._()-]+", value) is not None, "Unsafe firmware metadata")
    files["firmware.conf"] = (f"ROM='{rom}'\nFIRMWARE='{fw['build_id']}'\n"
        f"EXPECTED_SIZE='{fw['stock_boot_size']}'\nEXPECTED_STOCK_HASH='{fw['stock_boot_sha256']}'\n"
        f"EXPECTED_IMAGE_HASH='{manifest['boot_sha256']}'\n").encode()
    provenance = {"schema": 1, "device": "oneplus-9-pro", "codename": "lemonadep", "os": rom,
        "firmware": fw["build_id"], "anykernel3": lock, "source_commit": source_commit, "ci_run": ci_run,
        "guard": "exact full stock active boot partition SHA256; unlocked TWRP only",
        "installed_recovery_supported": False, "device_tested": False,
        "write_scope": "current boot_a or boot_b only; prequalified kernel-only replacement",
        "qualification": manifest}
    files["build.json"] = (json.dumps(provenance, indent=2, sort_keys=True) + "\n").encode()
    files["README.txt"] = (f"EXPERIMENTAL OnePlus 9 Pro lemonadep / {rom} / {fw['build_id']}\n"
        "Only exact untouched stock current-slot boot accepted. Installed TWRP/Magisk/modified boot rejected.\n"
        "Use temporarily booted TWRP only, unlocked bootloader, with an independently verified backup/recovery plan.\n"
        "No backups, vbmeta/verity changes, inactive-slot writes, module installs, wipes, slot changes or automatic reboot.\n"
        "Uses pinned official AnyKernel3 BusyBox with a restricted AK3-format installer; upstream core is reference-only, never sourced.\n"
        "Payload was kernel-only repacked and ABI-qualified before packaging; preserves exact stock non-kernel components.\n"
        "Stock boot SHA identifies the supported boot baseline, not independently mounted userspace firmware.\n"
        "No physical device flash or boot testing performed. Read docs/twrp-packaging.md before use.\n").encode()
    files["docs/twrp-packaging.md"] = (ROOT / "docs/twrp-packaging.md").read_bytes()
    files["SHA256SUMS"] = ("".join(hashlib.sha256(content).hexdigest() + "  " + name + "\n"
                                  for name, content in sorted(files.items()))).encode()
    output.mkdir(parents=True, exist_ok=True)
    dest = output / f"oneplus-9-pro-{rom}-{fw['build_id']}-droidspaces-ranet3-twrp.zip"
    if dest.exists():
        raise ValueError("Refusing to overwrite an existing package")
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, content in sorted(files.items()):
            info = zipfile.ZipInfo(name, (2026, 1, 1, 0, 0, 0))
            info.create_system = 3
            executable = name in {"META-INF/com/google/android/update-binary", "anykernel.sh", "tools/busybox"}
            info.external_attr = (0o100755 if executable else 0o100644) << 16
            archive.writestr(info, content, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    with zipfile.ZipFile(dest) as archive:
        require(archive.testzip() is None and set(archive.namelist()) == set(files), "ZIP verification failed")
        require(all(archive.read(k) == v for k, v in files.items()), "ZIP content changed")
    dest.with_suffix(".zip.sha256").write_text(sha256(dest) + "  " + dest.name + "\n")
    print(dest)
    return dest


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--built", required=True, type=Path)
    p.add_argument("--qualified", required=True, type=Path)
    p.add_argument("--os", required=True, choices=("coloros", "oxygenos"))
    p.add_argument("--anykernel3", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--source-commit", required=True)
    p.add_argument("--ci-run", required=True)
    args = p.parse_args()
    package(args.built, args.qualified, args.os, args.anykernel3, args.output, args.source_commit, args.ci_run)
