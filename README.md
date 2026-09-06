# N2S: NVIDIA-to-昇腾迁移证据库

N2S 用案例化证据记录模型从 NVIDIA/CUDA 软件栈迁移到昇腾/NPU 软件栈时的代码变化、
可运行性、数值行为和同设备 A/B 结果。案例中的观察不能自动成为通用迁移规则。

## 案例证据状态

- `exploratory`：探索性观察，只说明指定项目、模块/模型、版本和设备上的结果。
- `candidate`：已形成可复用规则包并至少完成模块级验证；未覆盖范围继续列为阻塞项。
- `approved`：在明确证据层级和适用范围内审批通过，可进入主迁移指南。
- `rejected`：证据不足、收益不成立或副作用不可接受。

当前批准的通用规则数量：**0**。

## 官方社区知识

`upstreams/` 接入了固定版本的昇腾官方具身智能 recipe，作为环境配置、排障和探索参考。运行
`tooling/n2s-knowledge refresh-if-due` 可按 UTC 日期至多检查一次更新；`search`、`show` 和 `diff`
提供带 source、revision、路径与信任状态的访问。详见 [upstreams/README.md](upstreams/README.md)。

官方材料默认仅为 `upstream_documented`，不会自动改变以下规则状态、审批或 `auto_apply`。性能数字
保留原设备、卡数、batch、模型、数据和测量口径，不作跨硬件归一化。

## 通用规则

案例观察和通用规则使用两套不同状态，不能因为案例测试通过就自动晋级：

- `principle`：从一个或多个案例提炼出的原则，尚无足够的可替换实现与验证。
- `candidate`：已有规则契约、detector、codemod、validator 和证据，但仍有明确的推广阻塞项。
- `approved`：满足逐规则验收契约，并由维护者或明确标识的受托 agent 留下审批记录。

规则包、机器可读注册表和生命周期见 [rules/README.md](rules/README.md)。自动化工具默认只对
`approved` 规则生成可执行计划；`candidate` 只能检查和生成审阅计划。

## 分层验证

未完成这些层级的错误报告也能先进入 [case 工单](cases/work-items/README.md)，保持
`pending_validation`，不冒充已验证案例。跨硬件任务、证据复用和用户确认流程见
[实验工作流](evaluations/README.md)；任意模型均使用同一份
[工单与跨端复测指南](cases/work-items/EXPERIMENT_GUIDE.md)。

- `module`：固定合成或录制输入下的局部 baseline/candidate A/B，是接收探索性案例的最低要求。
- `integration`：不用外部权重，以最小调用链确认修改位置确实执行、输入输出契约保持成立。
- `model`：加载 checkpoint 或执行端到端推理/训练，只在声明涉及模型输出、训练、checkpoint 语义
  或无法由较低层级证明的高风险自动修改时要求。

模型级验证不是提交社区案例的统一门槛。批准范围不得超过已完成的证据层级；只有模块证据时，
结论必须限定到已测设备、框架版本、算子、dtype 和 shape，不能声称对整个模型成立。

两个非 MINT 固定源码快照及静态 adapter 报告见
[validation-projects](cases/validation-projects/README.md)。NVIDIA 主机交接使用
[CUDA block A/B bundle](cases/MINT/cuda/README.md)；逐规则证据评定见
[candidate-rules review packet](reviews/candidate-rules/README.md)。

## 审批流程

1. 案例按 [ADMISSION_REQUIREMENTS.md](ADMISSION_REQUIREMENTS.md) 保存代码、环境和原始样本。
2. 维护者或受托审查 agent 检查溯源、复现命令、数值偏差、同设备性能和回退方法。
3. 候选项完成与声明范围相称的 NPU/CUDA 或高精度参考对照；扩大到模型或跨项目范围时再补相应证据。
4. 审批记录必须写明审查主体、证据层级、日期、适用范围和限制；仓库所有者明确确认后才可启用
   `auto_apply`。

未经维护者确认的审批记录，不得在 N2S 主指南中使用“必须”“通用”“总是更快”等规则性表述。

## 当前案例

- [MINT](cases/MINT/README.md)：LeRobot 0.4.3 与 0.6.2 两条 Ascend 迁移源码线，状态为
  `exploratory`。
