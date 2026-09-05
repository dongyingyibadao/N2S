# N2S: NVIDIA-to-昇腾迁移证据库

N2S 用案例化证据记录模型从 NVIDIA/CUDA 软件栈迁移到昇腾/NPU 软件栈时的代码变化、
可运行性、数值行为和同设备 A/B 结果。案例中的观察不能自动成为通用迁移规则。

## 案例证据状态

- `exploratory`：探索性观察，只说明指定模型、版本和设备上的结果。
- `candidate`：跨模型和跨版本复验完成，等待人工审批。
- `approved`：人工审批通过，可进入主迁移指南。
- `rejected`：证据不足、收益不成立或副作用不可接受。

当前批准的通用规则数量：**0**。

## 通用规则

案例观察和通用规则使用两套不同状态，不能因为案例测试通过就自动晋级：

- `principle`：从一个或多个案例提炼出的原则，尚无足够的可替换实现与验证。
- `candidate`：已有规则契约、detector、codemod、validator 和证据，但仍有明确的推广阻塞项。
- `approved`：满足逐规则验收契约并经人工审批，才允许工具自动应用。

规则包、机器可读注册表和生命周期见 [rules/README.md](rules/README.md)。自动化工具默认只对
`approved` 规则生成可执行计划；`candidate` 只能检查和生成审阅计划。

两个非 MINT 固定源码快照及静态 adapter 报告见
[validation-projects](cases/validation-projects/README.md)。NVIDIA 主机交接使用
[CUDA block A/B bundle](cases/MINT/cuda/README.md)；逐规则证据评定见
[candidate-rules review packet](reviews/candidate-rules/README.md)。

## 审批流程

1. 案例按 [ADMISSION_REQUIREMENTS.md](ADMISSION_REQUIREMENTS.md) 保存代码、环境和原始样本。
2. 维护者检查溯源、复现命令、数值偏差、同设备性能和回退方法。
3. 候选项至少完成目标 NPU 与 CUDA 对照，并覆盖声明适用范围内的多个模型。
4. 人工审批人签名、记录日期和适用层级后，才可把条目改为 `approved`。

未经人工审批，不得在 N2S 主指南中使用“必须”“通用”“总是更快”等规则性表述。

## 当前案例

- [MINT](cases/MINT/README.md)：LeRobot 0.4.3 与 0.6.2 两条 Ascend 迁移源码线，状态为
  `exploratory`。
