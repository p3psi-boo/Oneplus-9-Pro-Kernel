"""Fetch the AOSP compiler used by the stock CFI-enabled SM8350 kernel."""
import hashlib
import json
import os
import pathlib
import shutil
import stat
import subprocess
from project import ROOT, run, sha256

def local_git_env():
    """Do not use inherited Git overrides or network protocols in offline mode."""
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(GIT_ALLOW_PROTOCOL="file", GIT_NO_LAZY_FETCH="1", GIT_CONFIG_NOSYSTEM="1",
               GIT_CONFIG_GLOBAL=os.devnull, GIT_TERMINAL_PROMPT="0", GIT_OPTIONAL_LOCKS="0")
    return env


def local_git(path, *args):
    return subprocess.check_output(
        ["git", "-c", "safe.directory=" + str(path), "-c", "core.hooksPath=" + os.devnull, *args],
        cwd=path, text=True, env=local_git_env()).strip()


def local_revision(path, commit):
    path = pathlib.Path(path).resolve()
    if not (path / ".git").is_dir() or local_git(path, "rev-parse", "--show-toplevel") != str(path):
        raise ValueError("Offline input must be the root of a local Git checkout: " + str(path))
    if local_git(path, "rev-parse", "HEAD^{commit}") != commit:
        raise ValueError("Offline input commit mismatch: " + str(path))
    return path


def compiler_tree_sha256(root):
    """Hash installed file content, executable modes, directories, and symlink targets."""
    if not root.is_dir() or root.is_symlink():
        raise ValueError("Locked clang installation must be a directory")
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*"), key=lambda item: os.fsencode(item.relative_to(root))):
        mode = path.lstat().st_mode
        relative = os.fsencode(path.relative_to(root))
        if stat.S_ISLNK(mode):
            record = b"link\0" + relative + b"\0" + os.fsencode(os.readlink(path))
        elif stat.S_ISREG(mode):
            executable = b"exec" if mode & stat.S_IXUSR else b"file"
            record = executable + b"\0" + relative + b"\0" + sha256(path).encode("ascii")
        elif stat.S_ISDIR(mode):
            record = b"directory\0" + relative
        else:
            raise ValueError("Unsupported path type in clang installation: " + str(path))
        digest.update(record + b"\0")
    return digest.hexdigest()


def configure(platform, source=None, work_root=None, prepare_command=None):
    if prepare_command is not None and source is None:
        raise ValueError("Preparing clang requires the locked offline source")
    if platform != "sm8350":
        if source is not None:
            raise ValueError("Offline clang source is supported only for SM8350")
        return None
    lock = json.loads((ROOT / "tools.lock.json").read_text())["android_clang"]
    staged_root = (work_root or ROOT / ".work") / "toolchains"
    destination = staged_root / lock["commit"]
    if source is not None:
        source = pathlib.Path(source).resolve()
        if (source / ".git").exists():
            source = local_revision(source, lock["commit"])
            local_git(source, "diff", "--exit-code", "--quiet", "HEAD", "--", lock["directory"])
        else:
            expected = lock.get("tree_sha256")
            if not expected or compiler_tree_sha256(source / lock["directory"]) != expected:
                raise ValueError("Offline clang installation differs from the locked tree digest")
        destination = source
        if prepare_command is not None:
            command = pathlib.Path(prepare_command).resolve()
            if not command.is_file():
                raise ValueError("Invalid clang preparation command: " + str(command))
            destination = staged_root / (lock["commit"] + "-adapted")
            installation = destination / lock["directory"]
            shutil.copytree(source / lock["directory"], installation, symlinks=True)
            # Nix store inputs are read-only; adapt only this owned, staged copy.
            for item in (installation, *installation.rglob("*")):
                if not item.is_symlink():
                    item.chmod(item.stat().st_mode | stat.S_IWUSR)
            run(command, installation, env=local_git_env())
    binary = destination / lock["directory"] / "bin"
    if source is not None and not (binary / "clang").is_file():
        raise ValueError("Offline clang does not contain the locked installation: " + str(binary))
    if source is None and not (binary / "clang").exists():
        destination.mkdir(parents=True, exist_ok=True)
        run("git", "init", "--quiet", destination)
        run("git", "remote", "add", "origin", lock["repository"], cwd=destination)
        run("git", "config", "remote.origin.promisor", "true", cwd=destination)
        run("git", "config", "remote.origin.partialclonefilter", "blob:none", cwd=destination)
        run("git", "sparse-checkout", "set", lock["directory"], cwd=destination)
        run("git", "fetch", "--filter=blob:none", "--depth=1", "origin", lock["commit"], cwd=destination)
        run("git", "checkout", "--detach", "FETCH_HEAD", cwd=destination)
    if source is None:
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=destination, text=True).strip()
        if commit != lock["commit"]:
            raise ValueError("AOSP compiler source commit mismatch")
    version = subprocess.check_output([str(binary / "clang"), "--version"], text=True)
    if lock["version_string"] not in version:
        raise ValueError("AOSP compiler version mismatch: " + version)
    os.environ["PATH"] = str(binary) + os.pathsep + os.environ["PATH"]
    return lock
