# LIBERO evaluation protocols

The development runs and published-result reproductions intentionally use different sample sizes.
Every report must show both the success count and denominator; percentages alone are not sufficient.

| Result target | Framework/checkpoint line | Episodes per task | Rollouts per suite | Total rollouts | Seed | Actions executed per inference |
|---|---|---:|---:|---:|---:|---:|
| LeRobot PI0.5 published (`97/99/98/96`) | `pi05_libero_finetuned_v044` | 10 | 100 | 400 | 1000 | 10 |
| OpenPI PI0.5 original (`98.8/98.2/98.0/92.4`) | OpenPI LIBERO checkpoint | 50 | 500 | 2000 | 7 | 5 |
| MINT-4B paper (`97.4/99.6/98.2/97.8`) | MINT native LeRobot 0.4.3 line | 50 | 500 | 2000 | 42 | 4 |
| Development A/B | Any pinned line | 5 | 50 | 200 | recorded per run | recorded per run |

The LeRobot PI0.5 documentation explicitly launches `eval.n_episodes=10` over all 10 tasks in each
suite. Its published percentages therefore have a denominator of 100 per suite.

OpenPI's public evaluator defaults to `num_trials_per_task=50`, seed 7, and `replan_steps=5`. Its
suite horizons are 220/280/300/520 for Spatial/Object/Goal/LIBERO-10. The LeRobot evaluator uses
280/280/300/520 and the published LeRobot reproduction explicitly uses 10 action steps. These are
separate public protocols; an OpenPI percentage is not used as the direct baseline for a LeRobot run.

The MINT paper says it follows the standard LIBERO protocol and reports binary episode success, but
does not explicitly state the episode count or random seed. Its 0.2 percentage-point granularity is
consistent with 500 rollouts per suite. The public MINT repository supplies seed 42 in its evaluation
example. The MINT alignment launcher consequently uses 50 episodes per task and seed 42, and records
this evidence/assumption in the run manifest. This is the closest reproducible public protocol, not a
claim that the omitted paper details were independently confirmed with the authors.

LIBERO uses the benchmark-provided initial-state arrays. The LeRobot environment advances through
those arrays deterministically for each task; the configured seed is retained in `eval_info.json`.
Suite horizons are 280 steps for Spatial/Object, 300 for Goal, and 520 for LIBERO-10.

## Parallel evaluation

Formal evaluation may run suites in parallel because each suite has an independent environment,
fixed initial-state order, and a dedicated output directory. Keep `eval.batch_size=1`; do not batch
multiple rollouts together for a published-number comparison. The four-NPU launchers assign one
complete suite to each NPU, so their result is protocol-equivalent to the serial launchers.

`eval_joint_formal_8npu.sh` uses NPU 0-3 for the LeRobot PI0.5 protocol and NPU 4-7 for the MINT
paper-alignment protocol. It is safe to run from a second instance that mounts the same persistent
root only when its run tag is unique. Never point two instances at the same output directory.
