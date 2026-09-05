# 来源说明

- 快照名称：`ascend-v043`
- 复制来源：`/opt/ascend-vla/src/MINT-v043-ascend`
- 复制日期（UTC）：2026-08-30
- 源内声明 revision：`59fa23d0537f545ca07b7d111a9f5697bbabe11e`
- 对应框架线：LeRobot 0.4.3 source overlay
- 许可证：MIT，补自官方 MINT commit `691a5e650fbccceaf70568799294eba24f79e114`

`59fa23d` 不在当前本地官方 Git 对象库中。2026-08-30 执行比较重建时，临时裸仓库按完整 SHA
从官方远端 fetch 成功，说明该对象当时仍可由远端直接恢复。README 完全一致；policy 包只有
`modeling_mint.py` 的三个 diff hunk，分别为 NPU FP32 fallback、compile guard 和 prefix dtype
对齐。计划指定的比较仍固定使用 `4eab579` 同版本近邻基线；不能声称该近邻基线到本快照的
全部 diff 都由 Ascend 迁移产生。

排除规则见上级 `README.md`。新增的 `LICENSE`、本文件、环境和清单属于案例元数据，不是原始
Ascend 源码的一部分。
