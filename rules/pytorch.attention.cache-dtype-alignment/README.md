# Cached attention boundary dtype alignment

状态：`candidate`，风险为 high。可复用原则是：进入同一个 attention kernel 的 Q/K/V，以及实现
要求一致时的 mask，必须满足该实现的 dtype 契约。当前自动 adapter 更窄，只处理 MINT 已验证的
prefix cache 形态，并从代码中唯一的 `q_proj.weight.dtype` 表达式推导目标 dtype。

## 差异与原因

未对齐的 cached prefix 可能让后续 query 与 key/value 使用不同 dtype。记录的 NPU SDPA control
对此直接报错；对齐后固定输入运行通过。改写在 prefix 构造后、cache forward 前插入局部 cast，
不硬编码 BF16/FP32，不改权重、mask、position 或 cache layout。

```python
prefix_embs, prefix_pad_masks, prefix_att_masks = self.embed_prefix(...)
prefix_dtype = self.backbone.language_model.layers[0].self_attn.q_proj.weight.dtype
prefix_embs = prefix_embs.to(dtype=prefix_dtype)
```

## 影响与限制

局部 cast 可能产生新 tensor 和舍入，也可能遮蔽上游 autocast/配置错误。对齐 BF16 的算子 smoke
相对 CPU FP32 最大绝对误差为 `0.008095860481262207`、余弦相似度为
`0.9999948790364719`，不是模型级批准阈值。新增的配对 A/B 在 Ascend 910B2C 上复现了算子和
固定 MINT checkpoint 的未对齐 baseline dtype 异常；candidate 连续五次推理通过。由于 baseline
没有输出，action/logit/top-k delta 在数学上不可定义，而不是零。单独的 pre-aligned control 将
cast 纳入 50 次交替计时：candidate median 比 control 高 `14.58%`，增量峰值多 `17408` bytes；
这只描述 `[2,4,16,32]` 小张量 smoke。训练 scope control 的 loss、选定梯度和峰值显存完全一致，
但训练仍在规则排除范围。固定 LeRobot PI0 与 OpenPI PI0 源码快照均通过 detector/codemod/
validator 静态验证；它们尚未运行模型 A/B。CUDA cache 行为和非 MINT runtime 仍待验证。

如果找不到唯一投影 dtype、prefix 已经 cast、不是 cached inputs_embeds 路径，或属于量化/FP8/
异构 QKV，detector 必须拒绝。suffix、mask、fused attention 和量化路径需要独立 adapter 与证据。
