# 迁移中的即时反馈

迁移 Agent 在第一次修改前建立或选定 case，随后持续追加记录。先记错误，再查资料和尝试修复；
失败、精度未对齐和资源阻塞都值得提交，不必等整个模型跑通。此机制适用于任意模型，所有记录
仍为 `generalization: pending_validation`，不会改变既有规则或审批。

## 最短操作

在 ignored 的 `evaluations/_local/` 准备脱敏 JSON。可以复制
[lookup.json](../../evaluations/templates/lookup.json)、
[failure.json](../../evaluations/templates/failure.json) 或
[validation.json](../../evaluations/templates/validation.json)，逐项替换占位内容。
模板不代表已执行查询或实验；未替换的来源和证据路径不能提交。

已有检索结果时，优先生成合法的未读草稿，再补实际查阅与判断，避免手抄 URI、revision 和 trust：

```bash
mkdir -p evaluations/_local
tooling/n2s-knowledge search QUERY --accepted-only --include-community --json | \
  tooling/n2s-experiments feedback-draft --case CASE_ID --stage preparation \
  --search-results - > evaluations/_local/lookup-draft.json
# 阅读原文与实现，编辑草稿；不要只删除 draft 标记。
tooling/n2s-experiments feedback-preflight --case CASE_ID --file evaluations/_local/lookup-draft.json
```

草稿是 `draft: true`，来源初始为 `status: not_read`、`accessed_at: null`、
`read_depth: catalog`、`applicability: unknown`。可以保存到工单，但不计作已完成阶段的证据。
真正阅读后填写实际访问时间、读取层级、原文声明和适用性对照，再设置 `draft: false`。
`feedback-draft` 支持 `--query`、`--resolves`（均可重复）、`--issue-scope` 和 `--limit`；
`feedback-preflight` 只检查不写入；`feedback` 与 `feedback-preflight` 的 `--file -` 可读取标准输入。

```bash
mkdir -p evaluations/_local
cp evaluations/templates/failure.json evaluations/_local/feedback.json
# 编辑 JSON，填入真实观察并脱敏；然后录入，不探测硬件、不执行模型。
tooling/n2s-experiments feedback --case CASE_ID \
  --file evaluations/_local/feedback.json --confirm-sanitized
tooling/n2s-experiments workflow-check --case CASE_ID
```

工具生成 ID、UTC 时间、case ID、证据哈希与通用性状态，写入 `events/ID.json`。输入不要包含
`schema_version`、`id`、`case_id`、`recorded_at`、`generalization` 或 `evidence_sha256`。
完整字段约束见 [feedback.schema.json](../../evaluations/schemas/feedback.schema.json)。
工具不 commit/push；在关键节点、暂停或交接前按 [工单发布流程](README.md) 审阅并发布。

## 什么时候记什么

| 节点 | stage / kind | 内容 |
|---|---|---|
| 第一次修改前 | preparation / lookup | 任务、查询、实际读过的原文、范围对照、采用理由及剩余差距 |
| 出现阻塞或数值问题 | troubleshooting 或 optimization / failure、numerical_issue | 首个因果异常、环境、目标路径、固定输入、预期与实测；先记后修 |
| 为每个错误重新查证 | troubleshooting 或 optimization / lookup | 新查询、深入链接内容及社区错误对照；`resolves` 填相关错误 ID，保留实际发生阶段 |
| 改动或回退 | troubleshooting 或 optimization / change | 修改路径、机制、原因、源码 revision/树哈希、明确 rollback |
| 实际验算已解决错误 | troubleshooting 或 optimization / resolution | `resolves` 填错误 ID，引用新验算报告；查到资料本身不算解决 |
| 功能和精度验算 | troubleshooting / validation | 官方权重、实际 NPU 路径、有限输出与约定精度；优化可保持 pending |
| 功能迁移后第三次查询 | optimization / lookup | 实测瓶颈、算子/性能方案、版本限制、已内置或不适用的方案 |
| 优化后最终验算 | optimization / validation | 正确性仍达标，同设备 baseline/modified 测量及原始口径 |

`queries`、`source_checks`、`evidence_refs` 和 `resolves` 默认空数组。lookup 必须有查询和来源
对照；错误必须有 `environment` 和 `error`；change 必须有 rollback；resolution 和 validation
必须引用已存在的脱敏证据。`resolves` 只允许指向本 case 更早的 failure/numerical_issue。
只有 resolution 会消除待解决标记，lookup 的该字段仅关联错误。

可选 `issue_scope` 为 `target`、`tooling` 或 `recordkeeping`，分别表示目标项目、N2S 工具、
记录本身的问题。新录入未指定时按 case 类型选择（`tooling` 工单默认 `tooling`，其余默认
`target`）；历史事件缺失字段仍按 `target` 保守处理，不自动重分类。工具接入失败不等于已经
修改目标项目；准备顺序检查依据实际 `change`，未解决项仍在分类报告中保留。

## 来源对照要能复核

`source_checks[]` 每项写明实际 URI/URL、访问时间、读取状态、信任状态、原声明、适用性和对照。
Git URI 必须使用完整 40 位 commit，reference URI 使用已登记 manifest 的 64 位 SHA256。
可变 Git 网页另固定 commit；非 Git 网页记录 `content_sha256` 与读取时间。
用 `read_depth` 区分 `catalog`、`body`、`implementation`、`issue`、`version_matrix`；沿链接
继续读取时填写 `parent_url` 或 `parent_uri`。这些字段描述真实读取，不由搜索摘要自动推断。
实际链路示例见[从目录深入到实现](../../upstreams/LINK_WALKTHROUGH.md)。

```json
{
  "uri": "reference://ascend-reference-20261005@b83a696461745e01f8e44e8a2e672db9fdadca7d66b6e19d7eaaaac53b5081a8/附件/GLD Wan2.2训练管线昇腾适配结果-v1.md",
  "url": null,
  "accessed_at": "实际读取的 UTC 时间",
  "status": "read",
  "read_depth": "body",
  "trust": "community_reference_bundle",
  "claim": "该报告只覆盖随机 transformer、mock 数据的短步冒烟和 checkpoint 保存",
  "applicability": "different_scope",
  "comparison": "目标使用真实官方权重与数据，精度和长期训练仍需独立验算"
}
```

上例演示字段，不能在未读取原文时复制成已查证记录。`read` 表示读取了相关正文或实现；
导航、登录页、只有概述属于 partial/unavailable。无匹配记 status/applicability 为 no_match，
可以 URI/URL 为 null，并写查询范围和改用的关键词；不代表社区不存在解决办法。
支持、反证、相关但范围不同的材料都保留，避免只记录支持当前修改的内容。

## 验算与完成

`evidence_refs` 使用仓库相对路径，指向 `cases/` 下已脱敏的 `.json`、`.txt`、`.md` 文件，
例如本 case 的 `runs/RUN_ID/evidence.txt` 或独立 `measurement-01.md`。工具保存并重核 SHA256；
引用后不要改写报告，新测量使用新文件、新事件。不要引用仍会更新的 issue/task 文件作为测量。
记录权重来源/哈希、源码 revision 和修改哈希、输入、seed、真实设备/版本、完整测量及回退。
原始日志、权重、数据、上游实现和私有路径不默认随工单发布。

功能、精度、性能分开填。没有参考值/容差，accuracy 保持 pending；没有实测，性能数值为 null、
optimization 为 pending/blocked。同设备比较固定卡数、版本、输入/权重、dtype、batch，说明同步、
预热与重复次数；`direction` 声明指标越低还是越高越好。跨端原始耗时不能作为修改收益。

workflow-check 列出查询记录、草稿数量、完成范围、分类问题及证据缺口；不完整时退出码为 1。
仅有未读草稿不计作完成查询；完整迁移仅有目录层阅读也会报告正文缺口。
优化阶段关联错误的查询可以满足该错误的查证记录，但不会把错误标记为已解决。

默认完整模型迁移仍要求先记录功能/精度通过，再进行优化查询，并在最终报告中确认官方权重
NPU 执行、有限输出、约定精度和同设备实测收益。较窄任务按用户明确约定的
[完成范围](../../evaluations/README.md#completion-scope) 检查，报告区分单项验收、模型迁移、
优化调查/目标和规则审批。无收益可完成调查，不能满足 `required_gain`；没有测量不得写实测收益。
最终验算后又改目标代码或遇到新问题，应重新验算。未达目标、无法访问资料或资源不足时，
保留 open case 和待测任务；不妨碍及时发布失败观察。

新工单带 `maintenance_workflow: three_stage_v1`；validate 会拒绝证据不足却标为 resolved 的工单。
已有历史工单不自动补写或改状态。检查器验证记录的一致性，审阅者仍须核对来源正文、精度标准
和测量本身。它不能强迫其它 Agent 遵守指引，也不能自动审批通用规则。
