import torch


class Model:
    def __init__(self, config):
        self.forward = self._forward
        if config.compile_model:
            torch.set_float32_matmul_precision("high")
            self.forward = torch.compile(self.forward, mode=config.compile_mode)

    def _forward(self, value):
        return value
