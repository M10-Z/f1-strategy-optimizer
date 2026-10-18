# 有界本地原始消息接收记录

这是为未来获授权输入准备的**本地记录组件**，没有连接真实流，也没有新增账号、订阅、凭据或网络权限。v1 默认、v2 实验未通过和此前启动包保持不变；没有新模型/holdout 评估。基线提交为 `f948e1c183fb95a1d3a6f48749cab57482582a66`。

## 简短用法

使用现有环境记录示例 JSONL（输出必须是新路径）：

```sh
python -m f1_strategy_optimizer.raw_receiver record-local \
  examples/local-receiver-messages.jsonl --log output/my-receipts/messages.jsonl \
  --source local-file-demo --session-id demo --collector-id local-demo --stream laps
python -m f1_strategy_optimizer.raw_receiver replay output/my-receipts/messages.jsonl
python -m f1_strategy_optimizer.raw_receiver export-envelope \
  output/my-receipts/messages.jsonl --required-stream laps \
  --output output/my-receipts/envelope.json
```

这会记录**本地读入调用当下**的 received_at；示例正文中的旧事件时间不会变成接收时间。没有时钟证据时准确度为 unknown，导出的门控接收时间为空，原始本地时间仍在 capture.local_received_at 中保留。

核心文件也可用纯标准库直接运行，例如 `python -S src/f1_strategy_optimizer/raw_receiver.py replay output/my-receipts/messages.jsonl`。`python -m` 形式会执行原有包初始化，需使用已有项目环境（含 NumPy）；本轮没有为独立记录功能修改模型包初始化。

未来本地回调可使用 `RawReceiver(path, source=..., session_id=..., collector_id=...)`，在回调入口调用 `receive(original_bytes, stream=...)`，连接状态由 `connection('connected'/'disconnected', reason=...)` 单独记录；用上下文管理器关闭。组件不负责建立连接，也没有修改 FastF1 回调。核心模块仅使用标准库；下游现有门控使用项目已有环境。

## 保存边界

- receive 的第一个操作采样 `time.time_ns()` 和 `time.monotonic_ns()`，在解析正文、读取键、序列化和写盘之前。两次采样相邻但不是原子的；不等于网卡到达时刻或提供方发布时间。
- 保存 UTC received_at、完整 utc_unix_ns、单调纳秒、run_id、日志序号、source/session/collector、连接状态、原始字节的 base64 与 SHA256。UTC 文本精度为微秒，整数纳秒另外保留。bytes 精确保留；str 按 UTF-8 编码。不会用 Python 对象重新构造原始正文。
- 顶层 `_id` 保存为 source_sequence，`_key` 为 source_object_key；显式 revision/revision_key 另存。它们不是时间，不假设 ID 连续，也不凭到达顺序编造源修订号。每次消息、重传和修订全部追加，不覆盖旧值。
- 单写入者、串行调用；新文件使用独占创建和 append 打开，默认权限 0600。成功返回前写入并 fsync；默认最多 **16 MiB / 10000 条日志记录 / 256 KiB 单消息**，构造器可显式改限额。达限明确报错、停止同一写入器，调用方应停止输入并另开文件；超限正文不声称已保存。
- 每行含前一条和本条哈希；关闭时另存 `.receipt.json`，记录最终哈希、总字节和条数。重放先核对完整日志与回执，再返回记录，不重新采样时钟、不重写日志。缺回执、截断、乱序或 I/O 故障拒绝当作成功记录。写入失败可能留下部分字节，需保留检查，不能原地自动修复/重试。
- append-only 是本 API 的行为，不是操作系统不可修改属性。哈希/回执用于完整性检查，不是第三方签名；同时重写日志和回执无法凭它们独立认证来源。没有宣称生产级断电容灾。

## 时钟与断连

clock_evidence 可由用户提供 source、max_error_seconds、evidence_ref 及额外的时钟来源/校准信息；前三项不足时 status=unknown，未知上界保留 null。齐全也只标 `declared_not_verified`，组件不验证 NTP、引用文件或校准结论。没有证据时不应填写虚构的零误差。原始时间不会按声明偏移自动修正。

门控兼容字段 `received_at_uncertainty_seconds` 表示用户声明的 UTC 误差上界。已有 observation_import 在该字段出现时按 **received_at + 上界** 计算 available_at，保留原 received_at；旧记录未带该字段时行为不变。它仍是未经核验的上界，不是校准完成的证明。若事件时间晚于记录接收时间，原门控仍拒绝，等待时钟协调证据，不自动移动数据。

UTC 回拨、单调时钟回退，以及相邻 UTC/单调增量差超过默认一秒检测阈值会留痕。阈值只是异常检测启发式，不是精度证明。原始采样不钳制、不重排。只要本日志出现时钟异常，当前保守适配器就将**整个运行段的日历时间门控接收字段**置空；原始 UTC/单调时间仍可重放检查。单调时间只在同一运行段内比较，重启必须新日志。

连接关闭和重连单独追加；缺口时长使用单调时间，检测到单调回退时不声称缺口时长可靠。丢失消息数始终 unknown。重连后 coverage_gap_seen 保持 true，额外 required 的 local_connection_coverage 流保留 null，阻止把重连误判为历史连续覆盖。起始连接声明也仅代表本地状态，不证明全车阵、源完整性或数据恢复；新日志不能补回旧缺口。

## 与现有门控兼容

`to_envelope()` 接受本地原始消息中的**显式规范化 JSON**：event_id、kind、event_time、payload，revision 可缺失；stream/source/session 来自采集器。未知时钟或异常段保留原始 local_received_at、但不提供可用 received_at。未声明连接已建立的消息也不会进入可用快照。绑定浏览器时可另提供 decision_sha256、driver_id、original_immediate_target_lap，不能覆盖采集/session/时钟元数据。

不可解码字节、FastF1 原始 list/CompletionMessage 或其他未支持格式全部先保存为原始字节，在规范化阶段明确列入 rejected_payloads；这里没有实现其语义解码器，更没有推断 pit exit。额外连接覆盖流必须保留，不能删除来制造门控通过。模型资格、源发布时间核验及即时目标开关继续为 false。

## FastF1 兼容核对

2026-10-18 核对 [FastF1 当前 main 的 client.py](https://github.com/theOehrly/Fast-F1/blob/main/fastf1/livetiming/client.py)：`_on_message` 更新内存中的 `_t_last_message`，监督循环用它判断超时；输出是格式化消息加换行并 flush，没有额外写入本地接收时间。提供方正文自身的时间字段不能替代 received_at。main 会变化，本说明对应核对日看到的代码；没有运行其联网 recorder。

因此，本组件不能从旧 FastF1 录制文件恢复历史 received_at，也不直接声称是其默认文件格式的可替换实现。未来应在获授权回调最外层先记录原始输入，再做独立、留有证据的解码。现阶段只有本地输入接口。

## 测试与演示

```sh
python scripts/demo_raw_receiver.py --output output/my-new-receiver-demo
python -m pytest tests/test_raw_receiver.py -q
```

固定合成场景覆盖乱序/延迟修订、断连重连、系统 UTC 回拨、缺少时钟证据；注入时钟只能使用 synthetic_demo 标签。已保存四组原始日志/回执/envelope，重复重放完全一致；另执行了真实系统时钟下的**本地文件读入**，不代表真实流验证。

定向测试还覆盖入口先采样、二进制原样保存、非标准 NaN 原文保留、误差上界等待、单调回退、容量与单消息限额、已有文件拒绝覆盖、截断、失败 fsync 拒绝成功重放。完整回归及结构化证据见 `docs/raw-receiver-evidence.json` 和 `output/raw-receiver-demo-20261018/`。

它只准备未来证据采集。可信时钟校准、pit exit 语义、源发布时间、同步活动/圈边界仍需外部获授权证据；没有因采到本地时间而自动解决这些缺口。
