# Environment setup observations, 2026-10-20

The default shell Python failed to import jsonschema before N2S refresh. The existing OpenPI isolated environment imports jsonschema successfully without installation. Retrying refresh with its bin directory first in PATH succeeded: accepted upstream revision 45d167135c81d97573bfbe0e564bb4a1d9642514, latest unreviewed snapshot 6274aa8c3aae3a8b522528e496054a87ea80f3db. Accepted sources remain used for migration decisions.

Bare npu-smi exited 127 because libc_sec.so was not on the dynamic loader path. Sourcing the existing scripts/ascend_env.sh restored the query; all sixteen 910B2C devices reported healthy. Existing per-device Python processes belong to a keep-alive process. No process was stopped. A single visible device will be used for bounded validation; shared background load prevents an uncontended performance claim.

Current Python 3.12.14, torch 2.9.0+cpu, torch-npu 2.9.0, LeRobot 0.4.3, Transformers 4.53.2, datasets 4.8.5, NumPy 1.26.4, CPU JAX 0.5.3, MuJoCo 3.8.1. No new model runtime has yet been verified.
