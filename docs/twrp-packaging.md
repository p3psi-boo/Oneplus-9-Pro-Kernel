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

Use the existing build and `scripts/repack.py` flow first. Obtain official
AnyKernel3 and check out the exact commit in `anykernel3.lock.json` (not a moving
branch). Then, separately for each OS:

```sh
python3 scripts/package_twrp.py \
  --built /absolute/path/to/ci/coloros \
  --qualified /absolute/path/to/repacked/coloros \
  --os coloros --anykernel3 /absolute/path/to/AnyKernel3 \
  --output /absolute/path/to/new-output \
  --source-commit b89562fd27334bacdd050eb0ac2f5bee1abc2cbd \
  --ci-run 44478812236
python3 -m unittest discover -s tests -p 'test_twrp_packaging.py' -v
```

For OxygenOS replace all three `coloros` occurrences with `oxygenos`. Output
files are never overwritten. ZIP entries are sorted with fixed timestamps,
permissions and compression settings; reproduce with the same Python/zlib.
The packager rechecks pinned upstream bytes, manifests, ABI checks and payload
hashes, then validates all ZIP contents and emits a sidecar SHA-256. Checksums
are corruption checks, not signatures. The supplied CI commit/run fields record
the operator's provenance claim; they do not authenticate GitHub independently.
Host shell mocks test refusal and write/readback control flow, not Android
BusyBox or real block-device behavior. No device flashing was performed.

## GitHub Actions: generate the ColorOS ZIP

1. Open **Build OnePlus 9 Pro Droidspaces (experimental)** in Actions.
2. Select **Run workflow** and choose `oneplus-9-pro`.
3. Check `package_twrp`.
4. Download `twrp-experimental-oneplus-9-pro-coloros-<run number>`.
5. Extract the GitHub artifact wrapper.

The inner `*-twrp.zip` is the TWRP package. The adjacent `.zip.sha256`
file checks that package. Do not flash the GitHub artifact wrapper.

The workflow builds both ROM variants for compile checks. Only the ColorOS job
fetches the exact official stock boot, verifies the boot and ABI, and uploads a
TWRP package. The OxygenOS job produces a raw kernel review artifact only.
The workflow publishes no GitHub Release. ZIP artifacts expire after 14 days.

The workflow builds only from the default branch, `oneplus-9-pro`. A push
that changes build or packaging files runs compile checks. To generate the
ColorOS TWRP package, run the workflow manually with `package_twrp` enabled.
An OTA download or validation failure leaves no
TWRP package. The build and packaging checks do not verify device boot.
