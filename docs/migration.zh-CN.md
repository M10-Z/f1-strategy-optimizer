# 从课程原型迁移

[English](migration.md)

可安装包位于 `src/f1_strategy_optimizer/`。虚拟环境目录不是源码包。

```python
from data_engine import fetch_cycle_data
from degradation_model import fit_tyre_degradation
from dp_solver import solve

df = fetch_cycle_data(cache_dir="cache")
model = fit_tyre_degradation(df)
strategy = solve(total_laps=57, model=model)
```

- `fit_tyre_degradation` 返回 `TyreModel`，不写图、不设置全局模型。`get_expected_lap_time(..., model=model)` 必须显式传入模型。
- `dp_solver.solve` 保留旧参数名，但要求 `model=`。新包接口为 `solve(model, RaceConfig(...))`。
- 拟合数据必须包含 `Year`、`Driver`、`Stint`、`LapNumber`。旧导出缺少赛段元数据时应重新获取，不要编造分组标识。
- `python main.py` 默认运行离线演示。显式旧参数 `--track/--start/--end` 选择历史数据路径；新命令为 demo、optimize、backtest，交互界面为 menu。
- 不再整体屏蔽警告，不在导入时创建缓存，不猜测 C 编号映射，不隐式豁免雨战规则，也不自动覆盖输出。
- 旧课程报告总耗时不是当前回归目标；缺陷修复和建模假设变化可能合理地改变推荐策略。

迁移前建议在仓库之外备份旧报告及源码。个人演示材料不属于分发包。
