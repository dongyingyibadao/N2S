# Candidate rule maintainer packet

This packet records an evidence-only agent assessment. Each JSON file is independent and uses `agent_assessed`
to identify the reviewing subject. The agent assessment may choose `approved`, `remain_candidate`, or `rejected`
for one rule without changing the others; repository-owner confirmation is still required to enable `auto_apply`.

The JSON reviews were reassessed against RTX 4090 CUDA evidence commit `917a826` on 2026-09-05. The capture closes
the CUDA module functional and numerical blocker. Its timing was collected under concurrent keepalive load, so it
is retained as raw evidence but cannot freeze a CUDA performance threshold.

Current engineering recommendations:

| Rule | Recommendation | Main reason |
|---|---|---|
| cache dtype alignment | remain candidate | MINT candidate and CUDA block work; exact adapter integration, thresholds and an independent rerun are pending |
| compile capability fallback | remain candidate | CUDA compile succeeds, while the only NPU failure proves missing Triton; a successful NPU control and second environment tuple are absent |
| sinusoidal FP64 fallback | rejected in the current capability scope | tested NPU and CUDA FP64 both work; any replacement must be a separately reviewed shape-scoped performance rule |

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
