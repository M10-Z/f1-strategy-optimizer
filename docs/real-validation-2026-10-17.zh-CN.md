# 真实数据验证尝试 — 2026-10-17

[English](real-validation-2026-10-17.md)

状态：**尚未取得真实圈速，验证受阻**。没有测得真实 MAE、基线改进、完赛名次精度或
校准事件概率，不把合成回归测试当作真实效果。

获取范围限定巴林正赛 2022–2024 年，计划用 2022–2023 年训练、2024 年留出。
开始时没有赛事缓存。FastF1 3.8.3 在 2022 年因 `DataNotLoadedError` 停止，
之后未下载 2023–2024 年场次。小型端点探测确认计时主源 `livetiming.formula1.com`、
内置镜像 `livetiming-mirror.fastf1.dev` 及已有 Jolpica 来源 `api.jolpi.ca`
均返回 `ProxyError: Tunnel connection failed: 403 Forbidden`。
GitHub 上的 FastF1 日历返回 HTTP 200，但不含圈速观测。另检查了一个公开的
[FastF1 衍生数据集](https://data.mendeley.com/datasets/djr8rnjtjp/1)，网页元数据可读，
下载 API 仍被环境代理拒绝，未取得或使用其数据。本地机器可读记录在
`output/real-validation-discovery/attempt.json`，不纳入 Git。

源码核查发现独立正确性缺陷：两个适配器都关闭赛会消息加载，但 FastF1 依靠这些消息
生成删除圈标记，参见 [FastF1 3.8.3 源码](https://github.com/theOehrly/Fast-F1/blob/v3.8.3/fastf1/core.py)。
现已启用消息加载，并对缺失/未知标记报错，补充回归测试。清洗记录可重叠的元数据排除
原因和之后的数值异常排除数。圈速回测增加仅训练集计算的分配方中位数基线，比较相同
留出样本；这些软件测试使用合成数据，并非真实效果验证。

产品目标随后调整为名次导向的多车策略规划。圈速误差继续作为组件检查，不再是最终
目标。恢复数据访问后，需要冻结每个决策点当时可见的信息，仅用此前观测估计车速，
明确交通/燃油混杂，再回放独立赛事片段。评估名次分布校准、针对明确对手策略的实际
名次/遗憾、进站响应及交通误差；历史完赛结果不能证明未发生策略的因果收益。
未来天气、SC/VSC 和对手行动不得作为历史决策时已知输入。

恢复限定范围组件检查的命令（使用新输出目录）：

```sh
python -m f1_strategy_optimizer backtest --track Bahrain --start 2022 --end 2024 \
  --holdout-year 2024 --cache-dir cache --output-dir output/bahrain-2024-real
```

需要环境允许一个可信计时来源，或提供含来源记录的本地缓存/规范化 CSV。
本轮未改变权限，未校准任何先验。
