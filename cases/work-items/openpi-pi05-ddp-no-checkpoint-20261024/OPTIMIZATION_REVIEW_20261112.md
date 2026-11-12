# PI0.5 无重计算与固定 global batch 的证据

2026-11-12 只读整理，没有新实验。本地数据来自 [measurement-effective256.json](measurement-effective256.json)，
状态仍为 `open / pending_validation`。

## 本地配置对照

16×Ascend910B2C、全部 activation recomputation 关闭、BF16 + 选定 FP32 参数，
有效 global batch 固定为 256，两路各 1 次 warmup 和 2 次计时更新、512 个计时样本：

| 配置 | 计时阶段最慢 rank 的 wall time | samples/s | 分配峰值 GiB |
|---|---:|---:|---:|
| local batch2 × accumulation8 | 14.105075 s | 36.298992 | 42.665060 |
| local batch4 × accumulation4 | 13.057050 s | 39.212532 | 52.075781 |

该窗口耗时降低 7.4301%，吞吐比 1.080265，代价是更高峰值内存。两路 16 ranks 均通过，
报告实际 `checkpoint_calls=0`、有限 loss/grad norm、805 组优化器 state，以及参数确有更新。
这是本机配置证据，不是新的通用算法。

限制：仅 2 次计时更新，保活仍运行；预期 frame index 来自 sampler 而非独立 instrumentation；
不同 microbatch 消耗随机数的方式不同，没有输出精度/收敛对照或 checkpoint 保存。
不是 64/128 卡实测，不能根据等效 batch 换算那两种规模的速度。后来的多机记录另有 HCCL
失败和早期训练进度，不补足本对照的精度及长期稳定性。

## 已有机制与本地修复分别记录

固定官方 `45d167135c81d97573bfbe0e564bb4a1d9642514` 的
`manipulation/pi05/train/src/scripts/run_train.sh`
（SHA256 `8dc0f76d31e49a2e0e2ed838cf0041a8b68d67b517d5bc8e3255551e391f761a`）
已经有 `--disable-gc`；同 revision 的 `src/modeling_pi05.py`
（SHA256 `259183d96817aad1f1cb9f4f30a9e75a0927a9b42e6fe07201de840e4dee25cf`）
支持条件 checkpoint。信任为 `accepted_upstream_documented`，不是 N2S 复现。

精选原始 OpenPI `community://openpi@215abfb217dbac7d5f1273282331b9b1866c0479/src/openpi/models_pytorch/gemma_pytorch.py`
（SHA256 `225092e06509da0ae37bb9dca55c00d2804255bb1496f7c8700304b4c52a95eb`）
在训练时强制重新开启 Gemma checkpoint，属于 `community_source_snapshot_static_only`。
本地清理 HF 子树开关并移除强制开启，实际通过计数器确认 0 次 checkpoint。
“只去外层”与“全部关闭”作用范围不同，不共享精度结论。

只读核对时，目标工程以下当前文件哈希仍匹配 10/24 测量记录；未分发其实现或 patch：

| 相对路径 | SHA256 |
|---|---|
| `src/openpi/models_pytorch/pi0_pytorch.py` | `7db3e6ff1f4f3dd86275a1219f730cbb4966dcd6d3f7a3731577280e51316d12` |
| `src/openpi/models_pytorch/gemma_pytorch.py` | `71d95f3ef7985c6cf739e6cb01de9448bd8026cf7c979b6a0dc2a1feb17e7a28` |
| `scripts/benchmark_ascend_ddp.py` | `cae3a833350d552bc3dbe2bf5ef9334a5681d54fbe996c04b816aa07b273f741` |

当前 benchmark 的 DDP `static_graph=False`，累积前段使用 `no_sync`；不能继承官方 static_graph
recipe 的性能结论。本次所读固定来源未包含同样的 global256 微批组合 A/B，不能据此断言全社区没有。
下一步应在已获授权的实验中增加重复窗口、输入/RNG 对照、约定精度和长期保存恢复验证。
