# 固定比较

`rebuild_comparisons.sh` 只读取官方 Git 对象和 N2S 快照，不 checkout、不切换分支、不修改
用户的 `MINT` 工作树。比较范围标准化为根 README/LICENSE/requirements、MINT Python 包和
Ascend 运行脚本；SDAT、MINT-light、网页与媒体不混入迁移 diff。

三组输出：

1. `official-legacy-4eab579_vs_ascend-v043.patch`
2. `ascend-v043_vs_ascend-v062.patch`
3. `official-main-691a5e6_vs_ascend-v062.patch`

若临时 fetch 成功，还会生成代码范围更窄的
`supplemental-official-declared-59fa23d_vs_ascend-v043-package.patch`。2026-08-30 的补充 patch
只有 `modeling_mint.py` 三个 hunk，可以精确归因首批三个 Ascend 候选；它不替代上面的三组
计划比较。

重建命令：

```bash
N2S/cases/MINT/comparisons/rebuild_comparisons.sh
```

可用 `MINT_OFFICIAL_REPO=/path/to/MINT` 指定另一份含固定对象的官方 clone。脚本会在临时裸
仓库尝试 fetch `59fa23d`，结果写入 `provenance-gap.json`。2026-08-30 的尝试成功，但三组计划
比较仍固定使用 `4eab579` 近邻基线；若以后 fetch 失败，也会明确保留缺口，绝不把全部差异
归因为 Ascend 修改。

`difference-matrix.json` 是对关键差异的人工分类，不取代完整 patch。所有条目当前均为
`exploratory`。
