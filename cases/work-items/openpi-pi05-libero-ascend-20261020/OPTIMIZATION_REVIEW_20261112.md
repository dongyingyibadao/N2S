# PI0.5 优化证据与来源对照

2026-11-12 只读审阅；未运行新实验。外部知识与本机观察分别保留原验证范围，
所有通用性结论仍为 `pending_validation`。本次对照覆盖 N2S 的固定官方及精选社区快照，
不代表已穷尽最新社区。

| 优化 | 来源判断 | 本地实测及边界 |
|---|---|---|
| Beta(1.5,1) 逆 CDF | 固定官方已有；本地是 NPU opt-in 适配 | 每调用均值 270.777→27.010 µs，约 10.025 倍；65,536 样本有限及经验 CDF 留档。随机序列改变，没有事先约定的分布验收阈值，不能当作整训练提速 |
| 去重复外层 suffix checkpoint | 固定官方已有；保留内部逐层重计算 | 固定 batch1 真 LIBERO 输入、2 轮预热、6 组 AB/BA、同步 forward/backward；中位 434.126→383.139 ms，均值 433.288→431.200 ms。候选有慢值，不能只报告中位约 11.75% |
| QKV、融合 attention、grouped MLP、DDP static graph | 固定官方已有 | 本 case 未证明全部适用于 OpenPI；mask 全遮挡行、adaRMS、训练梯度语义需分别确认。官方收益不能移植为本地测量 |

上述整模型 compute A/B 使用固定 noise/time，fast Beta 为关闭状态，因此主要比较去外层
checkpoint；Beta 采样是独立微基准。它排除数据读取、增强、传输、zero_grad 和 AdamW，
没有 optimizer update，不能把结果写成端到端训练吞吐或收敛收益。

`optimization-ab-controlled.json` 的 loss 1,600 个值逐元素相等；805 个实际梯度中
804 个完全相等，视觉 patch Conv2D 最大差 `5.238689482212067e-10`；baseline 重复自身
同一梯度差 `5.820766091346741e-10`。7 个缺梯度在两路一致且列出，不称“所有参数均有梯度”。
没有约定精度容差或跨端参考，不把微小误差自动判为精度通过。

## 实际查阅的固定来源

以下 URI 的公共前缀为
`upstream://cann-recipes-embodied-ai@45d167135c81d97573bfbe0e564bb4a1d9642514/`，
信任状态 `accepted_upstream_documented`。用 `n2s-knowledge show URI` 读取：

| 路径 | SHA256 | 本次读取与声明 |
|---|---|---|
| `manipulation/pi05/train/doc/README.md` | `4659712bc9f9040a555526ae91474e17dcc609298be149d1bf312d5140392172` | 全文；明确列出上述已有优化、默认状态及 recipe 范围 |
| `manipulation/pi05/train/src/modeling_pi05.py` | `259183d96817aad1f1cb9f4f30a9e75a0927a9b42e6fe07201de840e4dee25cf` | 相关 Beta、checkpoint 和融合实现；beta=1 的 uniform 幂变换已有 |
| `manipulation/pi05/train/src/scripts/run_train.sh` | `8dc0f76d31e49a2e0e2ed838cf0041a8b68d67b517d5bc8e3255551e391f761a` | 参数解析；已有 disable-gc 和 disable-outer-suffix-checkpoint |

对照 `community://openpi@215abfb217dbac7d5f1273282331b9b1866c0479/src/openpi/models_pytorch/pi0_pytorch.py`
（SHA256 `dcd7b6f508808ce4b7170a1720a4c62c6da04edae3652d16c94a469dca924e16`）的
Beta 与外层 checkpoint；这是 `community_source_snapshot_static_only`，不能代表当前完整社区。
来源正文和实现只读，未复制进 case 或执行。

## 值得继续吸收的本地增量

本 case 的主要增量是 OpenPI 版本特定的可开关适配、逐梯度对照和可复核的失败边界。
[16 卡 microbatch 对照](../openpi-pi05-ddp-no-checkpoint-20261024/OPTIMIZATION_REVIEW_20261112.md)
补充无重计算配置的本机证据；
[Jade Lotus 组合优化](../jade-lotus-ascend-fragments-optimization-20261028/OPTIMIZATION_REVIEW_20261112.md)
是另一套独立 worker 管线。后者更值得单独扩大社区对照，但不能混记成标准 OpenPI 的已验证优化。
