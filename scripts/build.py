"""Experimental Linux compile; a successful compile is not device validation."""
import argparse
import datetime
import json
import os
import pathlib
import re
import shutil
import stat
import subprocess
import time
from kernel_release import SUFFIX, branded_release
import droidspaces
from resukisu_source import resolve as resolve_resukisu
from toolchain import compiler_tree_sha256, configure, local_git, local_git_env, local_revision
from prepare_protocol import prepare
from module_trust import install as install_module_trust, verify_embedded
from project import ROOT, PATCHES, device, run, save, sha256

def checkout(repo, commit, dest, shallow=True):
    last = None
    for attempt in range(4):
        try:
            if os.path.isdir(dest):
                shutil.rmtree(dest)
            run("git", "init", "--quiet", dest)
            run("git", "remote", "add", "origin", "https://github.com/" + repo + ".git", cwd=dest)
            command = ["git", "fetch", "--no-tags"]
            if shallow:
                command += ["--depth=1"]
            run(*command, "origin", commit, cwd=dest)
            run("git", "checkout", "--detach", "FETCH_HEAD", cwd=dest)
            actual = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=dest, text=True).strip()
            if actual != commit:
                raise ValueError("Source commit mismatch")
            return
        except Exception as error:
            last = error
            print("checkout %s attempt %d failed: %s" % (repo, attempt + 1, error), flush=True)
            time.sleep(10 + attempt * 15)
    raise RuntimeError("checkout failed for " + repo + ": " + str(last))

def checkout_local(source, commit, dest, full_history=False):
    source = local_revision(source, commit)
    if full_history and local_git(source, "rev-parse", "--is-shallow-repository") != "false":
        raise ValueError("Offline ReSukiSU checkout requires complete Git history")
    # Fetch only committed objects from the local repository, not its working
    # tree. file:// transport also works with read-only stores under another uid.
    dest.mkdir(parents=True, exist_ok=False)
    run("git", "init", "--quiet", env=local_git_env(), cwd=dest)
    fetch = ["git", "-c", "safe.directory=" + str(source), "fetch", "--no-tags"]
    if not full_history:
        fetch.append("--depth=1")
    run(*fetch, source.as_uri(), commit, env=local_git_env(), cwd=dest)
    local_git(dest, "checkout", "--detach", "FETCH_HEAD")
    local_revision(dest, commit)
    if full_history and local_git(dest, "rev-parse", "--is-shallow-repository") != "false":
        raise ValueError("Staged ReSukiSU checkout lost its complete history")


def verify_gitless_source(source, commit, lock, role):
    if lock.get("commit") != commit or not lock.get("tree_sha256"):
        raise ValueError("No matching Gitless lock for " + role)
    if compiler_tree_sha256(source) != lock["tree_sha256"]:
        raise ValueError("Gitless source tree differs from the locked digest: " + role)


def stage_gitless_source(source, dest):
    shutil.copytree(source, dest, symlinks=True)
    for item in (dest, *dest.rglob("*")):
        if not item.is_symlink():
            item.chmod(item.stat().st_mode | stat.S_IWUSR)


def adapt_gitless_ksu_version(ksu, lock):
    """Use the pinned upstream commit metadata without manufacturing a Git repository."""
    count, tag, commit = lock.get("revision_count"), lock.get("tag"), lock.get("commit")
    if (not isinstance(count, int) or count < 1 or not isinstance(tag, str)
            or not re.fullmatch(r"v[0-9]+(?:\.[0-9]+)+", tag)
            or not isinstance(commit, str) or not re.fullmatch(r"[a-f0-9]{40}", commit)):
        raise ValueError("Invalid Gitless ReSukiSU version lock")
    dirty = compiler_tree_sha256(ksu) != lock["tree_sha256"]
    kbuild = ksu / "kernel/Kbuild"
    text = kbuild.read_text(encoding="utf-8")
    begin = "LOCAL_GIT_EXISTS :="
    end = "# call subst to process placeholders"
    if text.count(begin) != 1 or text.count(end) != 1 or text.index(begin) >= text.index(end):
        raise ValueError("Unexpected pinned ReSukiSU Kbuild version section")
    # The legacy checkout is detached and deliberately fetches no tags.
    # Preserve the probed version count and name, including the dirty flag.
    metadata = (
        "ifdef KBUILD_EXTMOD\ninclude $(KSU_SRC)/tools/ddk_compatible.mk\nendif\n\n"
        f"KSU_LOCAL_VERSION := {count}\n"
        "KSU_VERSION := $(shell expr 30000 + $(KSU_LOCAL_VERSION) + 700)\n"
        f"KSU_TAG_NAME := {tag}\n"
        f"KSU_COMMIT_SHA := {commit[:8]}{'-dirty' if dirty else ''}\n"
        "KSU_BRANCH_NAME :=\n\n"
    )
    kbuild.write_text(text[:text.index(begin)] + metadata + text[text.index(end):], encoding="utf-8")


def offline_build_env(source, epoch=None):
    if epoch is None:
        epoch = local_git(source, "log", "-1", "--format=%ct")
    epoch = int(epoch)
    if epoch < 0:
        raise ValueError("SOURCE_DATE_EPOCH cannot be negative")
    stamp = time.strftime("%a %b %d %H:%M:%S UTC %Y", time.gmtime(epoch))
    return dict(local_git_env(), SOURCE_DATE_EPOCH=str(epoch), LC_ALL="C", TZ="UTC",
                KBUILD_BUILD_TIMESTAMP=stamp, KBUILD_BUILD_USER="nix", KBUILD_BUILD_HOST="builder",
                KBUILD_BUILD_VERSION="1")


def build(name, config=None, rom='coloros', diagnostics_only=False, with_droidspaces=False, *,
          kernel_source=None, vendor_source=None, resukisu_source=None, clang_source=None,
          work_root=None, output_root=None, jobs=None, prepare_clang_command=None,
          prepare_sources_command=None):
    if os.name != "posix":
        raise RuntimeError("Build on Linux (GitHub Actions or WSL)")
    data = device(name)
    local_sources = {"kernel": kernel_source, "vendor": vendor_source, "resukisu": resukisu_source}
    gitless_locks = {}
    offline = any(value is not None for value in (*local_sources.values(), clang_source))
    if offline and (not all(value is not None for value in local_sources.values())
                    or clang_source is None or data["platform"] != "sm8350"):
        raise ValueError("Offline SM8350 builds require all four locked source checkout paths")
    if prepare_sources_command is not None and not offline:
        raise ValueError("Preparing sources requires locked offline inputs")
    if jobs is not None and jobs < 0:
        raise ValueError("--jobs cannot be negative")
    job_option = "-j" + str(jobs or os.cpu_count() or 2)
    work_root = pathlib.Path(work_root or ROOT / ".work").resolve()
    output_root = pathlib.Path(output_root or ROOT / "out").resolve()

    def checkout_stage(role, destination, shallow=True):
        origin = data[role]
        if role in gitless_locks:
            stage_gitless_source(local_sources[role], destination)
        elif offline:
            checkout_local(local_sources[role], origin["commit"], destination, full_history=not shallow)
        else:
            checkout(origin["repository"], origin["commit"], destination, shallow)

    if with_droidspaces:
        droidspaces.require_device(data)
        if config is not None:
            raise ValueError("Droidspaces requires the registered stock seed config")
        if os.environ.get("SUSFS") == "1":
            raise ValueError("Droidspaces profile does not support building with SUSFS")
    artifact_root = output_root / name / rom
    if with_droidspaces:
        artifact_root = output_root / "droidspaces" / name / rom
    resukisu_selection = {"mode": "pinned", "baseline_commit": data["resukisu"]["commit"], "requested_ref": "pinned", "resolved_ref": "refs/heads/pinned"}
    print("Latest ReSukiSU:", data["resukisu"]["repository"], data["resukisu"]["commit"], flush=True)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as summary:
            summary.write("Latest ReSukiSU: [" + data["resukisu"]["commit"] + "](https://github.com/" + data["resukisu"]["repository"] + "/commit/" + data["resukisu"]["commit"] + ")\n\n")
    firmware = data["firmware"][rom]
    if offline:
        source_locks = json.loads((ROOT / "tools.lock.json").read_text(encoding="utf-8")).get("offline_source_trees", {})
        for role, path in local_sources.items():
            path = pathlib.Path(path).resolve()
            commit = data[role]["commit"]
            if (path / ".git").exists():
                local_revision(path, commit)
            else:
                lock = source_locks.get(role, {})
                verify_gitless_source(path, commit, lock, role)
                gitless_locks[role] = lock
            local_sources[role] = path
    compiler_lock = configure(data["platform"], source=clang_source, work_root=work_root,
                              prepare_command=prepare_clang_command)
    stock_config = config is None
    if config is None:
        if not firmware.get("config"):
            raise RuntimeError("No verified stock config for " + name + "/" + rom)
        config = ROOT / firmware["config"]
        if sha256(config) != firmware["config_sha256"]:
            raise ValueError("Registered stock config checksum mismatch")
    for program in ("git", "make", "clang", "ld.lld", "aarch64-linux-gnu-gcc", "arm-linux-gnueabi-gcc"):
        if not shutil.which(program):
            raise RuntimeError("Missing build dependency: " + program)
    work = work_root / (name + "-" + (rom if offline else datetime.datetime.now().strftime("%Y%m%d%H%M%S")))
    work.mkdir(parents=True, exist_ok=False)
    source, output = work / "kernel" / ("msm-" + ".".join(data["kernel"]["version"].split(".")[:2])), work / "obj"
    checkout_stage("kernel", source)
    modules = work / "modules"
    checkout_stage("vendor", modules)
    vendor_patch = ROOT / "patches" / ("vendor-" + {"oneplus-8-pro": "oneplus-8", "oneplus-9-pro": "oneplus-9"}.get(name, name) + ".patch")
    if vendor_patch.exists():
        run("git", "apply", "--check", vendor_patch, cwd=modules)
        run("git", "apply", vendor_patch, cwd=modules)
    module_trust = install_module_trust(firmware, source)
    protocol = prepare(modules, data, host_clang=os.environ.get("HOST_CLANG") if offline else None)
    (work / "vendor").symlink_to(modules / "vendor", target_is_directory=True)
    overlay = modules / "kernel" / source.name
    for item in overlay.rglob("*"):
        if item.is_dir() and not item.is_symlink():
            continue
        target = source / item.relative_to(overlay)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() or target.is_symlink():
            if item.is_symlink() and target.is_symlink() and os.readlink(item) == os.readlink(target):
                continue
            if not item.is_symlink() and not target.is_symlink() and sha256(item) == sha256(target):
                continue
            raise RuntimeError("Vendor overlay conflicts with kernel source: " + str(target))
        if item.is_symlink():
            target.symlink_to(os.readlink(item))
        else:
            shutil.copyfile(item, target)
    if with_droidspaces:
        droidspaces.apply_patch(source)
    want_susfs = os.environ.get("SUSFS") == "1"
    print("SUSFS: " + ("enabled" if want_susfs else "disabled"), flush=True)
    susfs_patch = ROOT / "patches" / "susfs-v2.patch"
    if want_susfs and susfs_patch.exists():
        print("Applying susfs patch BEFORE KernelSU patches", flush=True)
        subprocess.run(["patch", "-p1", "-F3", "--forward", "-i", str(susfs_patch)],
                       cwd=source, check=False, text=True)
    patch = ROOT / "patches" / (PATCHES[name] + ".patch")
    compat_patch = ROOT / "patches" / ("compat-" + data["platform"] + ".patch")
    kernel_patches = [patch]
    if compat_patch.exists():
        kernel_patches.append(compat_patch)
    for kernel_patch in kernel_patches:
        if with_droidspaces:
            run("git", "apply", "--check", kernel_patch, cwd=source)
            run("git", "apply", kernel_patch, cwd=source)
        else:
            subprocess.run(["patch", "-p1", "-F3", "--forward", "-i", str(kernel_patch)],
                           cwd=source, check=False)
    for rel, fname in (("include/linux/susfs.h", "susfs.h"), ("include/linux/susfs_def.h", "susfs_def.h"),
                       ("fs/susfs.c", "susfs.c")):
        if not want_susfs:
            break
        hdr = ROOT / "patches" / "files" / fname
        if hdr.exists():
            shutil.copyfile(hdr, source / rel)
            print("installed header " + rel, flush=True)
    for rel, fname in ():
        override = ROOT / "patches" / "files" / fname
        if override.exists():
            shutil.copyfile(override, source / rel)
            print("overrode " + rel, flush=True)

    checkout_stage("resukisu", source / "KernelSU", shallow=False)
    (source / "drivers/kernelsu").symlink_to("../KernelSU/kernel", target_is_directory=True)

    kcfg = source / "KernelSU" / "kernel" / "Kconfig"
    if kcfg.exists():
        kl = kcfg.read_text(encoding="utf-8").splitlines()
        if any(l.strip() == "config KSU_SUSFS" for l in kl) and "SUSFS_STANDALONE" not in "\n".join(kl):
            i = next(k for k, l in enumerate(kl) if l.strip() == "config KSU_SUSFS")
            kl[i:i] = ["# SUSFS_STANDALONE", "endchoice", ""]
            j = next((k for k in range(i + 4, len(kl)) if kl[k].strip() == "endchoice"), None)
            if j is not None:
                del kl[j]
            for k in range(i, min(i + 8, len(kl))):
                if kl[k].strip().startswith("depends on THREAD_INFO_IN_TASK"):
                    kl[k] = "\tdepends on KSU && THREAD_INFO_IN_TASK && 64BIT"
                    break
            kcfg.write_text("\n".join(kl) + "\n", encoding="utf-8")
            print("SUSFS moved out of hook choice", flush=True)

    # SUSFS selects the same symbol namespace as the tracepoint branch, so the
    # manual-hook branch must win whenever manual hooking is enabled.
    ksu_int = source / "KernelSU" / "kernel" / "runtime" / "ksud_integration.c"
    if ksu_int.exists():
        text = ksu_int.read_text(encoding="utf-8")
        old = "#elif defined(CONFIG_KSU_SUSFS)\n"
        new = "#elif defined(CONFIG_KSU_SUSFS) && !defined(CONFIG_KSU_MANUAL_HOOK)\n"
        if old in text and new not in text:
            ksu_int.write_text(text.replace(old, new, 1), encoding="utf-8")
            print("ksud_integration: manual hook branch preferred", flush=True)

    # KSU's ksu_hook_init() selects exactly one hook method. With both
    # MANUAL_HOOK and SUSFS enabled the manual branch wins and susfs_init()
    # is never reached, leaving susfs_extra_works uninitialised.
    ksu_init_c = source / "KernelSU" / "kernel" / "core" / "init.c"
    if want_susfs and ksu_init_c.exists():
        text = ksu_init_c.read_text(encoding="utf-8")
        at = text.find("ksu_hook_init")
        marker = "#endif\n#elif defined(CONFIG_KSU_SUSFS)"
        if at >= 0 and marker in text[at:] and "susfs_init();" not in text[at:].split(marker, 1)[0]:
            head, tail = text[:at], text[at:]
            tail = tail.replace(marker,
                                "#endif\n#ifdef CONFIG_KSU_SUSFS\n    susfs_init();\n#endif\n"
                                "#elif defined(CONFIG_KSU_SUSFS)", 1)
            ksu_init_c.write_text(head + tail, encoding="utf-8")
            print("ksu core/init.c: susfs_init() forced for the manual hook branch", flush=True)

    fs_makefile = source / "fs" / "Makefile"
    if want_susfs:
        # The susfs hunks reference VMA_PAD_START/VMA_PAD_END in task_mmu.c, but
        # the patch guards its own #include with a different CONFIG combination.
        # Make the header reachable for every feature subset.
        tm = source / "fs" / "proc" / "task_mmu.c"
        if tm.exists():
            text = tm.read_text(encoding="utf-8")
            if "susfs_def.h" not in text:
                lines = text.splitlines(keepends=True)
                for i, line in enumerate(lines):
                    if line.startswith("#include"):
                        lines.insert(i + 1, "#include <linux/susfs_def.h>\n")
                        break
                tm.write_text("".join(lines), encoding="utf-8")
                print("fs/proc/task_mmu.c: susfs_def.h include forced", flush=True)
    if want_susfs and fs_makefile.exists() and "susfs.o" not in fs_makefile.read_text(encoding="utf-8"):
        with fs_makefile.open("a", encoding="utf-8") as stream:
            stream.write("\nobj-$(CONFIG_KSU_SUSFS)\t+= susfs.o\n")
        print("fs/Makefile: susfs.o registered", flush=True)

    for path, addition in (
        ("drivers/Makefile", "\nobj-$(CONFIG_KSU) += kernelsu/\n"),
        ("drivers/Kconfig", '\nsource "drivers/kernelsu/Kconfig"\n'),
    ):
        with (source / path).open("a", encoding="utf-8") as stream:
            stream.write(addition)
    if "resukisu" in gitless_locks:
        adapt_gitless_ksu_version(source / "KernelSU", gitless_locks["resukisu"])
    pinned_epoch = gitless_locks.get("kernel", {}).get("commit_epoch")
    epoch = os.environ.get("SOURCE_DATE_EPOCH", pinned_epoch)
    env = offline_build_env(source, epoch) if offline else dict(os.environ)
    env.update(ARCH="arm64", SUBARCH="arm64")
    if prepare_sources_command is not None:
        command = pathlib.Path(prepare_sources_command).resolve()
        if not command.is_file():
            raise ValueError("Invalid source preparation command: " + str(command))
        run(command, source, modules, source / "KernelSU", env=env)
    output.mkdir()
    native_features = {}
    if data["platform"] == "sm8250":
        # Android normally exports these variables to every recursive make.
        # Reading the include in the top-level make alone does not export them.
        feature_file = source / "oplus_native_features.mk"
        for line in feature_file.read_text().splitlines():
            match = re.fullmatch(r"([A-Z][A-Z0-9_]*)=(.*)", line.strip())
            if match:
                native_features[match[1]] = match[2]
        if not native_features:
            raise ValueError("Official native feature assignments are missing")
        env.update(native_features)
    linker = "aarch64-linux-gnu-ld" if data["platform"] == "sm8250" else "ld.lld"
    # Versioned stock modules retain their CRC and signature checks.
    stock_release = firmware.get("kernel_release")
    release = branded_release(stock_release)
    if release:
        if not release.startswith(data["kernel"]["version"]):
            raise RuntimeError("Stock kernel version differs from source baseline")
        (source / ".scmversion").write_text("", encoding="utf-8")

    options = ["make", "-C", str(source), "O=" + str(output), "ARCH=arm64",
               "CC=clang", "LD=" + linker, "AR=llvm-ar", "NM=llvm-nm",
               "OBJCOPY=" + ("aarch64-linux-gnu-objcopy" if data["platform"] == "sm8250" else "llvm-objcopy"), "OBJDUMP=llvm-objdump", "STRIP=llvm-strip",
               "CLANG_TRIPLE=aarch64-linux-gnu-", "CROSS_COMPILE=aarch64-linux-gnu-",
               "CROSS_COMPILE_ARM32=arm-linux-gnueabi-"]
    options += ["OPLUS_FEATURE_SECURE_GUARD=" + ("yes" if data["platform"] == "sm8250" else "no"), "OPLUS_FEATURE_SECURE_ROOTGUARD=no",
                "OPLUS_FEATURE_SECURE_MOUNTGUARD=no", "OPLUS_FEATURE_SECURE_EXECGUARD=no",
                "OPLUS_FEATURE_SECURE_KEYINTERFACESGUARD=no"]
    if data["platform"] == "sm8250":
        options += ["KCFLAGS=-gdwarf-4", "BRAND_SHOW_FLAG=oneplus"]
    if config:
        shutil.copyfile(config, output / ".config")
    else:
        target = data["kernel"]["defconfig"]
        if data["platform"] == "sm8350":
            target = "vendor/lahaina-qgki_defconfig"
            run("bash", "scripts/gki/generate_defconfig.sh", target, cwd=source, env=env)
        run(*options, target, env=env)
    translations = {}
    if data["platform"] == "sm8350":
        stock_lines = (output / ".config").read_text().splitlines()
        for line in stock_lines:
            if line.startswith("CONFIG_OPPO_FINGERPRINT") and "=" in line:
                key, value = line.split("=", 1)
                translations[key] = key.replace("CONFIG_OPPO_", "CONFIG_OPLUS_", 1)
                with (output / ".config").open("a") as stream:
                    stream.write(translations[key] + "=" + value + "\n")
    fragment = (ROOT / "configs/resukisu.config").read_text(encoding="utf-8")
    if not want_susfs:
        fragment = "\n".join(
            "# CONFIG_KSU_SUSFS is not set" if line.strip() == "CONFIG_KSU_SUSFS=y" else line
            for line in fragment.splitlines())
    else:
        disable = [x.strip() for x in os.environ.get("SUSFS_DISABLE", "").split(",") if x.strip()]
        if disable:
            drop = set("CONFIG_" + d + "=y" for d in disable)
            fragment = "\n".join(l for l in fragment.splitlines() if l.strip() not in drop)
            fragment += "\n" + "\n".join("# CONFIG_" + d + " is not set" for d in disable)
            fragment += "\nCONFIG_BOOTPARAM_HUNG_TASK_PANIC=y"
            print("SUSFS disabled features: " + ", ".join(disable), flush=True)
    # A missing trailing newline would glue CONFIG_LOCALVERSION onto the last
    # fragment line, silently dropping the release suffix.
    fragment = fragment.rstrip("\n") + "\n"
    with (output / ".config").open("a", encoding="utf-8") as stream:
        stream.write("\n" + fragment)
        if module_trust:
            stream.write('CONFIG_SYSTEM_TRUSTED_KEYS="certs/stock-trusted.pem"\n')
        if release:
            stream.write('CONFIG_LOCALVERSION="' + release[len(data["kernel"]["version"]):] + '"\n')
            stream.write("# CONFIG_LOCALVERSION_AUTO is not set\n")

    if with_droidspaces:
        droidspaces.merge_config(output / ".config")
    run(*options, "olddefconfig", env=env)
    if with_droidspaces:
        droidspaces.verify_config(output / ".config", config)
    final_config = (output / ".config").read_text()
    for required in ("CONFIG_KSU=y", "CONFIG_KALLSYMS_ALL=y", "CONFIG_MODVERSIONS=y"):
        if required not in final_config.splitlines():
            raise RuntimeError("Kconfig dropped required option: " + required)
    run(*options, job_option, "KBUILD_SYMTYPES=1", "net/oplus_modules/data_module/", env=env)
    if with_droidspaces:
        droidspaces.verify_protocol_crc(output)
    if name == "oneplus-8t":
        run(*options, job_option, "net/ipv4/route.o",
            "net/ipv6/route.o", "net/xfrm/xfrm_policy.o", env=env)
    if diagnostics_only:
        if data["platform"] == "sm8250":
            run(*options, "KBUILD_SYMTYPES=1", "drivers/input/touchscreen/touch.o", env=env)
        dest = artifact_root / "abi-types"
        dest.mkdir(parents=True, exist_ok=True)
        for item in output.rglob("*.symtypes"):
            target = dest / item.relative_to(output)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(item, target)
        for item in (output / "net/oplus_modules/data_module").rglob("*.symversions"):
            print(item.read_text())
        shutil.copyfile(modules / "vendor/oplus/kernel/network/data_module/proto-src/netlink_msg.pb-c.h", dest / "netlink_msg.pb-c.h")
        print("ABI type diagnostics only; no kernel image produced.")
        return
    run(*options, job_option, "Image", env=env)
    actual_release = (output / "include/config/kernel.release").read_text().strip()
    if actual_release != release:
        raise ValueError("Kernel release mismatch: expected %r, got %r" % (release, actual_release))
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as summary:
            summary.write("Kernel release: `" + actual_release + "`\n\n")
    image = output / "arch/arm64/boot/Image"
    if not image.is_file() or image.stat().st_size < 1024:
        raise RuntimeError("Kernel image missing")
    dest = artifact_root
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(image, dest / "Image")
    shutil.copyfile(output / ".config", dest / "kernel.config")
    for diagnostic in ("Module.symvers", "System.map"):
        if (output / diagnostic).is_file():
            shutil.copyfile(output / diagnostic, dest / diagnostic)
    compiler = subprocess.check_output(["clang", "--version"], text=True)
    manifest = {"device": name, "os": rom, "firmware": firmware["build_id"], "kernel_release": actual_release, "stock_kernel_release": stock_release, "kernel_release_suffix": SUFFIX, "kernel": data["kernel"], "resukisu": data["resukisu"], "resukisu_selection": resukisu_selection,
        "compat_patch_sha256": sha256(compat_patch) if compat_patch.exists() else None, "vendor_patch_sha256": sha256(vendor_patch) if vendor_patch.exists() else None, "vendor": data["vendor"], "patch_sha256": sha256(patch), "image_sha256": sha256(image), "compiler": compiler, "compiler_lock": compiler_lock, "stock_protocol": protocol, "linker": subprocess.check_output([linker, "--version"], text=True).splitlines()[0], "native_features": native_features,
        "module_trust": module_trust, "config_sha256": sha256(output / ".config"), "stock_config_supplied": stock_config, "config_translations": translations,
        "compile_verified": True, "device_verified": False}
    if with_droidspaces:
        manifest["droidspaces"] = droidspaces.profile()
    if offline:
        manifest["source_mode"] = "offline-locked-trees" if gitless_locks else "offline-git"
        if gitless_locks:
            manifest["offline_source_trees"] = gitless_locks
        manifest["source_date_epoch"] = int(env["SOURCE_DATE_EPOCH"])
        if prepare_clang_command is not None:
            manifest["clang_preparation_sha256"] = sha256(prepare_clang_command)
        if prepare_sources_command is not None:
            manifest["source_preparation_sha256"] = sha256(prepare_sources_command)
    verify_embedded(firmware, dest)
    save(dest / "build.json", manifest)
    print("Compile complete; boot packaging and on-device checks remain.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--device", required=True, choices=list(PATCHES))
    parser.add_argument("--os", choices=("coloros", "oxygenos"), default="coloros")
    parser.add_argument("--config", type=pathlib.Path, help="Uncompressed config from the matching stock kernel")
    parser.add_argument("--diagnostics-only", action="store_true")
    parser.add_argument("--droidspaces", action="store_true",
                        help="Build the opt-in OnePlus 9 Pro Droidspaces profile")
    for role in ("kernel", "vendor", "resukisu", "clang"):
        parser.add_argument("--" + role + "-source", type=pathlib.Path,
                            help="Locked local Git checkout or source tree for offline " + role + " input")
    parser.add_argument("--work-root", type=pathlib.Path, help="Writable work directory root")
    parser.add_argument("--output-root", type=pathlib.Path, help="Writable artifact directory root")
    parser.add_argument("--jobs", type=int, help="Number of parallel make jobs (0 auto-detects)")
    parser.add_argument("--prepare-clang-command", type=pathlib.Path,
                        help="Optional executable to adapt a staged copy of the offline clang for this host")
    parser.add_argument("--prepare-sources-command", type=pathlib.Path,
                        help="Optional offline source host-preparation executable receiving kernel, vendor, and ReSukiSU paths")
    args = parser.parse_args()
    build(args.device, args.config, args.os, args.diagnostics_only, args.droidspaces,
          kernel_source=args.kernel_source, vendor_source=args.vendor_source,
          resukisu_source=args.resukisu_source, clang_source=args.clang_source,
          work_root=args.work_root, output_root=args.output_root, jobs=args.jobs,
          prepare_clang_command=args.prepare_clang_command, prepare_sources_command=args.prepare_sources_command)
