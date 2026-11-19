# Droidspaces for OnePlus 9 Pro (experimental)

The optional build profile targets OnePlus 9 Pro (`lemonadep`), Android 14,
and the SM8350 Linux 5.4.254 source commit already registered by this fork.
ColorOS and OxygenOS are built separately from their hash-pinned stock configs.
The registered stock config files are unchanged. Normal builds do not enable
the Droidspaces networking or IPC additions.

[Droidspaces' GKI configuration guide](https://github.com/ravindu644/Droidspaces-OSS/blob/cdadb9eb5d0f86aacffff60776333e6f6b73a30a/Documentation/Kernel-Configuration.md#gki-kernels-54-and-newer)
requires relocating IPC-related fields into reserved Android ABI padding.
The OnePlus patch adapts the guide's SYSVIPC (slots 6–8) and POSIX message queue
(slot 1) patches to this exact source, retaining downstream members and
not adding the OEM member present in the generic patch. The build rejects
a different source pin rather than applying the patch with fuzz.

The profile enables six required options (SYSVIPC, POSIX message queues, IPC
and PID namespaces, devtmpfs, and xtables address-type matching) and the
recommended GKI options for user namespaces, IPv6 NAT, macvlan, firewall and
tmpfs ACLs/xattrs. It refuses to build with SUSFS and keeps forced module
loading off. It checks CFI, SELinux and module version/signing options against
the registered stock config. It leaves the ABI-breaking CPU bandwidth and PID
cgroup options disabled; the related Droidspaces limits are not supported by
this profile. As with other privileged container runtimes, only run trusted
container images.

## ranet3 Linux mesh node (experimental)

[The upstream platform guide](https://ranet3.com/docs/platforms/) requires Linux
4.20 or later for strict rtnetlink routing queries. Its
[Linux daemon guide](https://ranet3.com/docs/getting-started/) also needs TUN
and `CAP_NET_ADMIN`. TUN, IPv4/IPv6 policy routing, and conntrack are already
built in on both stock ROMs. This profile adds inet-family nftables, sets,
conntrack matches and counters for ranet3's mesh and antispoof rules.
Enabling nftables on this 5.4 tree would normally insert a field into
`struct net`; a separate patch stores the field in nftables' existing
private per-network-namespace allocation instead.

`ranet3` handles [ESP and segment steering in userspace](https://ranet3.com/docs/segment-routing/).
This profile does not enable additional kernel XFRM/IPsec or SRv6 options.
It does not claim Linux exit-node/subnet-router support (`cap.egress`):
the egress implementation uses conntrack timeout objects alongside inet NAT,
and enabling timeout support changes the stock conntrack extension layout.
Do not enable it without a separate layout, CRC and runtime audit.
Native Android builds do not implement `cap.egress` or `cap.exit` regardless
of kernel settings. For this profile the intended deployment is the **Linux**
ARM64 daemon in Droidspaces, with `/dev/net/tun` and network administration
access inside the intended namespace. Do not relax Android's SELinux policy
to work around missing device access.

Before claiming compatibility, test a two-node mesh on the matching phone:
create the TUN interface, install IPv4/IPv6 routes with `cap.table`,
check the inet nftables rules with an overlay configured, and pass traffic
in both directions. Build/ABI checks do not replace this test.

## TWRP installation ZIPs (experimental)

See [the OnePlus 9 Pro TWRP packaging and installation notes](twrp-packaging.md).
Use only the per-firmware package for the exact stock ROM and an untouched
current-slot boot partition. Do not flash a raw CI artifact in recovery.

## Build and verify

On Linux with the same dependencies as the existing repository builds:

```sh
python3 scripts/build.py --device oneplus-9-pro --os coloros --droidspaces
python3 scripts/build.py --device oneplus-9-pro --os oxygenos --droidspaces
```

The **Build OnePlus 9 Pro Droidspaces (experimental)** Actions workflow builds
both variants without packaging a boot image. Kernel-only outputs, including
the final config, System.map and provenance, are under
`out/droidspaces/oneplus-9-pro/<os>/`.

Before considering a boot image, run the existing verified repacker against
the exact registered stock boot. The repacker uses `vmlinux-to-elf==1.3.6` for
stock symbol recovery (same as the existing boot packaging workflow). For
example, for ColorOS:

```sh
python3 scripts/repack.py --device oneplus-9-pro --os coloros --layout a/b \
  --firmware 'LE2120_14.0.0.1901(CN01)' --stock /path/to/original/boot.img \
  --stock-sha256 880506483c3d12c1dbfb30548fc67122fd026a03abe09aae0489a47f84408a85 \
  --built out/droidspaces/oneplus-9-pro/coloros \
  --output out/droidspaces/oneplus-9-pro/coloros-boot
```

For OxygenOS, use the corresponding manifest entries (`LE2121_14.0.0.1902(EX01)`)
and separate build/output directories. The repacker requires a full stock
export/CRC match on SM8350 and does not allow force-loading around ABI errors.
A build or a passing CRC comparison is not a boot or runtime certification.
After testing a matching build on-device, run **Droidspaces → Settings →
Requirements → Check Requirements** and verify container boot and networking,
plus Android touch, Wi-Fi, camera and fingerprint regressions.
