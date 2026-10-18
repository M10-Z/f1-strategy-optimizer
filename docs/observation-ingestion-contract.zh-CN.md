# 观测接入契约与归档收尾

本轮只核实数据缺口、实现离线导入门控和归档；没有调参、新赛事取数或最终评估重跑。工作台仍使用 **v1 默认**。v2 保持 **实验未通过**：三场最终 MAE 恶化 2.60%、P95 恶化 32.34%，覆盖率提高不能抵销精度失败。旧启动包仍对应 `31c8b32387438650c25ae3bb38473ebefa19391e`；新模块没有写进旧附件。

## 已核实的接口边界

巴林 2023 保存回执的实际 URL 为 `https://api.openf1.org/v1/pit?session_key=7953`，HTTP/CONNECT 为 **404/200**，源响应正文 30 字节。路径已经是正确的单数 `/v1/pit`，本轮没有重试。摩纳哥 2024 同一路径 `session_key=9523` 已有 **200/200**、4160 字节缓存。这是特定归档请求的失败，不是整个 pit 接口不存在或历史链路整体阻塞。回执路径和哈希保存于 `output/observation-contract/pit-path-audit.json`。

[OpenF1 Pit 官方文档](https://openf1.org/docs/#pit) 列出 `date`、`lane_duration`；date 只定义为 UTC 时间，没有定义入口或出口，也没有 publish/received/first-available 字段。维修区总时长不等于净进站损失。FastF1 PitOutTime 在本项目至多是重建的出口事件时间近似，精度和消息可用时间必须独立验证，不能当作真正发布时间。

[OpenF1 live 认证文档](https://openf1.org/auth.html) 中 `_id` 用于消息排序，`_key` 用于识别同一对象的更新；二者都不是发布时间。不得把数字 ID 转换为接收时间，也不能假设订阅所见 ID 连续。认证流需要授权及本地采集 received_at。本轮没有创建账号、订阅、凭据或公共服务，也没有连接 live 流。官方文档核对日期为 2026-10-17。

## 下一阶段输入契约

| 字段 | 要求及缺失处理 |
|---|---|
| session_id、source、stream | 明确会话、提供方、端点/主题、对象和车手。不同来源不能共享 stream 键；不能混合会话。 |
| event_time | 带时区的事件时间，保留原字段、定义与精度。未知入口/出口语义继续未知；不能用下载时间替代。 |
| received_at | 采集器首次取得**该消息/该次修订**的本地 UTC 时间，在回调入口记录；另存单调时钟、采集器标识、时钟偏差/同步证据和原始消息摘要。归档下载时间不是历史首次接收时间。缺失为 null。 |
| 发布时间 | 提供方若有文档化发布字段，单独保存。本地 received_at 只能证明本采集器何时见到消息，不能证明提供方首次发布时刻。 |
| event_id、revision、sequence | 稳定对象键、修订和传输顺序分别保存。_key 可映射对象键；_id 原样存 source_message_id 并用于排序，不解析为时间。未知值为 null。只有明示的本地逐 stream 连续计数契约才把数值缺口判为丢消息。 |
| 修订/重传 | 追加保存，不覆盖旧值。cutoff 下只选当时已接收版本的最高 revision；晚到修订不能改写较早快照。冲突重复、身份漂移、混源同键拒绝。 |
| 同步快照 | 共同 cutoff 下检查所有显式 required_streams 的可用时间、事件年龄、跨流时间差、缺值和活动状态。不同车手的最近圈开始时间不自动组成同步车阵；不插值、不把缺车填成退赛。 |
| 行动边界 | 保存 decided_at、effective_at、进/出维修区的事件定义、证据引用及各自接收时间。计划未来生效与已观察完成分开；顺序检查不等于证明真实发生。 |
| 目标身份 | 保存原任务、显式选择的 horizon、确认 cutoff、目标圈号、开始边界证据和拒绝原因。界面和导出必须使用相同标签，不能悄悄换圈。 |

接收时钟早于事件时钟会被拒绝，等待明确时钟校准；系统不移动时间戳使其过关。来源授权、语义、车阵完整与真实实时能力仍需来源说明和可审计采集链。

新增 [有界本地原始接收记录组件](raw-receiver.zh-CN.md) 可在本地调用入口保存 UTC/单调时间、原始字节、时钟声明、连接缺口和修订键。没有时钟证据时保持 unknown；声明误差上界通过 received_at_uncertainty_seconds 进入保守可用性时间。该组件尚未连接任何真实流，不恢复旧档案接收时间，也不解除现有目标限制。

## 可运行的离线校验

`src/f1_strategy_optimizer/observation_import.py` 是独立暂存入口，没有修改冻结预测器、评分器或工作台默认模型。`examples/observation-envelope.json` 是合成示例，包含 null 接收时间、null 正文和晚到修订。

```sh
python -m f1_strategy_optimizer.observation_import examples/observation-envelope.json \
  --output output/my-import.json --cutoff 2024-01-01T00:00:15Z \
  --mode historical_approximation --assumed-delay-seconds 3 \
  --horizon first_unstarted_after_confirmation \
  --driver-stream demo/laps/16 --original-target-lap 5
```

默认 recorded_receipts 模式缺 received_at 就不纳入快照，标签为 `IMPORTED_RECEIPTS_NOT_VERIFIED_LIVE`。显式选择 historical_approximation 并提供延迟时，按 event_time+delay 产生 available_at，**保留 received_at=null**；标签为 `HISTORICAL_APPROXIMATION_NOT_LIVE`，horizon 导出另写 **`retrospective assumed availability`**。已有声明接收时间的记录仍按接收时间门控，不能被假设延迟提前。二者都保持 publication_time_verified=false、model_eligible=false；输出文件存在即拒绝覆盖。

snapshot_checks_passed 仅表示结构、可见性、年龄、时间差及明示连续序号检查通过，不证明业务语义或来源可信；payload 内字段仍需专用适配器校验。records 区保留不可见修订供审计，下游只能消费 snapshot。本轮没有自动传给预测器。

## 显式选择不同 horizon

浏览器工作台已并列提供以下选择，命令行与 JSON 导出同样保存所选 horizon。新增独立门控导出无需完成模拟；完整模拟导出也记录所选目标、时钟和假设。详见 [浏览器验收](horizon-ui-acceptance.zh-CN.md)。

1. `immediate_post_pit`：原“立即出站后的紧接下一整圈”。保存 original_immediate_target_lap，当前始终拒绝；补到 pit 历史记录也不解除限制。
2. `first_unstarted_after_confirmation`：用户另选“确认时刻之后首个尚未开始的完整圈”。保存 confirmation_at、原圈号和新的候选/选中圈号。它是不同 horizon，不能将结果称为即时下一圈。

第二种选择从可见 lap_state 提出 candidate_target_lap=current_lap+1，但延迟的最新圈开始消息不足以证明该圈尚未开始。缺少覆盖确认 cutoff 的 not_started_through 边界声明时，selected_target_lap 仍为 null。声明不能覆盖其观测时间之后，旧声明也会拒绝。即使外部/合成声明满足结构检查，选出圈号后仍无数值预测、模型资格或真实性保证；下一阶段必须验证来源和行动边界才能接入预测。已有 v2 stay 输出不能自动改名为这一任务的预测。

## 有界门控证据

`scripts/audit_observation_import.py` 只读取四场已有开发前缀：巴林 3、其余各 23 个时点，全部 20 位登记车手，共 **72 个时点 / 1440 个槽位**。没有读取比利时或三场最终赛事的观测/误差，没有调用预测/评分函数。固定四种情形，没有参数搜索：

| 情形 | 可见槽位 | 缺失槽位 | 解释 |
|---|---:|---:|---|
| 无 received_at、默认模式 | 0 | 1440 | 未捏造历史接收时间 |
| 明示假设延迟 3 秒 | 1300 | 140 | 摩纳哥部分前缀尚无可用圈开始状态 |
| 合成接收延迟 30 秒 | 1044 | 396 | 模拟延迟导致更少状态可见 |
| 上一情形加入 cutoff 后 30 秒修订 | 1044 | 396 | 晚到修订没有进入较早 snapshot |

注入接收时间全部是**模拟**。各情形都没有通过全体车手共同快照检查：输入只是异步最近圈开始事件，存在缺失、陈旧或时间差；不能据此声称源完全不可用，也不能放宽阈值包装成同步全场。

晚到修订泄漏、即时目标解锁、无边界证据选中后续 horizon 均为 **0**。最终代码的完整计数和输入哈希保存于 `output/observation-contract/final-gates/development-gates.json`；初次门控产物亦保留。回归 **314 项通过**（含新增 11 项），31 条既有 NumPy/pandas 警告；新代码 Ruff 通过。测试覆盖缺值、错误时钟、冲突修订、乱序接收、晚到更新、撤销旧值、序列缺口、混源、陈旧、时间差及显式 horizon 门控。

## 当前可实践范围与阻塞

| 已可实践 | 范围/限制 |
|---|---|
| 本地浏览器工作台、历史快照、人工场景、方案比较和导出 | v1 默认；依赖明确假设，模拟排序不是因果收益。 |
| 四场开发分析及封存评估档案 | v2 为失败实验，不能宣传为精度升级。 |
| 离线 receipt-envelope 导入 | 浏览器可导入 JSON 并检查缺值、延迟和修订；未连接预测器或实时流。 |
| 后续完整圈 horizon 契约/导出 | 可显式请求并审计候选圈号；缺未开始边界继续拒绝数值预测。 |

仍需用户或获授权提供方交付可信逐消息/逐修订 received_at、采集器时钟和重连/漏包记录、出口语义，以及覆盖确认时刻的同步活动/圈边界状态；策略模拟还需库存、车阵和行动生效边界。现有历史缓存无法逆向恢复首次可用时间。应先补证据再接入，不再通过新 holdout 或调参掩盖采集限制。

本轮代码、测试、文档和结果以新提交及完整恢复包备份 Library；旧启动包身份不变。Library 保存代码快照/Git 历史，不等于 Git 远端已推送、main 已合并或软件已部署。精确附件 ID、SHA256 和提交号见交付回执。
