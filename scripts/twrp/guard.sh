# Pure validation shared with host tests. No I/O or writes here.
guard_facts() {
  [ "$FACT_TWRP" != '' ] || return 1
  case "$FACT_DEVICE" in lemonadep|OnePlus9Pro) ;; *) return 1 ;; esac
  case "$FACT_FLASH_LOCKED" in ''|0) ;; *) return 1 ;; esac
  case "$FACT_DEVICE_STATE" in ''|unlocked) ;; *) return 1 ;; esac
  [ "$FACT_FLASH_LOCKED" = 0 ] || [ "$FACT_DEVICE_STATE" = unlocked ] || return 1
  case "$FACT_SLOT" in _a|_b) ;; *) return 1 ;; esac
  [ -z "$FACT_SLOT_ALT" ] || [ "_$FACT_SLOT_ALT" = "$FACT_SLOT" ] || return 1
  [ -z "$FACT_CMDLINE_SLOT" ] || [ "$FACT_CMDLINE_SLOT" = "$FACT_SLOT" ] || return 1
  [ "$FACT_SIZE" = "$EXPECTED_SIZE" ] || return 1
  [ "$FACT_STOCK_HASH" = "$EXPECTED_STOCK_HASH" ] || return 1
  [ "$FACT_IMAGE_HASH" = "$EXPECTED_IMAGE_HASH" ] || return 1
}
