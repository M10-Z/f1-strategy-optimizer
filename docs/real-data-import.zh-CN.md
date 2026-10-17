# 真实赛事缓存与清洗 CSV 导入

[English](real-data-import.md)

以下路径不需要新增网络权限。请保存来源/提供者、赛事/场次、获取日期、版本、清洗步骤
和原始文件哈希；文件名本身不能证明数据真实。程序记录 CSV 原始字节与规范化数据哈希，
但不会独立核实真实性，也不会自动读取旁附来源文件。

## 已有 FastF1 缓存

将可信来源的**完整缓存目录**复制到可写目录并保留结构，不要仅复制单场 pickle。
适配器使用 FastF1 3.8.x 兼容元数据，加载圈速、天气和赛会消息；删除圈标记未知会失败。
仅有部分文件的旧缓存不一定可用，不能自动联网补齐。含巴林 2022–2024 的缓存可运行：

```sh
f1-strategy backtest --track Bahrain --start 2022 --end 2024 --holdout-year 2024 \
  --offline --cache-dir /path/to/trusted-cache --output-dir output/trusted-bahrain-validation
```

只用更早年份训练；缓存缺失会明确失败。检查已加载/失败年份和评估覆盖，部分成功不等于
完整验证。缓存及生成结果不提交 Git。

## 已清洗、规范化 CSV

| 字段 | 最小校验 |
|---|---|
| `Year`、`LapNumber`、`TyreLife`、`Stint` | 有限正整数 |
| `LapTimeSeconds` | 有限正数，单位秒，不能是时间格式字符串 |
| `Driver` | 非空车手标识，自动去除两侧空格 |
| `Compound` | SOFT/MEDIUM/HARD，规范化空格和大小写 |
| `Event`（建议） | 同一非空赛事/赛道，提供时会规范化 |
| `TrackTemp`（可选） | 保留元数据；当前拟合/留出验证使用参考温度 |

拒绝空表和重复年份/赛事/车手/圈号。本轮修复了车手标识两侧空格可绕过重复检查，以及
空白赛事名未被拒绝的问题。只检查字段、不拟合也不下载：

```python
import pandas as pd
from f1_strategy_optimizer.models import validate_laps
laps = validate_laps(pd.read_csv("/path/to/cleaned-laps.csv"))
print(len(laps), sorted(laps.Year.unique()))
```

原始 FastF1 表应先通过 `clean_session_laps`，需要计时、配方、赛段、车手、进出站、
准确性、赛道状态及已知删除标记。清洗 CSV 路径信任提供者的清洗，不会恢复被排除的圈或
独立证明标记；应记录真实清洗过程，不能编造标记。每个文件仅拟合一个赛事。

```sh
f1-strategy backtest --csv /path/to/cleaned-laps.csv --holdout-year 2024 \
  --output-dir output/trusted-csv-validation
```

至少需要一个更早训练年份和非空留出年份，并有足够样本及胎龄变化才能拟合相应配方。
字段有效不保证模型可用；检查覆盖、误差和仅训练集计算的基线比较。

## 进入名次验证的最小条件

上述 CSV 已删除进站/非绿旗圈，单独不能验证多车策略。至少提供一个可信比赛片段，包含
带时间戳的同圈全场顺序/间距、配方/胎龄、实际进出站或进站边界、车队、可见赛道/天气
状态，并把后续真实结果单独保存。注明赛季、赛事、总圈数、决策边界、来源及观测可用时点。
若要声称库存/规则可行，还需库存/已用轮胎和适用赛事规则证据；未知库存不能猜造。

已有 JSON 可表达观测快照，但车辆速度、轮胎曲线、进站损失和情景权重仍须**独立标注
假设**。公开圈速受燃油、交通和车手行为混杂。[规范化回放适配器](replay.zh-CN.md)现已可用；
原始缓存自动重建/对齐仍需来源适配。取得数据后先测量已有转移模型误差，不能把后来发生的 SC/天气
或对手行动提前输入决策。一段数据可做冒烟验证，不足以可靠校准概率；推广精度结论需
更多留出比赛。

[计时域名访问仍受阻](real-validation-2026-10-17.zh-CN.md)。本轮没有导入或评估真实数据。

后续新实例已取得另一批真实归档，见[来源校验与事件时间观测基准](event-replay.zh-CN.md)。
这些原始响应仍不能直接当作已清洗 CSV 或完整行动匹配策略输入，需满足各自的额外证据契约。
