# Non-MINT validation source snapshots

This directory contains small, weight-free source snapshots used to test rule detectors and adapters against
projects other than MINT. A snapshot is evidence about one fixed revision; it is not a vendored dependency.

| Project | Revision | Relevant code shapes |
|---|---|---|
| Hugging Face LeRobot | `4aaff99be4a1d81568c08c8f0296b41b40c99ec4` | shared sinusoidal dtype helper, PI0/SmolVLA compile config, PI0/SmolVLA KV cache |
| Physical Intelligence OpenPI | `215abfb217dbac7d5f1273282331b9b1866c0479` | PI0-local sinusoidal helper, PI0 compile mode, PI0 KV cache |

No checkpoint, dataset, output, cache, media, or generated model artifact is included. `LICENSE` and any
model-specific license shipped at the selected revision are retained. Each project directory contains `REMOTE`,
`REVISION`, and `SHA256SUMS`; the hashes cover every snapshot file except `SHA256SUMS` itself.

Rebuild and verify from the two pinned commits:

```bash
N2S/cases/validation-projects/rebuild_snapshots.sh
```

The rebuild uses a temporary Git repository and an exact file allowlist. It never checks out into MINT or edits
either upstream working tree.

Run the fail-closed detector/codemod validation matrix and rebuild the deterministic report:

```bash
TORCH_DEVICE_BACKEND_AUTOLOAD=0 python N2S/cases/validation-projects/validate_snapshots.py
```

The generator verifies every snapshot hash before scanning. A matched candidate must pass its before/after
validator and become detector-idempotent. A zero-finding result is accepted only for the explicit OpenPI compile
exclusion: that revision uses `pytorch_compile_mode` but exposes no constructor-time `config.device` proof.
