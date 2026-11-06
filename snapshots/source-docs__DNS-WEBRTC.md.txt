# DNS 与 WebRTC：目标、处理与验收

按 [AGENTS](../AGENTS.md)执行；TUN 门槛和适配原则见 [CLIENTS](CLIENTS.md)。**普通连接、DNS 查询、WebRTC 网络路径分别检测。** 已符合目标的设置保留，有偏差才按当前版本支持的方式修复。

<a id="dns-goals"></a>

## DNS 目标

| 查询类别 | 目标 |
| --- | --- |
| 本机、LAN、private | 使用经核实的本地 / 内网解析路径，不把内网名发送给公网解析器；适用时保留 mDNS |
| 用户例外 | 保持用户已认可的独立策略 |
| 国内域名 | 直连使用可信加密解析器，后续连接遵循直连策略 |
| 海外与未知公网域名 | 使用经代理的可信加密解析器；未知域名的中国 IP 兜底按实际解析流程实现 |
| 节点服务器域名 | 使用用户认可、在代理建立前即可工作的引导解析，避免循环依赖 |

核对首选、备用及并发解析器、系统解析器、浏览器安全 DNS 和 IPv6；解析失败不静默退回直连或明文路径。DoH 加密不证明查询经过代理，DNS 分流也不能仅看配置里的解析器名称或 IP 归属地。

<a id="private-dns-preflight"></a>

### 内网解析判断

应用前查清 system/local、回环 stub 的实际上游。客户端可能在运行时改写系统 DNS，要对照系统当前 DNS 与可取得的 DHCP 下发值，按实际联网接口区分物理网卡和 TUN 网卡，不固定接口名或虚拟 DNS 地址。路由器之后的转发设备看不到，不要求追查，在报告里注明即可。

| 系统 | 只读检查与边界 |
| --- | --- |
| macOS | `scutil --dns` 查看当前解析器；`ipconfig getpacket <实际接口>` 查看该接口的 DHCPv4 数据。将占位符换成当前物理接口，不假定是 `en0`；无 DHCP 租约时不能据此取得下发值，IPv6 另查 |
| Windows | [Get-DnsClientServerAddress](https://learn.microsoft.com/en-us/powershell/module/dnsclient/get-dnsclientserveraddress) 查看各接口的 IPv4 / IPv6 DNS，物理与 TUN 接口都要辨认；`netsh interface ipv4 show dnsservers` 辅助查看接口 DNS 配置（[说明](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/netsh-interface)） |
| Windows IPv4 来源线索 | 注册表 `HKLM\SYSTEM\CurrentControlSet\Services\Tcpip\Parameters\Interfaces\{GUID}` 的 `NameServer` / `DhcpNameServer` 仅作静态配置与 DHCP 来源线索，先对应当前接口；可能缺失或残留，不能判断由谁修改，也不能证明当前查询路径 |
| Windows 系统 DoH | [Get-DnsClientDohServerAddress](https://learn.microsoft.com/en-us/powershell/module/dnsclient/get-dnsclientdohserveraddress) 查看已知服务器的 DoH 配置，核对 `AutoUpgrade`、`AllowFallbackToUdp` 与当前实际使用的解析器；列出服务器不代表正在使用 DoH，也不代表浏览器独立安全 DNS 或查询出站已验证 |

这些结果用于辨认配置来源，仍须结合日志与实际查询核实路径。命令不可用、DHCP 值缺失或证据不足时，相应项记未验证，不据此判通过。

| 观察 | 判断与处理 |
| --- | --- |
| 上游是局域网网关、内网 DNS 或 mDNS | 通过 |
| 上游是公网地址或循环指向，用户在用内网名称 | 说明影响并取得选择：改用可用的内网解析、接受现状，或本地拒绝相应查询。选择前这一项等待用户；接受现状时记失败并注明已告知，最终最多部分完成 |
| 同上，用户没有使用内网名称 | 记不适用，报告写明系统解析器是公网地址、已告知用户。不中断其他项，不自行改系统 DNS 或相关客户端开关 |
| 不清楚用户是否在用内网名称 | 问用户。答复前这一项等待用户，其他项继续 |
| 查不到实际上游 | 这一项记未验证，其他项继续 |

本地拒绝只在用户明确同意时使用，保留例外并验证。NXDOMAIN 或没有内网设备不能证明查询未外发。

### 如何检测与处理

使用当前版本支持的日志、诊断接口或其他可验证方式，触发各类真实查询，核对实际解析器、出站和应用结果；注意缓存、备用解析和 GUI 覆写。单独的命令行 DNS 请求可能不经过目标应用路径，不能替代目标应用验证。

<a id="dns-probes"></a>

下面这些手段不依赖客户端，可以作为佐证。命令行探针先确认没有继承代理环境变量（curl 加 `--noproxy '*'`），否则测到的是显式代理路径。FakeIP 模式下 A / AAAA 是合成地址或空答案，看不出去向，要查 TXT 或日志。

| 手段 | 能看到什么 | 限制 |
| --- | --- | --- |
| 客户端的 DNS 或连接日志 | 实际解析器、DoH 连接命中的策略和出站 | 最直接的证据；注意日志级别和缓存 |
| 查询 `whoami.ds.akahelp.net` 的 TXT 记录（`dig`、`nslookup`、`Resolve-DnsName`） | 探针返回的解析器信息，以及查询携带的 ECS 子网前缀（若有） | 属于未知类域名，只提供这次探针的线索；ECS 与代理出口或本地运营商网段一致、不一致或缺失，都不能单独证明查询经过代理或绕行 |
| 查询 `o-o.myaddr.l.google.com` 的 TXT 记录 | 递归解析器的地址 | 属于海外类域名；看不出查询是否经过代理 |
| `https://www.cloudflare.com/cdn-cgi/trace` | HTTP 出口的 IP 和地区 | 只说明连接出口，与 DNS 路径无关 |
| ipleak.net 等浏览器检测页 | 浏览器这条路径上的出口和解析器 | 单次结果，不能单独判断解析器是否经过代理 |

ECS 可由客户端或中间解析器生成、转发或修改，并非连接源地址的证明（[RFC 7871 §7.1](https://www.rfc-editor.org/rfc/rfc7871.html#section-7.1)）；例如 Mihomo 的 [ecs / ecs-override](https://wiki.metacubex.one/config/dns/#ecs) 可指定或覆盖前缀，上游是否接受、转发还取决于其策略。`ns`、`ip` 等返回字段也不替代路径证据，不以 ECS 优先裁决。应将同一次查询与实际解析器连接、命中的策略及出站链关联，或取得能证明该路径的可信抓包；证据不足时，该查询路径记未验证。

国内类目前没有通用探针，只能靠日志。没有日志时，出口结果加规则首匹配可以作佐证，但这一类仍记未验证。

据此调整最小必要的分域解析、节点引导、DNS 出站及接管设置；不强制使用某家公共 DNS 或模板字段。浏览器独立安全 DNS 若保留，也须满足相同策略。IPv4 与 IPv6 分开检查；没看到明文 53 端口流量，不能证明加密 DNS 没有绕路。证据不足就标未验证，不伪称抓包或真实出站已确认。

官方资料入口：[Mihomo DNS](https://wiki.metacubex.one/config/dns/) · [Surge DNS](https://manual.nssurge.com/dns/encrypted-dns.html) · [sing-box DNS](https://sing-box.sagernet.org/configuration/dns/)与[迁移说明](https://sing-box.sagernet.org/migration/)。具体字段由 Agent 按目标版本核实。

<a id="webrtc"></a>

## WebRTC 检测与处理

目标是避免 WebRTC 绕过约定路径，暴露未经认可的本地公网出口，同时确认用户需要的音视频功能。接管方式、UDP 和 IPv6 覆盖都影响结果；TUN 已开或扩展已安装不构成通过证据。[RFC 8828](https://www.rfc-editor.org/rfc/rfc8828.html)

1. 在同一浏览器配置档确认普通 HTTPS 的预期出口；保持现用代理开启。使用用户认可的 STUN / TURN 测试端点收集 ICE 候选，例如官方 [Trickle ICE](https://webrtc.github.io/samples/src/content/peerconnection/trickle-ice/)。不使用未知 TURN 凭据，不公开完整网络地址。
2. 识别 host、srflx、relay 候选并结合实际路径判断。relay 是中继地址，代理也可能有多个出口，不要求所有地址与 HTTP 出口字面相等；mDNS host 名称不证明公网路径已受保护。测试端点要走代理规则才能说明问题：按后缀逐级查它命中哪个名单，并先过用户规则，`stun.l.google.com` 目前靠 `google.com` 命中 proxy。国内端点按 direct 走，看到本机出口是分流结果，不算泄露。
3. 发现不符合目标的路径时，按当前浏览器支持的策略或扩展处理，再复测。支持的 Chrome / Chromium 可参考官方 [WebRTC Network Limiter](https://chromewebstore.google.com/detail/webrtc-network-limiter/npeicpdbkakmehahjeeohfdhnlpdklia)及 [IP handling policy](https://developer.chrome.com/docs/extensions/reference/api/privacy)；核对实际策略值，不绑定扩展版本、选项名称或位置。其他浏览器按其能力处理，不套用 Chrome 的结论。
4. 必要时检查扩展冲突、配置档权限和受管策略；安装、重启或可能暴露额外出口的对照先说明影响并取得同意，不绕过组织控制，不默认关闭整套 WebRTC 功能。处理后核对持久化和用户实际需要的通话功能。

| 观察 | 判断 |
| --- | --- |
| 证实存在未经认可的本地公网 IPv4 / IPv6 直连暴露 | 失败，修复后重测；无法修复时按主流程处理 |
| 候选及实际路径符合约定，测试端点工作正常 | 该轮路径检查通过；不扩大到未测设备、网络或通话能力 |
| 没有公网候选、零候选或页面空白 | 不单独判通过。获准后做隔离对照：同一设备开一个无扩展的临时浏览器配置档，现用代理和 TUN 都不动，确认 STUN 可达，再和原配置档比较。证据仍不足则未验证 |
| 没有浏览器 / 无法操作目标浏览器 | 前者按实际场景记不适用；后者指导用户并标明回传证据或未验证 |

DNS 与 WebRTC 互不替代：一项通过不证明另一项通过。修复若影响通话，说明影响并让用户选择恢复相关改动或继续研究支持的路径，不能静默放宽防护目标。

<a id="acceptance"></a>

## 逐项验收

样本从**本次实际规则和目标环境**中选择；不要假定某个示例域名永远在同一名单。每项记“通过 / 失败 / 未验证 / 不适用”和简短证据。

| 项目 | 完成条件 |
| --- | --- |
| TUN 与模式 | 运行状态、路由和目标应用证明实际接管，规则模式有效；系统代理请求不替代此项。按[接入范围](CLIENTS.md#scope)不适用时写明理由 |
| 规则加载与分流 | 完整接入五类资源真实加载且不为空，代表样本命中预期规则；受限接入分别列实际资源、主配置行为和缺失项 |
| 实际可用性 | 改前改后比较国内、海外 HTTPS 及适用内网服务，没有本次引入的解析、连接或 TLS 故障；只看命中不够 |
| DNS | 各查询类别、备用路径和浏览器解析符合上方目标，有实际解析器及出站证据 |
| WebRTC | 按上方判断表确认路径，分别记录配置档、策略与音视频功能结果 |
| IPv6 | 分别验证代理出口能力和设备目标流量接管；通过 HTTP 代理的 curl -6 成功不能单独证明二者 |
| 持久化 | 适用时刷新订阅；获准后重启客户端、浏览器并复查相关配置。没做就明确未验证，不适用须说明理由 |

配置检查、规则加载、真实请求和实体设备是不同层次。无浏览器不等于其他应用已验证；用户拒绝重启不等于检查失败。按 [AGENTS 状态表](../AGENTS.md#执行范围与最终状态)汇总，不能隐藏缺口。

<a id="report"></a>

## 简短交付格式

```text
环境与依据：时间、接入范围、目标设备/配置档、实际版本、文档提交 SHA 与必要官方依据
实际改动：修改位置、字段/策略、节点与例外是否保留；无须修改的项目注明保持现状
结果：规则 / DNS / WebRTC，以及 TUN、网页、IPv6、持久化各项状态和证据
规则身份：来源、格式、查询到的发布代、实际加载信息与刷新方式
恢复：配置前像、浏览器原选项、用户可独立执行的恢复方法及其文件路径
最终状态与缺口：完整通过 / 部分完成 / 等待用户 / 失败已回退；具体下一步
后续更新：已提醒经常更新；规则如何刷新；模板和说明怎么跟进（拉分支同步 / VPS 定期拉取 / 定期手动复查 / 尚未决定）；报告文件路径
项目反馈：发现的问题、已提交或补充的 Issue 链接；未提交时写明原因及本地草稿路径
```

查询到的最新发布 SHA 不等于客户端已加载的 SHA；只观察到更新时间时如实记录，严格同代需求见 [SYNC](SYNC.md)。报告脱敏，区分亲自观察、用户回传和未验证结果；结论只对本次实际范围负责。
