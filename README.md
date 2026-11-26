# OnePlus 9 Pro Kernel

本项目为一加 9 Pro（`lemonadep`）构建实验内核。内核基于一加公开的 Linux 5.4.254 源码。内核集成 ReSukiSU，用于管理 Root 权限。

## 特性

- **Droidspaces**：实验配置支持在手机上运行 Linux 容器。
- **ranet3**：实验配置支持在 Linux 容器中运行普通节点。不支持出口节点。
- **CH347T**：内置 USB 转 SPI/GPIO 驱动。适用于 Mode 1 转接板与 CC1101 的实验接入，无需手动加载模块。[接入与验证](docs/ch347t.md)
- **原厂驱动**：保留原厂模块的签名与版本检查设置。打包前核对原厂导出符号及其 CRC，结果不代表原厂模块已在真机加载。

## 适用范围

GitHub Actions 用 Nix 构建内核。它只为 ColorOS `LE2120_14.0.0.1901(CN01)` 生成产物。

**注意：** 刷入前必须备份原厂 `boot.img`。安装包要求解锁引导程序。当前槽的引导镜像必须保持原厂状态。编译、ABI 校验和真机验证是三项独立检查。目前未验证真机启动。

## 获取安装包

推送构建相关改动到 `oneplus-9-pro` 后，[ColorOS TWRP](https://github.com/p3psi-boo/Oneplus-9-Pro-Kernel/actions/workflows/droidspaces.yml) 会自动编译、校验并打包。也可以在 Actions 手动运行，不需要勾选选项。运行成功后，下载产物并解压，只刷入内层的 `*-twrp.zip`。

- [TWRP 安装与恢复说明](docs/twrp-packaging.md)
- [Droidspaces 与 ranet3 说明](docs/droidspaces.md)
- [Nix 构建与验证](docs/nix-build.md)
- [许可证](LICENSE)
