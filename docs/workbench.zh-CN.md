# 本地 F1 策略工作台

[English](workbench.md) · [预测与探索接口](exploration-ui-contract.zh-CN.md)

工作台复用现有事件回放和探索引擎，以 Python 标准库提供本地 HTTP 服务，前端不依赖
框架、CDN 或账号。默认只监听 `127.0.0.1`，启动后无需联网。

## 启动

在仓库目录运行（已有虚拟环境可跳过前两行）：

```sh
python -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/python -m f1_strategy_optimizer.workbench
```

Windows 对应使用 `.venv\Scripts\python.exe`。浏览器打开 **http://127.0.0.1:8765**。
也可安装后执行 `f1-workbench`。终端按 Ctrl+C 退出。端口占用可用 `--port 8767`，
模拟时限可用 `--timeout 30`（默认 45 秒，最长 300 秒）。不需要再次下载巴林数据。

## 首次使用

1. 保持“2023 巴林大奖赛 · 真实归档示例”、15:18 UTC、Leclerc。也可选择 15:38、16:13
   这两个已冻结时点，以及全部 20 位车手中的任一位。
2. 查看已知状态、来源、事件时间、推断与未知字段。默认下一圈为固定目标，间距是异步
   报告预测。未知、陈旧、样本不足时会显示原因。
3. 检查人工假设。可直接改进站损失、模型终点圈、条件及各车速度、间距和胎龄；完整
   JSON 可编辑库存、对手行为、情景、敏感性与来源理由，编辑后点击“应用 JSON”。
   更换车手仅映射示例中的身份和车队，数值仍是手工示例，不从实际后续结果生成。
4. 明确勾选假设确认，再运行比较。页面显示后台任务耗时，可以取消；超时会终止进程，
   不返回虚构结果。每个候选展开后显示进站后首圈交通代理与相同情景的队友代价。
5. 查看前三可行方案与独立留场基线、前后车、敏感性。修改假设或切换时点/车手，会使
   旧比较和导出失效，需要重新运行；切换时点/车手也会清除已揭晓内容。
6. 点击“揭晓当前车手的实际下一阶段”。页面此前不请求结果；揭晓只展示该车手的实际
   下一完整圈和固定时域间距评分。之后导出 JSON，保留事实、假设、模拟、揭晓状态、
   代码版本、引擎/前端/数据文件哈希及源响应证据。未揭晓时也可导出，reveal 为 null。

默认示例仅建模 **20 车中的 4 车，第 9–14 圈共 6 圈**。显著显示的“模型终点名次”仅在
该车阵和时域内成立，不是全场最终名次。未知库存采用明确确认的无限库存模型，不代表
真实库存可行。情景权重是主观假设，敏感性未翻转不代表稳健。真实行动边界仍未知，
事实圈时/间距误差不能验证替代策略收益。

## 示例证据与数据隔离

安装包内 `workbench_data` 保存之前巴林开发运行的三个原始冻结决策，哈希未改，另存
对应事实评分和来源清单；不包含整场原始归档。目录 `catalog.json` 记录文件 SHA256，
加载时校验。真实来源为 OpenF1 2023 巴林 session 7953 与 Jolpica 2023 round 1。

页面初始化只请求目录、冻结决策和人工假设。揭晓文件仅在显式 POST `/api/reveal` 时读取；
完整来源审计仅在导出时读取。导出审计含事后信息，不能再作为盲测输入。独立 holdout
数据和报告不影响这个开发示例，也不自动注入假设。

示例数据是既有 `output/bahrain-conservative-expanded` 的第 1、5、12 索引（从 0 开始）
冻结记录与同索引评分，来源清单同时保存；三个时点为 15:18、15:38、16:13 UTC。页面
确认假设是现在的研究者行为，不代表这些假设曾在 2023 年发布。

## 本地接口与错误

`GET /api/catalog`、`GET /api/decision?case=...`、`GET /api/assumptions?case=...&driver=...`
不返回事实结果。`POST /api/explore` 提交当前选择与人工假设，返回任务 ID；
`GET /api/jobs/<id>` 查询状态；`POST /api/cancel` 停止任务。`POST /api/reveal` 主动揭晓；
`POST /api/export` 导出服务器保存的相匹配的模拟和证据，不接受浏览器伪造模拟报告。
POST 使用页面会话令牌。最多同时两个模拟任务，最多保留 100 个任务；重启服务会清空
内存任务，已下载记录保留。已有工作成果与磁盘输出不会被覆盖。

自定义目录可通过 `--data-dir` 加载相同 catalog 格式，列出多个比赛。每场需提供独立
冻结决策列表、以 decision_sha256 为键的评分字典、来源证据、完整假设模板，并把这些
文件的 SHA256 写入 catalog 的 file_sha256。服务器不下载、训练或生成新时点。

输入错误、无可行方案、进程异常、取消及超时都有明确状态。页面修改假设后不复用旧
模拟，也不会把原来车手的实际结果当作新选择的结果。浏览器请求 15 秒无响应时显示
连接超时；后台模拟受单独进程时限约束。

## 浏览器验收

可选开发工具为 Playwright 与系统 Chromium，不属于工作台运行依赖。

```sh
# 正常服务与专用超时服务分别在两个终端启动
.venv/bin/python -m f1_strategy_optimizer.workbench --port 8765
.venv/bin/python -m f1_strategy_optimizer.workbench --port 8766 --timeout 0.001
python scripts/verify_workbench_browser.py
```

脚本验证真实示例、人工假设、主动揭晓前无结果请求、导出字段、切换车手/时点、旧结果
失效、错误 JSON 和真实进程超时；检查 1440px 桌面与 390px 窄屏，输出截图、记录和耗时
至 `output/workbench-acceptance`。本轮实测与留出结论见验收记录。

[实测浏览器验收记录](workbench-acceptance.md)。

## 本轮四赛事目录

当前工作区已准备好 `output/workbench-all-events`，包含巴林 3 个真实时点，以及摩纳哥、
英国、意大利三个整场留出的各 23 个预注册时点，共 4 场、72 个冻结记录。使用：

```sh
.venv/bin/python -m f1_strategy_optimizer.workbench --data-dir output/workbench-all-events
```

默认端口仍为 8765，若已占用可加 `--port 8767`。当前验收实例使用 8767。
比赛选择可切换至三场 2024 留出赛事。其模拟仍使用未校准的手工数值模板，仅调整年份、
赛事及所选身份；不会按留出成绩拟合假设。两个英国数据适配技术勘误随决策导出保存。

如需从本轮已完成的结果离线重建目录（输出必须为新目录）：

```sh
.venv/bin/python scripts/build_workbench_catalog.py \
  --report output/whole-race-holdout/final/evaluation.json \
  --decisions output/whole-race-holdout/final/decisions.json \
  --output-dir output/workbench-all-events-new
```

[留出实测及技术勘误](holdout-validation.zh-CN.md)说明原严格版与最终可评分版本的区别。
