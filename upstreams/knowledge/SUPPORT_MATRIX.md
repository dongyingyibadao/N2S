# Accepted official manipulation support matrix

Source: `cann-recipes-embodied-ai@45d167135c81d97573bfbe0e564bb4a1d9642514`.
Every row is `upstream_documented` and `not_verified` by N2S. Empty software cells mean the recipe does not
pin that component in the indexed source; they do not mean unrestricted compatibility.

| Model | Mode | Device | CANN | PyTorch / torch_npu | Framework revision | Official path |
| --- | --- | --- | --- | --- | --- | --- |
| PI0 | online inference | Atlas A2 | 8.3.RC1 | 2.1.0 / 2.1.0.post12 | LeRobot | `manipulation/pi0/infer_with_torch/README.md` |
| PI0 | OM inference | Ascend 310P | 8.0.0-8.2.RC1 | not pinned | LeRobot | `manipulation/pi0/infer_with_om/README.md` |
| PI0 | training | Atlas A2 | 8.3.0+ | platform wheels | LeRobot `58f70b6b...` | `manipulation/pi0/train/README.md` |
| PI0.5 | online inference | Ascend 310P | 8.2.RC1 | 2.5.1 / 2.5.1.post1 | LeRobot | `manipulation/pi05/infer_with_torch/README.md` |
| PI0.5 | OM inference | Ascend 310P | 8.0.0-8.2.RC1 | not pinned | LeRobot `58f70b6b...` | `manipulation/pi05/infer_with_om/README.md` |
| PI0.5 | training | Atlas A2 | 8.3.RC1 | not pinned / 2.8.0.post2 | LeRobot 0.4.4 `8fff0fde...` | `manipulation/pi05/train/README.md` |
| ACT | OM inference | Ascend 310P | 8.0.0-8.2.RC1 | not pinned | LeRobot | `manipulation/act/infer_with_om/README.md` |
| ACT | training | Atlas A2 | 8.3.0+ | platform wheels | LeRobot `58f70b6b...` | `manipulation/act/train/README.md` |
| SmolVLA | training | Atlas A2 | 8.3.0+ | platform wheels | LeRobot `58f70b6b...` | `manipulation/smolvla/train/README.md` |
| DiffusionPolicy | OM inference | Ascend 310P | 8.0.0-8.2.RC1 | not pinned | LeRobot | `manipulation/diffusion-policy/infer_with_om/README.md` |
| OpenVLA | OM inference | Ascend 310P | 8.0.0-8.2.RC1 | not pinned | OpenVLA | `manipulation/openvla/infer_with_om/README.md` |
| Isaac-GR00T N1.6 | online inference | Atlas A3 | 8.3.RC1 | 2.7.1 / 2.7.1 | Isaac-GR00T | `manipulation/Isaac-GR00T/README.md` |
| Spirit v1.5 | online inference | Ascend 310P | 8.3.RC1 | 2.7.1 / 2.7.1 | Spirit v1.5 | `manipulation/spirit-v1.5/infer_with_torch/README.md` |

The machine-readable catalog additionally records capabilities, known issues, performance measurement
contexts, and knowledge-only relationships to current N2S rules in `manipulation.json`.
