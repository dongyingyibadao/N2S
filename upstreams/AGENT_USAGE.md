# Agent 使用外部知识的三阶段流程

N2S 是给迁移 Agent 使用的知识和证据入口。按任务查资料、读原文与实际实现，再决定修改；
迁移中的观察持续回流到 case。此流程适用于所有模型，不把项目专属适配自动变成通用规则。

## 新项目：可直接交给 Agent 的指令

将下面的指令发给迁移 Agent，替换目标项目、N2S 的实际路径和任务类型。目标项目使用 N2S
之外的独立 Git checkout。Agent 应能读取 N2S、访问相关链接，并在本项目的 case 中追加记录。
跨目录工作时，不能保证 Agent 会自动加载 N2S 的 `AGENTS.md`，所以在指令中明确要求读取。
下面是发给 Agent 的任务说明，不是终端命令。

```text
目标项目：/path/to/new-project
N2S：/path/to/N2S
任务：将目标项目迁移到当前昇腾环境，完成【推理或训练】及性能优化。

请先读取并遵循 N2S/AGENTS.md，以及其中引用的知识使用和 case 反馈指南。
首次访问时，在 N2S 根目录运行 tooling/n2s-knowledge refresh-if-due。

第一次修改前：
记录项目 baseline revision，按任务检索 N2S 的官方和社区知识，
深入阅读相关链接的正文与实现，比较设备、版本和实际执行路径，并建立本项目的 case。

迁移过程中：
每次出现错误、精度偏差或失败尝试，立即追加 case 记录；
重新检索对应问题，阅读相关社区解法，记录采用理由、修改和回退方法。

功能跑通后：
使用官方权重和固定输入检查实际 NPU 执行及精度；
再查询昇腾算子与性能优化，验证正确性和同设备性能收益。
先与我确定精度容差、性能目标、实验命令和用卡范围。

N2S 内只追加本项目的 cases/work-items/CASE_ID/；
所有通用性结论保持 pending_validation，保留现有规则和审批状态。
暂停或结束前运行 tooling/n2s-experiments workflow-check --case CASE_ID，报告证据和未完成项；
脱敏审阅后将 case 发布到 main，失败和阻塞也及时记录。
```

其他机器先拉取最新版 N2S，即可使用摘要和链接；完整离线资料包按
[导入说明](REFERENCE_BUNDLES.md#本地原文与换机器) 单独导入。项目的具体检索、原文阅读和工单
维护由 Agent 完成，是否跑通仍由实际验算确定。

## 来源与判断边界

| 来源 | 可读内容 | 信任与边界 |
|---|---|---|
| 官方 cann-recipes-embodied-ai | 完整镜像、固定接纳版本、最新只读快照 | accepted_upstream_documented / unreviewed_latest_upstream；recipe 声明与 N2S 复现分开 |
| LeRobot、OpenPI 精选源码 | 固定 commit 的少量文件、许可证及静态报告 | community_source_snapshot_static_only；不是完整仓库或端到端验证 |
| ascend-reference-20261005 | N2S 摘要、任务目录、外部链接；导入后可读完整本地资料包 | community_reference_bundle；群报告、截图、官方摘录各保留原验证范围 |
| 本次在线读取 | follow URL 或自己的只读网页/Git 工具 | retrieved_unreviewed；HTTP 成功不证明正文完整或方案有效 |

参考包的 64 位 revision 是 manifest SHA256，Git 文件使用 40 位 commit。
[官方支持矩阵](knowledge/SUPPORT_MATRIX.md)、[资料包路由与导入](REFERENCE_BUNDLES.md) 分别
描述两种来源。未导入时仍可搜索摘要与在线链接，不能假称读过本机不存在的原文。
所有外部脚本、Python、hook 和 shell 配置只作为数据阅读。

## 第一次：迁移前按任务查阅

确定目标源码及完整 baseline commit、模型/框架、实际设备、驱动/CANN/torch/torch_npu、
运行模式、权重与输入，以及用户认可的功能/精度/性能标准。先建立独立 case，无需等待跑通。
根据任务选择一项或多项：environment、training、inference、distributed、memory、numerics、
performance、simulation、data。

```bash
tooling/n2s-knowledge status --json
tooling/n2s-knowledge guide --task training --stage preparation --json
tooling/n2s-knowledge search "具体模型或操作" --accepted-only --include-community --json
```

具身策略可加 --scope manipulation；其它场景先不缩小范围。--task、--stage 路由资料包条目，
官方全文继续按关键词和 scope 检索。多个词按 AND 匹配；无结果时换模型、算子、框架、异常类型
或取消 scope。必要时查最新官方快照，保留未审阅标签，不能由无匹配推断上游没有方案。

对相关结果逐项完成：读全文 → 打开原始链接/固定源码 → 比较范围 → 留下采用/拒绝原因。
优先打开 links[].snapshot_uri 对应的官方固定版本；references[] 给出每个资料原文/附件的
URI、SHA256 与本地路径。截图用图像阅读工具确认，不能仅看文件名。

```bash
tooling/n2s-knowledge show upstream://cann-recipes-embodied-ai@45d167135c81d97573bfbe0e564bb4a1d9642514/manipulation/pi0/train/README.md
tooling/n2s-knowledge follow https://raw.githubusercontent.com/OpenMOSS/MOVA/61e39c2e6e9b9047fb086112ab9bfae8d5b74182/ASCEND_SUPPORTS.md
```

follow 只读已登记 HTTPS 链接，返回时间、原响应哈希、最终 URL、正文和未审阅标签。导航、
登录页或 JS 外壳记为 partial/unavailable，改读原始文件、固定 commit 或可访问镜像。
子链接可用自己的只读网络/Git 工具进一步打开，记录精确 URL/commit，不只引用仓库首页。
可变网页不能冒充旁边列出的接纳 commit；非 Git 文档引用访问日期和哈希/版本。

检查 [N2S 证据对照](../evaluations/evidence-reuse.json)、相关 case、规则审查与静态报告。
复用同范围解释/证据，目标运行路径、精度、性能仍未覆盖的差距再进入待测任务。
310P OM 的 FP32 回退不能推导为 910B2C 不支持 FP64；同名模型的 LeRobot recipe 也不能
证明 OpenPI 原仓成功。用 feedback 追加 preparation/lookup，记录外部声明、N2S 已验证部分、
支持/反证/范围不同、采用理由和剩余差距。

## 第二次：遇到问题重新深入查证

出现依赖/运行/通信/OOM/算子错误、NaN/Inf、精度转换或偏差，先立即把首个因果异常、目标
路径、版本、输入、预期/实测和假设写成 failure/numerical_issue。原日志留本地，case 保存
脱敏摘要；无参考值或容差也作为待验证问题记录。不要等结束后凭记忆补写。

```bash
tooling/n2s-knowledge guide --task numerics --stage troubleshooting --json
tooling/n2s-knowledge search "异常类型或算子" --stage troubleshooting --accepted-only --include-community --json
```

深入新命中的 recipe、issue/PR、实际实现及 case。按因果链换关键词，比较设备、版本、模式、
dtype/shape、权重/预处理和执行路径。每个相关链接记录原文内容、支持/反证/范围不同、措施及
待证明部分；访问失败和无匹配也保存。troubleshooting/lookup 的 resolves 关联错误事件，
仅查阅不会把错误标为已解决。记录失败尝试、修改位置/理由和回退。

验算用新 run/测量报告保存；实际验证修复后才追加 resolution。GLD Wan stage2 的 mock
冒烟不能解决 DA3 视频依赖错误，未触发的 DeepSpeed 预案不能写成已验证修复。
每个新问题都重复本阶段，优化引起的错误也一样。

## 第三次：功能迁移后查昇腾优化

官方权重在 NPU 运行且精度已有对照后，仍须再次检索。训练重点查训练效率，推理查实际
部署负载。结合 profiling/计时确定瓶颈，阅读优化原文、内核/配置实现与版本限制。

```bash
tooling/n2s-knowledge guide --task training --stage optimization --json
tooling/n2s-knowledge guide --task performance --stage optimization --json
tooling/n2s-knowledge search "RMSNorm" --task performance --stage optimization --accepted-only --include-community --json
```

调查融合 attention/QKV/RMSNorm/MLP、rotary、host 同步/缓存、数据加载、分配策略、checkpoint
粒度、DDP static_graph、图模式、通信与并行；推理还检查 DP/TP、并发、上下文、prefix cache、
CPU 绑定和 MTP。已内置、不适用、缺正文和已弃用的方案也记录，不能把所有开关一起启用。

追加 optimization/lookup。在已有执行授权内验算：固定同设备/卡数、版本、输入/权重、dtype、
batch 和 seed，记录同步/预热/重复测量、step/吞吐/显存，以及输出/loss/梯度有限性和精度。
性能收益不能来自未披露的降低精度、减少输入或换硬件；NVIDIA/NPU 时间差不算同设备修改收益。
退化则回退并记录，有新错误回到第二阶段。维护知识库或探测硬件不授权实验、安装或下载。

## 回流与完成判断

按 [FEEDBACK_GUIDE.md](../cases/work-items/FEEDBACK_GUIDE.md) 在每个关键节点追加反馈，
保持来源对照，不修改既有规则、审批或历史证据。结束/交接前运行 workflow-check --case CASE_ID。
本次成功需要官方权重 NPU 运行、事先认可的精度对照和正确性仍达标的同设备优化证据。
无参考、未测性能、无收益、无适用方案或资源不足时，写明已到哪层、待办与阻塞，保持 open；
不能用“命令成功”或“查过优化资料”替代完成。用户调整目标时明确记录新任务范围。

工具检查记录的结构和一致性，不能强迫忽略指引的 Agent 查阅，也不能自动判断任意模型精度。
结束报告列出三阶段查询、实际打开的原文、修改/验算、未解决问题、case 路径与待测任务。
成功、失败和阻塞都及时脱敏发布到已选择的 origin/main；发布前审查内容和全部 outgoing commits。
所有 case 保持 generalization: pending_validation，外部声明或模型成功不会审批通用规则。
