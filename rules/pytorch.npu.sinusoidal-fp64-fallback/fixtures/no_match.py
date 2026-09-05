import torch


def choose_parameter_dtype(target_dtype, device_type):
    if device_type == "mps" and target_dtype == torch.float64:
        return torch.float32
    return target_dtype
