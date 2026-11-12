# PI0.5 独立 worker 管线：可能值得扩大对照的组合优化

2026-11-12 只读审阅既有报告和当前本地实现，无新实验。这里的 Jade Lotus 是 CPU FP32
权威、可抢占独立 NPU worker 管线，不能混同标准 OpenPI DDP 或官方 LeRobot recipe。
`open / pending_validation`；500 更新的最终验收未完成。

| 组合 | 已有证据 | 不能外推的范围 |
|---|---|---|
| native dtype pinned D2H、一次最终 fence、按 dtype 分组 CPU snapshot | [固定 live gradient 报告](measurement-fixed-live-gradient-d2h-01.json)：同一真实 backward、805 叶、3,248,572,176 元素，1 次预热 + 每路 4 次 AB/BA；中位 5.766152→4.325755 s，约 1.333 倍，全部快照逐位一致 | 单卡组件，0 optimizer update；每叶 D2H 仍有 805 次。降至 2 组的是 CPU widening/snapshot 次数，不能写成只发起 2 次 D2H |
| 精确 mixed BF16/FP32 native wire | [native/owned 报告](measurement-native-owned-preflight-02.json)：FP32 等价 12,994,288,704 B→6,736,577,376 B，少 48.1574%；完整梯度 roundtrip 原位精确 | FP32 叶原样，BF16 叶存精确 uint16 位，不是有损压缩；CPU 编码不证明完整 NPU export + durable wire 的速度 |
| 固定顺序 FP32 reducer 的有界并行读取 | [预读报告](measurement-reducer-prefetch-01.json)：32 个真实来源的固定 256 MiB 块，1/2/4 再 4/2/1 读者；中位 13.87997→4.94476 s，约 2.807 倍，manifest/payload 精确一致 | CPU/共享文件系统组件；未清缓存，未选块未覆盖，非整训练提速 |
| 同 4 读者 owned 参数 RAM | [native/owned 报告](measurement-native-owned-preflight-02.json)：ABBA 加载 + finite rescan 中位 10.924611→7.479580 s，完整 payload 一致 | CPU/shared-FS，额外 RAM 换时间；不能与旧单读者 baseline 混比 |

已有 32 卡短程观察的 warm mean 113.33→71.95 s 来自不同分配和时段，不能称为同物理卡受控 A/B。
idle metadata cache、native snapshot 不全量展开 FP32 等后续候选主要有 CPU 契约和故障边界测试，
完整 NPU 及端到端验收待做。上述组件倍率不能相乘作为模型提速。

## 本次读过的来源与实现

固定官方 `upstream://cann-recipes-embodied-ai@45d167135c81d97573bfbe0e564bb4a1d9642514/manipulation/pi05/train/doc/README.md`
（SHA256 `4659712bc9f9040a555526ae91474e17dcc609298be149d1bf312d5140392172`）
覆盖 Beta、外层 checkpoint、QKV、融合 attention、grouped MLP、DDP；它没有描述这里的
独立 worker 梯度导出和 durable wire 组合。相关 `src/lerobot_train.py`
（SHA256 `7ed2ba905c31acdda5652d5d37777ce8338f814f44b19f33cf2d0ebe07e84ad3`）
的 DataLoader pin/prefetch 是不同方向的数据加载，不能作为本管线已被覆盖的证明。
二者 trust=`accepted_upstream_documented`，外部实现不代表 N2S 实测。

当前本地实现的下列 SHA256 与原 source-review 记录一致；没有 Git revision，不能伪造 upstream URI。
原始 source-review 中还保留完整文件/配置哈希、故障契约和未覆盖范围。

| 相对路径 | SHA256 |
|---|---|
| `jade_lotus/npu_gradient_transfer.py` | `5411c2e45621aefeba30f9fb0c974cc9b2d988f23be5c92ea38165c39f64a36e` |
| `jade_lotus/native_snapshot.py` | `89ab88e24f702829fc92fcf62e5bf75c165db3f528bb925ded2f150416003e6e` |
| `jade_lotus/array_blob.py` | `a9458c6afb4d7d0dd93daec5ab3a6dc5bea722a773dbe176d1492ad648ef9c10` |

Pinned/nonblocking、预读、mmap 和 native dtype 原理本身已有广泛应用。这里值得保留的是
它们在实际混合梯度、严格顺序 reducer、可抢占协议下的组合和证据，最多可表述为
“本次已读固定来源未见相同组合”，不能宣称社区首创。

后续应扩大来源检索，并在用户授权下补完整 NPU export/roundtrip、32 卡同设备重复 A/B、
抢占恢复、严格精度和 500 更新验收。源码漂移、严格梯度不一致及确定性布局问题仍未全部闭环。
