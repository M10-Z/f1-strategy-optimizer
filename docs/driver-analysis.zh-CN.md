# 赛道、车队与车手分析

[English](driver-analysis.md)

独立入口与主命令行共用数据适配器、分组轮胎模型和动态规划求解器。安装后也可使用 `f1-driver-analysis`。`--offline` 只读现有 FastF1 缓存；`f1-menu` 提供中英文交互填写和数据模式选择。

## 快速开始

```sh
python -m pip install -e ".[data]"
python -m f1_strategy_optimizer.driver_analysis --track Bahrain --team Ferrari --driver LEC
```

历史复盘只要求赛道、车队和车手。未指定年份时，按由近到远的顺序搜索最近三个日历年，选择计划开赛时间至少已过去六小时的匹配赛事；实际计时数据仍必须成功加载。解析后的年份、赛事、车手和车队会打印并保存。

赛道可用赛历中的完整赛事名、地点或国家，忽略大小写和标点；存在歧义时失败。车手可用全名、缩写或车号。车队必须与出场名单一致，不猜测转会和年份不匹配的情况。名称使用 FastF1 英文名称，目前没有中文别名或图形选择器。

```sh
python -m f1_strategy_optimizer.driver_analysis --track Bahrain --team Ferrari --driver "Charles Leclerc" --year 2025 --history-years 3 --output-dir output/leclerc-bahrain-2025
```

默认只拟合所选车手在所选车队的数据。每种配方至少需要六个清洗后圈，并有足够组内胎龄变化；这是数值筛选阈值，不保证统计可信度。至少两种干地配方拟合成功才能继续。数据不足时可扩展历史范围，或显式允许扩大数据来源：

```sh
python -m f1_strategy_optimizer.driver_analysis --track Bahrain --team Ferrari --driver LEC --year 2025 --fallback team
```

`--fallback team` 对缺失配方尝试同队数据；`--fallback field` 进一步允许全场数据。来源记录实际车手、车队、年份和样本量。默认不会隐式扩大来源。

## 预测模式

```sh
python -m f1_strategy_optimizer.driver_analysis --track Bahrain --team Ferrari --driver LEC --year 2025 --mode predict --laps 57
```

预测不加载目标正赛结果，也不使用目标年正赛圈训练。它用目标赛事已完成 FP1 的出场名单核验身份，并要求显式填写计划圈数。FP1 数据尚不可用时会失败，不猜测名单。`--history-years 3` 包含目标年，因此预测最多使用此前两个赛季。今天运行历史预测只是结构性的时间切分，不能证明所有数据版本在当时已经可用。

## 输出和边界

每次默认在 `output/` 创建唯一目录，也可指定 `--output-dir`。非空目标目录会被拒绝，文本输出为 UTF-8。

- `driver-analysis.md`：身份、策略、来源与限制。
- `driver-analysis.json`：完整参数、来源层级、跳过年份和实际赛段。
- `analysis-laps.csv`：清洗后的历史候选数据池；来源记录说明实际拟合子集，JSON 记录 SHA-256。
- `driver-model.png`：原始拟合形状和优化器使用的有效曲线。
- `driver-strategies.png`：起始胎、进站损失、温度、衰减先验及已知低进站损失情景。它们是独立假设，不是未来安全车事件概率。

历史数据足够时，复盘还会用严格更早年份训练独立模型，报告目标车手每种配方的留出 MAE/RMSE。这是圈速验证，不是不同策略能够取胜的证据。历史不足会明确报告，不用训练分数代替。

历史圈数默认取记录中的最大比赛圈，缩短赛事时可能不同于计划圈数。进站损失默认是可配置的 24 秒先验，不是自动测得的赛事值；用 `--pit-loss` 修改。温度使用模型的 35°C 参考值，不是测量或预报。

实际赛段来自未清洗圈数据。未完赛、被套圈、缺圈、旧胎起步、不支持的配方或无效约束会阻止不加限定的模型比较。可评估时，每次赛段转移都按进站收费；红旗换胎可能不符合该假设。时间差是模型中的假想差异，不是已证实的真实收益。

优化器假定干地新胎无限供应，只执行简化约束；不实现完整 FIA 规则、交通、超车、实时赛会控制或不确定天气。复盘包含目标赛事，不应称为赛前预测。底层 CLI 帮助、引擎日志及生成报告中的技术字段目前主要使用英文；仓库使用说明和终端交互提供中英文。

## 测试

```sh
python -m pytest tests/test_driver_analysis.py
```

覆盖身份、转会、歧义、显式来源扩展、未完赛、UTF-8 输出、最近年份选择和预测时排除目标正赛。
