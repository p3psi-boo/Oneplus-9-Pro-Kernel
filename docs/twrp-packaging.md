# Restricted TWRP packages: OnePlus 9 Pro

Experimental, **not device-tested**. Only `lemonadep`, an unlocked bootloader,
A/B **current boot slot**, and these separate exact stock baselines are supported:

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

## GitHub Actions: generate actual ZIPs

`Build OnePlus 9 Pro Droidspaces (experimental)` now has an **opt-in packaging
stage**, not only a kernel artifact. It builds both variants from the checked-out
commit, downloads each exact official stock boot through
`fetch_oneplus9pro_stock_boot.py`, verifies its registered SHA-256/size, performs
strict repack/ABI qualification, and packages against pinned official AnyKernel3.
There are no private download URLs, secrets, vendor binaries checked into Git,
release publishing, merges, or device operations.

### While this work remains on the draft PR

GitHub does not reliably expose `workflow_dispatch` for a new workflow until it
exists on the default branch. Use the existing `pull_request` event instead:

1. A repository maintainer reviews the **current PR head** and workflow changes.
2. On the same-repository PR targeting `oneplus-9-pro`, add label `build-twrp`.
   If already present, remove it and re-add it. Creating the label alone does not
   start a run. Adding it starts the two-ROM matrix for that head commit.
3. Find the labeled-event run of the above workflow. On success, download
   `twrp-experimental-oneplus-9-pro-coloros-<run number>` and the separate
   `twrp-experimental-oneplus-9-pro-oxygenos-<run number>` artifacts.
4. Extract the GitHub artifact wrapper. The **inner** `...-twrp.zip` is the
   flashable-format package; its adjacent `.zip.sha256` checks that exact ZIP.
   The artifact wrapper is not flashable. Inspect `build.json` inside the ZIP
   for the exact source commit, run ID and qualification evidence.

Only the fresh `labeled` event with the exact label and a same-repository head
can enable PR packaging. Ordinary PR opens/updates continue compile-only even
if the label remains present. Fork PRs cannot enable this label packaging path.
A new commit needs review and another explicit remove/re-add label event.
The workflow uses `pull_request`, **not** `pull_request_target`; permissions are
read-only, checkout credentials are not persisted, and no secrets are passed.
Repository Actions approval/settings can still block a run. The relevant changed
paths must match the existing workflow path filter, as they do for this PR.

### After dispatch becomes available

In Actions, choose this workflow, **Run workflow**, the intended branch, and
check `package_twrp`. Leaving it unchecked builds kernel-review artifacts only.
An equivalent CLI invocation is:

```sh
gh workflow run droidspaces.yml --ref YOUR_REVIEWED_BRANCH -f package_twrp=true
```

Each ROM runs in parallel on its own runner. Budget roughly **45–120 minutes**
plus queue time for a clean end-to-end build; the job has a 120-minute limit.
This is a planning estimate, not a completed hosted packaging benchmark.
Stock-host outages/range failures, hash mismatches, ABI mismatch or upstream
changes fail closed, and that ROM produces no TWRP artifact. The independent ROM
may still succeed; never substitute its ZIP. Kernel-only review artifacts may
remain available even when packaging fails. Artifacts expire after 14 days.

Workflow structure and packaging are host-tested; the newly added full hosted
pipeline must run successfully before its end-to-end result is claimed. No run
is started merely by documenting this workflow, and no release is published.
