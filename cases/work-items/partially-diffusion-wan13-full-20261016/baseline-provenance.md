# Source identity and execution boundary

The source baseline commit `949abb74b523268f528beda228592a0e6fb793f8` is a new, isolated local archival Git commit created on 2026-10-16. It is **not** an upstream Causal-Forcing commit or an original target-project revision. The model family originates from https://github.com/thu-ml/Causal-Forcing; that URL identifies the model family only.

The actual Partially_diffusion checkout has incomplete Git metadata: HEAD and config exist, but refs and objects are absent. Its original Git revision is unavailable. The archival repository is `LOCAL_PATH_0001`, copied from the pre-edit capacity baseline source snapshot. It has 198 source files and excludes symlinks, artifacts, weights, datasets, caches and bytecode. `baseline-source-manifest.json` records the file hashes and canonical SHA256 tree.

The N2S `new` command inspected this archival repository only to establish an honest source identity. It did not run a model. Runtime experiments execute the user's actual target project, never the N2S source snapshots or this archival snapshot. N2S runner execution is not represented as having occurred. The live target source and selected execution configuration must be hashed with every actual experiment.

Prior measurements occurred on 2026-10-13. They are imported evidence, not new runs on 2026-10-16. Prior capacity: 16 cards, microbatch 32 per card, accumulation 1, global batch 512, 8 AdamW updates. Current largest-batch search is a different experiment.

All observations remain project-specific with generalization pending validation. No rules, source snapshots, registry or approval state are modified, and this task does not publish anything to a remote.
