# 工具状态

只有完成对应副作用 A/B 的工具才能进入案例工具清单。发现可执行文件不等于验证通过。

| 工具 | 当前状态 | 已完成 | 仍需完成 |
|---|---|---|---|
| `npu-smi` | `exploratory_validated` | 字段、权限、退出码和多次采集耗时由 NPU 入口记录 | 长时采集扰动 A/B |
| `msprof` | `available_unvalidated` 或 `not_available` | 入口记录是否可发现 | profiler 开/关同设备耗时与显存 A/B |
| `msaccucmp` | `available_unvalidated` 或 `not_available` | 入口记录是否可发现 | 最小算子 dump 与数值比较闭环 |
| `torch_npu.contrib.transfer_to_npu` | `experimental` | 无 | 隔离子进程对显式 NPU 代码的功能、数值、性能和 monkey-patch 副作用 A/B；再做跨模型验证 |

工具原始检查结果位于 `evidence/npu/tool_checks.json`。未完成项不作为推荐工具写入通用指南。
