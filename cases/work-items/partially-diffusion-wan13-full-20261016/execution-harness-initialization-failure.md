# Execution A/B harness initialization failure

Recorded from the main agent's actual first trial on 2026-10-16. The diagnostic worker created its evidence directory under the future trainer output before calling the real trainer. The trainer deliberately refuses an existing output directory and raised `Shared output initialization failed: FileExistsError`. The failure occurred before model execution. It provides no model precision, gradient, memory or performance result.

The worker was corrected to create the evidence directory inside `install_capture`, after trainer output initialization. A new output suffix `-v2` is used for the rerun; failed output and logs are retained. The current script is `scripts/validate_wan13_full_execution.py`. Its corrected output ordering was read by the review agent. Actual repeated training results are still pending.

This is an experiment harness issue. The trainer's no-overwrite contract remains intact.
