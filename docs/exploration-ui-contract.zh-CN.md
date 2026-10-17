# 预测与探索策略 UI 接口 v1

[English / 完整字段与命令](exploration-ui-contract.md)

本契约定义 Python/JSON 接口与离线示例；[本地网页工作台](workbench.zh-CN.md)已按以下边界实现。UI 分开调用：

| 操作 | API | 主要输出 |
|---|---|---|
| UTC 前缀与预测 | `event_replay.freeze_decision(archive, cutoff, policy=None)` | 带来源、时效和未知标记的 state；逐车 default_prediction；decision_sha256 |
| 显式假设探索 | `strategy_exploration.propose_exploration(frozen, assumptions)` | top3、独立 stay_out、逐字段覆盖、模型范围、行动边界、库存、邻车威胁、敏感性、冻结输入和预算 |
| 用户主动揭晓 | `event_replay.evaluate_frozen(frozen, archive)` | 事实观测误差和排除原因；严格策略评分仍为空 |
| 批量导出 | `event_replay.run_archive(...)` | 先持久化 decisions.json，再写含结果的 evaluation.json/md |

默认圈时使用前缀中位数，间距使用保持值，选择依据是此前巴林开发结果。当前可见赛段
中位数 context_median 作为实验对照：至少三个合格样本才使用，否则回退前缀中位数。
所有方法使用相同目标和覆盖口径；这些观测预测不识别轮胎或策略的因果收益。

UI 先只读取 decisions.json，展示未知、推断及陈旧字段，不自动填充。
探索时要求填写[完整假设示例](../examples/exploration-assumptions.json)，逐项展示原值、来源、
假设值和理由。示例只建模 20 车中的 4 车、从第 8 圈至第 14 圈，速度和物理参数均为手工
示意假设。`expected_finish_position` 必须显示为“模型终点名次”，且仅在所声明车阵内有效。
情景权重不是校准概率；未知无限轮胎模型不代表真实库存可行。

top3 与 stay_out 分开展示，不可行 stay_out 保留原因。邻车威胁来自假设间距；交通字段是
“进站后首个完整圈代理”，不是精确出站位置。队友成本与同情景可行 stay_out 对照，没有
基线时为 null。敏感性展示胜出方案是否改变以及原方案在变化后的排名；有限扰动未翻转
不等于稳健。揭晓结果需单独操作，不能把观测预测误差当作策略收益验证。

所有变体在任何模拟开始前共同计入预算并在内存冻结、计算哈希；CLI 在模拟结束后写
exploration.json、resolved-inputs.json 和 exploration.md，并非运行前持久化。假设文档是
事后研究者声明，历史可用时间未知；历史 cutoff 不表示假设当时已发布。真实进站行动
边界仍未核实。导出时保留原冻结决策、假设、模拟结果、解析后输入及全部哈希。

限制：最多 30 个模型圈、30 车、8 情景、500 候选、2 次未来停站、5 个单参数敏感性；
全部变体最多 10,000 rollouts。部分车阵必须显式确认；库存必须是有限字典或明确确认未知。
验证错误及无可行方案 CLI 返回 2；已有输出目录不覆盖。Python 参数错误一般为 ValueError，
结构损坏也可能为 TypeError/KeyError。

整场留出见[预注册文件](../examples/whole-race-holdout-lock.json)，本轮没有读取这些比赛结果。
新增巴林固定五分钟时点仍是开发集，部分时点与既有开发重叠。事后进站/控制状态分组
只解释误差，不进入特征，也不移除困难样本。完整命令和字段说明见英文版。
