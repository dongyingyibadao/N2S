# 待验证迁移工单

这里接收成功、失败、超时、OOM 和环境阻塞记录；没有模块 A/B 也能先开工单。它们不是
`rules/` 中的候选规则，统一保持 `generalization: pending_validation`。

```text
CASE_ID/
  issue.json          来源、目标、观察、官方引用、待验证迁移假设
  tasks/TASK_ID.json  固定问题、硬件与版本、输入协议、命令和验收条件
  runs/RUN_ID/
    run.json          一次运行的源码/环境/任务指纹和结果
    evidence.txt      可选，经人工脱敏的日志摘录或测量报告
    review.json       可选，仅评定本次任务，不审批规则
```

已有 `mint-rule-followups` 是历史证据的剩余问题清单，不是假装已经开始了新 MINT 实验。
每次新实验创建独立 ID，并用 `models` 标明模型，避免两台机器创建同名工单。
所有模型统一使用 [迁移与复测指南](EXPERIMENT_GUIDE.md)，不需要各自的首次实验说明。

## 记录要求

工单写清楚官方源码 URL 和完整 revision、用户认可的“跑通”标准、实际环境与资源、修改前后
行为、完整错误类型和关键堆栈、迁移假设与排除项、回退方式、下一端应测什么。缺失内容明确
写 `pending` 或 `not_available`。成功仅能把工单 `state` 改为 `resolved`，不能把通用性改成已验证。

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
工具检查不是提交钩子；检查后修改了文件必须重新检查。日志脱敏、许可证和分支内容仍须人工确认。

其它配置上在干净 main 工作树执行 `git pull --ff-only origin main`，再按模型和硬件筛选任务。
需要现场探测时才运行 `list --backend auto`，读取更新不会自动执行模型实验。
确认任务源码、资产和软件版本后重新计划、重新取得运行同意，最后追加新的 run 并重复发布检查。
