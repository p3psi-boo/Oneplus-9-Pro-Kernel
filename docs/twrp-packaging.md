# Restricted TWRP packages: OnePlus 9 Pro

Experimental, **not device-tested**. These packages require `lemonadep`,
an unlocked bootloader, and a matching **current A/B boot slot**.

GitHub Actions generates a TWRP package only for ColorOS. The OxygenOS row
records the local baseline; there is no automated OxygenOS TWRP package.

| Package | Official stock build |
|---|---|
| ColorOS | `LE2120_14.0.0.1901(CN01)` |
| OxygenOS | `LE2121_14.0.0.1902(EX01)` |

Never interchange packages or treat another Android 14 build as compatible.
The device profile pins the SHA-256 of each complete 192 MiB stock boot image.
The installer requires the current boot partition to match it byte-for-byte.
This is stronger than trusting recovery's ROM fingerprint, but does **not**
independently attest mounted userspace when someone has mixed firmware manually.

## Recovery and risk

Use **temporarily booted TWRP**, leaving the current boot partition pristine.
OnePlus 9 Pro uses recovery-as-boot. An installed TWRP, Magisk, previously flashed
custom kernel, or any other modified boot image is rejected, not preserved or
silently overwritten. There is no bypass or permissive mode. A second install
will also fail the stock hash check. The newest official TeamWin image listed
when reviewed was `3.7.1_12-0` (2024-02-21); this listing is **not** evidence that
this recovery works with these exact Android 14 builds.

Before attempting installation, independently back up the current boot partition
and important data off-device; verify your exact stock image, slot, bootloader
access, and a working recovery/restore procedure. This installer intentionally
creates **no backup**. Do not proceed without a verified recovery plan. A power
loss or write failure can leave the current slot unbootable. On a write/readback
error, do not reboot blindly; restore through your independent recovery plan.
No automatic rollback or inactive-slot modification is attempted.

The script rejects unknown/locked or contradictory bootloader properties,
unknown/conflicting slots, non-TWRP and live Android environments, wrong model,
wrong size, wrong stock baseline and corrupt payloads before writing. It resolves
only current `boot_a` or `boot_b`, rechecks immediately before writing, then
checks the complete written image digest. External concurrent modification and
power failure cannot be made safe by shell guards. Readback success is not proof
of device boot, AVB acceptance, module loading, Droidspaces or ranet3 operation.

## Scope and upstream

This is a **restricted custom AK3-format installer**, using official AnyKernel3
BusyBox pinned by commit and SHA-256 in `anykernel3.lock.json`. Upstream
`ak3-core.sh` is bundled as reference-only and is never sourced. The generic
upstream updater/core modes are deliberately not used: they contain additional
mount, backup, patching and partition handling behavior outside this scope.
There is exactly one bounded full-image write and no zero-fill, vbmeta/verity
patch, separate partition write, recovery install, slot switch, module install,
root-app mode, wipe, reboot, or persistent backup. Temporary files are isolated
under a unique `/tmp/ak3-guarded.*` directory and removed on exit.

The host first runs existing `repack.py` qualification: source/config provenance,
full stock export CRC comparison, module-signature checks, and non-kernel content
preservation. The ZIP carries that prequalified image instead of repacking on
phone. Relative to the exact accepted stock baseline only the kernel changes;
stock ramdisk/DTB/boot metadata/embedded AVB contents remain as qualified. This
does not disable device AVB or guarantee an unlocked device will boot it.

## Reproduction

Use the [Nix build and validation commands](nix-build.md#本地验证和打包) on a clean checkout
to qualify and package the ColorOS kernel without Actions. ZIP entries are sorted
with fixed timestamps, permissions and compression settings; reproduce with the
same Nix toolchain and provenance values. The ZIP identifies the exact project
commit separately from the AnyKernel3 commit. The sidecar SHA-256 detects
corruption; it is not a signature. Host fixtures exercise packaging and installer
refusal/write/readback logic, but not Android BusyBox or real block devices.

## GitHub Actions: generate the ColorOS ZIP

1. Open **Build OnePlus 9 Pro ColorOS with Nix** in Actions.
2. Select **Run workflow** and choose `oneplus-9-pro`.
3. Check `package_twrp` and run the workflow.
4. Download `twrp-experimental-oneplus-9-pro-coloros-nix-<run number>`.
5. Extract the GitHub artifact wrapper.

The inner `*-twrp.zip` is the TWRP package. The adjacent `.zip.sha256`
file checks that package. Do not flash the GitHub artifact wrapper.

Nix compiles and packages only ColorOS. Before upload, the workflow checks the result
against the registered stock boot. Without `package_twrp`, it uploads only
the verified kernel review artifact. It publishes no GitHub Release.
Artifacts expire after 14 days. Build and ABI checks do not verify device boot.

See [Nix build and validation](nix-build.md).
