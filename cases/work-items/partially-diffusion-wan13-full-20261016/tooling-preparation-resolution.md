# Preparation tooling observations

1. The first knowledge refresh used the shell default Python and failed with `ModuleNotFoundError: No module named jsonschema`. No environment was installed or changed. Reading `tooling/README.md` identified the provisioned-Python requirement. Retrying with the existing Ascend Python environment completed refresh. Accepted official revision remains `45d167135c81d97573bfbe0e564bb4a1d9642514`; fetched revision `db9b2453ad70ac919f8c42e02a61d16db63f4e66` is unreviewed. A troubleshooting search for jsonschema had zero results; the actual local tool dependency documentation supplied the remedy.

2. `n2s-experiments new` rejected the live target because its incomplete Git metadata does not identify a repository. The remedy was a new isolated source-only Git archive, documented in baseline-provenance.md, without mutating target Git metadata.

3. The first temporary archive copy followed an artifacts symlink in the capacity source snapshot and began copying immutable user cache data. It was immediately stopped by terminating only its own Python process. Only the partial task-owned `LOCAL_PATH_0001` copy was removed. No source assets, original cache, weights, existing jobs or keepalive process were stopped, changed or deleted. The successful retry used explicit source-file enumeration, excluding all symlinks, artifacts and bytecode. The successful source-only archive is about a few MiB.

These failures happened during preparation before model edits and are recorded retrospectively after the case could be opened. None is a model numerical failure.
