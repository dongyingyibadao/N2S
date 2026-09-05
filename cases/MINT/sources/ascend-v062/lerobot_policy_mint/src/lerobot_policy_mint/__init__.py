#!/usr/bin/env python

import os

try:
    import lerobot
except ImportError as exc:
    raise ImportError(
        "lerobot is not installed. Please install lerobot to use the MINT policy package."
    ) from exc

from .configuration_mint import MINTConfig
from .modeling_mint import MINTPolicy
from .processor_mint import MINTPrepareStateTokenizerProcessorStep, make_mint_pre_post_processors


def _install_legacy_pi05_prompt_compatibility() -> None:
    """Restore the processor semantics used to train the public MINT checkpoint."""
    if os.environ.get("MINT_USE_CURRENT_PI05_STATE_PROMPT") == "1":
        return

    from lerobot.processor import ProcessorStepRegistry

    # The public artifact serializes the LeRobot v0.4.3 PI0.5 registry name.
    # That implementation padded LIBERO state from 8 to 32 dimensions before
    # tokenization. LeRobot 0.6 no longer pads in this step, changing the prompt.
    ProcessorStepRegistry._registry[  # noqa: SLF001
        "pi05_prepare_state_tokenizer_processor_step"
    ] = MINTPrepareStateTokenizerProcessorStep


_install_legacy_pi05_prompt_compatibility()

__all__ = [
    "MINTConfig",
    "MINTPolicy",
    "MINTPrepareStateTokenizerProcessorStep",
    "make_mint_pre_post_processors",
]
