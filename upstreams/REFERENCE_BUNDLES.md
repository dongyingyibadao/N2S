# 昇腾参考资料包与任务目录

`ascend-reference-20261005` 来自用户整理的 2026-10-05 资料包，主手册 revision 7。
登记于 [reference-bundles.json](reference-bundles.json)，N2S 编写的 27 条摘要见
[catalogs/ascend-reference-20261005.json](catalogs/ascend-reference-20261005.json)。
原来源为 [参考手册](https://sii-czxy.feishu.cn/docx/NwxrdHTD1ohfvSxm732cT2mUngb)，在线原文可能需要权限。

资料登记、原文缓存、检索结果与外部实现的关系，以及可逐步执行的 MOVA 深读实例，见
[从目录深入到实现](LINK_WALKTHROUGH.md)。资料包导入不会克隆其中链接的所有 Git 仓库。

## 按任务查阅

```bash
tooling/n2s-knowledge guide --task training --stage preparation --json
tooling/n2s-knowledge guide --task numerics --stage troubleshooting --json
tooling/n2s-knowledge guide --task performance --stage optimization --json
tooling/n2s-knowledge search "torchvision.io.video" --accepted-only --include-community --json
```

资料包摘要默认进入 `search`；`--include-community` 另外加入 LeRobot/OpenPI 精选源码。
`--accepted-only` 约束官方 Git 版本，参考包保持自身 manifest SHA256，不会被标成已接纳官方
证据。`--task` / `--stage` 只筛选参考包内容，不隐藏按关键词匹配的官方全文。不同任务可查询多次。

| 任务 | 资料入口 | 必须核对的边界 |
|---|---|---|
| 环境、依赖、镜像 | R01/R02/R04/R13、D01/D02 | 镜像、版本、实际设备、shell 初始化；模板有系统/目录写入 |
| 训练、分布式 | R05/R06/R09/R11/R12/R14/R15、D03/D04 | 框架/权重/数据、BF16、HCCL、FSDP/ZeRO 路线；部分仅冒烟 |
| 具身推理、OM | R07/R08/R10 | 实现差异、310P/A2/A3、在线/离线/训练分别确认 |
| 显存、吞吐 | R16、O01/O02 | 固定状态与激活、周期采样与峰值、同设备测量 |
| 精度与换算 | N01、R03/R15、D04 | 版本、算子、图/量化/并行路径；预案和外部报告不等于 N2S 复现 |
| 仿真闭环、远程策略 | R18 | 策略与 CUDA 仿真/渲染分开，网络及归一化需端到端核对 |
| 数据、资产和历史资源 | R17/R20 | 当前存在性和权限；历史路径不是下载或实例运行授权 |

R01—R20 对应原手册入口，D01—D04 是错误路由，O01/O02 是优化路由，N01 是数值问题路由。
`references[]` 给出原文/附件 URI、SHA256、本地路径；`links[]` 给出实际仓库、目录、固定提交、
issue 或文档地址及资料包当时的读取状态。相关官方条目也给出 N2S 的 `snapshot_uri`。

## 本地原文与换机器

完整文档、群记录/JSON、15 张图、3 个原附件和相对链接在 ignored 只读缓存中，不随 N2S Git
push 传播。另一台机器仍能使用提交的摘要和在线链接；需要离线原文时，传输完整授权资料包，
再导入解压后的 `昇腾卡参考资料` 目录，不固定个人绝对路径：

```bash
tooling/n2s-knowledge import-bundle --source ascend-reference-20261005 --path /path/to/昇腾卡参考资料
tooling/n2s-knowledge status --json
tooling/n2s-knowledge show 'reference://ascend-reference-20261005@b83a696461745e01f8e44e8a2e672db9fdadca7d66b6e19d7eaaaac53b5081a8/附件/GLD Wan2.2训练管线昇腾适配结果-v1.md'
```

导入先核对已登记 manifest SHA256，再核对 61 个清单文件的字节数和 SHA256，连同 manifest
共缓存 62 个文件。保留原字节与通知，不执行 shell、Python 或 hook；文件不可执行且目录/文件
均只读。重复导入校验已有快照；哈希变化、路径逃逸或软链接会拒绝。搜索和打开也检查哈希。
`status` 明确报告 `available` / `not_imported` / `invalid`。

资料包 revision 为 manifest SHA256：
`b83a696461745e01f8e44e8a2e672db9fdadca7d66b6e19d7eaaaac53b5081a8`，不是 upstream commit。
新版资料应使用新的 source ID 登记哈希/目录，保留旧登记与引用，不覆盖旧快照。原资料的 Git 内容只有在线链接，
不能宣称这些仓库都已离线保存。

## 深入读取链接

```bash
tooling/n2s-knowledge follow https://raw.githubusercontent.com/OpenMOSS/MOVA/61e39c2e6e9b9047fb086112ab9bfae8d5b74182/ASCEND_SUPPORTS.md
```

`follow` 从目录中已登记的 HTTPS 文本链接出发，限制大小与超时，不启动网页脚本、安装程序或
远端代码。返回 `retrieved_unreviewed`、读取时间、原响应 SHA256、最终 URL 和正文；网络失败
返回 `unavailable`。它不保存网页、不修改规则，也不扩大 Git 镜像注册表。branch/root 网页不因
关联官方 snapshot 而得到该 commit 标签。返回的 `discovered_links` 列出正文实际出现的链接；
用 `follow CHILD_URL --from-url PARENT_URL` 验证父正文后继续访问。
需要多层链接或动态页面时，保留从已登记根链接出发的访问链，必要时使用自己的只读网络工具
深入访问并记录；HTTP 200、导航和登录页均不能填成“已确认解法”。

## 已知缺口

- `pi05/docs/BATCH_SIZE_20260909.md` 正文未取得；batch 表来自两卡 DDP BF16 短步截图，
  峰值采集方式缺失，未覆盖长期训练或 checkpoint，不证明通用最优 batch。
- GLD 的 8/16 卡两步、random transformer、mock 数据及 checkpoint 只支持该管线冒烟；
  真实权重/数据/精度仍待验证，DA3/torchvision/Conda 报错另有未闭环记录。
- Qwen3.5 0.8B 低吞吐、fastwam、跨区网络、RoboTwin 全 NPU 闭环没有最终成功证据。
- npu-smi 网页仅取得导航，参数依据截图；部分 Git 子目录仅取得概述/页面外壳。
- 删除消息不可恢复；部分配方标题与参数不一致，镜像/公共路径为历史信息。

可复用同范围的解释和证据来减少重复探索，新环境只补剩余差距。完整资料、个人信息、内部
路径、上游正文/patch/权重不默认随 case 发布。摘要均保持 `community_reference_bundle`、
`n2s_validation: not_verified`。三阶段操作见 [AGENT_USAGE.md](AGENT_USAGE.md)。
