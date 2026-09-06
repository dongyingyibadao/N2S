# Case-only evaluation workflow

This workflow collects unverified observations and scoped evidence without changing N2S rules.
All experiment-owned tracked writes go to `cases/work-items/CASE_ID/`. Schemas and the initial
evidence-reuse assessment live here; machine-local plans, locks and raw logs live in ignored `_local/`.
No command promotes a rule, edits the registry, commits or pushes.
This is a model-independent workflow. The user runs experiments; maintaining N2S does not authorize
model execution. See `cases/work-items/EXPERIMENT_GUIDE.md` for the shared intake and retest guide.

## Evidence First

Consult `evidence-reuse.json`, the original reviews, `n2s-knowledge search/show` and existing cases before
adding tasks. The initial assessment covers the three current rules, not every possible community claim.
It neither changes their approval contracts nor treats a similar patch as runtime verification.

Record the exact claim, pinned source, hardware/software/input scope, supporting or contrary evidence,
reviewer and remaining gap. An accepted external explanation stays `upstream_documented`; an existing
local result retains its original environment and limitations. Neither is relabeled as a new local run.
Tasks may cite both using `evidence_refs`. Only schedule what those references do not already cover.

Each task asks one question in a declared scope. Split adapters, input protocols and incompatible software
tuples into separate tasks. A shared task can list both `cuda` and `npu` only when the same protocol applies.
Broad generality is never inferred from one successful host. Existing draft followups intentionally have
no runnable commands; an agent must define the missing test, not execute a placeholder.

## Interfaces

Run from the N2S root. Use a provisioned, trusted Python environment; the tool needs `jsonschema` from
`tooling/requirements.txt`. No tool command installs dependencies.

```bash
tooling/n2s-experiments probe --python /path/to/environment/bin/python
tooling/n2s-experiments list --backend cuda
tooling/n2s-experiments list --backend npu
tooling/n2s-experiments list --backend npu --model MODEL_NAME
tooling/n2s-experiments list --backend auto --python /path/to/environment/bin/python
tooling/n2s-experiments validate
```

`probe` runs isolated imports of installed torch/torch_npu plus available device-management queries;
it does not import project files, load weights or launch a model. Missing backends are reported, not
silently replaced with CPU. Visibility restrictions are recorded. CANN discovery uses standard install
paths and reports `not_available` for other layouts; confirm those versions manually in the case.
Available devices do not mean free devices. Check scheduler allocation, free memory and other users'
workloads before approving execution. `memory_gb` and `estimated_minutes` are estimates, not reservations.

`list --backend cuda/npu` is a portable queue view, not a claim that the current host can run it. `auto`
checks actual devices and exact declared package versions. Dependency tasks require reviewed acceptance;
they represent prerequisites only, not evidence that this host or model is correct. Specify separate
tasks when prerequisites must be tied to a particular source/environment.

## Planning And Execution

Create a case using `new --model MODEL_NAME`; repeated `--model` arguments identify related models, without
granting shared validation status. Fill its generated task according to `schemas/task.schema.json`. Keep it `draft`
until its concrete argv, fixed inputs, variant, acceptance criteria, costs and permissions have been reviewed.
Use `{python}` as an argv element to bind execution to the probed interpreter. There is no shell expansion.
Arguments are an array, not a shell command string. Commands execute in a separate target Git checkout.
Never point at an N2S case source snapshot, `upstreams/_cache`, or the N2S repository itself.

`protocol.assets` identifies input/checkpoint files by project-relative or absolute path in `name` and SHA256;
their hashes are checked before planning and again before running. Prefer portable relative paths. All
nonignored source files are hashed, including untracked helpers. Ignored dependencies and external code are
not captured by this mechanism: pin them in the environment or assets and review their provenance.

```bash
tooling/n2s-experiments plan --task CASE_ID/TASK_ID --project /path/to/model-project --python /path/to/env/bin/python
# Show the full plan to the user. Only after their explicit agreement:
tooling/n2s-experiments run --plan /absolute/path/from/plan.json --approve FULL_PLAN_SHA256
```

Approval binds task, input assets, command, source fingerprint, environment, N2S runner and protected rule content.
Any drift requires a new plan. A token is consumed before execution and cannot be reused. A checkout-wide
nonblocking lock prevents overlapping tool runs; it is not a cluster-wide GPU reservation. Reviewed runs
with the same task/source/environment trigger a duplicate warning; rerunning requires `--repeat-reason`.
Source/protocol changes preserve historical records but prevent those records satisfying the changed task.
Model scope is also pinned in plans and runs: relabeling a case cannot reuse an old model's acceptance or
execution approval. Keep the concrete tested model and adapter explicit in each task protocol.

Timeouts and interrupts stop the launched process group and append a failure record. Exit 0 means only
`command_succeeded`, not correct actions, useful training or approval. Background/daemon jobs are unsupported.
The runner checks protected rule/review hashes before and after execution and flags `safety_violation` if
they change; it never reverts user files. **This is not a security sandbox.** Arbitrary approved commands can
write files or contact the network; inspect them and use container/OS isolation when needed. The declared
network/install flags describe the requested permission, not an enforced network filter.

## Result Lifecycle

Raw stdout/stderr stays in `_local/logs/` and may contain private paths or credentials. Inspect it locally,
then create a small UTF-8 report with sanitized exception text or measured output checks. Include failure
stage, command, actual device, input/seed, expected/observed values, modification description, rollback,
limitations and next test. A basic credential scanner is only an additional check, not a privacy guarantee.

```bash
tooling/n2s-experiments attach --run /path/to/run.json --evidence /path/to/sanitized.txt \
  --summary 'Observed result and remaining gap' --confirm-sanitized
# attach returns a NEW report run preserving original provenance, linked by parent_run_sha256.
tooling/n2s-experiments review --run /path/to/report-run/run.json --reviewer REVIEWER \
  --conclusion does_not_meet --summary 'Failure stage, evidence and next task'
```

`review` conclusions are `meets_task_acceptance`, `does_not_meet` and `inconclusive`. Acceptance requires a
successful process/reported result, a defined protocol and an attached report, then the reviewer's explicit
judgment of that report. Generic software cannot determine arbitrary model correctness from logs. Both the
review and run keep `generalization: pending_validation`. Reviews and run artifacts are append-only; record
a new attempt/reviewed report to correct an earlier interpretation, do not rewrite published history.

For an experiment performed outside the runner, `record --task ... --project ... --outcome reported_failure
--summary ... --evidence ... --confirm-sanitized` appends a manual observation. `reported_pass` and `blocked`
are also available. It captures the **current** source/environment at intake time, not a reconstructed past
execution; state any mismatch and the real execution time in the report. Do not use it to invent provenance.

## Cross-Host Handoff

The owner selected `origin/main` for infrastructure and reviewed case records. Commit only the reviewed case
directory after `validate` and `publish-check`; see the case guide. Use normal pushes, never force-push. Another host
pulls these small records, reads the task and reconstructs the target checkout/assets. No local absolute plan,
environment or old execution approval transfers. The next host generates its own plan and asks the user again.
Append a new run under the same task only when its protocol is unchanged; otherwise create a new task and cite
the old evidence. External model-code publication is not required at this stage. A dirty source hash is not a
portable patch: document changes and acknowledge any inability to reconstruct the exact original implementation.

Same-hardware baseline/modified runs provide A/B evidence. Cross-hardware checks require matched inputs and
scoped numerical tolerances; never compare raw NVIDIA/Ascend speed as a migration quality score.

## Verification

The experiment tests use temporary local Git repositories and CPU subprocess fixtures, not GitCode, model
downloads or accelerator experiments. They cover failure/timeout records, approval replay and drift, locking,
redaction checks, case-only publishing, immutable evidence and a second-host clone/run/local-push round trip.

```bash
PYTHONPATH=tooling/src python -m unittest discover -s tooling/tests -v
TORCH_DEVICE_BACKEND_AUTOLOAD=0 python -m unittest discover -s cases/MINT/tests -p 'test_*.py' -v
tooling/n2s-experiments validate
tooling/n2s-rules validate-registry
python reviews/candidate-rules/validate_reviews.py
```
