# MINT 架构与数据流

## 三条源码线

官方 legacy/Ascend 0.4.3 使用 LeRobot 0.4.3 接口；官方 main/Ascend 0.6.2 使用 LeRobot
0.5.1 到 0.6.2 演进后的 processor 和 Transformers 接口。Ascend 0.6.2 还适配了当前
Transformers 5 的模块层级、embedding 和 checkpoint 语义。核心 MINT 结构保持为
PaliGemma 主干、Gemma action expert 和 MultiScaleVQVAE。

## 组件

1. **Processor 与配置**：processor 重命名观测、增加 batch、按数据集统计量归一化，将不足
   32 维的 state 补零、离散到 256 个 bin，并把任务和 state 组成 PaliGemma prompt。配置记录
   图像尺寸、action chunk、VQ codebook、patch scale、dtype、compile 和优化器参数。
2. **PaliGemma 主干**：视觉塔编码多路 224x224 图像，language model 编码 task/state token。
   图像和语言 embedding 组成 prefix。
3. **Action expert**：Gemma expert 读取 prefix 和多尺度 action token suffix。在训练中对各
   scale 的 codebook token 计算交叉熵；推理时使用 prefix KV cache 逐 scale 生成 token。
4. **MultiScaleVQVAE**：CNN encoder 将 16x7 action chunk 编为 latent；量化器按
   `patch_nums=[1,2,4]` 生成由粗到细的 token；decoder 将累计 latent 重建为 action。
   粗 scale 表示 intention，细 scale 补充 execution detail。
5. **Ensemble**：`IntentionEnsembler` 按 intention 相似度加权历史 action chunk；
   `TemporalEnsembler` 按时间衰减组合重叠 chunk。temperature 是 MINT 行为参数，不属于通用
   设备迁移设置。

## 训练流

```text
images + state + task + action chunk
  -> processor/normalizer -> image tensors + prompt tokens
  -> MultiScaleVQVAE encoder/quantizer -> ground-truth scale tokens
  -> PaliGemma prefix + Gemma expert suffix
  -> per-scale logits -> cross-entropy loss
  -> backward -> finite-gradient check -> optimizer update
```

## 推理流

```text
images + state + task
  -> processor -> PaliGemma image/language prefix
  -> prefix forward -> KV cache
  -> SOS + level embedding -> coarse intention token
  -> next-scale autoregression -> fine execution tokens
  -> MultiScaleVQVAE decoder -> 16x7 action chunk
  -> intention/temporal ensemble -> execute n_action_steps
```

## 迁移敏感边界

- sinusoidal embedding 原实现请求 FP64；NPU fallback 为 FP32，属于计算精度候选。
- prefix、suffix query、attention mask 与 KV cache 必须匹配投影权重 dtype，属于运行 dtype
  对齐候选。
- `torch.compile` 的模型级行为由设备后端和版本共同决定；Ascend 源码选择 eager。
- 配置内嵌、temperature、32 维 state prompt、VQVAE 路径发现、Transformers 5 embedding
  语义和 checkpoint remap 均是 MINT/release 兼容问题，不能与设备通用修改混为一谈。
