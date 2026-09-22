# 校园网自动登录

该程序在 Ubuntu VM 上自动选择校园网接口。如果 HTTP 探测返回 Portal，则读取本地凭据、请求登录并复核联网；已联网时直接退出。网络请求同时绑定所选接口及其当前 IPv4 地址。`ens37` 仅用于 SSH 管理。

自动选择会读取 IPv4 默认路由接口。只有一个候选时直接使用；存在多个候选时，程序分别执行不带凭据的联网及 NJUPT Portal 状态探测。登录命令会先检查全部候选：只要确认任一接口已有 NJUPT 在线会话，就立即成功退出且不读取凭据，避免同一 PC 占用多个设备名额。

确需认证另一个 Portal 接口时使用：

```bash
njupt-autologin login --force
```

`--force` 只允许程序越过“其他接口已经登录”的检查，并优先选择等待认证的 NJUPT 接口。若选中的接口本身已经在线，程序仍直接退出，不会重复提交认证。没有强制参数时，多个已登录校园接口按默认路由 metric 选择；只有普通联网证据且无法区分时拒绝猜测。始终可以用 `--interface ens33` 手动限定候选接口，但默认策略仍会先检查其他接口的 NJUPT 在线会话。

注销当前自动选择的校园网接口：

```bash
njupt-autologin logout
```

也可以用全局参数限定接口：

```bash
njupt-autologin --interface ens33 logout
```

注销使用 Portal 页面配置中的 AC 注销端点。该端点的响应正文会错误地标记失败，因此程序不相信正文，而是轮询所选接口，只有确认 HTTP 探测重新出现 Portal 才报告成功。注销前会暂停正在运行的自动登录 timer，避免两分钟后重新登录；timer 保持 enabled，系统重启后会恢复。注销失败时程序会恢复原先运行的 timer。

Portal 网页自身的注销按钮当前不可作为可靠替代。现场测试用同一个 Firefox 会话完成网页登录、重新进入在线页并点击注销；网页登录正常得到 HTTP 204，网页也实际发送了完整注销请求，但后端返回 `result=0`，接口保持在线。该流程没有建立 Cookie，因此脚本侧没有可补充到浏览器的会话 Cookie。网页自身创建的登录会话也出现相同结果，故障位于 Portal 原生注销流程。需要主动退出时，请使用上面的 CLI 命令或 GUI 中的注销按钮。

## 安装与配置

要求 Linux、Python 3.10+、`iproute2` 与 systemd 用户管理器。GUI 还需要发行版提供的 Tk 绑定（Debian/Ubuntu 软件包名为 `python3-tk`）；项目不依赖第三方 Python 包。在源码目录执行：

```bash
python3 -m pip install --user .
njupt-autologin configure
njupt-autologin status
njupt-autologin login
```

Ubuntu 若禁止系统 Python 的用户级 pip 安装，可使用虚拟环境，或直接以 `PYTHONPATH=src python3 -m njupt_autologin` 代替上面的命令。`configure` 交互输入校园网账号、密码与运营商（`campus`、`telecom` 或 `mobile`），默认保存到 `~/.config/njupt-autologin/credentials.json`，权限为 `600`。也可从标准输入导入 JSON，例如：

```bash
printf '%s\n' '{"username":"example","password":"example","operator":"mobile"}' | njupt-autologin configure --credentials-stdin
```

上例仅演示格式。实际密码应使用交互输入或受保护文件传入，避免写入 shell 历史或命令行参数。`login` 可使用 `--credentials-file` 或 `--credentials-stdin`；配置文件必须是普通文件，且不能对组或其他用户开放。

### Debian/Ubuntu 软件包

源码仓库可以直接构建架构无关的 `.deb`，构建脚本只使用 Python 标准库和系统自带的 `dpkg-deb`：

```bash
python3 packaging/debian/build_deb.py
sudo apt install ./dist/njupt-autologin_0.7.2_all.deb
```

软件包安装 CLI、原生桌面 GUI、桌面菜单入口以及 systemd 用户服务和定时器。`apt` 会自动处理 `python3`、`python3-tk`、`iproute2`、`systemd` 和 `pkexec` 前置依赖。安装后可以通过 GUI 配置并启用服务，也可以直接执行：

```bash
njupt-autologin configure
systemctl --user enable --now njupt-autologin.timer
```

若希望用户未登录桌面或 SSH 时也能运行，仍需由系统管理员为该用户启用 linger。

## 无人值守运行

配置凭据后执行：

```bash
njupt-autologin install-service
systemctl --user status njupt-autologin.timer
```

安装命令把当前 Python 包复制到 `~/.local/share/njupt-autologin/app/`，创建用户级 oneshot 服务和定时器，并启用定时器。服务启动后约 30 秒首次检查，此后每 2 分钟检查一次。登录失败会返回非零状态，由下一次定时检查再试，不会快速循环请求。

若需在用户未登录桌面或 SSH 时开机启动，系统管理员需为该用户启用 linger：

```bash
sudo loginctl enable-linger "$(whoami)"
loginctl show-user "$(whoami)" -p Linger
```

查看最近一次运行：

```bash
systemctl --user show njupt-autologin.service -p Result -p ExecMainStatus
journalctl --user -u njupt-autologin.service -n 20 --no-pager
```

## 图形界面

图形界面是小巧的原生 Tk 窗口，使用系统控件和定制 `ttk` 主题，不启动本地 HTTP 服务，也不需要浏览器或第三方 Python 包：

```bash
njupt-autologin-gui
```

若用户级脚本目录尚未进入当前会话的 `PATH`，可直接运行 `~/.local/bin/njupt-autologin-gui`，或重新登录桌面后再启动。

界面支持输入校园网账号和密码、选择运营商和网卡、立即登录、保存登录信息、安装并启用开机自启服务、注销当前校园网会话、查看服务状态以及卸载服务。接口默认为 `auto`；密码输入框会遮蔽内容，已保存凭据存在时留空表示沿用原密码。

“立即登录校园网”会先检查是否已有 NJUPT 在线会话，已在线时直接返回；需要认证时才读取表单或已保存的密码，并在成功后保存登录信息。“安装并启用开机自启”会在完成服务安装后立即执行同一登录流程，避免首次安装后等待 timer。网络与服务操作在后台线程执行，窗口不会因请求而停止响应。

安装自启时会同时检查 linger。若尚未启用，界面通过系统的 `pkexec` 权限对话框执行 `loginctl enable-linger`。卸载默认保留登录信息；只有勾选“卸载时同时删除保存的登录信息”才会删除凭据。卸载不会关闭 linger，因为当前用户的其他服务也可能依赖它。

Tk 界面层可在后续 Windows 版本中直接复用，Windows 官方 Python 安装通常包含 Tk 运行时。当前校园网接口探测和开机服务后端仍使用 Linux 的 `iproute2` 与 systemd，Windows 版本需提供对应的网络接口和服务管理实现。

命令行也可以卸载服务：

```bash
njupt-autologin uninstall-service
njupt-autologin uninstall-service --remove-credentials
```

## 状态与边界

`status` 以退出码 `0` 表示联网、`2` 表示 Portal、`3` 表示网络不可用；`login` 成功或已联网返回 `0`，认证失败返回 `4`，配置错误返回 `5`。加 `--json` 可输出状态对象。Portal 的配置或字段变更会使程序拒绝尝试登录，需重新分析网页协议。

本项目在当前校园网环境中验证了脚本登录、浏览器原生登录和 AC 端点注销。脚本与浏览器登录均能得到 HTTP 204；CLI/GUI 注销会在确认接口重新出现 Portal 后才报告成功。Portal 原生网页注销在浏览器自身登录后仍返回失败。使用不同运营商、不同账户类型或不同校园网部署前应另行验证。
