# n2s-rules 工具

该工具把规则应用设计成 fail-closed 事务。依赖固定为 LibCST 1.9.0、PyYAML 6.0.3 和
jsonschema 4.26.0；可以直接使用仓库入口，也可以安装 `N2S/tooling`。

```bash
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
