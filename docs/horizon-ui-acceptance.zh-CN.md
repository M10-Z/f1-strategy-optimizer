# 浏览器 horizon 与可用性门控验收

本次交付将离线目标门控接入现有浏览器，**v1 默认、v2 实验未通过**不变。没有新赛事取数、精度实验、参数选择、认证流或实盘接入。

## 用户可操作的功能

打开工作台后，在“明确选择目标与可用时钟”面板选择：

- 原目标“立即出站后的下一整圈”；
- 独立目标“确认后首个尚未开始的完整圈”。

原目标、候选圈与选中圈分别显示。缺少可信出口或覆盖确认时刻的未开始边界，就显示不可用，选中圈号/数值预测为空。不会自动换到后续圈。即使导入边界只通过结构检查，也明确显示未经外部核验、不提供数值预测。

时钟可选“历史近似：事件时间+假设延迟”，或“仅采用导入 received_at”。前者显示 `retrospective assumed availability`，保留缺失 received_at；后者缺接收时间就不纳入快照。界面显示来源、事件时间、接收时间、延迟假设和修订证据。导入只使用本地 JSON，不联网。

“导出所选目标与门控 JSON”可独立保存拒绝结果，无需模拟/揭晓。完整模拟导出同样保存当下所选 horizon、时钟依据和假设；目标门控不改变下方原有人工情景模拟。页面请求进行中或导入无效时禁止导出，切换时点/车手清除旧导入，避免错绑。

## 消息 JSON 的浏览器绑定

浏览器导入在通用 envelope 上额外要求：session_id 为当前 session_key 字符串；decision_sha256 匹配当前冻结记录；driver_id 匹配所选车手；required_streams 包含 `driver:<driver_id>:lap_state`。记录 payload 的 current_lap 只是来源声明。原即时目标若已由冻结前缀确定，导入不能改写；没有已知原目标时，导入 original_immediate_target_lap 仅作显式、未经核验声明。

通用 CLI 示例 `examples/observation-envelope.json` 没有绑定当前比赛，不能直接当作浏览器实测数据。新启动包内 `verification/synthetic-delayed-revision-input.json` 是绑定**巴林 2023、16:13 UTC、Leclerc**的合成场景。选择该时点、车手与“仅采用导入 received_at”，导入后可见 revision=0，cutoff 后 30 秒的 revision=1 只留在审计记录中。页面显式显示“合成延迟/修订场景”，不声称捕获实时数据。

导出重放命令同时支持门控和完整模拟：

```sh
python -m f1_strategy_optimizer.workbench_replay path/to/download.json
```

重放检查整个记录哈希、冻结前缀和门控源码哈希，再从所选 horizon、原始消息和时钟假设重算，必须精确一致。完整模拟还复核假设/引擎版本并重算原模拟。揭晓及事后来源审计不进入这些计算。

## 实际验收

通过 Playwright 驱动真实 Chromium，使用包内现有三份巴林缓存和明确合成的延迟/修订消息；未改原预测或事实结果。验证脚本为 `scripts/verify_horizon_browser.py`。

| 验收项 | 结果 |
|---|---|
| 原即时目标、独立后续目标切换 | 原目标保留，缺边界保持不可用 |
| 当前归档切到仅 received_at | 无接收时间，快照为空，不补值 |
| 合成晚到修订 | revision=0 可见；晚到 revision=1 未进入快照 |
| 错绑车手 JSON | 拒绝导入/导出；恢复归档后可继续操作 |
| 四份实际门控下载 | 独立 Python 进程均为 exact_match |
| 一份带 horizon 的实际模拟下载 | 模拟及目标门控均 exact_match，56 次原场景 rollout |
| 主动揭晓请求 | 0；独立目标导出不读取结果文件 |
| 浏览器错误 | 0 |
| 390px 窄屏 | scrollWidth=innerWidth=390 |
| 全部回归 | 317 项通过，31 条既有 NumPy/pandas 警告 |

结构化证据在 `docs/horizon-ui-evidence.json`；原始下载和测试 XML 在 `output/horizon-browser/`。新启动包纳入代码、最新 wheel、中文启动说明、现有三时点缓存、报告及 verification 下载/合成输入。新包版本标签为 **horizon-ui-20261017**，精确源码提交及所有文件哈希在 MANIFEST.json。旧启动包与 Library 附件保留。

## 下一阶段前提

当前没有可信逐消息/逐修订实时 received_at、出口语义或同步圈边界，也没有实盘预测。必须由用户或获授权提供方补充采集时钟/漏包/重连证据、行动边界与同步状态，再进行接入验证。_id/_key 不能补造发布时间。本轮到此停止模型迭代，不通过追加 holdout 或调参替代这些前提。代码仅本地提交和 Library 备份，不推送远端、不合并 main。
