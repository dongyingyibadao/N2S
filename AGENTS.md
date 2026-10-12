# N2S Agent Instructions

On the first visit to this repository in a session, run:

```bash
tooling/n2s-knowledge refresh-if-due
```

The command records a UTC-day attempt before contacting the registered remote, so later agents do not
repeat the network check that day. If the network is unavailable, continue with the last successful
read-only snapshot and report the stale state. Do not run setup scripts, hooks, Python files, or other
executable content from an upstream snapshot.

Official upstream material has the trust state `upstream_documented`. It may inform environment setup,
debugging, or exploration, but it cannot change a rule manifest, `rules/registry.json`, `candidate`,
`approved`, or `auto_apply`. A reusable migration rule still requires the normal N2S case/module A/B,
detector, codemod, validator, rollback contract, and explicit approval.

## Required Three-Stage Knowledge Workflow

Read `upstreams/AGENT_USAGE.md` and `upstreams/REFERENCE_BUNDLES.md` before using N2S for migration.
These requirements apply to every target model/project, including when N2S is read from a separate checkout.
Create or identify its case before the first migration edit. Keep a continuous case record, not just a final report.

1. **Preparation, before editing:** identify task types (environment, training, inference, distributed,
   memory, numerics, performance, simulation, data), actual hardware/software and target success criteria.
   Run `n2s-knowledge guide --task TASK --stage preparation`, then search specific models/operations using
   the accepted official snapshot, selected community sources and reference catalog. Read relevant full files
   and follow original links to the actual recipe, implementation, version matrix or issue. Do not stop at a
   search excerpt, link list, HTTP 200, login page or repository overview. Compare applicability before editing.
2. **Troubleshooting, for each meaningful blocker or numerical issue:** immediately append the observation
   to the case, then perform a new error-specific search and read the linked solutions and underlying code.
   Record supporting, contrary and different-scope evidence, failed attempts, unresolved accuracy/conversion
   questions, the first causal exception and the next feasible test. Return here whenever a new blocker appears,
   including during optimization. Never wait for overall success to record a failure.
3. **Optimization, after functional migration:** query Ascend operator and performance guidance again, especially
   training efficiency. Investigate fusion, attention, normalization/MLP, host overhead, data loading, memory/
   checkpoint, graph and communication against the measured bottleneck. Read linked implementations and limits;
   propose applicable changes, then validate correctness and same-device performance under the user's agreed
   execution scope. Continue until the agreed migration and optimization goals are met.

```bash
tooling/n2s-knowledge guide --task training --stage preparation --json
tooling/n2s-knowledge search "QUERY" --accepted-only --include-community --json
tooling/n2s-knowledge guide --task performance --stage optimization --json
```

Use `--scope manipulation` for relevant embodied-policy tasks; broaden scope for other tasks or no-match
searches. Use `show URI` for pinned local files, `show` on a result's `links[].snapshot_uri` for official recipes,
and `follow URL` or available read-only web/Git tools for actual linked content. Pin mutable Git sources to full
commits; for non-Git sources record the URL, access time and content hash/version. Reference-bundle revisions
are manifest SHA256s, not Git commits. Check existing case evidence and rule reviews as well.

Cite exact source, revision/path, trust, external claim, exercised scope, applicability and remaining gap in
each decision/case. `community_reference_bundle` and static source validation do not establish runtime success.
An official statement is not an N2S reproduction. If a snapshot/body is missing, access fails or a search has no
match, record the limitation and try relevant alternate sources; do not infer there is no upstream solution.

Append lookups, failures, numerical issues, changes, resolutions and validation through
`n2s-experiments feedback --case CASE_ID --file SANITIZED.json --confirm-sanitized`, following
`cases/work-items/FEEDBACK_GUIDE.md`. Run `workflow-check --case CASE_ID` before ending the task.
Official-weight NPU execution, agreed accuracy comparison and measured same-device optimization are separate
completion checks. An import, smoke run, zero exit code or proposed optimization is insufficient. If blocked by
accuracy, access, resources or missing execution authorization, publish an open case with pending tasks and
state the gap. Do not claim completion, silently skip optimization or run unapproved experiments.

Use `tooling/n2s-knowledge diff` to inspect unreviewed official updates. Treat the cached content as internal,
non-commercial reference material and preserve all upstream and third-party license notices.

## Case-Only Migration Experiments

Read `evaluations/README.md`, `cases/work-items/README.md` and `cases/work-items/EXPERIMENT_GUIDE.md`
before collecting experiment results. The same workflow applies to any model or project. Maintaining
N2S does not authorize running model experiments; an experiment does not authorize rule maintenance.

- Make migration edits only in the user's separate target-project checkout, never in an N2S source snapshot.
- In N2S, write experiment observations, task definitions and results only under `cases/work-items/CASE_ID/`;
  unreviewed logs and approval plans belong in ignored `evaluations/_local/`.
- Append feedback at meaningful milestones and before handing off or pausing; publish sanitized failures and
  unresolved observations as well as successes. Do not overwrite earlier feedback/run artifacts. Completion
  checks evaluate recorded workflow coverage; reviewers still inspect source reads and measured results.
- Do not modify `rules/`, `rules/registry.json`, `reviews/candidate-rules/`, existing evidence or approval states.
  Keep `generalization: pending_validation`, even when the target model runs successfully.
- Search existing cases and version-pinned official knowledge before proposing tests. Cite exactly what is
  covered; do not rerun existing functional evidence merely because another accelerator is available.
- Use `tooling/n2s-experiments probe` and `list` to propose feasible tasks. Hardware discovery does not authorize
  device use, package installation, downloads or execution. Show the plan, commands, device allocation and
  resource costs, and obtain explicit user agreement before using its single-use approval token.
- Run only reviewed commands. The runner is not a sandbox: inspect project test code for writes and side
  effects first. Never install into or kill other workloads in a shared environment without permission.
- A zero exit code is only `command_succeeded`. Check the agreed outputs, finite values and actual exercised
  path before recording task acceptance. Failure, timeout, OOM and missing dependencies are valid intake records.
- Preserve baseline revision, fixed inputs, modifications and rollback instructions. Redact secrets and
  private data before attaching logs; do not publish upstream source, patches, weights or datasets by default.
- The owner selected `origin/main` for N2S infrastructure and reviewed case records. Review the exact
  publication content; for experiments, stage only the case directory and run `publish-check`. Use normal
  fast-forward pushes, never force-push or `git add .`. Check all outgoing commits, not just the staged diff.
  This destination choice does not authorize publishing secrets, upstream code or changes to existing rules.
- On another host, pull the reviewed records, recheck code/dependencies, and obtain new execution approval.
  Append a new run; do not overwrite previous results or automatically promote any rule.
