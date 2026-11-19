# 用 Nix 构建一加 9 Pro 内核

Nix 路径面向 `x86_64-linux`。产物是一加 9 Pro 的 ARM64 内核。
它只构建 ColorOS 的 Droidspaces 配置，不替换默认构建路径。
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

1. 打开「Build OnePlus 9 Pro Droidspaces (experimental)」。
2. 选择 `oneplus-9-pro`。
3. 勾选 `nix_coloros`。
4. 如需 TWRP 安装包，再勾选 `package_twrp`。

该运行先构建常规 ColorOS 内核。Nix 作业使用该产物作对照。
它不编译 OxygenOS。常规推送仍检查两套固件的编译。
它核对两份内核的有效配置和内核版本。
它还分别核对官方 ColorOS 内核的 13,797 个导出符号及其 CRC。
它把结果写入 `nix-coloros-parity-*` 产物。

如果任一检查失败，工作流不生成 Nix TWRP 安装包，也不回退到常规产物。
如果检查通过且勾选 `package_twrp`，工作流才用现有方法打包。
安装包位于 `twrp-experimental-oneplus-9-pro-coloros-nix-*` 产物。
安装包仍须通过精确固件、模块签名和引导镜像校验。
取消勾选 `nix_coloros`，可以使用默认打包路径。

详见 [TWRP 安装与恢复说明](twrp-packaging.md)。
ABI 对照不要求两个内核文件逐字节相同。
ABI 对照不验证真机启动。
