# 2024 整场留出验证：三场真实来源与透明技术勘误

三场赛事沿用预先固定的圈时前缀中位数与间距保持法。每场 20 名注册车手，按赛历起跑 UTC 后 +600 至 +7200 秒、每 300 秒取样，共 23 个截止点；每类指标的固定分母为每场 460、合计 1380。没有按误差重选车手、截止点、赛事或预测方法。

**执行限定：发生两次透明适配技术勘误。** 两次勘误时摩纳哥和意大利已经评分；英国国家别名勘误在英国结果请求之前提交，可选进站审计空时长勘误在原始数据获取之后、英国首次预测误差计算之前提交。原始拒选版与只修正别名的拒绝版均完整保留。本次不能称为未经修正的严格三场盲测执行。

## 既定默认的真实结果

| Event | Drivers | Lap scored/all | Median lap MAE (s) | Gap scored/all | Persistence MAE (s) |
|---|---:|---:|---:|---:|---:|
| Monaco Grand Prix | 20 | 213/460 | 1.037347 | 190/460 | 1.433716 |
| British Grand Prix | 20 | 276/460 | 5.074451 | 218/460 | 2.043459 |
| Italian Grand Prix | 20 | 259/460 | 1.790237 | 213/460 | 2.392629 |

等赛事平均圈时 MAE：**2.634012 秒**；覆盖 **748/1380，54.20%**。间距报告 MAE：**1.956601 秒**；覆盖 **621/1380，45.00%**。先逐赛事计算，再对三场等权平均；1380 个相关车手/截止点不是 1380 个独立试验。

同目标线性对照的等赛事平均 MAE 为圈时 2.570596 秒、间距 1.560394 秒。固定圈时默认 MAE 2.634012 秒，高于线性 2.570596 秒及最近合格完成圈 2.165170 秒；间距保持默认 1.956601 秒，高于线性 1.560394 秒，误差越小越好。这些结果不会触发本版本改默认或重复使用该保留集调参。其他已冻结方法的逐场结果、同目标差值均见 JSON。

最终本地准备、冻结和评估耗时 **11.080 秒**。本批次全部 69 个 decision 先持久化，再开始本批次评分；文件 SHA-256：`562508a0ddd4c203ada1a6a65ad752ca1b4291ac186e1299a8f06fcc93f1949d`。decision 外层及 state 内层 partition 在冻结前改为 holdout 并重算哈希，预测内核保持不变。

## 冻结与技术勘误证据链

原严格版仅 2/3 场可评分，国家别名修正版也仅 2/3；两版完整三赛事平均 MAE 均保留 null。最终技术勘误版才为 3/3；原有两场部分平均值从未冒称三场结果。

- 候选模型：`d466efa50375a28d05795d46740c89e6dcf80e8a`。
- 获取前冻结：`8d7926c32d1ffe31a7e9d1a15c48a2baba7eb7e7`。绑定原锁哈希、16 份源码/测试哈希、默认 policy、取样与评分；此时尚未请求任何 holdout 数据。
- 国家别名勘误：`358345f1eea44700b7728fb93fdb2523fe356576`。已保存 metadata 中，Silverstone session 9558 / meeting 1240 的 country_name 为 United Kingdom，原适配器期待 Great Britain；起跑仍为 2024-07-07T14:00:00Z。这是身份适配拒选，不能称为英国服务或数据不可得。赛事、赛道、时间与 23 个 offsets 未变。
- 可选审计空值勘误：`32c8938a03b6a4d8afdca84bd566f8d81db8678f`。已哈希的 Jolpica Tsunoda 第 27 圈第 1 次进站 duration 原值为 ""，原值保留，归一秒数为 null；不补零、不猜测、不丢行。原分页、哈希、URL、身份与重复键检查照常执行，进站审计不进入观测预测。
- 三版均保留：output/whole-race-holdout/original、corrected、final。
- 最终版摩纳哥及意大利的 decision、预测、评分、summary 和来源清单与原版逐项完全一致。技术纠错固定采用 final，与成绩高低无关。

## 来源完整性与剩余缺口

| Event | Accepted OpenF1 laps | Null durations | Accepted stints | Interval updates | Position updates | Quarantined rows |
|---|---:|---:|---:|---:|---:|---:|
| Monaco Grand Prix | 1237 | 20 | 39 | 23976 | 127 | 4 |
| British Grand Prix | 961 | 2 | 64 | 22499 | 252 | 2 |
| Italian Grand Prix | 1009 | 1 | 50 | 20444 | 482 | 0 |

共保存 **66 次普通 GET** 的原始 body、headers 与 meta，HTTP/CONNECT 均为 200/200，响应合计 11,557,408 字节。逐份核验 SHA-256 与字节数；未重试、未换域名、未改认证，也未在第二勘误后继续联网。

- 历史身份使用当场 Results.number 加规范化姓名 token 核验，每场 20/20；不用当前 permanentNumber。未来完赛名次、状态与耗时不进入 driver features。
- Jolpica 圈时与进站仅为独立赛后审计。来源差异保留在 source_audit；不混合首圈定义、不据审计结果筛选评分目标。
- 摩纳哥隔离 4 条无效/未知起始圈的 stint；英国隔离 1 条未知 date_start 的 lap 和 1 条无效 stint 起始圈。原记录保留，不造时间戳或轮胎赛段。
- 已接纳 OpenF1 圈记录中的 null 圈时分别为 20、2、1；不计为完成真实圈时或零秒。
- 原始目录：/workspace/real-data/holdout-2024-{metadata,monaco,british,italian}。完整 HTTP 凭据、逐页 offset/count/total 与哈希见 JSON。

## 固定分母下的全部排除原因

### Monaco Grand Prix

- Lap: `{"insufficient_prefix_laps": 236, "target_already_started": 11}`
- Gap: `{"insufficient_or_stale_numeric_interval_prefix": 262, "stale_interval_outcome": 7, "invalid_or_null_interval_outcome": 1}`

### British Grand Prix

- Lap: `{"insufficient_prefix_laps": 23, "target_already_started": 12, "target_duration_unknown": 1, "target_missing_no_retirement_inference": 148}`
- Gap: `{"insufficient_or_stale_numeric_interval_prefix": 228, "invalid_or_null_interval_outcome": 3, "stale_interval_outcome": 11}`

### Italian Grand Prix

- Lap: `{"target_already_started": 8, "target_missing_no_retirement_inference": 193}`
- Gap: `{"stale_interval_outcome": 5, "insufficient_or_stale_numeric_interval_prefix": 238, "invalid_or_null_interval_outcome": 4}`

## 能说明的范围

本次仅验证无条件未来完整圈时与固定 90 秒之后的新鲜异步间距报告。它不证明同步实测车距、历史在线发布时间、概率校准、真实进站行动边界、库存与完整规则可行性或策略因果收益。策略评分仍为 **0**，策略指标为 **null**。未来雨、赛会控制与进站圈不按结果事后删除；缺失、套圈字符串、过期报告和未完成目标均按原规则计入排除原因。只有三场整场保留赛事，不能把相关的逐车逐时点样本当作大量独立试验。若后续调参，须另保留新的整场测试集。

## 交付与本地复算

- [Model/policy/source freeze](../examples/holdout-evaluation-freeze.json)
- [British metadata identity erratum](../examples/holdout-identity-erratum.json)
- [Nullable optional pit-audit erratum](../examples/holdout-audit-erratum.json)
- [Durable report, counts, SHA-256 and HTTP receipts](holdout-validation.json)
- [Full local final report](../output/whole-race-holdout/final/evaluation.json)
- [All 69 frozen decisions](../output/whole-race-holdout/final/decisions.json)

复算须保留原两版输出与原始缓存；它们的哈希已进入勘误清单。使用新的输出目录，下列命令只读本地资料，不联网。

```sh
python -m f1_strategy_optimizer.holdout_audit_erratum \
  --data-root /workspace/real-data \
  --output-dir output/whole-race-holdout/reproduction-new-directory \
  --manifest examples/holdout-audit-erratum.json \
  --audit-commit 32c8938a03b6a4d8afdca84bd566f8d81db8678f
```

各阶段冻结时的针对性检查（均在英国首次误差评分前完成）：16 项适配器/冻结合成测试、7 项 metadata 别名测试、6 项可选审计测试通过，Ruff 通过；完整集成回归由主线程统一执行。
