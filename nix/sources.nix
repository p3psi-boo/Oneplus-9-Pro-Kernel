{ fetchgit, lib, project }:
let
  device = builtins.fromJSON (builtins.readFile (project + /devices/oneplus-9-pro.json));
  tools = builtins.fromJSON (builtins.readFile (project + /tools.lock.json));
  hashes = builtins.fromJSON (builtins.readFile ./sources-lock.json);
  source = role: url: rev: extra: fetchgit ({
    inherit url rev;
    hash = hashes.${role};
    leaveDotGit = false;
    fetchSubmodules = false;
  } // extra);
in {
  kernel = source "kernel" "https://github.com/${device.kernel.repository}.git" device.kernel.commit {};
  vendor = source "vendor" "https://github.com/${device.vendor.repository}.git" device.vendor.commit {};
  resukisu = source "resukisu" "https://github.com/${device.resukisu.repository}.git" device.resukisu.commit {};
  clang = source "clang" tools.android_clang.repository tools.android_clang.commit {
    sparseCheckout = [ tools.android_clang.directory ];
    leaveDotGit = false;
  };
}
