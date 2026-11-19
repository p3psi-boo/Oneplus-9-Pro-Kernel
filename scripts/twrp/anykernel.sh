#!/sbin/sh
# Guarded prequalified-image integration of pinned upstream AnyKernel3.
# It NEVER calls AK3 flash_boot/write_boot/flash_generic/dump_boot or updater modes.
set -eu
set -o pipefail
umask 077
cd "$AKHOME"
BB="$AKHOME/tools/busybox"
mkdir "$AKHOME/applets"
"$BB" --install -s "$AKHOME/applets"
export PATH="$AKHOME/applets:$AKHOME/tools:/sbin:/system/bin:/vendor/bin"
fail() { printf 'ui_print %s\nui_print\n' "$*" >> "/proc/self/fd/$OUTFD"; exit 1; }
sha256sum -c SHA256SUMS >/dev/null || fail 'Package checksum mismatch; nothing written.'
. "$AKHOME/firmware.conf"
. "$AKHOME/guard.sh"
[ "$(id -u)" = 0 ] || fail 'Recovery root required.'
[ ! -d /postinstall/tmp ] || fail 'OTA postinstall mode is unsupported.'
[ -e /twres ] || fail 'TWRP recovery required; Android app install is unsupported.'
# A recovery directory/property alone must not permit live Android flashing.
[ "$(getprop sys.boot_completed)" != 1 ] || fail 'Running Android is unsupported.'
for service in zygote zygote_secondary; do
  [ "$(getprop init.svc.$service)" != running ] || fail 'Android runtime is active.'
done
FACT_TWRP=$(getprop ro.twrp.version)
FACT_DEVICE=$(getprop ro.product.device)
FACT_FLASH_LOCKED=$(getprop ro.boot.flash.locked)
FACT_DEVICE_STATE=$(getprop ro.boot.vbmeta.device_state)
FACT_SLOT=$(getprop ro.boot.slot_suffix)
FACT_SLOT_ALT=$(getprop ro.boot.slot)
FACT_CMDLINE_SLOT=$(sed -n 's/.*androidboot.slot_suffix=\([^ ]*\).*/\1/p' /proc/cmdline)
case "$FACT_SLOT" in _a|_b) ;; *) fail 'Cannot identify the active A/B slot.' ;; esac
PARTITION="boot$FACT_SLOT"
TARGET=
BOOT_ALIAS=
for parent in /dev/block/by-name /dev/block/bootdevice/by-name; do
  candidate="$parent/$PARTITION"
  if [ -e "$candidate" ]; then
    resolved=$(readlink -f "$candidate") || fail 'Cannot resolve boot partition.'
    case "$resolved" in /dev/block/*) ;; *) fail 'Unexpected boot block path.' ;; esac
    [ -b "$resolved" ] || fail 'Boot target is not a block device.'
    [ -z "$TARGET" ] || [ "$TARGET" = "$resolved" ] || fail 'Ambiguous boot partition aliases.'
    TARGET=$resolved
    BOOT_ALIAS=$candidate
  fi
done
[ -n "$TARGET" ] || fail 'Active boot block is missing.'
FACT_SIZE=$(blockdev --getsize64 "$TARGET") || fail 'Cannot read boot block size.'
FACT_STOCK_HASH=$(sha256sum "$TARGET" | cut -d' ' -f1) || fail 'Cannot hash current boot.'
FACT_IMAGE_HASH=$(sha256sum boot.img | cut -d' ' -f1) || fail 'Cannot hash payload.'
[ "$(wc -c < boot.img | tr -d ' ')" = "$EXPECTED_SIZE" ] || fail 'Payload size mismatch.'
guard_facts || fail 'Wrong model/slot/stock firmware or modified boot. Installed recovery/root ramdisks are NOT supported; nothing written.'
# Do not source upstream AK3 core/updater: their generic modes are outside scope.
# No module helper, backup, verity/vbmeta patch, automatic mount or other slot mode.
[ "$(getprop ro.boot.slot_suffix)" = "$FACT_SLOT" ] || fail 'Active slot changed.'
[ "$(readlink -f /dev/block/by-name/$PARTITION 2>/dev/null || readlink -f /dev/block/bootdevice/by-name/$PARTITION)" = "$TARGET" ] || fail 'Boot alias changed.'
[ "$(blockdev --getsize64 "$TARGET")" = "$EXPECTED_SIZE" ] || fail 'Boot size changed.'
[ "$(sha256sum "$TARGET" | cut -d' ' -f1)" = "$EXPECTED_STOCK_HASH" ] || fail 'Boot changed during validation.'
printf 'ui_print %s\nui_print\n' "Verified exact $FIRMWARE ($ROM); writing current $PARTITION only." >> "/proc/self/fd/$OUTFD"
# The sole partition-write operation: exact-size prequalified image, no zero-fill,
# no vbmeta/verity/ramdisk edits, no backup, no slot selection or other partitions.
dd if="$AKHOME/boot.img" of="$TARGET" bs=1048576 conv=fsync || fail 'BOOT WRITE FAILED. Do not reboot; restore exact stock boot using your independent recovery plan.'
sync
[ "$(sha256sum "$TARGET" | cut -d' ' -f1)" = "$EXPECTED_IMAGE_HASH" ] || fail 'BOOT READBACK FAILED. Do not reboot; recover using your independent plan.'
printf 'ui_print %s\nui_print\n' 'Current-slot boot readback verified. Device boot success is NOT verified.' >> "/proc/self/fd/$OUTFD"
