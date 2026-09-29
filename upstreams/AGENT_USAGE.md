# Agent 使用外部知识的流程

N2S 当前保存一份完整的昇腾官方 recipe Git 镜像，以及两份精选社区源码快照。外部文件是
迁移参考，引用时必须保留来源、固定 commit 和适用范围。此流程适用于 MINT、OpenPI、PI0.5
及后续项目。

## 可用来源

| 来源 | N2S 中的内容 | 能证明什么 |
|---|---|---|
| `cann-recipes-embodied-ai` | 完整本地 Git 镜像、已接纳版本索引、最新只读快照及人工知识目录 | 官方在相应 recipe 中记录了什么；是否由 N2S 复现，另看 `n2s_validation` |
| `lerobot`、`openpi` | 固定 commit 的少量源码、许可证、SHA256 和静态匹配报告 | 该源码版本中的代码形态，以及 N2S detector/codemod 对这些形态的静态检查结果 |

社区快照不是完整项目，也没有独立的模型权重、运行环境或端到端验证。已接纳官方版本和
`live` 最新版本可能不同；最新版本未经人工审阅时只能按 `unreviewed_latest_upstream` 使用。
官方 recipe 中的测试描述和数字按其原设备、版本、模型、输入与测量方法引用。

## 迁移前检索

在拟修改的目标项目中确定模型、框架、设备、软件版本、操作模式和具体错误或性能问题后：

```bash
tooling/n2s-knowledge status --json
tooling/n2s-knowledge search "具体算子或错误关键词" --scope manipulation --accepted-only --include-community --json
```

没有结果时，换用操作名、异常类型或框架名再查；必要时不带 `--accepted-only` 检索最新
官方快照，并明确结果是否为 `unreviewed_latest_upstream`。社区搜索只覆盖已保存的精选文件，
搜索不到不能推断社区仓库中没有相关实现。检索不执行快照中的代码。

人工整理项在搜索结果中还显示 `n2s_validation` 和与现有规则的关联；全文或社区源码命中
不会自动带有 N2S 验证结论。结果的 `uri` 指向精确版本，可直接打开：

```bash
tooling/n2s-knowledge show upstream://cann-recipes-embodied-ai@45d167135c81d97573bfbe0e564bb4a1d9642514/manipulation/pi05/infer_with_torch/README.md
tooling/n2s-knowledge show community://openpi@215abfb217dbac7d5f1273282331b9b1866c0479/src/openpi/models_pytorch/pi0_pytorch.py
```

`show` 只读取本地文件。对于社区精选快照，它会先验证文件清单的 SHA256、commit 和来源；
未收录的路径会给出固定 commit 的远端链接。查看代码时不要执行官方或社区快照里的脚本。

## 证据判断

读取相关文件后，再核对 [官方支持矩阵](knowledge/SUPPORT_MATRIX.md)、
[社区静态验证报告](../cases/validation-projects/reports/static_validation.json)、
[N2S 证据对照](../evaluations/evidence-reuse.json)、相关 case 和规则审查记录。
分别记录下面四点，供迁移决策和 case 引用：

1. **来源**：`source@40位commit/路径`，以及 `accepted_upstream_documented`、
   `unreviewed_latest_upstream` 或 `community_source_snapshot_static_only`。
2. **外部结论**：原文声称解决的问题、实际涉及的模型、设备、软件版本和输入范围。
3. **N2S 已验证内容**：有无本地 module/integration/model 证据；静态代码匹配只算静态检查，
   不能写成运行成功。可复用已有同范围证据，避免机械重跑。
4. **本次差距或反证**：目标项目与来源的不同、尚需运行的实际调用路径、已有失败或相反结果。

示例：官方 PI0.5 的 310P patch 记录了 FP64 到 FP32 的处理；N2S 在已有 910B2C 测试输入上
观察到 FP64 可用。两者的设备和版本不同，不能据此对所有 NPU 应用回退。另一个例子是
OpenPI 源码快照中的 compile 配置：静态检查明确拒绝缺乏构造期设备证明的自动改写。

官方或社区材料可以让 Agent 采用有出处的排查方向；目标项目的适配是否成功，应由该项目
的实际环境和测试证明。若工作产生新观察，写入 `cases/work-items/CASE_ID/` 的 `knowledge_refs`
和任务证据引用，并区分“引用来源”“已测试结果”和“待验证假设”。不把上游正文、patch、
权重或社区源码作为 N2S 自有材料重新发布，也不据此修改规则审批或 `auto_apply`。
