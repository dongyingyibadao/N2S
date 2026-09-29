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

## External Knowledge For Migration

Before proposing a migration change using N2S, read `upstreams/AGENT_USAGE.md`. Search the accepted official
snapshot and the pinned community source snapshots for the specific operation or error:

```bash
tooling/n2s-knowledge search "QUERY" --scope manipulation --accepted-only --include-community --json
```

Open relevant results with `tooling/n2s-knowledge show URI`, then compare model, framework, device, software
versions, mode and exercised code path with the target project. Check the N2S case evidence and rule review for
support, contrary evidence and known exclusions. Cite the exact source, revision, path, trust state, reusable
claim and remaining gap in the migration reasoning or case. A community snapshot's static validation does not
establish runtime success; an official recipe statement is not an N2S reproduction. If the local snapshot is
incomplete or the search has no match, say so rather than inferring that no upstream solution exists.

Use `tooling/n2s-knowledge diff` to inspect unreviewed official updates. Treat the cached content as internal,
non-commercial reference material and preserve all upstream and third-party license notices.

## Case-Only Migration Experiments

Read `evaluations/README.md`, `cases/work-items/README.md` and `cases/work-items/EXPERIMENT_GUIDE.md`
before collecting experiment results. The same workflow applies to any model or project. Maintaining
N2S does not authorize running model experiments; an experiment does not authorize rule maintenance.

- Make migration edits only in the user's separate target-project checkout, never in an N2S source snapshot.
- In N2S, write experiment observations, task definitions and results only under `cases/work-items/CASE_ID/`;
  unreviewed logs and approval plans belong in ignored `evaluations/_local/`.
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
