# 首次发布审阅：2026-11-12

整理已有 PI0.5 独立可抢占 worker 管线的组件和短程证据，没有运行新实验。
保留 `open / pending_validation`：源码漂移、严格梯度不一致、确定性布局错误仍未全部闭环，
完整 32 卡 500 更新、最终正确性与端到端同设备提速验收未完成。

梯度 D2H、精确 native wire、固定顺序 reducer 预读及 owned RAM 的证据值得复用，
但分别属于单卡组件、CPU 编码或共享文件系统测量，不能合并成整模型速度结论。
来源比较及进一步验证方向见 [OPTIMIZATION_REVIEW_20261112.md](OPTIMIZATION_REVIEW_20261112.md)。

本目录证据文件没有发现需要替换的私有路径或凭据，发布副本原字节保留；
[发布溯源表](publication-provenance-20261112.json) 保存原始/发布 SHA256。
原件另有 ignored 本地归档；此后追加的新审阅单独记录，未改写历史事件。
既有 source-review 是来源声明、对照和哈希，未分发上游源码正文或 patch。
