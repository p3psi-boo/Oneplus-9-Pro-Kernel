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
这个开发环境不等于构建沙箱。在 Linux 上编译内核时，使用下节的构建命令。

## 隔离构建

```sh
nix build --no-update-lock-file --option sandbox true --option sandbox-fallback false \
  .#coloros-kernel --out-link result
```

`flake.lock` 固定 Nixpkgs。Nix 源码锁文件固定源码树的内容。锁文件不包含 `.git` 数据。
设备清单固定一加内核、厂商模块和 ReSukiSU 的提交。
工具清单固定 AOSP Clang 11.0.2。隔离编译阶段只读取预先获取的输入。
本项目不要求外部二进制缓存。内核最终链接保留 LTO 与 CFI，内存用量较高。
请使用磁盘上的 Nix 构建目录，不要使用 RAM 文件系统。GitHub Actions
在编译前记录可用内存、磁盘空间和构建目录文件系统类型。

`result` 包含 `Image`、`kernel.config`、`System.map`、
`Module.symvers` 和 `build.json`。这些文件不是 TWRP 安装包。

## 在 GitHub Actions 验证和打包

推送构建相关改动到 `oneplus-9-pro` 会触发「ColorOS TWRP」。也可以在 Actions 中选择该分支并手动运行。两种方式在主分支都能生成 TWRP 安装包。手动选择其他分支可跑同一套编译和 ABI 校验，只上传供审查的内核文件，不生成刷机包。工作流只构建 ColorOS，没有常规构建回退。

工作流核对内核配置、版本和签名检查设置。
工作流核对官方 ColorOS 内核的 13,797 个导出符号及其 CRC。
任何校验失败时，工作流不上传成品。
校验和打包也通过 Nix 运行，使用锁定的工具。工作流缓存通过校验的内核文件，
不缓存原厂 boot、重打包的 boot 或安装包。再次运行相同提交时，先核对提交 SHA
和每个文件的摘要，再复用内核并重新校验。没有缓存时才重新编译。
校验通过后，工作流上传 `nix-coloros-verified-kernel-*` 产物。
打包成功后，工作流另行上传 `twrp-experimental-oneplus-9-pro-coloros-nix-*`。

## 本地验证和打包

从干净的 Git 检出构建内核。产物记录实际提交。复制 Nix 结果并不会改变提交记录。
下列命令使用同一条验证与打包路径。没有本地原厂镜像时，验证命令会下载所需数据并校验镜像。

```sh
commit=$(git rev-parse HEAD)
nix run --no-update-lock-file .#coloros-pipeline -- qualify \
  --built result --stock .work/twrp-stock/coloros/boot.img \
  --output out/qualified-coloros --source-commit "$commit"
nix run --no-update-lock-file .#coloros-pipeline -- package \
  --built result --qualified out/qualified-coloros \
  --output out/twrp-delivery --source-commit "$commit" --run-id 0
```

`--run-id 0` 表示本地打包，不是 GitHub Actions 运行。

本地也可以用 `scripts/verify_nix_coloros.py` 对照两份构建。
该对照要求提供一份常规构建和一份 Nix 构建。
ABI 校验不验证真机启动。详见 [TWRP 安装与恢复说明](twrp-packaging.md)。
