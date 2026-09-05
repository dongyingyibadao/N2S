import torch


def get_safe_dtype(dtype: torch.dtype, device: str | torch.device):
    if isinstance(device, torch.device):
        device = device.type
    if device == "mps" and dtype == torch.float64:
        return torch.float32
    return dtype
