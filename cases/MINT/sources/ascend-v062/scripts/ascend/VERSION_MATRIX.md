# LeRobot, PI0.5, and MINT Ascend version matrix

Snapshot date: 2026-08-26.

| Line | LeRobot source | Transformers | Model artifact | Purpose |
|---|---|---|---|---|
| MINT-native control | `v0.4.3` (`0b067df57d21d3a02d6c511f1609172fa39ac29b`) | `4.53.3` OpenPI branch (`dcddb970176382c0fcf4521b0c0e6fc15894dfe0`) | `huangrm/MINT-libero`, or the same PI0.5 artifact below | Isolate Ascend changes with MINT's original framework semantics |
| Published PI0.5 | checkpoint release `v0.4.4` | Serialized with the release-time PI0.5 implementation | `lerobot/pi05_libero_finetuned_v044` revision `8e174154ef5f6c60a8da12ae99c303d8963138c1` | Published-weight evaluation and official 6,000-update recipe |
| Current integration | source snapshot version `0.6.2` | `>=5.4,<5.6` | The same published PI0.5 and MINT artifacts after migration | Retain compatibility with current LeRobot development |

Upstream's latest stable tag at the snapshot date is `v0.6.1`; the local `0.6.2` tree is a
development snapshot, not a stable release tag.

The old source line is imported through `PYTHONPATH` from `projects/lerobot-v043-ascend`. Python
package metadata can still print `0.6.2` because the shared persistent environment contains the
current editable installation; `preflight_v043.py` verifies the imported source path and pinned
source revision separately.

## Ascend-only compatibility boundary

The MINT-native control keeps these device-level changes:

- discover and validate `torch.npu` devices;
- fall back from FP64 to FP32 where Ascend does not support FP64;
- disable CUDA-oriented `torch.compile` on NPU;
- align prefix/KV-cache dtypes for Ascend SDPA;
- serialize and restore NPU RNG state for checkpoints.

The local PaliGemma tokenizer redirect avoids a gated Hub dependency. The LIBERO task filter is an
evaluation convenience. Neither changes model weights. MINT's 32-value state prompt and plain
language embedding are release-time semantic compatibility, not Ascend changes.

The `0.4.3` and `0.6.2` PI0.5 policy directories differ substantially. The current tree adds and
changes policy configuration, processor behavior, model logic, and memory support, so a current-vs-
old result difference must not be attributed to Ascend without the same-checkpoint A/B evaluation.
