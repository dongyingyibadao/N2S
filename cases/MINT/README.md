# MINT 昇腾迁移案例

本案例固定保存实际使用的 Ascend MINT 0.4.3 与 0.6.2 源码线，并与官方仓库固定 commit
分层比较。全部结论为 `exploratory`，只回答“MINT 中该变化在当前 Ascend 环境是否必要、是否
可运行”，不推广为其他模型的迁移规则。

## 导航

- [ARCHITECTURE.md](ARCHITECTURE.md)：三条源码线的组件与数据流。
- [GENERALITY.md](GENERALITY.md)：主要结构变化、通用性判断和候选规则映射。
- [sources/README.md](sources/README.md)：源码快照、过滤规则和完整性校验。
- [comparisons/README.md](comparisons/README.md)：三组固定比较和 provenance gap。
- [comparisons/difference-matrix.json](comparisons/difference-matrix.json)：机器可读差异分类。
- [TESTING.md](TESTING.md)：统一测试协议与入口。
- [evidence/README.md](evidence/README.md)：当前精简证据和原始产物索引。
- [TOOLS.md](TOOLS.md)：诊断工具验证状态。
- [EXPERIMENT_BACKLOG.md](EXPERIMENT_BACKLOG.md)：未完成实验。

## 固定源码线

| 名称 | 来源 | revision / 版本 | 用途 |
|---|---|---|---|
| official legacy | `RenMing-Huang/MINT` | `4eab5795345721001c412ff1ca2c886a11eab606` | 0.4.3 可重建近邻基线 |
| Ascend 0.4.3 | `/opt/ascend-vla/src/MINT-v043-ascend` | 声明原始 revision `59fa23d0537f545ca07b7d111a9f5697bbabe11e` | 实际 0.4.3 迁移源码 |
| official main | `RenMing-Huang/MINT` | `691a5e650fbccceaf70568799294eba24f79e114` | 0.6.2 上游固定基线 |
| Ascend 0.6.2 | `/opt/ascend-vla/src/MINT` | 无独立 Git 对象，快照清单固定 | 实际部署源码 |

`59fa23d` 不在本地官方仓库对象库中；2026-08-30 的重建脚本在临时裸仓库中按 SHA 从远端
直接 fetch 成功。补充的精确 policy 包比较显示只有 `modeling_mint.py` 三处修改：FP32 fallback、
NPU compile guard 和 prefix dtype 对齐。计划指定的三组比较仍使用 `4eab579` 作为同版本近邻
基线，因此该组全部 diff 仍不能整体归因为 Ascend 修改。恢复结果见
`comparisons/provenance-gap.json`。

## 当前结论边界

- 当前已确认 Ascend 910B2C 上的算子 smoke、单步训练和三回合 LIBERO 推理可运行。
- CUDA 结果为 `pending_cuda`。
- 不比较 H200、4090 与 910B 的绝对速度，不定义统一性能阈值。
- 当前批准为通用规则的条目为零。
- 三项精确 Ascend policy 修改已建立 `candidate` 规则包；候选状态不授权自动应用。
