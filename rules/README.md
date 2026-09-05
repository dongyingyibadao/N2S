# N2S 通用规则库

这里保存可机器检查、可回退的 PyTorch/torch-npu 迁移规则。案例负责陈述事实，规则包负责定义
在什么前置条件下可以复用事实。两者的状态互不替代。

## 规则包内容

每个规则目录必须包含：

- `manifest.yaml`：范围、前置/后置条件、影响、逐规则验收契约、证据和审批状态。
- `README.md`：修改前后差异、原因、方法、影响、反例和人工适配点。
- `fixtures/`：可改写的 before/after，以及至少一个必须拒绝的 no-match 样例。
- `detector.py`：只识别已经证明可处理的代码形态。
- `codemod.py`：基于 LibCST 的保格式改写；输出代码不依赖 N2S。
- `validator.py`：修改前置条件和修改后结构验证。
- `evidence/summary.yaml`：原始证据索引、当前结果和尚未完成的实验。

机器可读字段由 [rule.schema.json](schema/rule.schema.json) 约束。`registry.json` 从各 manifest
确定性生成，并同时固定 manifest 与完整规则包 SHA256；`n2s-rules validate-registry` 会检查
schema、插件接口、fixture 和注册表漂移。

## 状态与自动化边界

状态按 [LIFECYCLE.md](LIFECYCLE.md) 从 `principle`、`candidate` 到 `approved`。当前三条 MINT
衍生规则都是 `candidate`，批准规则数量为零。

`inspect` 是只读操作，可以显示候选规则；`plan` 默认只选择批准规则。使用
`--include-candidates` 产生的候选计划只供审阅，`apply` 无条件拒绝。自动应用还要求 manifest
启用 `auto_apply`、存在完整审批记录、源文件哈希未变化、validator 通过和验证命令成功。审批人必须
把允许的环境范围写入 approval；在范围尚不能由 detector 证明时，validator 或验证命令必须拒绝。

## 当前候选

- `pytorch.npu.sinusoidal-fp64-fallback`：只在已识别的位置编码安全 dtype helper 中增加 NPU
  FP32 fallback。
- `pytorch.npu.compile-capability-fallback`：对已识别的 `torch.compile` 配置分支增加 NPU eager
  fallback；原则是按能力降级，不是永久关闭 NPU compile。
- `pytorch.attention.cache-dtype-alignment`：在缓存注意力边界将 prefix embedding 对齐到投影
  权重 dtype；原则覆盖 Q/K/V/mask 一致性，当前 codemod 只支持已验证的 prefix 形态。

使用方式见 [tooling/README.md](../tooling/README.md)。
