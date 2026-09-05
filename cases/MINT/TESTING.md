# 测试协议

所有结果遵循 [result.schema.json](schemas/result.schema.json)，保存固定输入、seed、原始计时样本、
数值指标、显存和异常。`pass` 只表示该次固定测试完成预期功能，不代表满足跨模型通用阈值。

## 入口

```bash
N2S/cases/MINT/run_npu_checks.sh
N2S/cases/MINT/run_cuda_block_checks.sh
```

NPU 入口默认运行候选算子、cache dtype operator A/B、FP64/compile runtime A/B、两套快照导入、
0.6.2 快照算子 smoke 和 `npu-smi` 采集验证。
设置 `N2S_RUN_MODEL_SMOKES=1` 后额外运行随机权重推理、单次训练更新和本地官方 checkpoint
加载 smoke；需要约 35 GB NPU 显存和本地模型资产。

CUDA block 入口使用固定合成输入，只运行 cache dtype、sinusoidal FP64/FP32 和 compile/eager 的
局部 A/B。它不加载模型、checkpoint 或数据集。当前仓库中的旧 `pending_cuda` 只记录历史环境；
正式 CUDA 回传由自校验 bundle 生成。

cache dtype 有独立的配对 A/B。算子层检查由两个入口默认执行，分别记录混合 dtype baseline、
局部 cast candidate，以及把 cast 纳入计时和峰值显存的 pre-aligned control。模型层检查会从
同一份固定源码在临时目录物化两个变体；baseline 只移除 `sample_actions` cache 建立前的 dtype
lookup/cast，candidate 保持归档源码不变。两个变体使用同一个序列化输入并在隔离子进程运行。

模型 A/B 需要完整 MINT 依赖，默认不随模块入口运行，只在申请模型输出、训练、checkpoint 语义
或模型级性能范围时作为增强验证。在当前 NPU 主机可显式执行：

```bash
N2S_RUN_MODEL_AB=1 N2S_RUN_MODEL_TRAINING_AB=1 N2S/cases/MINT/run_npu_checks.sh
```

训练不属于当前 cache 规则的自动适用范围，只作为源码变体没有影响训练路径的 scope control；
全量训练需要约 35 GB 显存。旧的 `N2S_RUN_CACHE_DTYPE_MODEL_AB` 与
`N2S_RUN_CACHE_DTYPE_TRAINING_AB` 仍可只选 cache 规则。未指定 checkpoint 时模型 A/B 使用固定
seed 的随机权重，只能作为 integration 证据，不能支撑 checkpoint 或模型输出声明。

CUDA 交接使用自校验 bundle，而不是要求操作者手动设置开关。构建、固定依赖、NVIDIA 主机单条
命令和回传文件说明见 [cuda/README.md](cuda/README.md)。bundle 只运行三个模块 harness，共三份
schema 验证后的结果 JSON，并在 manifest 中固定 `model_execution: false` 和
`model_parameters_loaded: false`。

## 候选检查

- FP32 sinusoidal embedding 对 CPU FP64 参考：最大绝对误差、最大相对误差、RMSE、余弦相似度。
- eager 与 compile：固定输入输出偏差、预热后每次耗时、median、p95、峰值显存和异常。
- dtype 对齐：不一致 dtype 的 SDPA 结果/异常，以及对齐后的执行结果和 FP32 参考偏差。
- dtype 对齐 A/B：baseline/candidate 原始样本、median、p95、增量峰值显存和 CPU FP32 偏差。
- integration：按获批 adapter 用无权重最小调用链确认实际路径，未运行的 adapter 不进入批准范围。
- 可选模型级：仅在申请相应范围时记录固定 checkpoint、输入、seed 下的 action、top-k、loss 和
  梯度有限性；模块证据不得替代模型结论，缺少模型证据也不阻止保存模块案例。

不设置统一 pass 阈值。任何性能判断只允许比较同一物理设备、同一环境和同一输入的修改前后。
