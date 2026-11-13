# DNS 与 WebRTC：目标、处理与验收

本页用于获准的完整设备接入与专项排查。规则入口与操作边界见 [AGENTS](../AGENTS.md)。完整接入先核对 [TUN 前置条件](CLIENTS.md#tun-required)，备份即将修改的设置，并给用户一份断网时也能执行的恢复方法。**普通连接、DNS 查询、WebRTC 网络路径分别检测。**

<a id="dns-goals"></a>

## DNS 目标

| 查询类别 | 目标 |
| --- | --- |
| 本机、LAN、private | 使用经核实的本地 / 内网解析路径，不把内网名发送给公网解析器；适用时保留 mDNS |
| 另行确认保留的用户例外 | 保持用户认可的独立策略，包括解析路径。保留的域名类例外按同一域名条件取得 DNS 策略 |
| 国内域名 | 直连使用可信加密解析器，后续连接遵循直连策略 |
| 海外与未知公网域名 | 使用经代理的可信加密解析器；未知域名的中国 IP 兜底按实际解析流程实现 |
| 节点服务器域名 | 使用用户认可、在代理建立前即可工作的引导解析，避免循环依赖 |

核对首选、备用及并发解析器、系统解析器、浏览器安全 DNS 和 IPv6；解析失败不静默退回直连或明文路径。DoH 加密不证明查询经过代理，DNS 分流也不能仅看配置里的解析器名称或 IP 归属地。

**DNS 路径按域名类别决定，不由业务连接的最终出站反推。** 首次解析、缓存未命中、重试、回退和连接建立时的再次解析都须保持该类别的目标。例如未知域名解析后因中国 IP 兜底而业务直连，其后续 DNS 仍须经代理加密；不能因为业务选择了 DIRECT 就另换直连解析器。出站自带或全局默认的域名解析器、规则动作中的解析也属于这些阶段，同样按域名类别核对；节点服务器域名的引导解析不能经过该节点所在的代理。具体字段和实现由执行 Agent 按现场能力选择。

<a id="private-dns-preflight"></a>

### 内网解析判断

应用前查清 system/local、回环 stub 的实际上游。客户端可能在运行时改写系统 DNS；系统当前值、网络下发值和核心实际使用的解析器分属不同层次，不能互相推断；取证时不固定接口名或虚拟 DNS 地址。路由器之后的转发设备看不到，不要求追查，在报告里注明即可。

分别核对**普通应用的系统查询路径**和**代理核心内部解析器的下一跳**。系统显示的地址可能只是被接管的占位地址；普通查询得到 FakeIP 只能证明该样本被接管。系统列表出现公网地址、DHCP 下发内网地址、普通查询已被接管，均不能单独证明核心处理 private 时的上游；`system/local` 也不保证导入系统的逐域或 mDNS 策略。实际内网名称只在用户认可且已核实的内网解析路径上测试，不能先向未确认的上游发送名称来探路。无法确定时记未验证。

系统层面的取值只用于辨认配置来源，取法见[系统检查入口示例](CLIENT-EVIDENCE.md#系统-dns-的只读入口示例)；仍须结合日志与实际查询核实路径，不替代上述路径判断。取不到或证据不足时，相应项记未验证，不据此判通过。

| 观察 | 判断与处理 |
| --- | --- |
| 上游是局域网网关、内网 DNS 或 mDNS | 通过 |
| 上游是公网地址或循环指向，用户在用内网名称 | 说明影响并取得选择：改用可用的内网解析、接受现状，或本地拒绝相应查询。选择前这一项等待用户；接受现状时记失败并注明已告知，最终最多部分完成 |
| 同上，用户没有使用内网名称 | 记不适用，报告写明系统解析器是公网地址、已告知用户。不中断其他项，不自行改系统 DNS 或相关客户端开关 |
| 不清楚用户是否在用内网名称 | 问用户。答复前这一项等待用户，其他项继续 |
| 查不到实际上游 | 这一项记未验证，其他项继续 |

本地拒绝只在用户明确同意时使用，保留例外并验证。NXDOMAIN 或没有内网设备不能证明查询未外发。

### 如何检测与处理

使用当前版本支持的日志、诊断接口或其他可验证方式，触发各类真实查询，核对实际解析器、出站和应用结果；注意缓存、备用解析和 GUI 覆写。单独的命令行 DNS 请求可能不经过目标应用路径，不能替代目标应用验证。不依赖客户端的探针、检测页及其限制见[参考方法](#dns-probes)，它们只作佐证；DNS 是否通过按[逐项验收](#acceptance)判定。

据此调整最小必要的分域解析、节点引导、DNS 出站及接管设置；不强制使用某家公共 DNS 或模板字段。浏览器独立安全 DNS 若保留，也须满足相同策略。IPv4 与 IPv6 分开检查；没看到明文 53 端口流量，不能证明加密 DNS 没有绕路。证据不足就标未验证，不伪称抓包或真实出站已确认。

官方资料入口：[Mihomo DNS](https://wiki.metacubex.one/config/dns/) · [Surge DNS](https://manual.nssurge.com/dns/encrypted-dns.html) · [sing-box DNS](https://sing-box.sagernet.org/configuration/dns/)与[迁移说明](https://sing-box.sagernet.org/migration/)。具体字段由 Agent 按目标版本核实。

<a id="webrtc"></a>

## WebRTC 检测与处理

目标是避免 WebRTC 绕过约定路径，暴露未经认可的本地公网出口，同时确认用户需要的音视频功能。接管方式、UDP 和 IPv6 覆盖都影响结果；TUN 已开或扩展已安装不构成通过证据。[RFC 8828](https://www.rfc-editor.org/rfc/rfc8828.html)

取证和处理时遵守：

- 在实际使用的浏览器配置档中取证，现用代理保持开启。测试端点使用用户认可的 STUN / TURN；不使用未知 TURN 凭据，报告不公开完整网络地址。
- 测试端点的去向按本次实际规则核对：先过用户规则，再按后缀逐级查它命中哪个名单，不沿用文档或以往报告中的名单归属。走代理的端点才能说明代理路径是否被绕过；国内端点按 direct 走，看到本机出口是分流结果，不算泄露。
- relay 是中继地址，代理也可能有多个出口，不要求所有候选与 HTTP 出口字面相等；mDNS host 名称不证明公网路径已受保护。
- 接入时按[浏览器检测与更新](../AGENTS.md#浏览器检测与更新)在每个获准的实际配置档中安装、配置或核对防护，再由 Agent 在同一配置档检测。复查按各配置档实际生效的策略及路径取证。
- 安装、重启或可能暴露额外出口的对照应在相应授权内执行。遵守受管策略，记录改动前的扩展和设置，处理后核对持久化及用户需要的通话功能。需要本人确认或额外权限时标明对应步骤，继续完成可独立执行的项目。

候选收集工具、浏览器官方教程和排查方向见[参考方法](#webrtc-methods)。

| 观察 | 判断 |
| --- | --- |
| 证实存在未经认可的本地公网 IPv4 / IPv6 直连暴露 | 记为失败。修复后重测，无法修复时记录缺口并核实相关改动的恢复结果 |
| 候选符合[逐项验收](#acceptance)的 WebRTC 条件，测试端点工作正常 | 该轮路径检查通过；不扩大到未测设备、网络或通话能力 |
| 用户已接受完全停用，且原生设置回读与新页面的 PeerConnection 接口检查一致 | 单列“WebRTC 已停用”，说明网页通话及数据通道受限；IP、DNS 仍须检测，不据此宣称代理路径或完整设备验收通过 |
| 没有公网候选、零候选或页面空白 | 不单独判通过。获准后可做隔离对照，现用代理和 TUN 都不动，做法见[参考方法](#webrtc-methods)。证据仍不足则未验证 |
| 没有浏览器 / 无法操作目标浏览器 | 没有浏览器时记不适用。无法操作时说明限制，未取得实际证据的检测项记未验证 |

DNS 与 WebRTC 互不替代：一项通过不证明另一项通过。修复若影响通话，说明影响并让用户选择恢复相关改动或继续研究支持的路径，不能静默放宽防护目标。

<a id="acceptance"></a>

## 逐项验收

完整设备接入按本节验收。每项记“通过 / 失败 / 未验证 / 不适用”，写明证据、类型和来源。适用项都有通过证据时报告完整通过。存在证据缺口或用户接受了能力限制时报告部分完成。缺少必要权限或用户选择时报告等待用户。发生故障时核实恢复结果，再报告是否已回退。只接入规则时见[交付与恢复](../AGENTS.md#交付与恢复)。

通用规则：

- 证据分四类：**配置**（文件、界面或 API 返回的设置）、**加载**（从核心回读的运行配置、资源条目数和更新时间）、**运行**（本次目标流量在核心日志或连接记录中实际命中的规则、解析器和出站）、**外部**（检测页、ICE 候选、抓包等网络侧观察）。每项写明通过所需的证据；只有其他类型的证据时记未验证。
- 证据与目标矛盾时记失败，不能用另一类看似正常的证据抵消。
- 样本从**本次实际规则和目标环境**中选择并注明来源；不要假定某个示例域名永远在同一名单。
- 不适用必须写理由，依据[接入范围](CLIENTS.md#scope)或下列条件。未验证不等于失败；无浏览器不等于其他应用已验证；用户拒绝重启不等于检查失败。

**TUN 与模式**

- 通过：目标应用发起的连接在核心连接记录中以 TUN 或经核实的等效系统隧道入站出现，IPv4、IPv6 分别记录；客户端处于规则模式。
- 需要：运行。
- 不能单独证明：TUN 开关、虚拟网卡、路由表、系统代理或显式代理请求成功。
- 不适用：服务器、规则分发、用户明确只要规则，按接入范围写明理由。

**规则来源与刷新**

- 通过：五类资源来自[发布地址](CLIENTS.md#资源与规则语义)或经核实内容等效的镜像；每个资源都开启了自动刷新；本次至少从该来源成功获取过一次，加载记录的更新时间或条目数能与本次查询到的发布对应。
- 需要：配置（来源与刷新设置）+ 加载（更新时间或条目数）。
- 不能单独证明：手工下载的本地文件、只写了地址而没有成功获取的记录、刷新被关闭或间隔未知。
- 规则分发场景：以 [SYNC](SYNC.md) 的 sync / verify 结果为准；之后怎样定期刷新由使用者决定，未安排时如实写明。

**规则加载与分流**

- 通过：五类资源都已加载且条目数不为零；每类至少一个取自本次发布数据的样本，在运行记录中首条命中对应规则并走预期出站；至少一个不在任何名单中的样本走默认代理。
- 覆盖验收：回读最终运行配置，确认[替换范围](CLIENTS.md#replace-business-rules)内的旧业务规则、旧规则集引用和旧兜底已停用。任一项仍生效时记覆盖未完成。
- 中国 IP 兜底：不在任何域名名单中的域名，按纯中国、纯境外、混合三种答案分别记录首条命中与出站。只有整组答案都在 cn-ip 内才可直连；纯境外与混合答案走默认代理。实现让域名不进入 IP 兜底时写明这一点，三种答案都应走默认代理。混合答案直连记失败；取不到混合答案的运行样本时，这一子项记未验证，源码或隔离实例的结果只作佐证。
- 需要：加载 + 运行。
- 不能单独证明：配置里写了规则、界面显示已加载、规则测试器的结果、另一台设备的命中；只用单一地址的答案判断中国 IP 兜底。
- 受限接入：分别列实际接入的资源、主配置承接的行为和缺失项，最终最多部分完成。

**用户例外优先**

- 通过：明确保留的用户例外在最终运行配置中仍位于托管规则之前，且至少一条例外的样本在运行记录中命中该例外。有域名类例外时，至少一条的实际解析器及其出站与接入前一致，或与用户确认的新策略一致。
- 需要：加载（最终规则顺序）+ 运行。
- 不能单独证明：编辑器、扩展或模块中的保存顺序；只核对了例外的路由命中，没有核对域名类例外的解析路径。
- 不适用：当前接入范围没有要保留的业务例外。

**核心自有地址**

- 通过：从运行配置读出 FakeIP 池和 TUN 接口的实际 IPv4、IPv6 前缀；按最终规则的首条命中，它们都不会落到真实 LAN 直连或中国 IP 兜底。
- 需要：加载（实际前缀与最终规则顺序）；能观察到相关流量时补充运行记录。
- 不能单独证明：模板或文档里的默认值、只核对了 FakeIP 池、只核对了一个地址族。
- 不适用：没有使用 FakeIP，且目标没有 TUN。

**实际可用性**

- 通过：改前、改后用同一组国内、海外 HTTPS 请求及适用的内网服务对比，没有本次引入的解析、连接或 TLS 故障。
- 需要：运行（改前、改后两次结果）。
- 不能单独证明：规则命中正确、改后单次请求成功。

**DNS**

- 通过：[DNS 目标](#dns-goals)中每个适用类别至少一个样本，实际解析器及其出站与目标一致，覆盖首次解析、连接建立时的再次解析，以及出站绑定或全局默认的解析器；未知域名经中国 IP 兜底直连时，DNS 仍走代理路径；节点服务器域名的解析不经该节点所在的代理。浏览器独立安全 DNS 若开启，同样核对。本机、LAN、private 类按[内网解析判断](#private-dns-preflight)判定。
- 覆盖验收：回读运行配置中订阅、客户端覆写和模块留下的业务 DNS 策略与回退。海外或未知公网域名仍使用已证实不符合目标的旧路径时，DNS 记失败。
- 需要：运行——同一次查询能关联到实际解析器连接、命中策略和出站链的日志，或可信抓包。
- 不能单独证明：配置里的解析器名称或地址、DoH 已加密、TXT / ECS 探针、命令行查询、未见明文 53 端口流量、NXDOMAIN。
- 未验证：没有日志的国内类；无法在不制造故障的情况下观察的备用和回退路径，只记配置证据。单地址与混合地址的证据分开记录。配置或客户端自带说明已表明某类别的备用路径偏离目标时，不能记未验证或通过：按[受限接入](CLIENTS.md#limited-integration)说明并由使用者选择，接受时最多部分完成。

**WebRTC**

- 通过：在每个目标浏览器实际使用的配置档中，先确认 STUN 测试端点在本次规则下走代理，再收集候选：host 候选只有 mDNS 名称或私有地址，没有公网 IPv4 或全局 IPv6；srflx 候选属于该配置档普通 HTTPS 的代理出口；relay 候选来自用户认可的 TURN。接入或调整防护时，回读各配置档实际生效的策略。用户需要的音视频功能已确认可用，或已记录用户的取舍。
- 需要：外部（候选列表）+ 运行或规则核对（测试端点的去向）。接入或调整防护时另需配置（实际生效的策略）。
- 不能单独证明：零候选、页面空白、扩展已安装、策略已设置、TUN 已开启。零候选按上方判断表做对照，证据仍不足记未验证。
- 失败：候选中出现未经认可的本机公网地址。代理有多个出口而无法确认 srflx 归属时记未验证。
- 不适用：设备没有浏览器。无法操作目标浏览器且没有用户回传时记未验证。

**IPv6**

- 通过：设备的 IPv6 目标连接在核心连接记录中以 TUN 入站出现；需要 IPv6 出口时，另行确认代理出口的 IPv6 能力。
- 需要：运行。
- 不能单独证明：经 HTTP 代理的 `curl -6` 成功、系统有 IPv6 地址。
- 失败：网络有 IPv6 连通但未被接管；处理方式由用户选择，见 [TUN 前置检查](CLIENTS.md#tun-required)。
- 不适用：当前网络没有 IPv6 连通（没有全局 IPv6 地址或默认路由），写明依据。

**持久化**

- 通过：按[持久化准则](CLIENTS.md#where-changes-survive)识别配置管理者和持久来源，在获准的重新生成、刷新或重启后，必要规则、DNS、明确保留的例外及适用的浏览器设置仍在运行状态中生效。
- 业务规则覆盖：节点订阅刷新或配置重新生成后，回读最终配置并确认旧业务规则、旧规则集引用和旧兜底没有恢复。旧规则恢复记失败。
- 需要：加载（重新生成或重启后回读运行配置）+ 运行抽样。
- 不能单独证明：文件写入成功、API 返回成功、临时加载成功。
- 未验证：复查未获准或未完成。重新生成后改动丢失记失败。不适用须写明理由，例如本次没有任何改动。

**恢复方法**

- 通过：恢复文件位于报告所写路径（碰不到设备时已交给用户），列出本次每项改动的前像或撤销方式，以及不依赖 Agent 连接的最小恢复步骤。
- 需要：核对文件存在及其内容；不要求实际执行恢复。
- 不能单独证明：报告里写了“已备份”，却没有路径或内容。
- 不适用：本次没有改动任何配置或浏览器设置。

<a id="report"></a>

## 简短交付格式

```text
环境与依据：时间、接入范围、目标设备/配置档、实际版本、文档提交 SHA 与必要官方依据
实际改动：修改位置、已覆盖的旧业务规则及兜底、节点来源、另行确认的例外
结果：逐项验收中每一项的状态、证据类型、证据及来源（亲自观察 / 用户回传）
规则身份：来源、格式、查询到的发布代、实际加载信息与刷新方式
持久化依据：配置管理者与持久来源、已完成的重新生成/刷新/重启、旧规则是否恢复、未做的复查及原因
恢复：配置前像、浏览器原选项、用户可独立执行的恢复方法及其文件路径
最终状态与缺口：完整通过 / 部分完成 / 等待用户 / 失败已回退；具体下一步
规则更新：规则集刷新方式、自动刷新状态及验证结果
项目反馈可选，附脱敏复现信息及 Issue 入口。
```

查询到的最新发布 SHA 不等于客户端已加载的 SHA；只观察到更新时间时如实记录，严格同代需求见 [SYNC](SYNC.md)。报告脱敏，区分亲自观察、用户回传和未验证结果；结论只对本次实际范围负责。

文档 SHA 以实际阅读的提交为准。需要核对时，可用 [master 提交记录](https://github.com/ryuu-restart/agent-route/commits/master)或 `git ls-remote https://github.com/ryuu-restart/agent-route.git refs/heads/master` 查询完整 SHA，再核对该提交下的文档。无法核对时记为未核实。

<a id="reference-methods"></a>

## 参考方法（可选）

本节是取证手段与工具入口，供执行 Agent 按现场能力选用，不是必经步骤，也不决定结果；是否通过只按[逐项验收](#acceptance)判定。主机名的名单归属、工具界面和选项会随时间变化，使用前按本次实际规则和当前版本核对。

<a id="dns-probes"></a>

### DNS 取证手段

下面这些手段不依赖客户端，可以作为佐证。命令行探针先确认没有继承代理环境变量（curl 加 `--noproxy '*'`），否则测到的是显式代理路径。FakeIP 模式下 A / AAAA 是合成地址或空答案，看不出去向，要查 TXT 或日志。

| 手段 | 能看到什么 | 限制 |
| --- | --- | --- |
| 客户端的 DNS 或连接日志 | 实际解析器、DoH 连接命中的策略和出站 | 最直接的证据；注意日志级别和缓存 |
| 查询 `whoami.ds.akahelp.net` 的 TXT 记录（`dig`、`nslookup`、`Resolve-DnsName`） | 探针返回的解析器信息，以及查询携带的 ECS 子网前缀（若有） | 通常属于未知类域名，按本次规则核对；只提供这次探针的线索；ECS 与代理出口或本地运营商网段一致、不一致或缺失，都不能单独证明查询经过代理或绕行 |
| 查询 `o-o.myaddr.l.google.com` 的 TXT 记录 | 递归解析器的地址 | 通常属于海外类域名，按本次规则核对；看不出查询是否经过代理 |
| `https://www.cloudflare.com/cdn-cgi/trace` | HTTP 出口的 IP 和地区 | 只说明连接出口，与 DNS 路径无关 |
| IPPure 的 [IP 检测](https://ippure.com/)与 [DNS 检测](https://ippure.com/DNS-Leak-Detect.html) | 浏览器这条路径上的出口和解析器 | 单次结果，不能单独判断解析器是否经过代理 |

ECS 可由客户端或中间解析器生成、转发或修改，并非连接源地址的证明（[RFC 7871 §7.1](https://www.rfc-editor.org/rfc/rfc7871.html#section-7.1)）；例如 Mihomo 的 [ecs / ecs-override](https://wiki.metacubex.one/config/dns/#ecs) 可指定或覆盖前缀，上游是否接受、转发还取决于其策略。`ns`、`ip` 等返回字段也不替代路径证据，不以 ECS 优先裁决；路径证据的要求见逐项验收的 DNS 项。

国内类目前没有通用探针，只能靠日志。没有日志时，出口结果加规则首匹配可以作佐证，但按逐项验收这一类仍记未验证。

<a id="webrtc-methods"></a>

### WebRTC 取证与处理入口

先识别浏览器、平台、版本与实际使用的配置档，再选择适用方法。以下是有官方资料或浏览器源码依据的入口，不代表已在所有版本实机通过。Chrome 和 Edge 固定使用 WebRTC Network Limiter；其他浏览器缺少该扩展安装能力时，继续查对应浏览器的原生设置或策略。Agent 在已有授权内完成配置。

#### 按浏览器选择方法

| 浏览器 | Agent 可采用的入口 | 生效核对与限制 |
| --- | --- | --- |
| 桌面 Chrome | WebRTC Network Limiter，选择 Use my proxy server (if present)，对应 `disable_non_proxied_udp` | 核对扩展启用状态、实际值及控制权；无法完成时标明原因和待配置状态。[扩展接口](https://developer.chrome.com/docs/extensions/reference/api/privacy) |
| 桌面 Edge | 同一扩展、同一选项和策略值 | 核对实际配置档中的扩展启用和生效设置；受限时标明待配置。[扩展安装](https://support.microsoft.com/zh-cn/edge/add-turn-off-or-remove-extensions-in-microsoft-edge) |
| 桌面 Brave | 同一扩展；内置入口为 Settings → Privacy and security → WebRTC IP Handling Policy → Disable Non-Proxied UDP | 核对扩展是否接管设置，避免互相覆盖；该选项限制非代理 UDP，不等于关闭整个 WebRTC。[Brave 官方设置](https://support.brave.app/hc/en-us/articles/360017989132-How-do-I-change-my-Privacy-Settings) |
| 桌面 Opera | 按官方 Chrome 扩展安装入口尝试 WebRTC Network Limiter，启用并设置 `disable_non_proxied_udp` | 官方支持 Chrome 扩展安装不等于保证某扩展在所有版本可用；核对当前商店兼容性、扩展控制权及实际值。[Opera 官方安装和管理说明](https://help.opera.com/en/faq/) |
| 桌面 Firefox | 需要保留 WebRTC 时核对 Firefox 的策略与代理；已接受停用时使用下述原生开关 | Firefox 的同名 `disable_non_proxied_udp` 在未配置浏览器代理时允许非代理连接，不能直接沿用 Chromium 的判断。[Mozilla 策略接口](https://developer.mozilla.org/en-US/docs/Mozilla/Add-ons/WebExtensions/API/privacy/network) · [行为说明](https://developer.mozilla.org/en-US/docs/Mozilla/Firefox/Releases/70#api_changes) |
| Safari | 优先在已获准范围内处理现用客户端的 UDP、IPv6 接管；需要完全停用时另行评估锁定模式 | 锁定模式有源码依据，但影响整个设备，不作为默认接入动作；实际版本、站点例外及结果须复查。[Safari 具体方案](#safari-webrtc) |

使用官方策略时，先确认该平台、版本与配置档受其支持，记录原值、来源和适用范围；不得为配置 WebRTC 擅自接入设备管理或覆盖组织策略。管理页显示写入成功仍需核对实际生效值、重启要求、扩展冲突及站点例外。浏览器品牌相同也不代表桌面和移动端具有相同能力。

#### 扩展安装与回读

支持的浏览器由 Agent 在目标配置档安装或启用 [WebRTC Network Limiter](https://chromewebstore.google.com/detail/webrtc-network-limiter/npeicpdbkakmehahjeeohfdhnlpdklia)，选择对应 `disable_non_proxied_udp` 的设置。0.2.1.4 显示为「Use my proxy server (if present)」。按实际版本核对，不把这一文案当作其他扩展通用的选项名。[Chrome 安装教程](https://support.google.com/chrome_webstore/answer/2664769?hl=zh-Hans)

在支持该接口的扩展环境中回读 `privacy.network.webRTCIPHandlingPolicy` 的值和 `levelOfControl`。Chrome 官方说明：设置调用即使成功，也可能立即被企业策略或其他扩展覆盖。遇到 `not_controllable` 或 `controlled_by_other_extensions` 时，确认实际控制来源；不能仅凭扩展选项勾选成功交付。无权修改的来源保留并报告限制。[Chrome 扩展接口](https://developer.chrome.com/docs/extensions/reference/api/privacy)

#### Firefox 原生停用与保留功能两条路径

若用户已明确接受网页 WebRTC 通话和数据通道不可用，Agent 可在桌面 Firefox 的实际配置档中执行：

1. 记录 `media.peerconnection.enabled` 的原值、是否为自定义值，以及控制来源。
2. 在 `about:config` 查找已有的 `media.peerconnection.enabled`，将其设为 `false`。若该版本没有此项，不通过新建同名偏好伪造支持。
3. 重新打开测试页面，回读偏好，并检查正常网页环境中的 `RTCPeerConnection` 是否已不可用。只看到 IPPure 空白或零候选不算完成。
4. 单列“WebRTC 已停用”，记录通话 / 数据通道限制；继续完成同配置档的 IP、DNS 检测，并记录 WebRTC 检测页实际状态。恢复时还原原值；此前没有自定义值则重置偏好，再重新打开页面复查。

Mozilla 的[配置编辑器说明](https://support.mozilla.org/en-US/kb/about-config-editor-firefox)提供偏好修改及恢复方法；[Firefox 源码](https://searchfox.org/firefox-main/source/dom/webidl/RTCPeerConnection.webidl)用该偏好控制 `RTCPeerConnection` 接口。该做法针对连接接口，不表示摄像头、麦克风采集权限也被关闭；Mozilla 的 [privacy.network 文档](https://developer.mozilla.org/en-US/docs/Mozilla/Add-ons/WebExtensions/API/privacy/network)明确区分二者。

需要保留 WebRTC 时，先核对浏览器是否实际使用代理。Firefox 的 `disable_non_proxied_udp` 在无浏览器代理时仍可能直连；有严格代理要求时可核对该版本是否支持 `proxy_only`，其官方定义只允许经代理、基于 TCP 的 TURN 连接。它需要可用代理和应用端 TURN 支持，不能承诺所有通话可用，也不要求使用者另建 TURN 服务。由 Agent 选择有依据且在授权内的设置入口，回读并验证实际连接。[Mozilla 行为说明](https://developer.mozilla.org/en-US/docs/Mozilla/Firefox/Releases/70#api_changes)

<a id="safari-webrtc"></a>

#### Safari：网络层防护与可选停用

已获准时，由 Agent 接入 [webrtc-guard 常见探测防护](WEBRTC-GUARD.md)，优先拒绝命中的已接管连接。该资源不依赖 Safari 扩展，但仍须逐项核对下面的接管、命中和功能影响；自定义端点与绕过核心的流量不因此得到保障。

Safari 不能直接照搬 Chrome 扩展的策略接口：Mozilla 的[兼容性数据](https://github.com/mdn/browser-compat-data/blob/main/webextensions/api/privacy.json)将 Safari 的 `privacy.network.webRTCIPHandlingPolicy` 标为不支持。现有资料不能证明有一款 Safari 扩展能等效完成本项目的防护目标；商店名称相似、页面脚本拦截或隐藏 host 地址都不能代替运行证据。

**保留 WebRTC：优先检查现用客户端的实际网络接管。** 这是供 Agent 按版本实施的处理顺序，尚不构成具体设备通过的证据：

1. 在同一 Safari 配置档触发获准的 STUN / TURN 请求，对照客户端连接记录或获准的抓包，分别记录 IPv4、IPv6 的入站、规则命中和实际出站。HTTP 出口正常不能替代此检查。
2. 客户端没有观察到请求时，先排除测试未发出或日志不完整，再检查 TUN、双栈路由与排除项。只开启系统 HTTP 代理或看到 TUN 开关开启都不足以交付。Mihomo 的 `strict-route` 文档分别说明 Linux / Windows 行为，不能直接把这些保障当作 macOS 已完成的验证。[Mihomo TUN 文档](https://wiki.metacubex.one/config/inbound/tun/)
3. 请求进入客户端但命中 DIRECT 时，核对是否是约定的国内直连规则。如果用户目标是不向任何公网 STUN 端点暴露直连出口，就须在相应授权内让这些连接走受控代理或阻断；保留原直连结果不能报告该目标已达成。不能只加检测站的域名或几个常见端口就声称覆盖全部 WebRTC。
4. 核对当前节点与代理组的 UDP 支持及失败行为。Mihomo 官方说明，UDP 请求遇到不支持 UDP 的代理可能继续向下匹配；要检查后续 DIRECT 或兜底，确保目标流量不会因此回落直连。可用性不满足时，在用户接受的范围内采用阻断并说明通话影响，不能静默切换节点或放宽路径目标。[Mihomo 匹配顺序与 UDP 行为](https://wiki.metacubex.one/config/rules/)
5. 在持久配置入口应用最小改动后，回读配置并复测 IP、DNS、WebRTC 和需要的通话功能。IPv6 仍绕过时单列失败；零候选须区分策略阻断与测试故障，不能仅凭空白页通过。节点刷新或重载后的结果另行记录。

**完全停用的可选路径：Apple 锁定模式。** [WebKit 源码](https://github.com/WebKit/WebKit/blob/c8dd7991380207583aabb9cf2c86d48bdde54d3f/Source/WTF/Scripts/Preferences/UnifiedWebPreferences.yaml#L4862)将 `PeerConnectionEnabled` 标记为 `disableInLockdownMode: true`。这是停用 PeerConnection 的源码依据，不能扩大为所有 Safari 版本已经实测。

锁定模式会影响设备上的多项功能并要求重启，只有用户明确接受该影响时才实施。在 macOS 的系统设置 → 隐私与安全 → 锁定模式中操作；iPhone / iPad 使用系统设置中的对应入口。启用后还要检查 Safari 的站点例外，在新页面回读 `RTCPeerConnection` 的可用性；被排除的站点不受同样的 WebKit 限制。结果单列“WebRTC 已停用”，IP、DNS 继续验收，恢复时关闭锁定模式并按系统提示重启、复查。[Apple 官方说明](https://support.apple.com/en-us/105120)

Apple 的 `WKWebpagePreferences.isLockdownModeEnabled` 是应用开发接口，不能当作能直接控制现有 Safari 的设置命令；未核实生效的 `defaults write` 键也不纳入自动接入方案。[Apple API 说明](https://developer.apple.com/documentation/webkit/wkwebpagepreferences/islockdownmodeenabled)

#### 社区教程的使用边界

[K3V1991 的浏览器 WebRTC 教程](https://github.com/K3V1991/How-to-disable-WebRTC-in-Chrome-Firefox-Safari-Opera-and-Edge)可用于发现候选方法；配置前仍须核对实际版本和官方依据。不能直接采纳其中以下判断：

- Safari 的 `Remove Legacy WebRTC API` 涉及旧 API，不会因此停用现代 `RTCPeerConnection`。[WebKit 对旧 API 与现代 API 的说明](https://webkit.org/blog/7763/a-closer-look-into-webrtc/)
- Safari 的 `Disable ICE Candidate Restrictions` 会放开 host 候选过滤，不能作为增强防护的开关。[WebKit 开关说明](https://webkit.org/web-inspector/device-settings/)
- Chrome 的 STUN Origin Header、WebRTC 硬件编码和解码开关控制报文头或硬件加速，不能用来宣称已禁用 WebRTC。[Chromium 开关定义](https://chromium.googlesource.com/chromium/src/+/fb96126ce933cba0dd4fbe6cde9fd519b6a61ec3/content/public/common/content_switches.cc)
- 旧 Edge 的隐藏本地 IP 选项，以及任何仅隐藏局域网 host 地址的设置，都不能单独证明公网 IPv4 / IPv6 已遵循约定路径。

Safari 的具体处理见[网络层防护与可选停用](#safari-webrtc)。不默认更换 VPN、开启浏览器内置 VPN 或屏蔽全设备 UDP。未得到目标设备证据时记未验证。

#### 取证与复测

- 候选收集：用用户认可的 STUN / TURN 端点，例如官方 [Trickle ICE](https://webrtc.github.io/samples/src/content/peerconnection/trickle-ice/) 页面；同时在同一配置档确认普通 HTTPS 的出口，供判断 srflx 归属。
- 测试端点去向：按后缀逐级查它在本次规则中命中的名单，先过用户规则。公共 STUN 主机名的名单归属随规则发布变化，以本次查到的为准。
- 处理后结果不符时，检查扩展冲突、配置档权限和受管策略。
- 零候选对照：获准后，在同一设备开一个无扩展的临时浏览器配置档，现用代理和 TUN 都不动，确认 STUN 可达，再和原配置档比较。
