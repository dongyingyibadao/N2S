# NPU sinusoidal FP64 fallback

状态：`candidate`，版本 `0.2.0`。这不是“把 NPU 上所有 FP64 改成 FP32”的规则。它只处理
MINT 本地 helper、LeRobot 固定共享 helper 和 OpenPI 固定局部 helper 三种已识别形态。

## 差异与原因

MINT/LeRobot 形态把已有 MPS guard 扩展到 `mps` 和 `npu`；OpenPI 形态在其局部 helper 中插入
等价的 NPU-only guard。CPU、高精度参考、非 FP64 dtype 和其他设备保持不变。

```python
# before
if device_type == "mps" and target_dtype == torch.float64:
    return torch.float32

# after
if device_type in {"mps", "npu"} and target_dtype == torch.float64:
    return torch.float32
```

## 影响与限制

当前 `torch 2.9.0 + torch-npu 2.9.0` 的 NPU FP64 baseline 在三个测试形态均通过，因此回退在该
环境不是功能必需。256 维常用范围相对 FP64 的最大绝对误差为 `1.1957985683264116e-4`；1024 维
宽范围增至 `1.0269512865533403e-2`。4096x1024 workload 中 FP32/FP64 median 比为
`0.002539284572777645`，峰值增量少 `41947136` bytes。这些只支持进一步评估性能取舍，不能支持
“NPU 不支持 FP64”的通用理由，也不是批准阈值。

固定 MINT checkpoint 的 action/logit/loss/gradient delta 虽为零，但当前模型中 helper 静态调用数
为零；该结果是空路径 control，不能作为数值安全证据。LeRobot 与 OpenPI 目前只完成固定源码
快照上的 detector/codemod/validator 验证，runtime 和 CUDA 对照仍待完成。

detector 故意要求 helper 名、参数、比较式、返回值以及本地用途或固定路径 adapter 都吻合。
任意 FP64 tensor、loss、优化器、reduction 或无法证明用途的 helper 都不匹配。回退时恢复
MPS-only 条件，或移除 OpenPI 形态新增的 NPU guard。
