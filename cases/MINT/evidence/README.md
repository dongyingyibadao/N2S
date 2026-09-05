# 证据索引

`npu/` 保存当前 910B2C 的精简 JSON 和必要日志；`cuda/` 当前只保存 `pending_cuda`。大型权重、
数据、CANN work 目录和 MP4 均不复制。

`npu/prior_run_summary.json` 是 2026-08-29 已完成的真实单步训练和三回合 LIBERO 推理摘要。
`npu/original_files.sha256` 固定原始文件路径和哈希，`prior_training_excerpt.log` 保存判断训练完成
所需的最小日志片段。原始文件仍位于 workspace，可能包含绝对路径，移动后应依 SHA256 定位。

由当前 N2S 快照重新运行的结果包括候选检查、快照 import、算子 smoke、随机权重推理、单次
训练更新和官方 checkpoint 推理。`npu/model_checks.json` 将这些结果和已有 LIBERO smoke 汇总
到统一 schema；原始小型 JSON 仍单独保留。复跑方法见 [TESTING.md](../TESTING.md)。所有结果
均为 `exploratory`。

`cache_dtype_operator_ab.json` 是默认运行的配对算子证据。启用模型开关后另存
`cache_dtype_model_inference_ab.json`；训练 scope control 单独保存在
`cache_dtype_model_training_ab.json`。模型输出张量只在运行期间用于计算 delta，不归档；JSON
保存形状、dtype、有限性、内容 SHA256 和聚合数值。临时 baseline 源码不归档，但 JSON 内保存
baseline/candidate 源码 SHA256 和完整的最小 unified diff。

`runtime_rule_ab.json` 保存 FP64 baseline/candidate 的三个功能 shape、4096x1024 性能/显存 A/B，
以及 compile capability probe。`compile_model_*_ab.json` 和 `sinusoidal_fp64_model_*_ab.json` 使用
同一 checkpoint、序列化输入和隔离子进程；FP64 模型结果同时记录 matched helper 调用数，避免把
未执行路径的零 delta 误作安全证据。

CUDA 回传必须来自 [cuda bundle](../cuda/README.md)，包含九份 JSON、必要日志、聚合 manifest 和
`SHA256SUMS`。当前目录中的旧 `pending_cuda` 只证明无 NVIDIA 本机时的降级行为，不可用于审批。
