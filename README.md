# NJUPT 校园网自动登录

面向南京邮电大学校园网的自动登录工具，提供原生桌面界面和命令行，支持 Windows 11 与 Debian/Ubuntu。

## 功能

- 自动选择可用网络接口，也可手动指定网卡
- 已登录时直接退出，避免同一台电脑重复占用设备名额
- 提供立即登录、注销、状态刷新和账号配置
- Windows 登录系统后自动运行一次，无终端窗口且不需要管理员权限
- Linux 使用 systemd 用户服务，在用户服务启动后运行一次
- 登录信息仅保存在本机用户目录

## 下载

从 [Releases](https://github.com/RolixTesk/NJUPT-network-autologin/releases/latest) 下载最新版。后续由仓库工作流发布的版本同时提供原生 x64 与 ARM64 Windows 构建：

| 平台 | 文件 | 用途 |
| --- | --- | --- |
| Windows 11 x64 | `njupt-autologin-windows-<版本>-x64-setup.exe` | x64 原生安装版 |
| Windows 11 x64 | `njupt-autologin-windows-<版本>-x64-portable.zip` | x64 原生便携版 |
| Windows 11 ARM64 | `njupt-autologin-windows-<版本>-arm64-setup.exe` | ARM64 原生安装版 |
| Windows 11 ARM64 | `njupt-autologin-windows-<版本>-arm64-portable.zip` | ARM64 原生便携版 |
| Debian/Ubuntu | `njupt-autologin_<版本>_all.deb` | 与 CPU 架构无关，使用 `apt` 安装 |

Windows 安装程序可选择把命令行工具加入当前用户 `PATH`。程序已包含 Python 和 Tk 运行时，不需要另外安装依赖。

Debian/Ubuntu 安装示例：

```bash
sudo apt install ./njupt-autologin_0.9.3_all.deb
```

## 使用

安装后打开“NJUPT 校园网自动登录”，填写账号、密码和运营商。网络接口保持 `auto` 即可自动选择。

- **立即登录校园网**：当前未认证时登录，已经在线时不会重复提交。
- **注销当前会话**：退出当前校园网会话，并暂停本次启动期间的自动登录。
- **安装并启用开机自启**：保存配置，并在以后启动系统时自动尝试一次。

常用命令：

```bash
njupt-autologin status
njupt-autologin login
njupt-autologin logout
njupt-autologin install-service
njupt-autologin uninstall-service
njupt-autologin -help
```

更完整的安装、配置、构建和故障说明见 [使用文档](docs/usage.md)；模块边界、已知结构问题与效率改进方向见 [源码结构与代码审阅](docs/source-analysis.md)。

## 适用范围

项目按当前 NJUPT 有线校园网 Portal 实现。学校更新认证接口后，旧版本可能需要同步适配。请勿把账号、密码、抓包文件或本地配置提交到仓库。
