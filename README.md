# OnePlus 9 Pro Kernel

本项目为一加 9 Pro（`lemonadep`）构建实验内核。内核基于一加公开的 Linux 5.4.254 源码。内核集成 ReSukiSU，用于管理 Root 权限。

## 特性

- **Droidspaces**：实验配置支持在手机上运行 Linux 容器。
- **ranet3**：实验配置支持在 Linux 容器中运行普通节点。不支持出口节点。
- **原厂驱动**：构建保留原厂模块的签名和版本检查配置。打包前核对原厂导出符号及其 CRC。

## 适用范围

GitHub Actions 只为 ColorOS `LE2120_14.0.0.1901(CN01)` 生成 TWRP 安装包。OxygenOS 仍参加编译检查，不生成 TWRP 安装包。

**注意：** 刷入前必须备份原厂 `boot.img`。安装包要求解锁引导程序。当前槽的引导镜像必须保持原厂状态。真机启动未验证。

## 获取安装包

在 [GitHub Actions](https://github.com/p3psi-boo/Oneplus-9-Pro-Kernel/actions/workflows/droidspaces.yml) 选择默认分支 `oneplus-9-pro`。勾选 `package_twrp`。运行成功后，在产物中下载内层 `*-twrp.zip` 和对应的 SHA-256 校验文件。

- [TWRP 安装与恢复说明](docs/twrp-packaging.md)
- [Droidspaces 与 ranet3 说明](docs/droidspaces.md)
- [许可证](LICENSE)
