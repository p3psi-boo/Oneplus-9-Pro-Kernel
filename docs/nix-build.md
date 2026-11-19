# 用 Nix 构建一加 9 Pro 内核

Nix 路径面向 `x86_64-linux`。产物是一加 9 Pro 的 ARM64 内核。
GitHub Actions 只用这套工具链构建 ColorOS 的 Droidspaces 配置。
在 macOS 上使用时，必须进入 x86_64 Linux 环境。

## 本地开发

在仓库根目录运行：

```sh
nix develop --no-update-lock-file -c python3 -m unittest discover -s tests -v
nix develop --no-update-lock-file -c protoc-c --version
```

`nix develop` 提供固定的构建依赖。用它运行测试和检查工具版本。
这个开发环境不等于构建沙箱。在 NixOS 上编译内核时，使用下节的构建命令。

## 隔离构建

```sh
nix build --no-update-lock-file --option sandbox true --option sandbox-fallback false \
  .#coloros-kernel --out-link result
```

`flake.lock` 固定 Nixpkgs。Nix 源码锁文件固定源码内容。
设备清单固定一加内核、厂商模块和 ReSukiSU 的提交。
工具清单固定 AOSP Clang 11.0.2。隔离编译阶段只读取预先获取的输入。
Nix 可以复用相同输入的构建产物。本项目不要求外部二进制缓存。

`result` 包含 `Image`、`kernel.config`、`System.map`、
`Module.symvers` 和 `build.json`。这些文件不是 TWRP 安装包。

## 在 GitHub Actions 验证和打包

1. 打开「Build OnePlus 9 Pro ColorOS with Nix」。
2. 选择 `oneplus-9-pro`。
3. 勾选 `package_twrp`，运行工作流。

推送也会触发 Nix 编译。推送触发的运行不生成 TWRP 安装包。
工作流只编译 ColorOS，不用常规构建作回退。

工作流核对内核配置、版本和签名检查设置。
工作流核对官方 ColorOS 内核的 13,797 个导出符号及其 CRC。
任何校验失败时，工作流不上传成品。
校验通过后，工作流上传 `nix-coloros-verified-kernel-*` 产物。
勾选 `package_twrp` 时，工作流另行上传 `twrp-experimental-oneplus-9-pro-coloros-nix-*`。

本地也可以用 `scripts/verify_nix_coloros.py` 对照两份构建。
该对照要求提供一份常规构建和一份 Nix 构建。
ABI 校验不验证真机启动。详见 [TWRP 安装与恢复说明](twrp-packaging.md)。
