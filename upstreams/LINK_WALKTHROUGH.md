# 从参考资料目录深入到实现

本页说明 `ascend-reference-20261005` 的实际接入方式，以及迁移 Agent 应留下什么阅读证据。
示例用于读取资料，不授权安装、下载权重、运行模型或采用外部代码。

## 资料如何接入

原资料目录是 `ascend_reference_20261005/昇腾卡参考资料/`。N2S 使用三种不同的数据：

| 内容 | N2S 中的位置与用途 | 边界 |
|---|---|---|
| 来源登记 | `reference-bundles.json`：来源、日期、manifest SHA256、许可限制、已知缺口 | 资料包哈希不是 Git commit |
| N2S 编写的目录 | `catalogs/ascend-reference-20261005.json`：27 条任务、排障、优化入口 | 摘要和历史报告不代表当前工程已验证 |
| 原始资料 | `_cache/reference-bundles/SOURCE/MANIFEST_SHA256/`：只读原文、附件、截图、群记录 | ignored，不随 N2S Git 分发，不执行其中代码 |

导入时先核对 `核验/文件清单.json` 的 SHA256，再验证清单中 61 个文件的大小和 SHA256，
连同 manifest 共保留 62 个文件。目录中的相对链接和原字节保留；`status`、`search` 和
`show` 会核对缓存完整性。资料包包含 15 张图及 3 个原附件，截图需要图像阅读工具确认。

`guide` 按任务和阶段路由这 27 个入口；`search` 同时查目录摘要和已导入的文本原文。
结果中的 `references[]` 指向资料包原文，`links[]` 指向外部文档、仓库、具体文件或 issue。
相关官方链接还提供 `snapshot_uri`，可直接读取 N2S 独立保存的官方 Git 快照。

原资料明确采用 Git `links_only` 策略。因此，导入资料包不等于克隆其中所有仓库。
官方 recipe 镜像、精选社区源码和参考资料包是独立来源，各自保留版本与信任状态。
另一台机器拉取 N2S 后能使用目录和链接；离线原文需另外导入授权资料包：

```bash
tooling/n2s-knowledge import-bundle --source ascend-reference-20261005 --path /path/to/昇腾卡参考资料
tooling/n2s-knowledge status --json
```

## 实例：从 MOVA 入口读到设备适配实现

以下命令均在 N2S 根目录运行。工具启动异常时先运行标准库依赖诊断；用 `N2S_PYTHON`
显式选择已配置的工具解释器，不自动修改目标项目环境。

```bash
tooling/n2s-knowledge doctor --json
tooling/n2s-knowledge guide --task performance --stage optimization --json
tooling/n2s-knowledge search MOVA --accepted-only --include-community --json
```

搜索返回 R12「MOVA 固定 NPU 适配提交」，其中包括推荐环境、限制、资料包原文和固定提交链接。
先打开资料包原文，核对 R12 的来源与历史限制：

```bash
tooling/n2s-knowledge show 'reference://ascend-reference-20261005@b83a696461745e01f8e44e8a2e672db9fdadca7d66b6e19d7eaaaac53b5081a8/昇腾卡使用优化与Debug参考手册.md'
```

再读取真正的 MOVA 文档：

```bash
tooling/n2s-knowledge follow https://raw.githubusercontent.com/OpenMOSS/MOVA/61e39c2e6e9b9047fb086112ab9bfae8d5b74182/ASCEND_SUPPORTS.md
```

这个固定版本的 `Architecture Overview / NPU Adapter Layer` 实际包含相对链接
`mova/utils/adapter.py`。`follow` 将正文链接解析为 `discovered_links`；沿该链接继续读实现：

```bash
tooling/n2s-knowledge follow https://raw.githubusercontent.com/OpenMOSS/MOVA/61e39c2e6e9b9047fb086112ab9bfae8d5b74182/mova/utils/adapter.py --from-url https://raw.githubusercontent.com/OpenMOSS/MOVA/61e39c2e6e9b9047fb086112ab9bfae8d5b74182/ASCEND_SUPPORTS.md
```

`--from-url` 会重新读取父正文，确认目标确实出现在其中；继续下钻时按顺序重复该参数，
例如 `follow GRANDCHILD --from-url REGISTERED_ROOT --from-url CHILD`。
读取输出提供来源链、实际 URL、访问时间、内容哈希和正文状态。外部正文仍为
`retrieved_unreviewed`，不能继承资料包或官方快照的审核结论。

Agent 随后应在目标项目中找到对应调用，比较设备分支、通信后端、dtype、shape、mask、
归一化和训练/推理语义。例如 MOVA 普通 RMSNorm 不能直接证明带调制的归一化可以同样替换；
长上下文 attention 的实现也不能自动覆盖其他模型全遮挡行的行为。采用、暂缓和不适用都要说明依据。

本页示例的链接与相对路径于 2026-10-24 实际读取核对；未来访问失败时应记录失败，
改查固定快照或其它可访问来源，不能把示例当成未来网络可用性的保证。

此次只读走查的原响应 SHA256 如下；这里只保存溯源元数据，不复制外部正文或执行适配代码：

| 同一固定 commit 的文件 | SHA256 |
|---|---|
| `ASCEND_SUPPORTS.md` | `bf5181937d6064716c9dda3dfa16e056a2a6c06d0346449be11a5c08e0298098` |
| `mova/utils/adapter.py` | `f309608ea6abc464af7d70f6d3da85dce7958425fda2ef50d350ee929feffcfd` |

## 多 subagent 如何分担优化资料阅读

具备并行能力时，主 Agent 可将一次优化查询产生的相关入口去重后按来源分组，例如：

| 阅读任务 | 深读范围 | 返回重点 |
|---|---|---|
| 官方配方与版本 | 固定官方 recipe、配置及版本矩阵 | 支持设备、软件组合、优化开关及测量条件 |
| 社区实现 | MOVA 等固定提交文档及其实际实现链接 | 调用路径、dtype/shape/mask 语义、与目标代码的差异 |
| 问题与限制 | 相关 issue、精度问题、反例和已有 case | 失败条件、修复版本、反证和待验算范围 |

按实际可用并发分批执行，每条链接有明确负责人；各 subagent 共用目标画像，
返回可复核的 URL/URI、revision/hash、访问时间、父子链、阅读层级和适用性判断。
主 Agent 维护覆盖清单，接收新发现的相关链接，复读关键/冲突来源并统一追加 case；
subagent 只读，不改代码、写 case、启动实验或继续派生 agent。
受阻、待查及不适用项也要列出，不能以分派完成或报告一致代替实际阅读与验算。
无 subagent 能力时采用同样清单串行读取。完整要求见 [Agent 使用流程](AGENT_USAGE.md#支持-subagent-时并行深读)。

## 如何约束 Agent 的深读行为

`AGENTS.md` 要求迁移前、遇错时、优化时都查阅实际正文与实现。每次重要决策应在 case 留下：

1. 从哪个目录/原文入口出发，以及实际打开的下级 URL 或固定文件 URI。
2. 文件的 source、revision 或内容 SHA256、真实访问时间和信任状态。
3. `read_depth`：目录、正文、实现、issue 或版本矩阵；有上下级关系时填写 `parent_url` 或 `parent_uri`。
4. 原文具体支持什么、与目标工程有哪些差异、采用理由和仍需验算的部分。

用 `feedback-draft` 带入来源字段，再实际查阅和补充判断；草稿默认未读，不能作为阶段完成证据。
`feedback-preflight` 校验输入，`workflow-check` 报告草稿、来源和验收缺口；错误查询关联相应事件，
即使问题发生在优化阶段，也保留真实阶段。具体命令见 [反馈指南](../cases/work-items/FEEDBACK_GUIDE.md)。

只有目录、链接列表、HTTP 200、登录页或动态页面外壳时，不能声称已读实现或已确认方案。
缺正文、权限或精度依据时，发布 open case 并列出下一步；工具可检查记录的一致性和深读缺口，
不能仅凭访问成功证明 Agent 已理解代码，也不能替代对实际修改与测量的审查。
