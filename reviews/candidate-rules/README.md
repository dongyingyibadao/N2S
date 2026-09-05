# Candidate rule maintainer packet

This packet records an evidence-only agent assessment. Each JSON file is independent and uses `agent_assessed`
to distinguish the recorded decision from a pending human-maintainer review. The assessment may choose
`approved`, `remain_candidate`, or `rejected` for one rule without changing the others.

Current engineering recommendations:

The review JSON files are pinned to the pre-CUDA evidence revision recorded inside each file. A verified RTX 4090
module capture was added on 2026-09-05 after that assessment. It satisfies the functional and numerical CUDA block
run item; its timing was collected under a concurrent keepalive load and must be repeated on an idle device before
performance thresholds are frozen. The decisions below remain unchanged, but the JSON packets have not yet been
reassessed against the new capture.

| Rule | Recommendation | Main reason |
|---|---|---|
| cache dtype alignment | remain candidate | MINT candidate and CUDA block work, but the failing model baseline gives no paired delta and adapter integration is pending |
| compile capability fallback | remain candidate | one environment proves missing Triton only; no successful NPU compile control exists |
| sinusoidal FP64 fallback | rejected in the current capability scope | tested NPU FP64 works; any replacement rule must be redesigned as a shape-scoped performance candidate |

No rule is approved, so all thresholds, `approved_evidence_level`, and `approved_scope` remain null and every
manifest remains `candidate` with `auto_apply: false`. The entries in `required_before_decision` are the evidence required before a future
promotion or reconsideration. Compile must not be approved for all NPUs based only on the current missing-Triton
result. Static snapshot matches count as adapter coverage, not runtime evidence. The rejected FP64 decision is
limited to the current capability-fallback rationale; it does not prohibit a new shape-scoped performance rule.

`assessed_evidence_level` records the highest valid evidence used by the assessment. An approved review must also
set `approved_evidence_level`; the approved scope cannot exceed that level. Module evidence can support a narrowly
scoped module decision, while source adapters require integration evidence and model claims require model evidence.

Validate the packet:

```bash
python N2S/reviews/candidate-rules/validate_reviews.py
```

After the repository is committed, set `evidence_revision.repository_commit` to that commit. An assessment must
not set `automation.auto_apply` until the corresponding manifest blockers are resolved, thresholds are frozen,
and a fresh registry is built.
