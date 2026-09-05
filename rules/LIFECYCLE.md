# 规则生命周期与审批

## `principle`

一个可复用的语义判断，但尚不具备直接替换所需的完整证据或工具。可以被 agent 用于定位问题，
不能生成可应用计划。

## `candidate`

具备规则契约、代码形态 detector、LibCST codemod、修改后 validator、正反 fixtures 和可追溯
证据。候选规则可以用于检查与人工审阅，但 `eligible_for_apply` 固定为 false。

数值或运行时候选晋级前至少满足：MINT 加两个非 MINT 项目、两个模型家族、CUDA/高精度参考、
固定 checkpoint/input/seed 的模型级数值结果，以及同一 NPU 的修改前后耗时和显存 A/B。框架
API 规则改用“两个项目、两个相关框架版本”的覆盖要求。

## `approved`

逐规则阈值全部满足，已记录审批人、UTC 日期、证据 revision、批准适用范围和限制。只有该状态
可以设置 `automation.auto_apply: true`。工具每次只应用一条批准规则，随后立即执行结构 validator
和 manifest 中的验证命令；任一步失败都会恢复备份。

审批不是永久豁免。框架、设备、dtype、shape 或代码形态超出批准范围时，规则重新 fail closed。
新增 adapter 或扩大范围需要新增证据和再次人工审批。

## 回退与审计

每次应用保存源文件 SHA256、改写后 SHA256、备份路径、验证输出和注册表 SHA256。回退仅在当前
文件仍等于该次改写结果时执行，避免覆盖用户后续修改。候选计划不写目标源码，也不创建备份。
