# 第一阶段：确认 VM 的独立校园网身份

日期：2026-09-19。以下是一次现场观测，DHCP 地址、DNS 结果和 Portal 地址可能变化。

## 结论

Windows 宿主机已通过校园网访问公网时，Ubuntu VM 从 `ens33` 发出的 HTTP 请求仍被重定向到校园网 Portal。因此，VM 当前具有与宿主机不同的认证状态，可以作为独立实验客户端。VM 未认证期间，Windows 仍可通过 `ens37` SSH 管理 VM。

## 管理链路与路由

| 项目 | 现场结果 |
|---|---|
| Windows Host-only 接口 | VMware Network Adapter VMnet1，`192.168.10.1/24` |
| VM 管理接口 | `ens37`，`192.168.10.128/24` |
| VM 校园网接口 | `ens33`，`10.161.156.154/17` |
| Windows 校园网地址 | `10.161.163.236` |
| VM 默认路由 | `10.161.255.254`，经 `ens33` |
| VM 到 Windows 管理地址的路由 | `192.168.10.1`，经 `ens37` |

VM 两个接口在 NetworkManager 中均为 `connected`。SSH 服务从 Windows 可达；Windows 上已创建专用 Ed25519 密钥和 `campus-vm` 别名，`ssh campus-vm 'hostname; whoami'` 免交互成功。没有断开接口、刷新路由或修改宿主机网络配置。`ens33` 未认证时 SSH 仍可用，因此无需通过关闭接口来验证管理链路。

## HTTP 对照

对 Windows 使用 `curl.exe --noproxy '*'`，避免本地 HTTP 代理影响结果；对 VM 使用 `curl --interface ens33`。两端均未跟随重定向。

| URL | Windows 直连 | VM `ens33` |
|---|---|---|
| `http://connectivitycheck.gstatic.com/generate_204` | `204 No Content` | `302 Moved Temporarily` |
| `http://www.msftconnecttest.com/connecttest.txt` | `200 OK`，文本响应 | `302 Moved Temporarily` |

VM 两次 302 都指向 `http://10.10.244.11/a79.htm`，不含查询参数。直接经 `ens33` 获取该地址得到 `200` 和 `text/html; charset=gbk`。VM 对两个探测域名的解析和实际连接目标分别包括 `120.253.253.34` 与 `23.205.151.24`；到这些地址及 Portal 地址的路由均经 `ens33`。这说明请求到达校园网出口后被 Portal 拦截，而不是 VM 将实验流量送到 Host-only 接口。

## 复核方法与下一阶段

```powershell
ssh campus-vm "ip -br addr; ip route; ip rule; nmcli device status"
ssh campus-vm "ip -4 route get 192.168.10.1"
ssh campus-vm "curl --interface ens33 -i --max-redirs 0 --max-time 12 http://connectivitycheck.gstatic.com/generate_204"
curl.exe --noproxy "*" -i --max-redirs 0 --max-time 12 http://connectivitycheck.gstatic.com/generate_204
```

上述命令会显示原始 HTTP 头；公开记录时应检查是否含 Cookie、Token 或带敏感参数的 URL。下一阶段可分析 Portal 页面和认证协议，之后再实现 CLI 自动登录。本阶段没有尝试登录，也没有抓取或提交认证秘密。
