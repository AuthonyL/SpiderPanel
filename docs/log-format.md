# JSONL v1 日志格式

## 位置与编码

根目录取环境变量 `WQ_SPIDER_DIR`，缺省 `~/.wq_spider`，展开 `~`。文件为 `log/YYYY-MM-DD.jsonl`，日期取事件时间戳对应的本地自然日期。每行是一个 UTF-8 JSON 对象，必须以换行结束。写入方应以追加模式一次写入完整行，多个进程共享目录时避免逐字段写入。

`rules.LOG_VERSION` 为 1。面板从零扫描当前 WQ 日覆盖的本地日期文件，再持续读取；`--day` 固定启动时的文件大小。未结束行等待下一轮，不计为完整事件。坏 JSON、无效 UTF-8 或超限完整行作为坏行跳过。

## 公共字段

| 字段 | 采集器输出与含义 |
| --- | --- |
| `v` | 整数 1 |
| `ts` | Unix 秒，采集器输出整数；面板接受有限整数或浮点数 |
| `t` | 实际工具函数名，显式指定角色也不改变此字段 |
| `role` | `simulate`、`result`、`evaluate`、`prod`、`save` 或 `precheck` |
| `ph` | `start` 或 `end`；旧日志缺失或为 `null` 时视为结束行 |
| `pid`、`ppid` | 进程与父进程 id，非负整数 |
| `agent` | 解析出的 agent 名称，字符串或 `null`；不保存命令行 |
| `ok` | 结束行的布尔值，表示执行及摘要层结果，不等同于策略通过 |
| `dur` | 结束行的耗时秒数，由单调时钟计算，四舍五入到一位小数 |
| `err` | 可选错误字符串或 `null`，最多 200 字符 |
| `trunc` | 可选裁剪标记，见下文 |

正常调用写一条开始行和一条结束行。开始行没有 `ok`、`dur` 或结果正文。普通异常写 `ok:false` 和 `异常类型: 消息`，并尽可能保留 `sim` 或 `alpha`。取消、`KeyboardInterrupt` 等可能只留下开始行；面板在超时或进程退出时清理进行中状态，不据此认定成功。

没有独立调用 id。面板使用会话、`t` 与参数身份关联开始和结束；同一函数的并发调用应提供一致的 `sim` / `alpha`。

## 开始行的角色字段

| 角色 | 字段 |
| --- | --- |
| `simulate` | `n`：`alpha_expressions` 条数 |
| `precheck` | `n`：`expressions` 条数 |
| `result` | `sim`：`multisimulation_url` 的最后一个路径段 |
| `evaluate` | `sim`：`simulation_url` 的最后一个路径段 |
| `prod`、`save` | `alpha`：`alpha_id` |

URL 只提取最后一个非空路径段，忽略查询参数，不记录完整 URL。无法提取时写 `null`。开始行不保存表达式正文。

## 结束行的角色字段

| 角色 | 字段与行布局 |
| --- | --- |
| `simulate` | `status`、`sim`、`region`、`universe`、`delay`。`status == "submitted"` 时含 `exprs: [[hash, expression], ...]`；否则含 `n` 和 `err`。`ok` 取 `success is True` |
| `result` | `sim`、`status`、`alphas: [[hash, alpha_id, sharpe, fitness, turnover], ...]`；`status == "failed"` 时 `ok:false` 并含错误摘要，其余状态 `ok:true` |
| `evaluate` | `sim`、`best`、`alphas: [[alpha_id, hash, eval_passed, sharpe, fitness, failed_checks], ...]`。无 alpha 且 `has_best` 为假时 `ok:false`，`err` 来自建议摘要 |
| `prod` | `alpha`、`prod`；结果含非空 `error` 时附 `ok:false`、`err` |
| `save` | `alpha`、`passed`、`saved`；分别来自 `all_checks_passed`、`saved_locally`。结果含非空 `error` 时附 `ok:false`、`err` |
| `precheck` | `status` 为 `pass` / `fail`，其他值归为 `null`；`n` 为输入表达式条数 |

无法取得的字符串、指标与布尔值通常写 `null`。布尔字段只接受真实布尔值；指标只接受有限的 `int` / `float`，不接受布尔值或数字字符串。指标转为浮点数并四舍五入到四位小数，溢出或非有限数归为 `null`。`delay` 仅保留真实整数。`failed_checks` 仅保留字符串，最多 5 项。

表达式哈希为完整表达式移除所有正则 `\s+` 空白后，以 UTF-8 编码计算 SHA-1，取十六进制前 10 位；在文本裁剪前计算。不做语法规范化，大小写有别；缺失或无法编码时为 `null`。结果与评估中的表达式仅用于计算哈希，不重复记录正文。

`prod < rules.PROD_LIMIT` 才通过，当前 `PROD_LIMIT = 0.7`。兼容 v1 的聚合以无非空 `err` 且 `saved:true` 标记本地候选，不额外要求 `passed:true`；`passed:false` 且未保存时表示本地拒绝。两者都不是平台提交记录。

## 大小限制与裁剪

常量均在 `rules.py`：

- `MAX_LINE_BYTES = 32768`，包括末尾换行，按 UTF-8 字节计算。
- `EXPR_CHARS = 4000`，每条提交表达式最多保留的字符数。
- `EXPR_CHARS_TIGHT = 120`，整行超限时的表达式预览字符数。
- `ERR_CHARS = 200`，错误文本字符数；`MAX_FAILED_CHECKS = 5`。

裁剪顺序为：先将全部 `exprs` 文本缩至 120 字符；仍超限则清空评估行的失败检查列表；再从 `exprs` / `alphas` 尾部逐行移除，`trunc` 记录移除总数。仅缩短文本或清空失败列表不会设置 `trunc`。若仍需退化，保留公共白名单字段并设置 `trunc:-1`，表示专属摘要已丢弃。`trunc` 不是文本裁剪字符数。非 Python 写入方也应遵守行字节预算。

## 面板实际校验

`state._valid` 对每条对象执行以下规则；通过后还须位于当前 WQ 日时间窗口才能参与聚合：

- `role` 必须是上述六种字符串之一。`ts` 必须是有限数字、不是布尔值，且能转换为本地日期时间。`v` 缺失时取 1，存在时其值必须与 1 相等。
- `ph` 只允许缺失、`null`、`start`、`end`。`pid` 缺省 0，必须是真实非负整数；`ppid` 可以缺失或 `null`，否则也必须如此。
- `ok`、`passed`、`saved` 如非 `null`，必须是布尔值。`t`、`status`、`sim`、`alpha`、`err`、`region`、`universe`、`best`、`agent` 如非 `null`，必须是字符串。`delay` 如非 `null`，必须是真实整数；`prod` 如非 `null`，必须是有限数字。
- 开始行必须有非空 `t`。`n` 可缺失或为 `null`，否则必须是真实非负整数。开始行到此结束校验，不按结束行检查结果数组。
- 结束行的 `simulate.exprs`、`result.alphas`、`evaluate.alphas` 缺省为空数组。每行必须是数组，长度分别为 2、5、6；前两列各为字符串或 `null`。结果行后三列是有限数字或 `null`；评估行第 3 列是布尔值或 `null`，第 4–5 列是有限数字或 `null`，第 6 列是字符串数组。
- 结束行在 `ok` 不是 `false` 时，`precheck.status` 必须为 `pass` / `fail`，`simulate.status` 必须非空，`result.status` 必须为 `completed` / `pending` / `failed`，`prod` / `save` 必须有非空 `alpha`。`ok:false` 允许缺失这些结果字段，但仍检查数组及公共字段类型。

校验器不验证表达式语法、哈希是否匹配、`dur` / `trunc` 的类型，也不拒绝未知键；推荐写入方仅输出规范白名单字段。

## 最小示例

以下全部是虚构数据。第一行是开始行，后六行各展示一个角色的结束行。表达式是占位文本；时间戳示例需替换为实际事件时间。

```jsonl
{"v":1,"ts":1780000000,"t":"sample_submit","role":"simulate","ph":"start","pid":101,"n":1}
{"v":1,"ts":1780000001,"t":"sample_submit","role":"simulate","ph":"end","pid":101,"ok":true,"dur":1.0,"status":"submitted","sim":"sample_sim","exprs":[["9da43a202e","sample_expression_01"]]}
{"v":1,"ts":1780000002,"t":"sample_wait","role":"result","ph":"end","pid":101,"ok":true,"dur":1.0,"sim":"sample_sim","status":"completed","alphas":[["9da43a202e","sample_alpha",1.5,1.1,0.2]]}
{"v":1,"ts":1780000003,"t":"sample_evaluate","role":"evaluate","ph":"end","pid":101,"ok":true,"dur":1.0,"sim":"sample_sim","best":"sample_alpha","alphas":[["sample_alpha","9da43a202e",true,1.5,1.1,[]]]}
{"v":1,"ts":1780000004,"t":"sample_prod","role":"prod","ph":"end","pid":101,"ok":true,"dur":1.0,"alpha":"sample_alpha","prod":0.25}
{"v":1,"ts":1780000005,"t":"sample_save","role":"save","ph":"end","pid":101,"ok":true,"dur":1.0,"alpha":"sample_alpha","passed":true,"saved":true}
{"v":1,"ts":1780000006,"t":"sample_precheck","role":"precheck","ph":"end","pid":101,"ok":true,"dur":1.0,"status":"pass","n":1}
```
