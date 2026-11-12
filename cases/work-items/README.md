# 待验证迁移工单

这里接收成功、失败、超时、OOM 和环境阻塞记录；没有模块 A/B 也能先开工单。它们不是
`rules/` 中的候选规则，统一保持 `generalization: pending_validation`。

```text
CASE_ID/
  issue.json          来源、目标、观察、官方引用、待验证迁移假设
  tasks/TASK_ID.json  固定问题、硬件与版本、输入协议、命令和验收条件
  events/EVENT_ID.json 追加的查询对照、错误、改动、解决与验算节点
  measurements/REPORT.json  可选，脱敏的结构化测量报告；也可放在 case 根目录
  runs/RUN_ID/
    run.json          一次运行的源码/环境/任务指纹和结果
    evidence.txt      可选，经人工脱敏的日志摘录或测量报告
    review.json       可选，仅评定本次任务，不审批规则
```

已有 `mint-rule-followups` 是历史证据的剩余问题清单，不是假装已经开始了新 MINT 实验。
每次新实验创建独立 ID，并用 `models` 标明模型，避免两台机器创建同名工单。
所有模型统一使用 [迁移与复测指南](EXPERIMENT_GUIDE.md)，不需要各自的首次实验说明。
迁移 Agent 在第一次修改前开工单，并按 [即时反馈指南](FEEDBACK_GUIDE.md) 连续追加，
不要等整体成功才记录。三阶段原文阅读要求见 [AGENT_USAGE.md](../../upstreams/AGENT_USAGE.md)。

## 实验记录入口

以下为 2026-11-12 首次整理发布的历史观察，均保持 `open / pending_validation`。
以各目录的发布审阅、原始实验时间和测量范围为准；局部通过不代表长训完成或通用规则获批。

| 工单 | 可复用信息与仍需验证的范围 |
|---|---|
| [OpenPI PI0.5 LIBERO](openpi-pi05-libero-ascend-20261020/PUBLICATION_REVIEW.md) | 数据、训练/恢复、闭环及 Beta/外层 checkpoint 对照；官方权重身份与约定精度仍待核验 |
| [PI0.5 无重计算与多机通信](openpi-pi05-ddp-no-checkpoint-20261024/PUBLICATION_REVIEW.md) | 固定 global256 的 microbatch 对照、HCCL 失败及重试；精度与长训未完成 |
| [PI0.5 独立 worker 组合优化](jade-lotus-ascend-fragments-optimization-20261028/PUBLICATION_REVIEW.md) | 精确梯度导出/存储、reducer 预读组件证据；完整正确性和 500 更新验收未完成 |
| [GR00T N1.6](gr00t-n16-libero-ascend-20261111/PUBLICATION_REVIEW.md) | 无重计算、模型/状态对照、恢复与短程记录；后续慢速问题及 20,000 更新待验证 |
| [Wan1.3B 全训练](partially-diffusion-wan13-full-20261016/PUBLICATION_REVIEW.md) | bounded reducer、精确 mask cache、容量与 checkpoint/恢复；不证明跨 CUDA 等价或 3,000 步完成 |

PI0.5 的已有官方方法、本地实测和可能值得扩大来源对照的组合见各目录的
`OPTIMIZATION_REVIEW_20261112.md`。未穷尽社区时不声称首创，不将组件收益当作整模型收益。

## 记录要求

工单写清楚官方源码 URL 和完整 revision、用户认可的“跑通”标准、实际环境与资源、修改前后
行为、完整错误类型和关键堆栈、迁移假设与排除项、回退方式、下一端应测什么。缺失内容明确
写 `pending` 或 `not_available`。新工单完成约定范围的阅读与验算后，经 workflow-check 和审阅
才能标为 `resolved`；完整模型迁移默认仍要求三阶段阅读及功能/精度/同设备优化验算。
模块复测、优化调查和工具修复需显式声明较窄的[完成范围](../../evaluations/README.md#completion-scope)，
不得用缩小范围代替原定目标。未完成仍可发布 open 工单，通用性始终待验证。

每项任务对应一个问题。baseline 与 modified 分成独立任务，共享输入和 `comparison_key`；不因
baseline 失败就阻止修复任务运行，也不把跨端成功等同于同设备 A/B。任务内容变化后，旧结果仅
保留历史价值，不自动满足新协议。新增任务之前先看 `evaluations/evidence-reuse.json`。

禁止放入 token、密码、内部地址、用户数据、完整环境变量、checkpoint、数据集和未经许可的
官方正文/patch/代码。源码改动默认只记录路径、作用、哈希和重建说明。确需传播实现时，使用
用户明确授权、遵守对应项目许可证的外部源码提交；不要把官方只读缓存重新发布为 N2S 自有内容。

## 发布

用户已选择 `origin/main` 作为 N2S 基础设施和已审阅实验记录的发布目标。每次仍需检查发布内容，
不把目标分支选择理解成可以推送未脱敏日志或无关改动。实验应从已发布的干净 main 开始。
维护工具本身的提交与实验 case-only 提交分开；下列命令仅用于实验记录，ID 需替换。

```bash
git status --short --branch
git remote -v
git switch main
git pull --ff-only origin main
tooling/n2s-experiments workflow-check --case CASE_ID
tooling/n2s-experiments validate --case CASE_ID
git add -- cases/work-items/CASE_ID/
tooling/n2s-experiments publish-check --case CASE_ID
git diff --cached --stat
git diff --cached
git commit -m "Record CASE_ID migration observation"
# 检查相对目标远端基线的所有待推送提交和文件，不仅是最后一次提交。
git log --oneline origin/main..HEAD
git diff --name-only origin/main...HEAD
git push origin HEAD:main
```

若 `publish-check` 因暂存区有无关文件而拒绝，不替用户撤销或清空暂存区；在独立干净工作树
整理本次提交，或请用户处理。禁止 `git add .`、force push、覆盖已有运行记录和自动解决冲突。
工具检查不是提交钩子；检查后修改了文件必须重新检查。事件和 run 已提交后不可覆盖。
根目录及 `measurements/` 下的结构化 JSON 报告也按发布后不可改写管理，每文件不超过 1 MiB；
后续修正使用新文件、新反馈并保留原记录。JSON 只能存报告，不得包裹上游代码或未脱敏日志。
日志脱敏、许可证和分支内容仍须人工确认。

其它配置上在干净 main 工作树执行 `git pull --ff-only origin main`，再按模型和硬件筛选任务。
需要现场探测时才运行 `list --backend auto`，读取更新不会自动执行模型实验。
确认任务源码、资产和软件版本后重新计划、重新取得运行同意，最后追加新的 run 并重复发布检查。
