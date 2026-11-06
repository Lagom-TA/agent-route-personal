# 客户端适配原则

整体流程见 [AGENTS](../AGENTS.md)。本页提供资源、规则语义和适配边界；字段、界面、命令以**目标设备实际版本**为准。使用者的 Agent 负责查询资料、选择实现并验证，不要求项目维护者适配每一种客户端。

<a id="scope"></a>

## 接入范围

先确定目标属于哪一种，并写进报告。

| 目标 | TUN | DNS | WebRTC | 结论范围 |
| --- | --- | --- | --- | --- |
| 电脑或手机上的代理客户端 | 必需 | 全部目标 | 适用；设备没有浏览器时不适用 | 可完整通过 |
| 服务器或网关上的代理核心 | 按实际接管方式判断，不强制 | 核心自身的解析路径 | 没有浏览器时不适用 | 只覆盖这台机器，不代表连接它的设备 |
| 只把规则文件同步、分发给其他设备 | 不适用 | 不适用 | 不适用 | 只覆盖规则文件的更新和校验 |
| 用户明确不开 TUN，只要规则 | 说明影响后跳过 | 只处理规则依赖的解析，其余未验证 | 未验证 | 最多部分完成 |

只接规则时，未被接管的应用、DNS 和 WebRTC 可能绕过代理，必须告诉用户，不能报告防护通过。修改远程服务器前，先确认断开 SSH 后还能恢复，例如通过云厂商控制台。海外服务器上的“直连”是这台服务器直接访问，“国内直连”是否需要，按用户的目的确认。

<a id="tun-required"></a>

## TUN 前置检查

电脑和手机上接入要求 TUN 或经核实的等效系统隧道，包括客户端对应的增强模式或系统 VPN 接管能力。检查运行状态、系统路由以及目标应用的流量和 DNS 路径，IPv6 单独验收；仅有开关、配置字段或虚拟网卡不够。

尚未启用时，按实际版本给使用者具体开启步骤和独立恢复方法，待其启用、确认后再接入。系统代理、浏览器代理或 mixed 入站不能替代。无法启用或无法确认时保持原配置，报告等待用户；用户明确接受后才可只接规则。TUN 也不能替代规则模式与 DNS 路径检查。

IPv4 接管成立就继续接入。IPv6 没被接管时单独记失败并说明影响：直接走 IPv6 的连接会绕过代理。处理方式由用户选：开启客户端支持的 IPv6 接管，或接受限制（最多部分完成）。关闭 IPv6 只能由用户决定，不能当默认修复。

TUN 和系统代理可以同时开。这时网页可能走系统代理、WebRTC 的 UDP 走 TUN，要分别取证；连接记录里的入站类型能看出走了哪条路径。

## 资源与规则语义

[机器索引](https://raw.githubusercontent.com/ryuu-restart/agent-route/release/index.json)列出资源地址、格式及条目数，[清单](https://raw.githubusercontent.com/ryuu-restart/agent-route/release/manifest.json)记录发布信息与摘要。公开读取无需凭据。

| 客户端 / 核心 | 使用格式 | 资料入口 |
| --- | --- | --- |
| Mihomo 及其图形客户端 | `mihomo/<规则>.yaml`，域名与 IP 使用相应 behavior | [规则集](https://wiki.metacubex.one/config/rule-providers/)、[DNS](https://wiki.metacubex.one/config/dns/) |
| Surge / Shadowrocket | `surge/<规则>.list`，无策略列的 RULE-SET 文本 | [Surge 规则集](https://manual.nssurge.com/rules/ruleset.html)；Shadowrocket 目前没查到公开的官方配置手册，核对 App 内说明、[社区手册](https://github.com/LOWERTOP/Shadowrocket)（非官方）和实际能力，不直接照搬 Surge 字段 |
| sing-box 及其图形客户端 | `sing-box/<规则>.json`，source rule-set version 3 | [规则集](https://sing-box.sagernet.org/configuration/rule-set/)、[迁移说明](https://sing-box.sagernet.org/migration/) |

`<规则>` 为 private、reject、proxy、direct、cn-ip；地址前缀为 `https://raw.githubusercontent.com/ryuu-restart/agent-route/release/`。格式版本是实际兼容要求，不是文档装饰。旧格式公开地址继续保留，但新接入优先选择索引中的标准资源。来源是镜像或自建转换时，内容等效且刷新正常就保留，报告注明未核对发布代。

完整接入保持：**用户例外 → 节点地址 → 本地与 LAN → DNS 服务器路径 → private → reject → proxy → direct → cn-ip → 默认代理**。按客户端能力实现等效语义，不要求逐行照搬模板；FakeIP / 合成地址不能当成真实 LAN 或中国 IP 直连。

private 为通用内网域名；direct 只含域名，cn-ip 只含公网中国 IPv4 / IPv6。保留精确域名与后缀的区别。cn-ip 在域名策略之后兜底，需实际获得真实地址；不能因混合答案中存在一个中国 IP 就全部直连。sing-box 的 non-cn-ip 辅助集可用于 DNS 判断，具体实现按版本确认。个人节点、业务例外和广告白名单由使用者维护。

<a id="baseline"></a>

## 版本与可选示例

先核对真实核心而非仅看 GUI 版本，再查对应版本的官方配置文档、迁移说明、程序帮助或配置 Schema。版本不同先确认能力，不直接要求升级或降级；没有可靠依据时报告不确定性。仅有社区资料时注明来源性质，并用实际检查与运行证据核实，不能写成官方已保证。

四套[完整示例及历史验证记录](../examples/README.md)仅供参考。示例支持的功能、验证版本和限制不等于整个项目的最低版本或未来兼容承诺。也可以不使用模板。

<a id="pitfalls"></a>

## 已知易错点

只收官方写明或真实踩过的坑，用来提醒该查什么，不是配置教程；字段仍以实际版本为准。发现新的坑请[反馈](https://github.com/ryuu-restart/agent-route/issues/new/choose)。

| 范围 | 易错点 | 依据 |
| --- | --- | --- |
| Surge | 加密 DNS 默认直连，不经过规则。开启 `encrypted-dns-follow-outbound-mode` 后，命中的节点地址如果是域名，这条连接仍回退直连 | [手册](https://manual.nssurge.com/dns/encrypted-dns.html) |
| Surge | 模块里的规则只能用 DIRECT、REJECT 等内置策略，代理规则放不进去 | [手册](https://manual.nssurge.com/profile/module.html) |
| Mihomo | `respect-rules` 要配 `proxy-server-nameserver`，否则节点解析可能依赖节点自身。设置 `direct-nameserver` 后，直连的二次解析默认不遵循 `nameserver-policy`，内网名可能被发给它 | [文档](https://wiki.metacubex.one/config/dns/) |
| Clash Verge Rev | v2.5.5 起，扩展配置只替换 `dns` 下写出的子字段，未写的保留；写出 `nameserver-policy` 会替换整个策略表，不逐条合并。`ipv6`、`tun.enable` 等设置页接管的字段会在末尾回写 | [文档](https://www.clashverge.dev/guide/extend.html)、[v2.5.10 合并代码](https://github.com/clash-verge-rev/clash-verge-rev/blob/c83f7ad529c7c9cb3d2d54a0955ef8c1b22a411b/src-tauri/src/enhance/merge.rs#L19) |
| Clash Verge Rev | v2.5.10 先处理规则编辑器，再执行全局扩展和订阅扩展；后续脚本直接 prepend 托管块，会把它放到编辑器中的用户例外前。可在同一“编辑规则”入口按“用户例外 → 托管规则”排列 prepend，再核对后续扩展及最终生成配置 | 2026-11 核对 [v2.5.10 执行顺序](https://github.com/clash-verge-rev/clash-verge-rev/blob/c83f7ad529c7c9cb3d2d54a0955ef8c1b22a411b/src-tauri/src/enhance/mod.rs#L916) |
| Clash Verge Rev | v2.5.10 开启 DNS 覆写时，实际接管的 DNS 字段和 hosts 会在扩展之后恢复。2026-11-06 官方网页对此与该版本源码描述不同，不能只凭“扩展后执行”认定能覆盖设置；按实际版本核对最终配置 | [v2.5.10 回写代码与测试](https://github.com/clash-verge-rev/clash-verge-rev/blob/c83f7ad529c7c9cb3d2d54a0955ef8c1b22a411b/src-tauri/src/enhance/mod.rs#L1439)，未经本项目实机验证 |
| Clash Verge Rev | v2.5.7 优先读取当前订阅 UID 对应的 `profile_dns_settings`，没有该项才回退到 `enable_dns_settings`。不能只看旧全局字段判断 DNS 覆写是否生效；核对当前订阅的实际开关及最终生成配置，不默认关闭覆写 | [v2.5.7 源码](https://github.com/clash-verge-rev/clash-verge-rev/blob/ea509b82363a40c3c32e951d7ce9d66d66da411f/src-tauri/src/config/dns.rs#L116)；2026-11 [用户实机补充](https://github.com/ryuu-restart/agent-route/issues/11#issuecomment-6678341203)，仅限所述环境，未独立复现 |
| FlClash | “DNS覆写”“追加系统DNS”会改变订阅里的 DNS 策略 | 2026-10 实测，[代码](https://github.com/chen08209/FlClash/blob/main/lib/common/task.dart) |
| FlClash | “自动设置系统DNS”把 `223.5.5.5` 写进系统设置。网络的 DNS 来自 DHCP 时，系统里就只剩这个公网地址，Mihomo 的 `system` 随之指向公网，内网名会发给它 | 2026-11 本机核对，[代码](https://github.com/chen08209/FlClash/blob/v0.9.2/lib/common/system_dns.dart) |
| FlClash | “查找进程”关闭时 `find-process-mode` 为 off，会覆盖订阅里的值，PROCESS 规则不生效 | 2026-11 本机核对 |
| sing-box | 路由规则不会替域名解析（除非用 `resolve`），直接传入 SOCKS / HTTP 的未知域名走默认出站。没有 `sniff` 时，只有 IP 的流量匹配不到域名规则 | [文档](https://sing-box.sagernet.org/configuration/route/rule_action/)，2026-10 隔离实测 |
| FakeIP | 常用的 FakeIP IPv6 段在 `fc00::/7` 内，这条 LAN 规则排在前面时，FakeIP 流量可能被当成内网直连 | [项目模板](../examples/full/mihomo.yaml)的规则顺序和测试 |
| Shadowrocket | 普通 DoH 地址不经过节点，要加 `#proxy`。`proxy-dns-server` 只解析节点域名。`[Host]` 没写能引用规则集，内网域名要逐条加 | [社区手册](https://github.com/LOWERTOP/Shadowrocket)（非官方，未经真机验证），2026-10 用户反馈 |
| Chrome / Chromium | 策略为 `disable_non_proxied_udp` 时 ICE 候选可能为 0，这不证明安全。TUN 下不装扩展，srflx 也可能已是节点出口 | 2026-11 对照：无扩展临时配置档与原配置档比较 |
| 广告名单 | 会拦一些遥测和功能开关域名，如 `statsig.anthropic.com`、`featuregates.org`。AI 工具行为异常时先查这里，实际影响未实测 | 2026-11 名单抽查 |

<a id="config-check"></a>

## 配置检查

选用当前客户端真实支持的检查命令、配置检查器或导入校验；命令、路径和参数从实际帮助确认。检查候选文件及 GUI 最终生成的有效配置，不能只检查片段。无可用入口就注明未做原生检查，并明确可获得的导入、加载及运行证据。

配置语法通过不代表资源已加载、DNS 走向正确或设备已接管。资源、规则、DNS 等依赖应在应用前齐备；不能为了测试而另起未管理的代理或第二条 TUN。

<a id="where-changes-survive"></a>

## 配置持久化

先确认配置是本地编辑、订阅生成还是托管；订阅由用户自建时，先问是否改生成端。使用该版本支持的持久覆写、扩展或模块机制；核对它是合并还是整段替换，以及实际规则顺序。保留用户例外，不让受管规则提前覆盖它们，也不让旧最终规则抢先命中。

找不到可靠的持久化位置时，说明改订阅原文或另建本地配置的影响，取得用户选择；不要静默换配置来源。节点变化后，节点连接例外和引导解析也需重新核对。接入后刷新订阅，并在获准重启后复查实际配置；没做就不能报告已持久化。

<a id="limited-integration"></a>

## 能力不足与受限接入

托管配置或模块可能限制可用策略和排序。先按官方资料与现场检查确认限制；若无法保持规则语义，说明缺失能力和替代方案，取得用户选择。没有可靠方案或用户未接受限制时停止相关修改。

用户明确接受受限接入时，只列实际接入的资源、主配置承接的行为和未实现项，最终最多报告部分完成。TUN 门槛（用户明确只要规则时见[接入范围](#scope)）、DNS / WebRTC 目标、用户例外保护不因此豁免；已确认的错误路径不能被改名为“受限”而判通过。[Surge 模块手册](https://manual.nssurge.com/profile/module.html)是这类限制的一个例子，不是其他客户端的通用实现。

## 更新与验证责任

规则每日 UTC+8 06:30 计划构建，可能延迟，以清单时间为准；验证失败保留旧发布。客户端通常约每 24 小时刷新，资源须真实加载且不为空；下载路径由现场网络和可用缓存决定。各资源不保证同时切换，严格同代下载、校验与本地回退见 [SYNC](SYNC.md)。

项目测试验证规则与记录的示例；目标设备的加载、分流、DNS、WebRTC 和持久化由使用者的 Agent 实测。最终按 [DNS-WEBRTC](DNS-WEBRTC.md#acceptance)交付，不能把项目 CI 或别人的设备结果当成自己的验收。
