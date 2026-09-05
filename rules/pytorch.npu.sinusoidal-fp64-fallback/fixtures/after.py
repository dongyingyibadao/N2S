import torch


def get_safe_dtype(target_dtype, device_type):
    if device_type in {"mps", "npu"} and target_dtype == torch.float64:
        return torch.float32
    if device_type == "cpu" and target_dtype == torch.bfloat16:
        return torch.float32
    return target_dtype


def create_sinusoidal_pos_embedding(time, device):
    dtype = get_safe_dtype(torch.float64, device.type)
    return time.to(dtype=dtype)
