# Launcher shell initialization

The new wrapper initially enabled nounset before sourcing CANN and emitted unbound variable messages for LD_LIBRARY_PATH and CMAKE_PREFIX_PATH. An error-specific N2S search found accepted Isaac-GR00T set_conda_env.sh, which temporarily disables nounset while sourcing vendor shell setup. Full file was read as data, never executed. This is analogous shell initialization, not model evidence.

The target wrapper now enables nounset only after sourcing existing ascend_env.sh. Re-running launcher help produced the expected usage and no unbound-variable diagnostics; bash -n passed. Python sources separately passed Ruff; an initial accidental Ruff invocation on the shell file was a verification-command mistake, not a target syntax failure.
