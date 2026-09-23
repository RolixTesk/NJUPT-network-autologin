# 源码结构与代码审阅

本文档以 0.9.3 为重构基线，记录模块边界、已确认的无用代码、结构问题和效率改进点。审阅以当前行为和 59 项离线单元测试为准，不把为凭据安全、跨平台兼容或 Portal 异常行为保留的分支误判为冗余。

## 总体结构

```text
CLI (cli.py) --------+                       Tk GUI (gui.py)
                     |                               |
                     +-> 共享登录用例 (operations.py) <-+
                                      |
                           Portal 协议 (client.py)
                           /          |           \
                  网卡发现       绑定 HTTP       状态策略
          (network_interfaces.py) (transport.py) (status_policy.py)
                                      |
                            凭据 (credentials.py)

CLI / GUI -> 平台适配器 (platform_services/)
                  |                     |
                  v                     v
       Linux systemd (service.py)   Windows HKCU Run

打包：packaging/debian/ 和 packaging/windows/
```

主要流程是：

1. CLI 或 GUI 先查找已确认的 NJUPT 在线会话，避免重复占用设备名额。
2. 网卡模块按默认路由枚举候选接口，传输模块将 socket 同时绑定到源 IPv4 和指定设备。
3. 连接状态由国内 204 探测、Portal `chkstatus` 和普通 HTTPS 组合判定，不信任任一单点结果。
4. 只有确认 Portal 存在后才读取凭据；登录前动态校验 Portal 配置，成功后再检查实际连通性。
5. 平台适配器只负责开机启动、暂停/恢复、卸载与网卡列表；不处理 Portal 密码。

## 模块职责

| 模块 | 当前职责 | 评价 |
| --- | --- | --- |
| `credentials.py` | 凭据解析、运营商后缀、安全读写、Windows ACL | 边界清晰，安全约束完整 |
| `network_interfaces.py` | 默认路由、接口地址、路由约束与接口名校验 | OS 网络发现已形成公共边界 |
| `transport.py` | 绑定指定接口和 IPv4 的 HTTP/TLS 请求 | 传输细节已从 Portal 协议分离 |
| `status_policy.py` | 组合 Portal 会话、204 探测和普通 HTTPS 证据 | 纯函数策略，可独立测试 |
| `client.py` | JSONP、Portal 协议、接口选择与登录/注销编排 | 已移除 OS 命令和 socket 实现；仍是协议门面 |
| `cli.py` | 参数解析、用例编排、输出与退出码 | 功能完整，但 `main()` 分支集中 |
| `operations.py` | CLI/GUI 共用的一次登录用例 | 统一全局会话保护、延迟读取凭据与状态复用 |
| `gui_actions.py` | 不依赖 Tk 的状态与 GUI 文案适配 | 登录策略已下沉到共享用例 |
| `gui.py` | Tk 视图状态、分区布局和后台任务调度 | 构建方法和执行器生命周期已拆开；类本身仍较大 |
| `platform_services/` | 平台选择、统一协议、Windows/Linux 转接 | 使用中性状态字段和公共网卡 API |
| `service.py` | Linux systemd 用户服务的完整实现 | 位置与平台适配目录不一致 |
| `packaging/` | 构建 Debian 包、Windows 便携包/安装器 | 安全白名单正确，公共逻辑可再抽取 |

## 无用与冗余代码

| 标记 | 证据 | 处理 |
| --- | --- | --- |
| `App._busy_scope` | 只在初始化和 busy 切换时写入，全库无读取 | 已删除，不改变 UI 状态 |
| `__version__` 的独立常量 | 打包器只读 `pyproject.toml`，代码库内没有消费者 | 暂保留作为常规包 API；应改为构建时生成，而不是手工维护第二份版本 |

下列代码经核对后不属于无用代码：

- `ServiceStatus` 在 `platform_services.__init__` 中是公共重导出，而不是无用 import。
- 凭据保存中的临时文件、`fsync`、`os.replace` 和 Windows ACL 是原子性与失败关闭设计。
- GUI 持有两个 `PhotoImage` 引用可防止 Tk 回收尚在显示的图像。
- `except Exception` 的后台边界用于确保异常不会让 GUI 永久停留在 busy 状态。

## 已修复的重点结构问题

| 原标记 | 修复结果 |
| --- | --- |
| S1 | 将网卡发现、绑定 HTTP 传输和状态组合分别迁入 `network_interfaces.py`、`transport.py`、`status_policy.py`；`CampusClient` 不再直接调用 PowerShell、`ip` 或 `socket`。 |
| S2 | 将 GUI 布局拆为 header、credentials、connection、service 四个构建方法；后台工作统一复用应用级有界执行器，并在窗口关闭时 shutdown。 |
| S3 | `ServiceStatus.linger` 已改为跨平台的 `startup_ready`，Linux/Windows 各自解释具体启动机制。 |
| S4 | 平台适配器改用 `default_interfaces()`、`valid_interface_name()` 公共 API，不再访问 `CampusClient` 私有方法。 |
| E2 | CLI 与 GUI 统一调用 `login_once()`；选中接口的首次状态通过 `initial_status` 传入登录流程，凭据仍只在确认 Portal 后读取。 |
| E3 | 多网卡探测使用最多三个工作线程并发执行，最终结果仍按默认路由顺序选择。 |
| E4 | GUI 不再为每次操作创建守护线程或嵌套线程池，所有 Tk 更新仍由主线程轮询完成。 |

## 剩余结构问题

| 级别 | 标记 | 问题与影响 | 建议 |
| --- | --- | --- | --- |
| 中 | S5 | Linux 适配器在 `platform_services/linux.py`，具体实现却在顶层 `service.py` | 将具体实现迁入 Linux 模块或同目录私有模块，保留临时兼容重导出 |
| 低 | S6 | CLI `main()` 同时处理六个子命令、策略和异常映射 | 以 `_run_login()` 等命令处理器拆分，保留统一异常边界 |
| 低 | S7 | Debian/Windows 构建各自“复制整包再删除非目标平台模块” | 抽出共享 staging 函数和单一平台白名单，构建后强制检查禁止文件 |
| 低 | S8 | `pyproject.toml` 和 `__init__.py` 手工维护两份版本号 | 以包元数据为单一真实源，或由构建步骤生成模块常量 |
| 低 | S9 | `gui.py` 仍集中持有视图状态、交互动作和控件引用 | 后续若继续扩展功能，可提取 view-model；当前规模下不急于引入框架 |

## 效率分析

| 级别 | 标记 | 现状 | 更高效的实现 |
| --- | --- | --- | --- |
| 已改进 | E1 | 单结果和完整列表过去存在两套扫描取舍 | 统一有界并发探测；收集 future 后仍按输入顺序返回，兼顾首选顺序和总等待时间 |
| 已改进 | E2 | CLI/GUI 和登录方法过去重复完整状态检查 | 共享登录用例复用首次状态；提交凭据前仍保留更窄的 Portal offline 校验，避免用速度交换安全性 |
| 已改进 | E3 | 多候选网卡过去串行探测，超时线性累积 | 最多三个工作线程并发探测；并发度有上限，不随网卡数无界增长 |
| 已改进 | E4 | GUI 每个动作新建线程，刷新还会嵌套临时线程池 | 单个长生命周期执行器复用线程，Tk 主线程轮询 future，关闭窗口明确取消和 shutdown |
| 已有优化 | E5 | Windows 路由和地址查询调用 PowerShell 成本高，且相同 metric 时人工按 ifIndex 排序可能偏离系统真实选路 | 5 秒缓存使一次 GUI 刷新共享快照；以 `Find-NetRoute` 的系统出口优先，其余候选再按 metric/ifIndex 排序 |

E2 的实现没有简单删除安全检查：状态评估只用于避免重复连通性探测，真正提交前仍通过 Portal 会话接口确认当前处于 offline。

## 建议的重构顺序

1. 将 Linux 服务具体实现归位到平台目录，并保留兼容导入层。
2. 将 CLI 命令分派拆为小处理器，降低 `main()` 的条件分支密度。
3. 抽取 Debian/Windows 共用的打包 staging 白名单。
4. 将包版本改为单一真实源。

## 本次已落地的改动

- 为凭据分区边界、原子写入、Windows ACL 失败关闭、网卡绑定、状态冲突判定、JSONP 校验、Portal 配置锁定、Tk 线程交接、Linux 快照安装和 Windows 单次启动暂停标记补充注释。
- 删除未被读取的 `App._busy_scope`。
- 拆出网卡、HTTP、状态策略和共享登录用例，消除平台私有调用和前端重复状态检查。
- 将多网卡探测改为有界并发，并用测试确认并发发生且结果仍遵循路由顺序。
- 拆分 GUI 布局，复用应用级线程池并增加明确的关闭生命周期。
- 中性化服务状态字段；Windows 构建和自动发布增加 x64/ARM64 原生产物矩阵。
- 按 Add Educational Comments 规则为四个新边界模块增加带编号的原因型注释。
- 修复 Windows 开机现场的网卡假阳性和 Portal 假阴性：自动选择跟随 Windows 真实默认出口；单一 204 响应不足以判定联网，但 204 与普通 HTTPS 均成功时可覆盖滞后的 Portal `offline` 标记。
- 修复 Windows 双默认路由同 metric 时的出口偏差：auto 现在优先选择 `Find-NetRoute` 给普通应用选出的接口，而不是自行用 ifIndex 打破平局。
- 修正 `service.py` 仍声称“周期检查”的过时模块注释；当前 Linux 和 Windows 均只在启动阶段执行一次。
