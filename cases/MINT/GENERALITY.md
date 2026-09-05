# MINT 修改的通用性评估

本页回答“结构上改了什么”和“能否作为通用修改”。结论来自精确的 `59fa23d` 对 Ascend 0.4.3
比较，以及官方 main、Ascend 0.4.3、Ascend 0.6.2 的分层比较。所有 MINT 案例证据仍为
`exploratory`；通用规则包当前为 `candidate`，批准数量为零。

## 精确归因的三项 Ascend 修改

| 修改 | 结构位置 | 通用性判断 | 规则包 |
|---|---|---|---|
| sinusoidal FP64 请求在 NPU 回退 FP32 | `get_safe_dtype` 与位置编码 | 数值类通用候选，但只能对已验证算子边界条件化应用，不能替换任意 FP64 | `pytorch.npu.sinusoidal-fp64-fallback` |
| NPU 不进入当前 `torch.compile` 分支 | 模型构造、训练和采样 callable | 运行时通用候选；原则是能力检测与 eager fallback，不是永久禁用 NPU compile | `pytorch.npu.compile-capability-fallback` |
| prefix embedding 对齐投影权重 dtype | cache 建立前的完整推理 | attention invariant 通用候选；每种框架/cache/fused/quantized 实现仍需独立 adapter | `pytorch.attention.cache-dtype-alignment` |

这三项是从恢复的官方 revision 到 Ascend 0.4.3 package 的全部精确 policy diff。能够精确归因并不
等于已经通用：它只消除了“这是否是 release 演进”的疑问，未补齐跨项目验证。

两个非 MINT 固定源码快照已加入：LeRobot 的 PI0/SmolVLA 与 OpenPI PI0。cache 和 FP64 adapter 在
相应源码上通过 detector/codemod/validator；compile 在 LeRobot 两个模型上匹配，在 OpenPI 因
缺少构造期 device 证明而拒绝。这是静态适用边界证据，不是 checkpoint runtime 证据。

当前 NPU 还改变了 FP64 候选的解释：三个 FP64 sinusoidal shape 都能运行，因此该规则不能继续
以“此 NPU 不支持 FP64”作为通用理由。它至多是需要逐 shape/range 数值阈值的性能候选。

## 0.6.2 的主要结构变化

| 变化组 | 主要内容 | 是否设备通用 |
|---|---|---|
| Transformers 5 PaliGemma/Gemma 适配 | language/vision module 层级、dtype 字段、norm、residual、attention 调用 | 否；可能拆成版本兼容规则，但当前是 MINT/PaliGemma 复合 adapter |
| token 与 cache 生成 | prefix/suffix embedding、KV cache、query/key/value/mask dtype 边界 | 只有 dtype 契约原则可候选复用；具体属性路径和 cast 位置不通用 |
| checkpoint loader | key repair/remap、MINT/PI0.5 判别、missing/unexpected key 严格检查 | 否；属于 checkpoint/release schema |
| language/state prompt | scaled word embedding opt-out、32 维 legacy prompt registry | 否；属于公开 MINT checkpoint 的训练语义，并有全局 registry 副作用 |
| VQVAE 配置和发现 | 参数内嵌、目录搜索、mtime 选择 checkpoint | 否；属于 MINT tokenizer 发布与目录布局 |
| processor 与预处理 | LeRobot import 移动、图像范围和 feature scaling | import 可成为窄版本兼容候选；范围/scaling 属于模型与 checkpoint 语义 |
| intention/temporal ensemble | temperature 和 MINT action 聚合行为 | 否；是策略超参数，不能用设备迁移解释 |

完整逐项判定、阻塞项和 case-only 原因见
[difference-matrix.json](comparisons/difference-matrix.json)。

## 判定方法

一项修改只有同时满足下列条件才可能成为通用规则：

1. 能写成与 MINT 类名、checkpoint 和任务无关的设备、算子或框架不变量。
2. 前置条件可以由静态 detector 或明确的运行时 probe 可靠确认；未知情况可以停止。
3. 修改不改变未声明的 checkpoint、prompt、预处理或策略语义。
4. 有可独立执行的 codemod、validator、正例和必须拒绝的反例。
5. 先满足模块级 A/B；再按申请范围补 integration、跨项目或模型级证据，并为该规则批准数值、
   性能和显存契约。较低证据层级不得支撑较高层级声明。
6. 维护者或明确标识的受托 agent 审批记录明确范围、限制和证据 revision；启用 `auto_apply` 仍需
   仓库所有者明确确认。

“在 MINT 上运行成功”“补丁很小”“多个项目都出现 dtype cast”都不是充分条件。反过来，框架
import 移动即使不是设备通用，也可以在覆盖两个项目和两个版本后成为版本范围明确的兼容规则。

## Agent 使用边界

Agent 可以用 candidate 原则定位项目、生成 review-only diff 和列出缺失证据；只有 approved 规则
允许自动落盘。自动应用每次只处理一条规则，固定输入哈希并验证后立即出报告，失败自动恢复。
目标代码不依赖 N2S 运行时。
