# 校园网自动登录

该程序在 Ubuntu VM 上经 `ens33` 检测有线校园网。如果 HTTP 探测返回 Portal，则读取本地凭据、请求登录并复核联网；已联网时直接退出。网络请求绑定 `ens33` 的当前 IPv4 地址，运行前还会检查互联网路由是否走该接口。`ens37` 仅用于 SSH 管理。

## 安装与配置

要求 Linux、Python 3.10+、`iproute2` 与 systemd 用户管理器。代码本身只使用 Python 标准库。在源码目录执行：

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

Ubuntu 安装 Tkinter 后可启动简易设置界面：

```bash
sudo apt install python3-tk policykit-1
njupt-autologin-gui
```

若用户级脚本目录尚未进入当前会话的 `PATH`，可直接运行 `~/.local/bin/njupt-autologin-gui`，或重新登录桌面后再启动。

界面支持输入校园网账号和密码、选择运营商和网卡、保存登录信息、安装并启用开机自启服务、查看服务状态以及卸载服务。密码输入框会遮蔽内容；已保存凭据存在时，密码留空表示沿用原密码。

“安装并启用开机自启”会同时检查 linger。若尚未启用，界面通过系统的 `pkexec` 权限对话框执行 `loginctl enable-linger`。卸载默认保留登录信息；只有勾选“卸载时同时删除保存的登录信息”才会删除凭据。卸载不会关闭 linger，因为当前用户的其他服务也可能依赖它。

命令行也可以卸载服务：

```bash
njupt-autologin uninstall-service
njupt-autologin uninstall-service --remove-credentials
```

## 状态与边界

`status` 以退出码 `0` 表示联网、`2` 表示 Portal、`3` 表示网络不可用；`login` 成功或已联网返回 `0`，认证失败返回 `4`，配置错误返回 `5`。加 `--json` 可输出状态对象。Portal 的配置或字段变更会使程序拒绝尝试登录，需重新分析网页协议。当前 Portal 的页面自身注销请求返回失败，因此没有提供注销命令。

本项目在当前校园网环境中完成过一次协议重放登录；VM 重启使原会话失效后，systemd 服务又通过完整程序完成一次登录并得到 HTTP 204，随后复跑正确识别为已联网。Portal 页面自身的注销请求返回失败，因此程序不提供注销命令。使用不同运营商、不同账户类型或不同校园网部署前应另行验证。
