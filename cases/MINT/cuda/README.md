# CUDA operator/block A/B validation bundle

This bundle captures fixed-input CUDA controls for the three candidate rules. It runs only local operator/block
A/B checks for cache dtype alignment, compile versus eager fallback, and sinusoidal FP64 versus FP32. It does not
instantiate a MINT/LeRobot model, load model parameters or checkpoints, run inference, or train. The bundle records
results only; it does not approve a rule or apply a threshold.

## Host requirements

- Linux x86_64 NVIDIA host with one visible Ampere-or-newer GPU and a driver compatible with CUDA 12.8.
- 4 GiB free device memory is a practical floor; 8 GiB or more is recommended for compile workspace headroom.
- Python 3.12, `venv`, `sha256sum`, and network access to the pinned PyTorch index and PyPI.
- About 10 GiB free disk for the private environment and package downloads. No model, checkpoint, or dataset is
  required.
- Allow roughly 15-30 minutes on the first run for dependency installation and Triton compilation. The measured
  blocks themselves are small.

The bundle installs into a private `.venv`. PyTorch is pinned to `2.9.0` with CUDA 12.8, Triton to `3.5.0`, and
jsonschema to `4.26.0`. Preflight verifies these versions, CUDA availability, and the execution scope. The result
manifest explicitly records `model_execution: false` and `model_parameters_loaded: false`.

## Build and run

Build from N2S:

```bash
N2S/cases/MINT/build_cuda_bundle.sh
```

Transfer the `.tar.gz` and its `.sha256` to the same directory. On the NVIDIA host, verify the archive and execute
the validation as one command:

```bash
sha256sum -c n2s-cuda-block-validation.tar.gz.sha256 && tar -xzf n2s-cuda-block-validation.tar.gz && ./n2s-cuda-block/cuda/run_bundle.sh
```

The final line prints the newly created results directory. Bring that complete directory back to N2S. It contains
three result JSON files, required logs, `cuda_validation_manifest.json`, and a self-verifying `SHA256SUMS`. The
JSON records fixed inputs, baseline/candidate output deltas, raw timing samples, median, p95, and peak memory. No
manual interpretation is needed on the NVIDIA host.

For an already provisioned, exactly pinned environment, set `N2S_SKIP_INSTALL=1` and `N2S_PYTHON` before the same
command. Preflight still rejects dependency version, CUDA runtime, or GPU availability drift.
