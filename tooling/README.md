# N2S 维护工具

该工具把规则应用设计成 fail-closed 事务。依赖固定为 LibCST 1.9.0、PyYAML 6.0.3 和
jsonschema 4.26.0；可以直接使用仓库入口，也可以安装 `N2S/tooling`。

仓库的三个入口都支持仅用标准库的 `doctor [--json]`，检查 Python、Git 和各自所需包，
不探测设备或导入目标项目。启动缺依赖时显示诊断，不自动安装。用 `N2S_PYTHON` 显式指定
已有工具解释器；实验的 `--python` 另行选择目标项目解释器，两者用途不同。

```bash
N2S/tooling/n2s-knowledge doctor --json
N2S_PYTHON=/path/to/tool-env/bin/python N2S/tooling/n2s-experiments doctor --json
```

```bash
# 仅在决定手动配置独立工具环境后运行安装命令。
python -m pip install -r N2S/tooling/requirements.txt
N2S/tooling/n2s-rules validate-registry
```

## 工作流

```bash
# 只读检查；默认显示 principle/candidate/approved
N2S/tooling/n2s-rules inspect --project /path/to/project --output inspect.json

# 默认只为 approved 规则计划；当前库因此会得到零项计划
N2S/tooling/n2s-rules plan --project /path/to/project --rule RULE_ID --output plan.json

# 候选计划仅用于审阅，apply 会拒绝
N2S/tooling/n2s-rules plan --project /path/to/project --rule RULE_ID \
  --include-candidates --output candidate-plan.json

# approved 计划每次只能包含一条规则
N2S/tooling/n2s-rules apply --plan plan.json --report apply-report.json
N2S/tooling/n2s-rules rollback --report apply-report.json
```

`plan` 固定注册表 SHA256、源文件 SHA256、预期输出 SHA256、finding 和 unified diff。`apply`
重新加载当前规则并复跑 detector/codemod/validator；registry、源码、finding 或输出任一漂移都会停止。
验证命令在目标项目目录以 argv 方式执行，不经过 shell。任一命令失败时已写文件立即恢复。

候选计划的 `eligible_for_apply` 固定为 false。工具没有 `--force` 或跳过审批参数；要晋级必须先
补齐 manifest 阻塞项、逐规则阈值与人工审批，再重新生成注册表。

## 目标项目副作用

成功 apply 在目标项目 `.n2s/backups/` 保存原文件，在 `.n2s/reports/` 保存审计报告。改写后的
Python 文件不 import N2S。rollback 会先确认文件仍等于本次改写的 SHA256，若用户随后修改过文件
则拒绝覆盖。inspect/plan 除调用者显式指定的 `--output` 外，不写目标项目。

## 官方知识工具

独立入口 `n2s-knowledge` 管理官方 Git 镜像、只读快照和固定版本索引，不执行上游代码：

```bash
N2S/tooling/n2s-knowledge refresh-if-due
N2S/tooling/n2s-knowledge status
N2S/tooling/n2s-knowledge search "torch_npu" --scope manipulation
N2S/tooling/n2s-knowledge guide --task training --stage preparation --json
N2S/tooling/n2s-knowledge search "RMSNorm" --stage optimization --accepted-only --include-community --json
```

同步、审阅、许可限制和接纳流程见 [upstreams/README.md](../upstreams/README.md)。
资料包任务目录默认参与搜索；`guide` 按任务/阶段给出原文入口和链接，`show` 读固定本地文件，
`follow URL` 从已登记 HTTPS 正文出发并返回时间、哈希和 `discovered_links`。
`follow CHILD --from-url ROOT --from-url PARENT` 逐层核对正文实际链接，不执行远端内容。
`search` / `guide` 可用 `--target-profile PROFILE.json` 对提供的任务、模型、模式、设备和软件
版本做可解释的软排序；差异和未知不会被标为兼容，也不会隐藏跨模型线索。
另一台机器用 `import-bundle --source ID
--path DIRECTORY` 导入同版本原资料；原文保持 ignored。详见
[REFERENCE_BUNDLES.md](../upstreams/REFERENCE_BUNDLES.md)。

## Case 实验工具

`tooling/n2s-experiments` 提供 `probe`、`new`、`list`、`plan`、`run`、`record`、`attach`、
`review`、`feedback-draft`、`feedback-preflight`、`feedback`、`workflow-check`、`validate`
和 `publish-check`，所有结果为 JSON。它不修改或晋级现有规则，
不执行 commit/push，不安装依赖，也不自动开始评测。详见
[evaluations/README.md](../evaluations/README.md)。
`feedback` 在迁移各节点追加脱敏事件，不探测硬件；`workflow-check` 列出三阶段查阅与功能、
精度、优化证据的缺口。使用 [即时反馈指南](../cases/work-items/FEEDBACK_GUIDE.md)，不等成功再录入。
`new` 的初始记录支持带子模块的工程；执行计划仍要求完整源码指纹。
按用户实际目标选择 `--task-type` 和 `--optimization-goal`，完成检查的范围见
[实验工作流](../evaluations/README.md#completion-scope)。
