#!/usr/bin/env python

import json

import torch
import torch.nn.functional as F
import torch_npu  # noqa: F401


def main() -> None:
    if not torch.npu.is_available():
        raise RuntimeError("torch.npu is not available")
    torch.npu.set_device(0)
    device = torch.device("npu:0")

    image = torch.randn(2, 3, 32, 32, device=device, dtype=torch.bfloat16)
    area = F.interpolate(image, size=(16, 16), mode="area")
    bilinear = F.interpolate(image, size=(24, 24), mode="bilinear", align_corners=False)

    conv = torch.nn.Conv1d(32, 48, kernel_size=3, padding=1, device=device, dtype=torch.bfloat16)
    conv_out = conv(torch.randn(2, 32, 16, device=device, dtype=torch.bfloat16))

    embedding = torch.nn.Embedding(512, 32, device=device, dtype=torch.bfloat16)
    logits = torch.randn(2, 16, 512, device=device, dtype=torch.float32)
    indices = logits.argmax(dim=-1)
    embedded = embedding(indices)
    sampled = torch.multinomial(logits.softmax(dim=-1).reshape(-1, 512), num_samples=1)

    sorted_logits, sorted_indices = logits.sort(dim=-1)
    remove = sorted_logits.softmax(dim=-1).cumsum(dim=-1) <= 0.1
    scattered = remove.scatter(-1, sorted_indices, remove)
    masked = logits.masked_fill(scattered, -torch.inf)

    loss = area.float().square().mean()
    loss = loss + bilinear.float().square().mean() + conv_out.float().square().mean()
    finite_masked = masked.nan_to_num(nan=0.0, posinf=0.0, neginf=0.0)
    loss = loss + embedded.float().square().mean() + finite_masked.square().mean()
    loss.backward()
    torch.npu.synchronize()

    result = {
        "device": torch.npu.get_device_name(0),
        "area_shape": list(area.shape),
        "bilinear_shape": list(bilinear.shape),
        "conv1d_shape": list(conv_out.shape),
        "embedding_shape": list(embedded.shape),
        "multinomial_shape": list(sampled.shape),
        "finite_gradients": all(
            parameter.grad is not None and torch.isfinite(parameter.grad).all().item()
            for parameter in [conv.weight, embedding.weight]
        ),
    }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
