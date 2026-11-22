# Agent 同步工具契约

用户端需要 Python 3.11+，仅使用标准库。工具不修改代理客户端、不安装定时任务，也不读取节点或浏览器配置。

```sh
python scripts/sync_rules.py sync --output /your/rules-cache --format all
python scripts/sync_rules.py status --output /your/rules-cache
python scripts/sync_rules.py verify --output /your/rules-cache
python scripts/sync_rules.py rollback --output /your/rules-cache
```

Windows 使用自己的目录路径。`--format` 默认选 `all`，下载三套传统文本。也可以单选 `mihomo`、`surge` 或 `sing-box`。Surge 和 Shadowrocket 共用 `surge`。输出目录必须显式传入。退出码 0 表示成功，1 表示同步或校验失败，命令参数错误返回 2。成功及业务错误输出 JSON，参数用法输出到 stderr。

具有 `format_variants` 的发布代还可选 `mrs`、`srs`、`domain-set`。MRS 缓存含 classical 防护 YAML，SRS 含防护与 DNS 辅助，Surge 纯域名缓存附带参考配置所需的中国 IP、防护、扩展匹配与 DNS 映射 LIST。所选格式缺失或摘要不符时，此次同步失败，原指针保留。较早的同步脚本可以继续读取新版发布中的文本，但无法识别新格式的缓存目录名。试用时使用独立的 `--output` 目录，可随时回到原有文本缓存。[格式选择](FORMATS.md)

sync 解析 release 完整 SHA 后，按该提交下载 manifest、index 和选定格式的五类规则，以及清单中已发布的 webrtc-guard 资源（sing-box 另含 DNS 判断用的 non-cn-ip.json），验证相对路径、每文件 16 MiB 上限、SHA-256 和同代时间。失败保留当前指针。48 小时只约束本项目发布时间，不约束上游提交年龄。首次同步无可用缓存时明确失败，不生成假成功结果。

默认通过 GitHub 匿名 REST API 查询 release SHA，共享出口耗尽额度时会失败。有缓存则保留，首次同步则停止。执行 Agent 可通过公开 Git 引用或其他可靠方式核实本仓库的完整 release SHA，再显式传入；工具无需 Git 或访问令牌：

```sh
python scripts/sync_rules.py sync --output /your/rules-cache --format mihomo --release-sha <完整40位小写十六进制SHA>
```

`--release-sha` 仅用于 sync，跳过的是 API 查版本这一步，同代时间、时效、路径、大小、哈希和回退 held 保护仍照常校验。它不证明该 SHA 仍是当前 release 分支头；调用方应记录选择依据。该参数不能用于强制接收过期发布或覆盖用户回退决定。

`missing_optional_resources` 列出旧工具缓存遗漏的已发布辅助或防护资源。旧缓存仍可校验，不能据此判定防护已安装；同代 `sync` 返回 `unchanged` 时也须检查此字段。需要立即补齐时，保留旧缓存，换一个新输出目录完整同步并核对后再应用；下一发布代也会完整下载。新工具写入的缓存若缺少这些资源会校验失败。回退到尚未包含防护资源的旧代时，Agent 须同步处理客户端引用并报告防护状态，不能只回退文件。

成功后 current.json 指向 generations 内独立版本目录，返回值包含 generation、directory、files、age_seconds、stale。current.json 不是任何客户端的配置格式。要把规则发给其他设备时，从它找到当前版本目录，复制到你自己的发布路径；版本目录名每代都会变。Agent 必须把实际验证、客户端加载和更新动作分别报告；本工具下载成功不表示客户端已更新。

同一缓存使用系统级排它文件锁，进程结束时自动释放。同步先在暂存目录校验下载内容，再发布版本目录并原子替换指针。`current` 和 `previous` 分别指向当前及上一份缓存，目录名包含完整发布 SHA 和下载格式。缓存文件和目录按当前 umask 创建，客户端以其他用户运行时需有读取权限。

`rollback` 在本地校验上一份缓存后交换指针。允许回退到过期缓存，结果中的 `stale` 会标明。回退决定适用于所有下载格式，默认同步和显式指定 `--release-sha` 均遵循以下规则。

- 请求当前已选的同一 SHA 和格式时返回 `unchanged`。
- 请求刚离开的发布 SHA，即使改选另一格式，也返回 `held`。其他 SHA 的清单发布时间早于或等于刚离开的发布时间，也返回 `held`。退出码为 0，`generation` 给出继续使用的缓存，`held_generation` 标识刚离开的原目录。
- 其他 SHA 的清单发布时间严格更晚、并通过全部同步校验后，才会切换并解除暂缓。再次执行 `rollback` 可显式切回刚离开的缓存并解除暂缓。旧指针和旧缓存可直接沿用。

指针写入失败时继续使用原来两代。进程若在目录发布后被强制终止，下次 `sync` 在锁内回收可识别的孤立缓存和暂存目录，即使本次请求返回 `unchanged`。工具通过自身写入的目录身份、文件清单和实际目录结构核对归属。旧工具留下的无指针孤立目录、标识写完整前进程被强制终止留下的目录，以及含额外文件、目录或链接的缓存，均保留给使用者处理。

`verify` 和 `status` 在本地检查当前文件完整性，可能创建缓存锁文件。发现损坏时，保留问题副本后可用新的输出目录重新同步。

本项目采用滚动发布，旧 GitHub SHA 不保证长期可下载。可靠回退依赖本地缓存。普通客户端优先用原生 URL 每 24 小时刷新；需要严格同代时，由 Agent 在目标用户授权下安排 sync 和客户端应用流程。本项目不承诺不同客户端同时切换。

机器接口：[索引 Schema](../schemas/index.schema.json)、[清单 Schema](../schemas/manifest.schema.json)。未知主版本拒绝使用，现有 v1 允许兼容性新增字段。同步工具实施运行时约束；开发 CI 另用 JSON Schema 校验生成器。

规则文本只作为数据解析，不执行其中的内容。来源说明：[sources.json](../sources.json)、[NOTICE.md](../NOTICE.md)。
