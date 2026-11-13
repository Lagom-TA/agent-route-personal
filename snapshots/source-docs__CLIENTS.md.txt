# 规则格式与客户端参考

<a id="客户端适配原则"></a>

[AGENTS](../AGENTS.md) 提供规则入口和操作边界。具体接法由使用者的 Agent 根据现有配置和实际客户端版本决定。

<a id="scope"></a>

## 接入范围

先确认用户要改的是哪一处配置，以及要覆盖哪些流量。

| 目标 | 做法与结论范围 |
| --- | --- |
| 现有代理客户端接入规则 | 按实际客户端能力[替换业务分流](#replace-business-rules)，验证已接管的流量 |
| 明确要求完整设备接入 | 按 [TUN 前置检查](#tun-required)和[逐项验收](DNS-WEBRTC.md#acceptance)验证获准的流量、DNS、WebRTC 和持久化 |
| VPS 只作节点 | 在电脑上负责分流的客户端接入。VPS 继续作为原有代理出口 |
| 获准在服务器或网关上接入 | 改实际执行分流的配置。结论覆盖该核心接管的流量，直连使用该服务器或网关的出站网络 |
| 仅同步或分发规则文件 | 按[同步工具](SYNC.md)核对文件更新和校验 |

只接规则时，向用户说明哪些应用实际经过该客户端。VPN 只有应用或 IP 网段分流时，说明域名或拦截能力的缺口。修改远程服务器前，先确认断开 SSH 后仍能通过独立入口恢复。

<a id="replace-business-rules"></a>

## 替换业务分流

在获准的配置中，用 AgentRoute 的五类规则和默认代理兜底整段替换旧业务分流。停用节点订阅、客户端覆写、模块和其他来源中的旧业务规则及其规则集引用，也停用旧的最终兜底。原配置及各生效来源先备份，供恢复时使用。

节点订阅继续用于更新节点。保留可用节点、必要策略组，以及节点连接、引导解析、内网、DNS 接管和核心自有地址所需的技术规则。默认代理策略组须核实实际通过代理节点出站。使用者另行提出并确认的自定义业务例外按约定处理，域名类例外按同一域名条件保留经确认的解析去向。

检查订阅、模块和客户端覆写留下的 DNS 规则、解析器及回退设置。与 [DNS 目标](DNS-WEBRTC.md#dns-goals)冲突的旧业务解析策略按授权移除或替换。用真实查询核对出站，按接入范围单列 DNS 结果。

<a id="tun-required"></a>

## TUN 前置检查

完整设备接入要求 TUN 或经核实的等效系统隧道，包括客户端对应的增强模式或系统 VPN 接管能力。检查运行状态、系统路由以及目标应用的流量和 DNS 路径，IPv6 单独验收。用实际连接取证。

尚未启用时，按实际版本给使用者开启步骤与恢复方法，待其启用并确认后再做完整接入。系统代理、浏览器代理或 mixed 入站的结果只覆盖实际接管的应用。无法确认全设备接管时报告该项待验证，或由用户选择按[默认规则范围](#scope)接入。规则模式和 DNS 路径分别核实。

IPv4 接管成立就继续接入。IPv6 没被接管时单独记失败并说明影响：直接走 IPv6 的连接会绕过代理。处理方式由用户选：开启客户端支持的 IPv6 接管，或接受限制（最多部分完成）。关闭 IPv6 只能由用户决定，不能当默认修复。

TUN 和系统代理可以同时开。这时网页可能走系统代理、WebRTC 的 UDP 走 TUN，要分别取证；连接记录里的入站类型能看出走了哪条路径。

## 资源与规则语义

[机器索引](https://raw.githubusercontent.com/ryuu-restart/agent-route/release/index.json)列出资源地址、格式及条目数，[清单](https://raw.githubusercontent.com/ryuu-restart/agent-route/release/manifest.json)记录发布信息与摘要。公开读取无需凭据。

| 客户端 / 核心 | 使用格式 | 资料入口 |
| --- | --- | --- |
| Clash 系列（Mihomo 内核） | `mihomo/<规则>.yaml`，域名与 IP 使用相应 behavior | [规则集](https://wiki.metacubex.one/config/rule-providers/)、[DNS](https://wiki.metacubex.one/config/dns/) |
| 小火箭（Shadowrocket）/ Surge | `surge/<规则>.list`，无策略列的 RULE-SET 文本 | [Surge 规则集](https://manual.nssurge.com/rules/ruleset.html)；Shadowrocket 目前没查到公开的官方配置手册，核对 App 内说明、[社区手册](https://github.com/LOWERTOP/Shadowrocket)（非官方）和实际能力，不直接照搬 Surge 字段 |
| sing-box 及其图形客户端 | `sing-box/<规则>.json`，source rule-set version 3 | [规则集](https://sing-box.sagernet.org/configuration/rule-set/)、[迁移说明](https://sing-box.sagernet.org/migration/) |

`<规则>` 为 private、reject、proxy、direct、cn-ip，独立防护资源为 webrtc-guard；地址前缀为 `https://raw.githubusercontent.com/ryuu-restart/agent-route/release/`。格式版本是实际兼容要求，不是文档装饰。旧格式公开地址继续保留，但新接入优先选择索引中的标准资源。来源是镜像或自建转换时，内容等效且刷新正常就保留，报告注明未核对发布代。

`webrtc-guard` 使用独立的端口及域名关键字条件，Mihomo 必须使用 `classical`。按[防护说明](WEBRTC-GUARD.md)置于必要技术规则之后、普通公网 DNS 地址例外及业务规则之前，明确拒绝匹配连接；不要用于 DNS 规则集。首次接入后才会随远程资源更新。

索引给出项目业务规则的动作和建议顺序 **private → reject → proxy → direct → cn-ip**。内网与国内规则的动作是直连，广告规则的动作是拦截，海外规则的动作是代理。未命中规则的流量走已确认的默认代理策略。

接入时保留节点连接、引导解析、LAN、DNS 和核心自有地址所需的技术路径。核对真实 FakeIP 池与 TUN 前缀，避免当作真实 LAN 或中国 IP 匹配。

`private` 为通用内网域名，`direct` 只含域名，`cn-ip` 只含公网中国 IPv4 / IPv6。保留精确域名和后缀的区别。域名进入中国 IP 兜底时须核对整组真实地址，混合国内外答案走代理兜底。Mihomo 的 `no-resolve` 跳过本条触发的解析，前序规则已经解析的地址仍可能命中。无法保证的域名使用代理兜底，按[受限接入](#limited-integration)说明适用范围。sing-box 的 non-cn-ip 辅助集用于 DNS 判断，具体实现按版本确认。[Mihomo 匹配说明](https://wiki.metacubex.one/en/config/rules/#no-resolve)

<a id="订阅适配"></a>

## 订阅格式

给 Agent 的入口包含规则索引和对应的格式。业务规则地址在索引的 `datasets[].resources` 中；入口的 `protections: ["webrtc-guard"]` 指向索引 `protections[].resources` 中的独立防护，建议刷新间隔为 24 小时。`routing_mode: replace` 和 `final_action: PROXY` 分别表示替换业务分流和默认走代理。具体覆写方式按实际客户端确定。

### Mihomo

索引的 `mihomo` 资源是原生 YAML 规则集，`mihomo_behavior` 标明 `domain`、`ipcidr` 或防护所需的 `classical` 类型。Clash Verge Rev 和 FlClash 等客户端以实际运行的内核为准。[Mihomo 规则集](https://wiki.metacubex.one/config/rule-providers/) · [Clash Verge Rev](https://github.com/clash-verge-rev/clash-verge-rev) · [FlClash](https://github.com/chen08209/FlClash)

### Surge

索引的 `surge` 资源是 RULE-SET 文本，策略由引用规则集的客户端配置指定。[Surge 规则集](https://manual.nssurge.com/rules/ruleset.html)

### Shadowrocket

小火箭（Shadowrocket）入口指向同一组 `surge` 格式文件。引用和刷新能力以实际 App 版本为准。

### sing-box

索引的 `sing-box` 资源是 source 格式的 JSON 规则集。[sing-box 规则集](https://sing-box.sagernet.org/configuration/rule-set/)

<a id="baseline"></a>

## 版本与可选示例

先核对真实核心而非仅看 GUI 版本，再查对应版本的官方配置文档、迁移说明、程序帮助或配置 Schema。版本不同先确认能力，不直接要求升级或降级；没有可靠依据时报告不确定性。仅有社区资料时注明来源性质，并用实际检查与运行证据核实，不能写成官方已保证。

四套[完整示例及历史验证记录](../examples/README.md)仅供参考。示例支持的功能、验证版本和限制不等于整个项目的最低版本或未来兼容承诺。也可以不使用模板。

<a id="pitfalls"></a>

## 通用检查点

以下内容供使用者的 Agent 按需参考。配置交付按[交付与恢复](../AGENTS.md#交付与恢复)说明，完整设备接入按[逐项验收](DNS-WEBRTC.md#acceptance)判定。发现规则或示例问题时，可使用[反馈入口](../AGENTS.md#issue-feedback)。

| 检查点 | 必须保持的准则 |
| --- | --- |
| 规则与顺序 | 回读最终规则和默认策略，核对旧业务规则和旧兜底已停用。另行获准保留的域名例外按同一域名条件保持其解析去向 |
| 配置来源与持久化 | 区分原始配置、覆写、当前配置档和运行配置；按实际版本核实谁拥有最终值，订阅刷新后仍须成立 |
| DNS 全阶段路径 | 首次、备用、再次解析及出站绑定的解析器都遵守域名类别目标；业务直连不自动授权 DNS 直连，节点域名不经该节点所在的代理解析，本地解析标签不证明实际上游。域名类别来自域名规则（含用户例外），IP 规则和中国 IP 兜底不改变它 |
| 域名与核心自有地址 | 已知域名应按域名规则判断；裸 IP、嗅探和 FakeIP 是不同证据。FakeIP 池、TUN 接口等核心自有地址按运行配置的实际值核对，各地址族的来源可能不同，都不能命中真实 LAN 或中国 IP 兜底 |
| 证据与能力边界 | 单字段、单次探针、语法检查或另一设备的成功都不代表目标设备通过；不能保持目标时报告限制并由使用者选择 |

具体版本的来源、已知案例和系统命令保存在[可选证据](CLIENT-EVIDENCE.md)。按需查证，不把案例当作通用操作步骤。

<a id="config-check"></a>

## 配置检查

选用当前客户端真实支持的检查命令、配置检查器或导入校验；命令、路径和参数从实际帮助确认。检查候选文件及 GUI 最终生成的有效配置，不能只检查片段。检查或导出工具可能只解析部分段落：先确认它的输出或说明覆盖了待验证的规则、规则集和 DNS，未覆盖的部分记未做原生检查。无可用入口就注明未做原生检查，并明确可获得的导入、加载及运行证据。

配置语法通过不代表资源已加载、DNS 走向正确或设备已接管。资源、规则、DNS 等依赖应在应用前齐备；不能为了测试而另起未管理的代理或第二条 TUN。

<a id="where-changes-survive"></a>

## 配置持久化

**覆盖后的复查。** 区分持久配置来源、生成或托管的运行副本和核心状态。应用后先回读运行配置。获准刷新节点订阅或重新生成配置后，再回读并抽查实际命中和出站，确认旧业务规则、旧规则集引用与旧兜底没有恢复，并核对 AgentRoute 规则集能否独立刷新。未执行刷新时注明持久化未验证。

**配置入口。** 使用配置管理者支持的持久入口实施覆盖，保留节点订阅和恢复前像。配置权限不足或无法满足用户目标时，按受限接入处理。需要换配置来源或改自建订阅生成端时，说明影响并取得用户选择。

**做法提示。** 可先确认配置是本地编辑、订阅生成、托管，还是由客户端每次连接时按自身骨架重新生成；再找该版本支持的持久覆写、扩展或模块机制，核对它是合并还是整段替换，以及实际规则顺序。具体使用 GUI、API 还是命令行由执行 Agent 按现场能力选择，不绑定某个按钮。版本案例见[可选证据](CLIENT-EVIDENCE.md#运行时加载与持久化的区别)。

<a id="limited-integration"></a>

## 能力不足与受限接入

托管配置或模块可能限制可用策略和排序。先按官方资料与现场检查确认限制；若无法保持规则语义，说明缺失能力和替代方案，取得用户选择。没有可靠方案或用户未接受限制时停止相关修改。

只支持追加规则，或发现旧业务规则、旧规则集或旧兜底仍生效时，标明覆盖未完成。用户接受受限接入时，说明实际接入的资源、主配置承接的行为和缺失项。完整设备接入还需验证适用的 TUN、DNS 和 WebRTC 目标。[Surge 模块手册](https://manual.nssurge.com/profile/module.html)提供了策略和排序受限的一个例子。

## 更新与验证责任

规则每日 UTC+8 06:30 计划构建，实际发布时间以清单为准。验证失败时保留旧发布。建议启用客户端自动刷新。严格同代下载、校验与本地回退见 [SYNC](SYNC.md)。

项目测试覆盖规则与记录的示例。目标设备的加载、分流、刷新、DNS 和 WebRTC 按用户需要分别检查。
