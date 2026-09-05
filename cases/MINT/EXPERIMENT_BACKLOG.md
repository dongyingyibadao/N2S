# 实验待办

以下项目均不阻止保存探索性案例。标为“广泛范围”或“模型范围”的项目只限制相应批准范围，
不阻止模块级案例或范围严格限定的模块规则。

- [ ] 在 CUDA 主机运行同一 sinusoidal、compile 和 SDPA block，回填三份模块级对照结果。
- [ ] 对 FP32 fallback、compile guard 和 dtype 对齐分别做同一 910B2C 的修改前后性能 A/B。
- [ ] 模型范围：固定官方 checkpoint、输入和 seed，记录 action delta、各 scale top-k 一致率与 logits/loss。
- [ ] integration/模型范围：在 0.4.3 和 0.6.2 两条线完成无权重最小调用链；需要模型声明时再做 checkpoint 交叉验证。
- [ ] 广泛范围：扩展到至少两个非 MINT 项目和两个模型家族，验证候选修改的适用边界。
- [x] 保存 LeRobot/OpenPI 固定 revision、LICENSE、SHA256 与重建脚本，并完成三条规则的静态匹配/拒绝矩阵。
- [ ] 为拟批准的 LeRobot/OpenPI adapter 增加无权重 integration probe；仅在模型范围内追加真实 checkpoint A/B。
- [ ] 为三条候选规则分别确定并审批数值、功能、性能与显存验收契约；不共享全局阈值。
- [ ] 为 compile fallback 覆盖至少两个 torch/torch-npu 环境，并加入成功 compile capability control。
- [ ] 为 cache dtype 原则分别验证标准 SDPA、fused、quantized 和有意异构 Q/K/V；未验证 adapter 保持拒绝。
- [ ] 为可能复用的 Transformers/LeRobot API 变化覆盖两个项目和两个相关框架版本，再决定是否建立窄兼容规则。
- [ ] 用 `msprof` 比较 profiler 开/关的原始时间样本、median、p95 和峰值显存。
- [ ] 用 `msaccucmp` 完成最小算子 dump、CPU/CUDA/NPU 数值比较和清理流程。
- [ ] 在隔离子进程测试 `transfer_to_npu` 的 monkey-patch 范围、功能、数值、性能和退出后状态。
- [x] 2026-08-30 已在临时裸仓库按完整 SHA 从官方远端恢复 `59fa23d`；本地官方工作树未改动。
- [x] 2026-09-01 已生成无权重自校验 CUDA block bundle、固定依赖、三结果 schema 和单命令 runner。
- [ ] 扩大 LIBERO 回合数；当前三回合仅为可运行性 smoke，不作为 benchmark。
