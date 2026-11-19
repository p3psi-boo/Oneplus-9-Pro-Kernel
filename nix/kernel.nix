{ lib, stdenv, project, fetchgit, writeShellScript, runCommand
, python3, git, gnumake, bc, bison, flex, perl, pkg-config, openssl
, elfutils, zlib, ncurses5, libxml2, protobufc, protobuf, pahole
, patchelf, file, cpio, which, rsync, pkgsCross, glibc }:
let
  sources = import ./sources.nix { inherit fetchgit lib project; };
  aarch64 = pkgsCross.aarch64-multiplatform.stdenv.cc;
  arm = pkgsCross.arm-embedded.stdenv.cc;
  # Kbuild's legacy spellings are intentionally kept; aliases point to pinned
  # Nix cross compilers rather than accidentally finding host distribution tools.
  crossAliases = runCommand "oneplus-cross-prefixes" {} ''
    mkdir -p "$out/bin"
    for tool in ${aarch64}/bin/aarch64-unknown-linux-gnu-* ${aarch64.bintools}/bin/aarch64-unknown-linux-gnu-*; do
      ln -sf "$tool" "$out/bin/aarch64-linux-gnu-''${tool##*aarch64-unknown-linux-gnu-}"
    done
    for tool in ${arm}/bin/arm-none-eabi-* ${arm.bintools}/bin/arm-none-eabi-*; do
      ln -sf "$tool" "$out/bin/arm-linux-gnueabi-''${tool##*arm-none-eabi-}"
    done
  '';
  prepareClang = writeShellScript "prepare-pinned-android-clang" ''
    set -euo pipefail
    root="$1"
    chmod -R u+w "$root"
    while IFS= read -r -d "" binary; do
      # Static Go wrappers and non-ELF resources require no loader alteration.
      if ${patchelf}/bin/patchelf --print-needed "$binary" >/dev/null 2>&1; then
        if ${patchelf}/bin/patchelf --print-interpreter "$binary" >/dev/null 2>&1; then
          ${patchelf}/bin/patchelf --set-interpreter '${stdenv.cc.bintools.dynamicLinker}' "$binary"
        fi
        ${patchelf}/bin/patchelf --set-rpath "$root/lib64:${lib.makeLibraryPath [ stdenv.cc.cc.lib zlib ncurses5 libxml2 ]}" "$binary"
      fi
    done < <(find "$root/bin" "$root/lib64" -type f -print0)
    # AOSP LLD 11 supports --no-threads, not newer --threads=N syntax.
    # Bound final LTO memory without disabling LTO, CFI, or ABI checks.
    test -L "$root/bin/ld.lld"
    rm "$root/bin/ld.lld"
    cat > "$root/bin/ld.lld" <<EOF
#!${stdenv.shell}
exec "$root/bin/lld" -flavor gnu --no-threads --thinlto-jobs=1 "\$@"
EOF
    chmod +x "$root/bin/ld.lld"
  '';
  hostClang = writeShellScript "nix-host-cfi-clang" ''
    exec clang \
      --gcc-toolchain=${stdenv.cc.cc} \
      -B${glibc}/lib \
      -isystem ${lib.getDev glibc}/include -isystem ${lib.getDev protobufc}/include \
      -L${glibc}/lib -L${lib.getLib protobufc}/lib -L${stdenv.cc.cc.lib}/lib \
      -Wl,--dynamic-linker,${stdenv.cc.bintools.dynamicLinker} \
      -Wl,-rpath,${lib.makeLibraryPath [ glibc protobufc stdenv.cc.cc.lib ]} "$@"
  '';
  prepareSources = writeShellScript "prepare-kernel-shebangs" ''
    set -eo pipefail
    # Reuse stdenv's exact interpreter resolver after source integrity checks.
    source ${stdenv}/setup
    patchShebangs --build "$1" "$2" "$(readlink -f "$3")"
    # This Kconfig probe links a HOST executable, unlike target compilation.
    # Actually test the same pinned clang with Nix host libc paths; do not force
    # CC_CAN_LINK/UAPI_HEADER_TEST or change the target compiler flags.
    substituteInPlace "$1/init/Kconfig" \
      --replace-fail '$(srctree)/scripts/cc-can-link.sh $(CC)' '$(srctree)/scripts/cc-can-link.sh $(HOST_CLANG)'
    substituteInPlace "$3/kernel/Kbuild" \
      --replace-fail 'GIT_BIN := /usr/bin/env PATH="$$PATH":/usr/bin:/usr/local/bin git' 'GIT_BIN := git'
  '';
in stdenv.mkDerivation {
  pname = "oneplus-9-pro-coloros-droidspaces-kernel";
  version = "5.4.254-experimental";
  src = lib.cleanSourceWith {
    src = project;
    filter = path: type:
      let relative = lib.removePrefix (toString project + "/") (toString path);
          top = builtins.head (lib.splitString "/" relative);
      in builtins.elem top [ "scripts" "configs" "patches" "compat" "devices" "device.json" "tools.lock.json" ]
        && builtins.baseNameOf path != "__pycache__"
        && !lib.hasSuffix ".pyc" relative;
  };
  nativeBuildInputs = [ python3 git gnumake bc bison flex perl pkg-config protobufc protobuf
    pahole patchelf file cpio which rsync crossAliases ];
  buildInputs = [ openssl elfutils zlib protobufc ];
  strictDeps = true;
  hardeningDisable = [ "all" ];
  dontConfigure = true;
  dontFixup = true; # Never strip or alter a verified kernel or its manifest.
  enableParallelBuilding = true;
  # Only a clean Git-backed flake has rev. Path/dirty evaluations must not claim
  # provenance they cannot establish; downstream qualification rejects null.
  sourceCommitJSON = builtins.toJSON (project.rev or null);
  buildPhase = ''
    runHook preBuild
    export HOME="$TMPDIR/home"
    mkdir -p "$HOME"
    export SOURCE_DATE_EPOCH=1735689600
    export HOST_CLANG=${hostClang}
    python3 scripts/build.py --device oneplus-9-pro --os coloros --droidspaces \
      --kernel-source ${sources.kernel} --vendor-source ${sources.vendor} \
      --resukisu-source ${sources.resukisu} --clang-source ${sources.clang} \
      --prepare-clang-command ${prepareClang} \
      --prepare-sources-command ${prepareSources} \
      --work-root "$TMPDIR/kernel-work" --output-root "$TMPDIR/artifacts" \
      --jobs "$NIX_BUILD_CORES"
    runHook postBuild
  '';
  installPhase = ''
    mkdir -p "$out"
    cp -a "$TMPDIR/artifacts/droidspaces/oneplus-9-pro/coloros/." "$out/"
    python3 - "$out/build.json" <<'PY'
import json, os, pathlib, re, sys
path = pathlib.Path(sys.argv[1])
manifest = json.loads(path.read_text())
revision = json.loads(os.environ["sourceCommitJSON"])
if revision is not None and not re.fullmatch(r"[0-9a-f]{40}", revision):
    raise SystemExit("Invalid clean Git source revision")
manifest["source_commit"] = revision
path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
PY
    for required in Image build.json kernel.config System.map Module.symvers; do
      test -s "$out/$required"
    done
  '';
  passthru = { inherit sources prepareClang prepareSources hostClang crossAliases; };
  meta = { platforms = [ "x86_64-linux" ]; license = lib.licenses.gpl2Only;
    description = "Sandbox-built experimental kernel; strict ABI repack and real-device validation remain separate gates"; };
}
