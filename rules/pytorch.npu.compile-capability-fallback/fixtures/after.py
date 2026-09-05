import logging
import torch


class Model:
    def __init__(self, config):
        self.forward = self._forward
        if config.compile_model and not str(config.device).startswith("npu"):
            torch.set_float32_matmul_precision("high")
            self.forward = torch.compile(self.forward, mode=config.compile_mode)
        elif config.compile_model:
            logging.warning("torch.compile is disabled on Ascend NPU; using eager execution.")

    def _forward(self, value):
        return value
