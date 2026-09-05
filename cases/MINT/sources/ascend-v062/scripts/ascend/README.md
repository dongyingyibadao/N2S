# 昇腾 910B 上的 MINT 与 PI0.5

本目录保存用于 LIBERO 训练和评测的昇腾启动脚本。运行前必须由接手者显式设置持久化根目录：

```bash
export ASCEND_VLA_PERSISTENT_ROOT=<持久化根目录>
```

The pinned old/current framework lines and their experimental roles are recorded in
[`VERSION_MATRIX.md`](VERSION_MATRIX.md).
The distinct smoke, LeRobot PI0.5, OpenPI PI0.5, and MINT paper evaluation denominators are recorded
in [`EVALUATION_PROTOCOLS.md`](EVALUATION_PROTOCOLS.md).

Code, Python packages, models, datasets, caches, checkpoints, logs, metrics, and rollout videos live
below that root. CANN 8.5 and required system libraries live in the container image. The Python
environment is the persistent `envs/lerobot-npu` virtual environment. No model, dataset, checkpoint,
or evaluation artifact is intentionally written into the image layer.

## Ascend compatibility changes

- Use `torch-npu` and `device=npu` with BF16 model weights.
- Disable CUDA `torch.compile`; MINT and PI0.5 use eager execution on NPU.
- Use PyAV for LIBERO videos because TorchCodec cannot load against the Ascend PyTorch build.
- Keep the PaliGemma vision tower and projector in FP32 where required by Transformers 5.x.
- Bypass `GemmaTextScaledWordEmbedding` by default when embedding MINT language tokens. MINT pins the
  Hugging Face `fix/lerobot_openpi` branch at commit
  `dcddb970176382c0fcf4521b0c0e6fc15894dfe0`, where this path is a plain `nn.Embedding`.
  Transformers 5.x otherwise multiplies those embeddings by `sqrt(2048)`, changing the policy
  semantics even though every checkpoint tensor loads successfully. Set
  `MINT_USE_TRANSFORMERS_SCALED_LANGUAGE_EMBEDDING=1` only to reproduce the pre-fix diagnostic
  baseline.
- Restore the LeRobot v0.4.3 PI0.5 state-prompt processor referenced by the public MINT artifact.
  It pads LIBERO state from 8 to 32 dimensions before discretization; LeRobot 0.6.2 changed the
  same serialized registry name to an 8-dimensional prompt. Set
  `MINT_USE_CURRENT_PI05_STATE_PROMPT=1` only to reproduce that incompatible behavior.
- Convert inference prefix embeddings to the language-model dtype before creating the KV cache.
  Ascend SDPA requires query, key, and value to have identical dtypes.
- Use the top-level `--discover_packages_path=lerobot_policy_mint` argument. A policy-scoped plugin
  argument leaks into `--policy.path` overrides in the current LeRobot parser.
- Load complete MINT checkpoints with zero missing and zero unexpected keys. PI0.5 initialization
  loads only the PaliGemma backbone; the MINT action expert stays randomly initialized.

## Environment and assets

```bash
source scripts/ascend/env.sh
python scripts/ascend/preflight_mint.py \
  --checkpoint "$MINT_CHECKPOINT" \
  --tokenizer "$MINT_TOKENIZER" \
  --dataset "$HF_LEROBOT_HOME/lerobot/libero" \
  --require-weights --require-complete-dataset
```

Expected complete LIBERO revision `a1aaacb7f6cd6ee5fb43120f673cebb0cfea7dd4`:

```text
1693 episodes, 273465 frames, 377 parquet files, 74 MP4 files, 0 incomplete files
```

After the generic `lerobot/pi05_base` file is checksum-verified, validate MINT backbone
initialization, checkpoint save, resume, and resumed-checkpoint inference with:

```bash
scripts/ascend/validate_mint_base_resume.sh mint_base_resume_validation
```

## Evaluation

MINT uses `n_action_steps=4`, matching the public repository example:

```bash
scripts/ascend/eval_libero.sh \
  "$MINT_CHECKPOINT" \
  "$MINT_OUTPUT_ROOT/eval/mint_spatial_smoke" \
  libero_spatial '[0]' 1 4 42 auto

scripts/ascend/eval_libero_benchmark.sh \
  "$MINT_CHECKPOINT" 5 mint_libero_4suites_5eps 4
```

Run the formal current-framework control on four NPUs with one suite per card:

```bash
scripts/ascend/eval_mint_official_4npu.sh \
  "$MINT_CHECKPOINT" mint_current_50eps_4npu 50 4 42 4,5,6,7
```

The command above is a 200-rollout development A/B (`5 episodes/task`), not a published-result
reproduction. The formal MINT comparison uses the launcher default of `50 episodes/task` (2,000
rollouts total). The formal LeRobot PI0.5 comparison uses `10 episodes/task` (400 rollouts total).
Always report successes/trials alongside percentages.

On an eight-NPU instance, run both formal protocols concurrently while retaining batch size 1:

```bash
scripts/ascend/eval_joint_formal_8npu.sh \
  "$MINT_ASCEND_ROOT/models/pi05_libero_finetuned" \
  "$MINT_CHECKPOINT" \
  joint_formal_8npu_$(date +%Y%m%d_%H%M%S)
```

PI0.5 uses NPU 0-3 and MINT on the pinned LeRobot 0.4.3 line uses NPU 4-7. The run tag must be
unique when another instance mounts the same persistent storage.

Each run retains `eval.log`, `eval_info.json`, and per-episode MP4 files. The validator decodes every
video referenced by `eval_info.json`. The benchmark report includes per-task and per-suite CSV,
JSON, Markdown, a published-vs-NPU comparison plot, and Wilson 95% confidence intervals.

Pass `--baseline-dir` and `--pi05-dir` to `generate_libero_report.py` to add the MINT pre-fix and
PI0.5 NPU four-suite results to the same tables and comparison plot.

For the final 50-episodes-per-task comparison, `finalize_libero_formal_campaign.sh` waits for the
four MINT/PI0.5 framework combinations, generates one joint report, and rejects any suite whose
trial count is not exactly 500. The expected `eval_info.json` counts can be changed from 4 to 8 via
`PI05_CURRENT_EXPECTED_FILES` and `PI05_V043_EXPECTED_FILES` when PI0.5 uses task sharding.

Generate batch-scaling CSV, JSON, and PNG from retained inference logs with:

```bash
python scripts/ascend/generate_mint_runtime_report.py \
  "$MINT_ASCEND_ROOT/outputs/benchmarks/mint_libero_public_checkpoint"
```

## Official training schedules

MINT follows arXiv:2602.08602 Appendix Table VI: global batch 128, AdamW, learning rate `2e-4`,
betas `(0.9, 0.95)`, weight decay `0.01`, chunk size 16, and 30000 optimizer updates. PI0.5 follows
the recipe embedded in `pi05_libero_finetuned_v044`, the checkpoint used for the published LIBERO
rates: global batch 256, AdamW, learning rate `2.5e-5`, mean/std normalization, and 6000 optimizer
updates. The newer 30000-update, global-batch-64 documentation quickstart remains available via
`PI05_RECIPE=quickstart`, but is not the published-result reproduction setting.

The trainer loop counts micro-batches. Therefore:

- trainer steps and checkpoint frequency are multiplied by gradient accumulation;
- scheduler lengths are not multiplied by gradient accumulation;
- Accelerate advances its scheduler once per data-parallel process per optimizer update, so
  scheduler lengths are multiplied by `NUM_PROCESSES`.

Examples for the current two-card allocation, one independent job per card:

```bash
# MINT on one NPU: batch 32 x gradient accumulation 4 = global batch 128
scripts/ascend/train_libero_reproduction.sh 1 32 mint_libero 30000 200

# PI0.5 on another NPU: batch 16 x gradient accumulation 16 = global batch 256
../lerobot-ascend/scripts/ascend/train_libero_reproduction.sh \
  1 16 pi05_libero "$MINT_ASCEND_ROOT/models/pi05_libero_base" 6000 100
```

Both launchers reject incomplete assets and existing output directories. Checkpoints contain model,
optimizer, scheduler, RNG, data-order, and training-step state.

## Resume and 12-hour run

```bash
scripts/ascend/resume_libero_train.sh \
  /path/to/checkpoints/000200/pretrained_model TARGET_MICRO_STEPS 1 resumed_run

scripts/ascend/launch_dual_12h.sh dual_12h_$(date +%Y%m%d_%H%M%S) 12h
scripts/ascend/monitor_dual_training.sh \
  "$MINT_ASCEND_ROOT/outputs/dual_12h/RUN_TAG"
```

The dual launcher assigns MINT to visible NPU 0 and PI0.5 to visible NPU 1. It retains a manifest,
separate launcher logs, process IDs, one-minute NPU telemetry, periodic resumable checkpoints, and a
stability report. Before occupying either card it verifies the pinned SHA256 values for both base
weights and the MINT tokenizer. It uses `timeout` only as a 12-hour wall-clock boundary; the most
recent periodic checkpoint remains the resume point.

For an eight-NPU allocation, run four-way DDP for each model concurrently:

```bash
scripts/ascend/launch_joint_8npu_12h.sh \
  joint_8npu_12h_$(date +%Y%m%d_%H%M%S) 12h
scripts/ascend/monitor_dual_training.sh \
  "$MINT_ASCEND_ROOT/outputs/joint_8npu_12h/RUN_TAG"
```

MINT uses visible NPU 0-3 with micro batch 8 and PI0.5 uses NPU 4-7 with micro batch 16. Both use
gradient accumulation 4, preserving their official global batches of 128 and 256 respectively.

To prioritize the official MINT recipe without starting PI0.5 training, use the dedicated four-NPU
launcher. The third argument selects four physical device IDs from a larger allocation:

```bash
scripts/ascend/launch_mint_4npu_12h.sh \
  mint_4npu_12h_$(date +%Y%m%d_%H%M%S) 12h 8,9,10,11
```

The launcher verifies the generic PI0.5 initialization and tokenizer SHA256 values, preserves the
paper's global batch 128, and writes a session manifest, one-minute NPU telemetry, logs, and periodic
resumable checkpoints under persistent `outputs/` paths. The default interval is 1,000 optimizer
updates because a complete model plus AdamW state is about 22 GB; override it with
`MINT_SAVE_UPDATES` when a shorter recovery point is worth the additional storage.

Create an environment and source snapshot after final code changes with:

```bash
scripts/ascend/record_environment.sh pre_training_snapshot
```
