# 候选版本验证 — 2026-10-17

[English](validation.md)

## 可复现检查

```sh
python -m pytest -q -W error::FutureWarning
python -m ruff check .
python -m ruff format --check src tests main.py _compat.py data_engine.py degradation_model.py dp_solver.py environment.py
python -m build
```

最终本地测试在 Python 3.13 下通过 **95 项测试**，代码检查和格式检查通过。
覆盖小型比赛独立穷举、终点配方计数、胎龄限制、分组拟合、时间留出验证、数据校验、
车手身份、显式来源扩展、排除目标正赛、离线演示导出以及中英文终端。
终端测试包括返回修改、输入纠错、按需帮助、结果停留、中文显示宽度和真实进程启动。

源码分发包和 wheel 单独检查。wheel 冒烟测试使用源码目录之外的隔离 Python，
运行合成演示、情景比较和留出验证，并检查两种语言的菜单。

CI 配置覆盖 Windows/Linux 与 Python 3.10/3.13。远程结果见仓库 Actions 页面，
本地通过不代表所有远程任务已通过。

## 分发边界

首次上传使用审核后的源码快照，不包含旧开发 Git 历史。显式选择文件，排除虚拟环境、
缓存、下载的赛事数据、本地报告、演示材料、凭据和私人路径。提交元数据使用 GitHub
no-reply 邮箱。示例图片只包含合成数据。

## 结果解释

这些检查验证软件行为，不证明真实预测精度或完整竞赛规则合规。
建模假设、外推、未校准先验和未实现的比赛因素见方法文档。
0.1.0 是研究候选版本，不是经过验证的实时比赛决策系统。
