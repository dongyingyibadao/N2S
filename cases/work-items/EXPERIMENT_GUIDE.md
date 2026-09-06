# 通用模型迁移与复测记录

本指南适用于任意模型和项目。模型名称、官方源码、权重、输入协议与验收指标是工单数据，
不为每个模型另外维护一套 N2S 流程。实验由用户自行进行；维护 N2S 不会自动启动模型实验。
用户后续可以明确授权 Agent 辅助执行，但运行权限和规则审批权限始终分开。

## 统一闭环

查阅已有证据 -> 创建待验证工单 -> 用户进行实验 -> 归档成功或失败 -> 发布到 main ->
另一环境读取工单并复测 -> 追加新结果。任何一步都不改动现有规则和审批状态。

`pending_validation` 表示可复用迁移假设尚待验证，不等于 `rules/` 中的 `candidate`。
已有案例只覆盖其记录的模型、版本、设备和输入；新模型不会因为旧模型测试通过而自动获准。

## 创建工单

在 N2S 之外使用独立目标源码工作树。记录官方 URL、完整 baseline commit、模型名称和目标，
不把 N2S 缓存中的历史快照当成用户本次实验源码。以下均为占位参数，不会下载或运行模型：

```bash
tooling/n2s-experiments new --id model-migration-YYYYMMDD-01 \
  --model MODEL_NAME --project /path/to/model-project --source-url OFFICIAL_REPOSITORY_URL \
  --title 'Model migration observation' --goal 'Official-weight inference and scoped accuracy comparison' \
  --backend npu
```

ID 使用小写字母、数字和连字符，替换示例日期后使用。一个工单可重复传入 `--model` 记录多个
相关模型；但每个实际实验任务应固定一个明确的源码、输入和环境范围，不能混合推导通用结论。

在 `issue.json` 记录错误阶段、修改位置和理由、作用、回退方法、官方引用和待验证假设。
工单默认 `open`，通用性固定 `pending_validation`。初始任务是 `draft`，没有可执行命令。
没有模块 A/B、模型尚未加载或环境依赖缺失，都可以先记录，不要求“成功后才允许提工单”。

## 可运行性与精度分别记录

用户当前目标是：官方训练权重能够正常运行，且推理精度没有明显退化。对任意模型都需要分别记录：

- 可运行性：实际加载的官方权重来源、revision/哈希，固定输入、seed、真实执行设备，以及输出
  结构、形状和有限性。import 成功、随机权重 smoke 或退出码 0 不能代替官方权重推理结果。
- 精度：参考来源、相同权重和输入下的误差或任务指标、原始结果及事先确定的可接受范围。
  张量误差和任务成功率不是同一个指标，不设置跨模型统一阈值。

当前环境沿用用户现有配置，不自动重建环境、安装依赖、下载资产或占用加速卡。环境信息可以
由用户记录，或在得到适当授权后用 `probe` 只读采集；探测成功不等于已获准运行。

若尚无参考输出或尚未确定容差，应写“可运行性已检查，精度待验证”，不能直接认定整体通过。
缺少另一端的参考可以进入待测队列，不妨碍提交本端观察。具体指标在该模型的任务协议中确定。

## 归档用户的实验

原始日志保留本地，脱敏后的 UTF-8 报告至少包含实际运行时间、命令、环境、输入/权重、错误
类型与关键堆栈或测量结果、修改说明、回退与下一步。不要发布完整环境变量、私有数据和凭据。

```bash
tooling/n2s-experiments record --task CASE_ID/TASK_ID --project /path/to/model-project \
  --outcome reported_failure --summary 'Observed failure stage and remaining question' \
  --evidence /path/to/sanitized-report.txt --confirm-sanitized
```

`reported_pass` 表示用户报告成功，`reported_failure` 表示失败，`blocked` 表示条件不足。
`record` 不运行模型；它采集录入时的环境和源码指纹，报告中必须说明与实际运行时的差异。
结果始终待审阅；结果审阅只判断该任务，不批准通用规则。历史 run 不可覆盖，后续追加新 run。

暂不要求为外部模型代码建立发布分支。N2S 中保留源码 revision、改动路径、作用、哈希和描述
即可。若以后无法重建相同修改，明确写出这一限制，不把独立重实现当作完全相同代码的复现。

## 跨环境待测清单

```bash
tooling/n2s-experiments list --backend npu
tooling/n2s-experiments list --backend cuda
tooling/n2s-experiments list --backend npu --model MODEL_NAME
```

这里维护一份任务库，模型和硬件只是筛选条件。每项任务写清楚待证明的结论、已有可复用证据、
源码与软件范围、固定输入、baseline/modified/control、验收条件和依赖任务。协议变化时建立
新任务或更新协议，旧结果不会自动满足新协议。不同模型的相同机制通过知识引用和相关规则 ID
关联，不共享未经验证的通过状态。

用户自行运行后使用 `record` 回填；若以后授权 Agent 执行，则先审阅真实命令、资源预算、
输入协议和副作用，再 `plan`，取得明确同意后 `run --approve`。详见
[工具工作流](../../evaluations/README.md)。N2S 不在读取仓库时自动跑测试任务。

## 发布和接续

按用户选择，N2S 基础设施和已审阅的工单发布到 `origin/main`。实验提交仅含相应 case 目录，
先脱敏、校验、检查暂存区和全部待推送提交，再正常 push；不改现有规则，不 force-push。
具体步骤见 [工单发布](README.md)。

另一台机器拉取 main 后，可以按模型和硬件查找待办。实验继续由用户控制，需要重新确认源码、
环境、输入及执行授权，不能复用旧机器的运行确认码。成功、失败和阻塞都以新 run 追加回流。
