"""OnePlus 9 Pro opt-in Droidspaces profile, pinned to the stock SM8350 tree."""
import re
from project import ROOT, run, sha256

DEVICE = "oneplus-9-pro"
KERNEL = "9e38a9fabb4de096bf386b7be988b7f7c5e4c58e"
UPSTREAM = "cdadb9eb5d0f86aacffff60776333e6f6b73a30a"
PATCH = ROOT / "patches/droidspaces-sm8350-ipc-kabi.patch"
NFT_PATCH = ROOT / "patches/ranet3-sm8350-nft-kabi.patch"
CONFIG = ROOT / "configs/droidspaces-sm8350.config"
STOCK_PROTOCOL_CRC = 0x8ED24291  # Observed in the stock Image; see compat/sm8350/README.md.
RANET3_BASE = ("CONFIG_TUN", "CONFIG_IP_MULTIPLE_TABLES", "CONFIG_IPV6",
               "CONFIG_IPV6_MULTIPLE_TABLES", "CONFIG_NF_CONNTRACK")
PROTECTIONS = ("CONFIG_MODULES", "CONFIG_MODVERSIONS", "CONFIG_MODULE_SIG",
               "CONFIG_MODULE_SIG_FORCE", "CONFIG_CFI_CLANG", "CONFIG_CFI_CLANG_SHADOW",
               "CONFIG_CFI_PERMISSIVE", "CONFIG_SECURITY_SELINUX",
               "CONFIG_SECURITY_SELINUX_DISABLE", "CONFIG_SECURITY_SELINUX_BOOTPARAM")
ASSIGN = re.compile(r"(CONFIG_[A-Z0-9_]+)=(.*)")
UNSET = re.compile(r"# (CONFIG_[A-Z0-9_]+) is not set")


def setting(line):
    match = ASSIGN.fullmatch(line)
    if match:
        return match.group(1, 2)
    match = UNSET.fullmatch(line)
    return (match.group(1), "n") if match else (None, None)


def values(config_text):
    return dict(pair for line in config_text.splitlines() if (pair := setting(line))[0])


def merge_config(config, fragment=CONFIG):
    overlay = values(fragment.read_text(encoding="utf-8"))
    lines = config.read_text(encoding="utf-8").splitlines()
    lines = [line for line in lines if setting(line)[0] not in overlay]
    lines.extend(f"# {key} is not set" if val == "n" else f"{key}={val}"
                 for key, val in overlay.items())
    config.write_text("\n".join(lines) + "\n", encoding="utf-8")


def verify_config(config, stock):
    actual = values(config.read_text(encoding="utf-8"))
    expected = values(CONFIG.read_text(encoding="utf-8"))
    baseline = values(stock.read_text(encoding="utf-8"))
    expected.update((key, "y") for key in RANET3_BASE)
    expected.update((key, baseline.get(key, "n")) for key in PROTECTIONS)
    mismatches = [f"{key}={wanted} (actual {actual.get(key, 'n')})"
                  for key, wanted in expected.items() if actual.get(key, "n") != wanted]
    if mismatches:
        raise ValueError("Droidspaces kernel config differs from profile: " + ", ".join(mismatches))


def require_device(data):
    if (data["id"] != DEVICE or data["platform"] != "sm8350"
            or data["kernel"]["version"] != "5.4.254"
            or data["kernel"]["commit"] != KERNEL):
        raise ValueError("Droidspaces profile has not been reviewed for this device/kernel")


def apply_patch(source):
    run("git", "apply", "--check", PATCH, NFT_PATCH, cwd=source)
    run("git", "apply", PATCH, NFT_PATCH, cwd=source)


def verify_protocol_crc(output):
    versions = output / "net/oplus_modules/data_module/built-in.a.symversions"
    text = versions.read_text(encoding="utf-8")
    matches = re.findall(r"^__crc_register_netlink_request = (0x[0-9a-fA-F]+);$", text, re.M)
    if len(matches) != 1 or int(matches[0], 16) != STOCK_PROTOCOL_CRC:
        observed = ", ".join(matches) or "missing"
        raise ValueError(f"Stock register_netlink_request CRC mismatch: expected {STOCK_PROTOCOL_CRC:#x}, got {observed}")


def profile():
    return {"upstream_commit": UPSTREAM, "patch_sha256": sha256(PATCH),
            "nft_kabi_patch_sha256": sha256(NFT_PATCH),
            "config_fragment_sha256": sha256(CONFIG)}
