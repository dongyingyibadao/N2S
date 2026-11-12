# 首次发布审阅：2026-11-12

本次归档已有 Wan1.3B 全训练容量、执行数值对照、冻结 mask cache、分布式启动与
checkpoint/恢复记录，没有重跑实验或审批通用规则；保留 `open / pending_validation`。

记录内的同 NPU 16-rank 固定输入对照支持所选 bounded reducer + exact mask cache 的局部
执行等价；短窗口耗时 12.806917→12.683932 s/update，约降低 0.9603%，无长期统计保证。
16-rank DDP 的数值差异仍未定位，采用回退配置不等于修复 DDP。
容量边缘 40 只通过短测、41 OOM，正式选择 32。恢复证据截至原采集的第 22 步，
不证明 3,000 步完成、跨 CUDA 等价或任务质量。

当前记录结构的 `workflow-check` 为 ready_for_review，仅表示记录覆盖，不能扩大上述边界。
原源码 revision 不可取得；`949abb74b523268f528beda228592a0e6fb793f8` 是独立本地归档 commit，
不是官方 revision，详见 [baseline-provenance.md](baseline-provenance.md)。

发布副本替换本机路径，原件完整保留在 ignored 本地归档；
[发布溯源表](publication-provenance-20261112.json) 记录原始/发布 SHA256 和变换。
反馈保留原 ID、时间和测量，证据哈希绑定发布副本；不随库分发源码、权重、数据与原始日志。
