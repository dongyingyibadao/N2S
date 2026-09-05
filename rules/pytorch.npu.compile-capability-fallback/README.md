# NPU torch.compile capability fallback

状态：`candidate`。通用原则是“在目标环境验证 compile 能力，并保留可观察的 eager fallback”，
不是“昇腾永远关闭 `torch.compile`”。当前 adapter 只识别由 `config.compile_model` 控制、内部包含
`torch.compile` 赋值且没有已有 else 的分支。

## 差异与原因

MINT 的 compile 固定输入在记录环境中因 NPU Inductor 导入缺失的 Triton 而失败，eager 路径通过。
改写保留所有非 NPU compile 参数和调用，只在 `config.device` 以 `npu` 开头时继续使用原 eager
callable，并记录 warning。

```python
# before
if config.compile_model:
    self.forward = torch.compile(self.forward, mode=config.compile_mode)

# after
if config.compile_model and not str(config.device).startswith("npu"):
    self.forward = torch.compile(self.forward, mode=config.compile_mode)
elif config.compile_model:
    logging.warning("torch.compile is disabled on Ascend NPU; using eager execution.")
```

## 影响与限制

功能收益是把已知编译失败改为 eager 可执行；代价是可能放弃已在新版本可用的编译收益。固定
checkpoint 推理 baseline 在第一次 compile 调用约 `15.98s` 后因缺 Triton 失败，eager 五次
median 为 `0.07377196568995714s`；训练 eager 完成一次 optimizer update。由于没有成功 NPU
compile control，这些数据不是有效的 compile/eager 速度比较，不得宣称 eager 更快。codemod
在需要时添加标准库 `logging` import，但不改变非 NPU 分支。已有 else、非 `config.device` 设备
来源或 correctness 依赖 compile 的代码都会拒绝。回退前必须先让 compile 路径通过同一协议。

固定 LeRobot 快照中的 PI0 和 SmolVLA compile block 均通过静态 adapter 验证。OpenPI 使用
`pytorch_compile_mode`，但构造时没有可静态证明的 device 字段，因此明确拒绝；不得为了增加
项目计数而放宽 detector。
