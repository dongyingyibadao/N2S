# Ascend 源码快照

| 快照 | 原始路径 | 内容 |
|---|---|---|
| `ascend-v043` | `/opt/ascend-vla/src/MINT-v043-ascend` | LeRobot 0.4.3 迁移源码与运行脚本 |
| `ascend-v062` | `/opt/ascend-vla/src/MINT` | LeRobot 0.6.2 实际部署源码与运行脚本 |

复制时排除了 `.git`、`__pycache__`、`*.pyc`/`*.pyo`、cache、data/dataset、output、video、
wandb，以及 `*.pt`、`*.pth`、`*.ckpt`、`*.safetensors` 和常见视频后缀。快照未包含权重、
数据集、输出或媒体。

每个快照补充：

- `LICENSE`：官方 `691a5e6` 的 MIT 许可证。
- `PROVENANCE.md`：来源、revision 和缺口说明。
- `environment.json`：本次实际软件/硬件环境。
- `PERMISSIONS.txt`：规范化后的相对路径与权限。
- `SHA256SUMS`：除清单自身外全部文件的 SHA256。

校验：

```bash
(cd N2S/cases/MINT/sources/ascend-v043 && sha256sum -c SHA256SUMS)
(cd N2S/cases/MINT/sources/ascend-v062 && sha256sum -c SHA256SUMS)
```

目录统一为 `0755`，普通文件为 `0644`，shell 脚本为 `0755`。清单固定的是 N2S 内快照，
不依赖 `/opt` 原路径继续存在。
