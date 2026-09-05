# 规则生命周期与审批

## `principle`

一个可复用的语义判断，但尚不具备直接替换所需的完整证据或工具。可以被 agent 用于定位问题，
不能生成可应用计划。

## `candidate`

具备规则契约、代码形态 detector、LibCST codemod、修改后 validator、正反 fixtures 和可追溯
的模块级 A/B 证据。候选规则可以从一个可复现案例形成，用于检查与审阅，但
`eligible_for_apply` 固定为 false；跨项目和模型级缺口写入 blockers，不阻止保存 candidate。

## 证据层级与范围上限

- `module` 是最低层级：固定输入/seed、CUDA 或 CPU 高精度参考、同一 NPU 的修改前后数值、耗时
  和显存 A/B。它可以支持 exact device/framework/operator/dtype/shape 范围的规则评定。
- `integration` 用无权重最小调用链证明 detector 匹配的实际 adapter 会执行修改路径。某个 adapter
  缺少这一层证据时，不得进入该 adapter 的批准范围。
- `model` 只对模型输出、训练、checkpoint/release、预处理语义或模型级性能声明强制要求。广泛的
  跨项目/模型家族结论仍需源案例加两个独立项目并覆盖至少两个模型家族。

证据层级不是质量分数。模块证据完整的窄规则可以比模型证据不完整的宽规则更可靠。批准范围必须
列出证据层级和精确环境，不能用较低层级结果推断较高层级行为。

## `approved`

逐规则阈值全部满足，已记录审批人、UTC 日期、证据 revision、批准适用范围和限制。只有该状态
可以设置 `automation.auto_apply: true`。工具每次只应用一条批准规则，随后立即执行结构 validator
和 manifest 中的验证命令；任一步失败都会恢复备份。

模块级批准可以存在，但只能覆盖已验证的算子/模块、设备、版本、dtype、shape/range 和模式。
若 codemod 修改真实模型调用链，每个获批 adapter 还必须有 integration 证据；没有模型级证据时，
approval 必须明确排除端到端模型正确性、训练稳定性和模型级性能声明。

审批不是永久豁免。框架、设备、dtype、shape 或代码形态超出批准范围时，规则重新 fail closed。
新增 adapter 或扩大范围需要新增证据和再次审批。

## 回退与审计

每次应用保存源文件 SHA256、改写后 SHA256、备份路径、验证输出和注册表 SHA256。回退仅在当前
文件仍等于该次改写结果时执行，避免覆盖用户后续修改。候选计划不写目标源码，也不创建备份。
