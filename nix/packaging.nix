{ lib, python3, python3Packages, sqlite, fetchurl, writeShellApplication
, git, openssl, cacert, project }:
let
  minilzo = python3Packages.buildPythonPackage {
    pname = "minilzo";
    version = "1.2";
    pyproject = true;
    src = fetchurl {
      url = "https://files.pythonhosted.org/packages/9f/cf/70409b35fbd32f5456fe72f410bf5fb30e279d3226e8a2228f11daede5f7/minilzo-1.2.tar.gz";
      hash = "sha256-TNzA3D6FWKKdim/tXGahrjyAFOEtCidVSJDEJI92sUE=";
    };
    build-system = [ python3Packages.setuptools ];
    pythonImportsCheck = [ "minilzo" ];
  };
  # Match the dependency proven against the official stock Image. Peewee 3
  # leaves the release-date column as a raw string in this upstream database.
  peewee = python3Packages.buildPythonPackage {
    pname = "peewee";
    version = "4.5.3";
    pyproject = true;
    src = fetchurl {
      url = "https://files.pythonhosted.org/packages/6f/85/8142c26b9942e2993fdcd9163089a8531ac255aecef1ca4cc1b611e8d193/peewee-4.5.3.tar.gz";
      hash = "sha256-Q0V2r6+AZCigH4SvdMQv3lk3LE9qbrom2bU3IRM0Soo=";
    };
    build-system = with python3Packages; [ setuptools cython ];
    buildInputs = [ sqlite ];
    pythonImportsCheck = [ "peewee" ];
  };
  vmlinuxToElf = python3Packages.buildPythonPackage {
    pname = "vmlinux-to-elf";
    version = "1.3.6";
    format = "wheel";
    src = fetchurl {
      url = "https://files.pythonhosted.org/packages/20/a8/13194b1110268f73f346d84654047233f2ba72f5f10c97eee70b2efe15a9/vmlinux_to_elf-1.3.6-py3-none-any.whl";
      hash = "sha256-Yil31Qa0TjcYdgaJ4Zbl73af+gyGTmTQg2UdtxMiHLU=";
    };
    dependencies = [ minilzo peewee ] ++ (with python3Packages; [ lz4 zstandard ]);
    pythonImportsCheck = [ "vmlinux_to_elf.scripts.kallsyms_finder" ];
  };
  python = python3.withPackages (_: [ vmlinuxToElf ]);
  tools = builtins.fromJSON (builtins.readFile (project + /tools.lock.json));
  magiskApk = fetchurl {
    inherit (tools.magiskboot) url sha256;
  };
  sources = lib.cleanSourceWith {
    src = project;
    filter = path: _:
      let relative = lib.removePrefix (toString project + "/") (toString path);
          top = builtins.head (lib.splitString "/" relative);
      in builtins.baseNameOf (toString path) != "__pycache__" && !lib.hasSuffix ".pyc" (toString path)
        && (builtins.elem top [
          "scripts" "configs" "patches" "compat" "devices"
          "device.json" "tools.lock.json" "anykernel3.lock.json"
        ] || builtins.elem relative [ "docs" "docs/twrp-packaging.md" ]);
  };
in writeShellApplication {
  name = "coloros-pipeline";
  runtimeInputs = [ git openssl ];
  text = ''
    unset PYTHONHOME PYTHONPATH
    export PYTHONNOUSERSITE=1
    export SSL_CERT_FILE="''${SSL_CERT_FILE:-${cacert}/etc/ssl/certs/ca-bundle.crt}"
    export GIT_SSL_CAINFO="''${GIT_SSL_CAINFO:-$SSL_CERT_FILE}"
    export COLOROS_MAGISK_APK=${magiskApk}
    exec ${python}/bin/python3 ${sources}/scripts/package_ci_coloros.py "$@"
  '';
}
