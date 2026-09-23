# 校园网自动登录

该程序在 Linux 和 Windows 上自动选择校园网接口。登录状态会同时核对 Portal 会话状态、国内 204 连通性探测和普通国内 HTTPS。单一 204 响应可能是 Portal 放行的特例，不足以判定在线；但 204 与普通 HTTPS 均成功时，实际外网证据优先于可能滞后的 Portal `offline` 标记。如果任一实际联网检查失败且 Portal 报告离线，则按待认证处理。如果确认需要认证，则读取本地凭据、请求登录并复核联网；已确认在线时直接退出。网络请求同时绑定所选接口及其当前 IPv4 地址。

自动选择会读取 IPv4 默认路由接口。Windows 上会把 `Find-NetRoute` 为普通未绑定流量选出的实际出口放在首位，避免相同 metric 的多网卡被程序自行按接口编号排成另一顺序。只有一个候选时直接使用；存在多个候选时，程序分别执行不带凭据的联网及 NJUPT Portal 状态探测。登录命令会先检查全部候选：只要确认任一接口已有 NJUPT 在线会话，就立即成功退出且不读取凭据，避免同一 PC 占用多个设备名额。

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

注销使用 Portal 页面配置中的 AC 注销端点。该端点的响应正文会错误地标记失败，因此程序不相信正文，而是轮询所选接口，只有确认 HTTP 探测重新出现 Portal 才报告成功。注销前会暂停本次启动期间的自动登录，避免用户主动退出后又被后台任务重新登录；启动配置保持 enabled，系统重启后会恢复。注销失败时程序会恢复原先的运行状态。

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
sudo apt install ./dist/njupt-autologin_0.9.3_all.deb
```

软件包安装 CLI、原生桌面 GUI、桌面菜单入口以及 systemd 用户服务和定时器。`apt` 会自动处理 `python3`、`python3-tk`、`iproute2`、`systemd` 和 `pkexec` 前置依赖。安装后可以通过 GUI 配置并启用服务，也可以直接执行：

```bash
njupt-autologin configure
systemctl --user enable --now njupt-autologin.timer
```

查看主命令或具体子命令帮助时，可以使用标准的 `-h`、`--help`，也可以使用兼容别名 `-help`：

```bash
njupt-autologin -help
njupt-autologin login -help
```

若希望 Linux 用户未登录桌面或 SSH 时也能运行，仍需由系统管理员为该用户启用 linger。

### Windows 11 软件包

Windows 安装包与便携版均包含 Python 和 Tk 运行时，使用时不需要安装 Python 或第三方包。运行安装程序后，从开始菜单打开“NJUPT 校园网自动登录”；便携版解压后运行 `njupt-autologin-gui.exe`。程序将凭据保存在 `%APPDATA%\njupt-autologin\credentials.json`，并通过 Windows ACL 限制为当前用户访问。

安装服务后，程序通过当前用户的 Windows 启动项，在登录系统约 30 秒后自动运行一次，不再周期检测，也不需要管理员权限。后台任务使用无控制台程序，GUI 调用系统组件时也不会显示终端窗口。GUI 注销校园网后，本次系统启动期间不会再次自动登录；重启并重新登录 Windows 后自动恢复。安装程序卸载时会移除启动项，默认保留凭据。

安装程序提供“将命令行工具添加到当前用户 PATH”选项，默认不勾选。勾选后，新打开的 PowerShell 或命令提示符可以直接运行 `njupt-autologin`；卸载时只移除本程序自己的 PATH 项。覆盖安装会保留既有选择，并自动把旧版本的任务计划迁移为无需管理员权限的当前用户启动项。

在 Windows 开发机上构建发布包：

```powershell
py -3.12 -m pip install pyinstaller
py -3.12 packaging\windows\build_windows.py --architecture x64
```

`--architecture` 用于核对构建机与目标一致，不执行交叉编译；ARM64 发布物必须在 ARM64 Windows 和 ARM64 Python 上使用 `--architecture arm64` 构建。脚本始终生成带架构名的便携版 ZIP；检测到 Inno Setup 6 时还会生成同架构的当前用户安装包。仓库的 Release 工作流在原生 x64 与 ARM64 runner 上分别构建这两组产物，并继续提供架构无关的 Debian `all` 包。

Windows 发布物只包含公共模块与 Windows 服务适配器，不包含 systemd/Linux 服务源码；Debian 包同样不会包含 Windows 适配器源码。

## 无人值守运行

配置凭据后执行：

```bash
njupt-autologin install-service
systemctl --user status njupt-autologin.timer
```

安装命令把当前 Python 包复制到 `~/.local/share/njupt-autologin/app/`，创建用户级 oneshot 服务和启动定时器，并启用定时器。用户服务管理器启动约 30 秒后执行一次，此后不再周期检测。若启动时网络尚不可用，可以从 GUI 点击“立即登录校园网”；下次系统启动时仍会自动尝试。

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

界面分为登录配置、登录状态和服务状态三块。没有保存凭据时，登录配置默认展开；已有凭据时默认收起，可从登录状态右上角的“登录配置”按钮以动画展开。网络接口使用只读下拉栏，自动列出当前可用的默认路由设备，并以 `auto` 为默认值。密码输入框会遮蔽内容，已保存凭据存在时留空表示沿用原密码。

登录状态同时核对校园网认证会话与普通外部网站连通性，并提供立即登录和注销操作。如果检测到多个默认路由网卡同时拥有校园网会话，界面会显示红色提醒。服务状态单独显示服务安装、启动任务启用和开机运行状态；已启用但本次启动已执行或暂停的任务显示为正常的“已启用”。

“立即登录校园网”会先检查是否已有 NJUPT 在线会话，已在线时直接返回；需要认证时才读取表单或已保存的密码，并在成功后保存登录信息。“安装并启用开机自启”会在完成服务安装后立即执行同一登录流程，避免首次安装后等待 timer。网络与服务操作在后台线程执行，窗口不会因请求而停止响应。

若 Portal 登录端返回“IP 已在线”但两项国内外网检查均失败，程序会发送一次 AC 注销请求清理残留记录，并且只重试一次登录，避免循环认证。连接刷新、立即登录和注销的过程与错误显示在“登录状态”模块；服务安装和卸载的反馈显示在“服务状态”模块。

安装自启时会同时检查 linger。若尚未启用，界面通过系统的 `pkexec` 权限对话框执行 `loginctl enable-linger`。卸载默认保留登录信息；只有勾选“卸载时同时删除保存的登录信息”才会删除凭据。卸载不会关闭 linger，因为当前用户的其他服务也可能依赖它。

Tk 界面只调用统一的平台服务适配器。Debian 版本通过 Linux 适配器封装 `iproute2`、systemd 和 linger；Windows 版本通过 Windows 适配器管理网卡与当前用户启动项。平台包在构建时只复制公共适配器定义和目标平台实现，不携带其他平台的服务源码。

命令行也可以卸载服务：

```bash
njupt-autologin uninstall-service
njupt-autologin uninstall-service --remove-credentials
```

## 状态与边界

`status` 以退出码 `0` 表示 204 和普通 HTTPS 均已确认联网、`2` 表示实际外网检查未通过且 Portal 要求认证、`3` 表示网络不可用。Portal 的 `offline` 标记不会覆盖两项已成功的实际联网证据。`login` 成功或已确认在线返回 `0`，认证失败返回 `4`，配置错误返回 `5`。加 `--json` 可输出状态对象。Portal 的配置或字段变更会使程序拒绝尝试登录，需重新分析网页协议。

本项目在当前校园网环境中验证了脚本登录、浏览器原生登录和 AC 端点注销。脚本与浏览器登录均能得到 HTTP 204；CLI/GUI 注销会在确认接口重新出现 Portal 后才报告成功。Portal 原生网页注销在浏览器自身登录后仍返回失败。使用不同运营商、不同账户类型或不同校园网部署前应另行验证。

本地 Portal 会话与外网探测出现矛盾、无法判断实际在线记录时，可在已经登录校园网的设备上打开[校园网自助服务页面](http://10.10.244.240:8080/Self/dashboard)核对服务端记录。该页面只作为人工排障依据，不参与每次状态刷新或自动登录，避免增加不必要的请求。
