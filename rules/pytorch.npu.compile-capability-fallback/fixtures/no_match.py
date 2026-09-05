import torch


def compile_required(model):
    return torch.compile(model)
