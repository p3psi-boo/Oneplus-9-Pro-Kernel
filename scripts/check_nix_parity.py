"""Check OnePlus 9 Pro ColorOS kernel compatibility across two build paths."""
import argparse
import hashlib
import json
import re
import struct
from pathlib import Path

from check_module_abi import exports
from droidspaces import DEVICE, profile, verify_config
from kernel_release import SUFFIX, branded_release
from project import PATCHES, ROOT, device, save, sha256


ROM = "coloros"
# Extracted from the SHA-registered official ColorOS boot via the pinned
# Magiskboot; stock.map is recover_symbols.py (vmlinux-to-elf 1.3.6) stdout.
STOCK_BOOT_SHA256 = "880506483c3d12c1dbfb30548fc67122fd026a03abe09aae0489a47f84408a85"
STOCK_IMAGE_SHA256 = "493668b33bc100bd913b3f24605a54de32bdf22915092dcdd4e9c147a41ff7d1"
STOCK_MAP_SHA256 = "95b650be8b403600ddb66d7254d326d085531222b4a66945cbeb24c300009161"
STOCK_EXPORT_COUNT = 13797
SCOPE = ("Effective kernel config, embedded release and official stock export CRCs only; "
         "does not establish build independence, byte reproducibility or device compatibility.")
ASSIGN = re.compile(r"(CONFIG_[A-Za-z0-9_]+)=(.*)")
UNSET = re.compile(r"# (CONFIG_[A-Za-z0-9_]+) is not set")
CONFIG_VALUE = re.compile(r'y|m|n|-?[0-9]+|0[xX][0-9A-Fa-f]+|"(?:[^"\\]|\\.)*"')
BANNER = re.compile(rb"(?:\x00|\A)Linux version ([A-Za-z0-9._+-]+) \([^\x00\r\n]*\) ")


def settings(path):
    result = {}
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if match := ASSIGN.fullmatch(line):
            key, value = match.groups()
        elif match := UNSET.fullmatch(line):
            key, value = match[1], "n"
        else:
            if not line or (line.startswith("#") and not line.startswith("# CONFIG_")):
                continue
            raise ValueError(f"Malformed kernel config line {number} in {path}")
        if key in result:
            raise ValueError(f"Duplicate kernel config setting {key} in {path}")
        if CONFIG_VALUE.fullmatch(value) is None:
            raise ValueError(f"Malformed kernel config setting {key} in {path}")
        result[key] = value
    if not result:
        raise ValueError(f"Empty kernel config in {path}")
    return result


def no_duplicate_keys(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError(f"Duplicate manifest field {key}")
        result[key] = value
    return result


def validate_build(directory, expected, registered_config):
    manifest = json.loads((directory / "build.json").read_text(encoding="utf-8"),
                          object_pairs_hook=no_duplicate_keys)
    if not isinstance(manifest, dict):
        raise ValueError(f"Build manifest is not an object in {directory}")
    for key, want in expected.items():
        if manifest.get(key) != want:
            raise ValueError(f"Unexpected build manifest field {key} in {directory}")
    for key in ("compile_verified", "stock_config_supplied"):
        if manifest.get(key) is not True:
            raise ValueError(f"Expected {key}=true in {directory}")
    image, config, symbols = (directory / name for name in ("Image", "kernel.config", "System.map"))
    digest = {"image_sha256": sha256(image), "config_sha256": sha256(config),
              "system_map_sha256": sha256(symbols)}
    for key in ("image_sha256", "config_sha256"):
        if manifest.get(key) != digest[key]:
            raise ValueError(f"Build manifest {key} does not match artifact in {directory}")
    result = settings(config)
    verify_config(config, registered_config)
    releases = {match.decode("ascii") for match in BANNER.findall(image.read_bytes())}
    if releases != {expected["kernel_release"]}:
        raise ValueError(f"Missing or unexpected embedded kernel release in {directory}: {sorted(releases)!r}")
    normalized = json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    digest["settings_sha256"] = hashlib.sha256(normalized.encode("ascii")).hexdigest()
    return result, {**digest, "kernel_release": expected["kernel_release"],
                    "config_settings": len(result)}


def export_check(stock, built):
    missing = sorted(stock.keys() - built.keys())
    mismatch = {name: {"stock": f"{stock[name]:#010x}", "built": f"{built[name]:#010x}"}
                for name in sorted(stock.keys() & built.keys()) if stock[name] != built[name]}
    return {"stock_exports": len(stock), "built_exports": len(built),
            "matching": len(stock) - len(missing) - len(mismatch),
            "missing": missing, "mismatch": mismatch, "passed": not missing and not mismatch}


def compare(native_dir, nix_dir, stock_kernel, stock_map):
    if native_dir.resolve() == nix_dir.resolve():
        raise ValueError("Native and Nix inputs must be separate artifact directories")
    data = device(DEVICE)
    firmware = data["firmware"][ROM]
    if firmware["stock_boot_sha256"] != STOCK_BOOT_SHA256:
        raise ValueError("Registered official ColorOS boot changed; revalidate stock parity fixtures")
    registered_config = ROOT / firmware["config"]
    if sha256(registered_config) != firmware["config_sha256"]:
        raise ValueError("Registered stock config checksum mismatch")
    if sha256(stock_kernel) != STOCK_IMAGE_SHA256:
        raise ValueError("Stock kernel is not the pinned official ColorOS Image")
    if sha256(stock_map) != STOCK_MAP_SHA256:
        raise ValueError("Stock map does not match pinned recover_symbols.py output (vmlinux-to-elf 1.3.6)")
    stock = exports(stock_kernel, stock_map)
    if len(stock) != STOCK_EXPORT_COUNT:
        raise ValueError(f"Expected {STOCK_EXPORT_COUNT} official stock exports, found {len(stock)}")
    expected = {key: data[key] for key in ("kernel", "vendor", "resukisu")}
    expected.update(device=DEVICE, os=ROM, firmware=firmware["build_id"],
                    kernel_release=branded_release(firmware["kernel_release"]),
                    stock_kernel_release=firmware["kernel_release"], kernel_release_suffix=SUFFIX,
                    droidspaces=profile())
    for key, name in (("patch_sha256", f"{PATCHES[DEVICE]}.patch"),
                      ("vendor_patch_sha256", "vendor-oneplus-9.patch"),
                      ("compat_patch_sha256", f"compat-{data['platform']}.patch")):
        patch = ROOT / "patches" / name
        expected[key] = sha256(patch) if patch.is_file() else None
    native_config, native = validate_build(native_dir, expected, registered_config)
    nix_config, nix = validate_build(nix_dir, expected, registered_config)
    for directory, result in ((native_dir, native), (nix_dir, nix)):
        result["stock_abi"] = export_check(stock, exports(directory / "Image", directory / "System.map"))
    differences = {key: {"native": native_config.get(key), "nix": nix_config.get(key)}
                   for key in sorted(native_config.keys() | nix_config.keys())
                   if native_config.get(key) != nix_config.get(key)}
    return {
        "passed": not differences and native["stock_abi"]["passed"] and nix["stock_abi"]["passed"],
        "scope": SCOPE, "device": DEVICE, "os": ROM, "firmware": firmware["build_id"],
        "kernel_release": expected["kernel_release"],
        "stock": {"boot_sha256": STOCK_BOOT_SHA256, "kernel_sha256": STOCK_IMAGE_SHA256,
                  "map_sha256": STOCK_MAP_SHA256, "exports": len(stock)},
        "config": {"passed": not differences, "differences": differences},
        "native": native, "nix": nix,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ("native-dir", "nix-dir", "stock-kernel", "stock-map", "report"):
        parser.add_argument("--" + flag, required=True, type=Path)
    args = parser.parse_args()
    report = args.report.resolve()
    if (report in (args.stock_kernel.resolve(), args.stock_map.resolve())
            or any(report.is_relative_to(p.resolve()) for p in (args.native_dir, args.nix_dir))):
        parser.error("write the report outside the input artifact directories and files")
    try:
        result = compare(args.native_dir, args.nix_dir, args.stock_kernel, args.stock_map)
    except (OSError, ValueError, KeyError, IndexError, TypeError, struct.error) as exc:
        result = {"passed": False, "scope": SCOPE, "error": str(exc)}
    save(report, result)
    print(json.dumps({"passed": result["passed"], "report": str(report),
                      **({"error": result["error"]} if "error" in result else {})}))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
