#!/usr/bin/env python

"""Run LeRobot 0.4.3 evaluation with the LIBERO reset progression from 0.6.x."""

from functools import wraps

from lerobot.envs.libero import LiberoEnv


_original_reset = LiberoEnv.reset


@wraps(_original_reset)
def _aligned_reset(self: LiberoEnv, seed=None, **kwargs):
    init_state_id = int(self._init_state_id)
    result = _original_reset(self, seed=seed, **kwargs)
    if self.init_states and self._init_states is not None:
        print(
            "LIBERO_ALIGNED_INIT_STATE "
            f"task_id={self.task_id} init_state_id={init_state_id % len(self._init_states)} "
            f"reset_kind={'episode' if seed is not None else 'autoreset'} seed={seed}",
            flush=True,
        )
        if seed is not None:
            self._init_state_id = (init_state_id + 1) % len(self._init_states)
    return result


LiberoEnv.reset = _aligned_reset

from lerobot.scripts.lerobot_eval import eval_main  # noqa: E402


if __name__ == "__main__":
    eval_main()
