# 接入与可选数据源

装饰器支持普通函数和异步函数，按参数名绑定位置参数与关键字参数。`ctx` 及已经加载的 MCP `Context` 对象会从摘要参数中剔除。结果可直接是字典；若结果是已经加载的 MCP `CallToolResult`，则只解析第一段 `type == "text"` 的内容为 JSON，不改变原返回对象。

## 按角色接入工具

```python
from SpiderPanel.tracker import track

@track(role="save")
def persist_sample(alpha_id: str):
    return {"all_checks_passed": True, "saved_locally": True}
```

若注册 MCP 工具，装饰器顺序为 `@mcp.tool()` 在上、`@track(...)` 在下。六个内置名称及容错导入示例见 [README](../README.md#python-工具装饰器)。显式角色覆盖函数名对应的角色，日志的 `t` 仍是原函数名。未传角色的未知名称直接返回原函数；未知角色在装饰时抛出 `ValueError`。

提取器的参数名与返回结构如下。表中路径是结果字典的键路径，数组元素记为 `[]`；未列出的内容不会被采集。

| 角色 | 预期参数名 | 预期结果结构 |
| --- | --- | --- |
| `simulate` | `alpha_expressions`：字符串列表；可选 `region`、`universe`、整数 `delay` | `success`：布尔；`status`；`multisimulation_id`；失败摘要取 `error`，再取 `message` |
| `result` | `multisimulation_url` | `multisimulation_id`，缺失时从参数 URL 取末段；`status`；`alpha_results[]` 中的 `alpha_id`、`details.regular` 字符串或 `details.regular.code`，以及 `details.is.sharpe/fitness/turnover`。失败摘要取 `failure.error`，再取 `message` |
| `evaluate` | `simulation_url` | `all_alphas[]` 中的 `alpha_id`、`expression`、`eval_passed`、`sharpe`、`fitness`、`failed_checks`；可选 `best_alpha_id`、`has_best`、`recommendation` |
| `prod` | `alpha_id` | 顶层 `prod`，可选 `error`；若客户端另有外层封装，需传入封装内的实际工具结果 |
| `save` | `alpha_id` | `all_checks_passed`、`saved_locally`，可选 `error` |
| `precheck` | `expressions`：字符串列表 | `status` 为 `pass` 或 `fail` |

`simulate` 的提交状态才写表达式正文。`result` 与 `evaluate` 从结果表达式计算哈希，以便关联已有正文。无效输入按空字典、空列表或 `null` 处理；非字符串失败项忽略。具体日志字段、数值清洗与裁剪见[日志规范](log-format.md)。

最小结果样例均为合成数据：

```json
{
  "success": true,
  "status": "submitted",
  "multisimulation_id": "sample_sim"
}
```

```json
{
  "status": "completed",
  "multisimulation_id": "sample_sim",
  "alpha_results": [{
    "alpha_id": "sample_alpha",
    "details": {"regular": {"code": "sample_expression_01"},
                "is": {"sharpe": 1.5, "fitness": 1.1, "turnover": 0.2}}
  }]
}
```

```json
{
  "all_alphas": [{"alpha_id": "sample_alpha", "expression": "sample_expression_01",
                  "eval_passed": true, "sharpe": 1.5, "fitness": 1.1, "failed_checks": []}],
  "has_best": true,
  "best_alpha_id": "sample_alpha"
}
```

其他角色的最小结果分别为 `{"prod":0.25}`、`{"all_checks_passed":true,"saved_locally":true}`、`{"status":"pass"}`。

装饰器只做尽力采集，普通采集错误不会改变函数返回值或异常。`WQ_SPIDER_DISABLE` 接受 `1` / `true` / `yes`；pytest 下只有显式配置 `WQ_SPIDER_DIR` 才启用写入。修改工具装饰器或环境变量后需重启工具进程。

## 可选数据源

通过 `progress_file` 与 `candidate_files`，或相应 CLI 参数配置。未配置时不读取。两种数据源每 5 秒只读一次，不导入、执行或锁定写入方；缺失或不可读时忽略，文件内容不变。建议写入方先写临时文件再原子替换进度表，避免读取半份 JSON。

### 回测进度注册表

```json
{
  "version": 1,
  "runs": [{
    "multisimulation_location": "https://example.invalid/simulations/sample_sim",
    "status": "RUNNING",
    "progress": 0.375,
    "children": ["https://example.invalid/simulations/sample_child_01",
                 "https://example.invalid/simulations/sample_child_02"],
    "submitted_at": "2026-01-15T10:00:00+00:00",
    "last_checked_at": "2026-01-15T10:00:30+00:00"
  }]
}
```

顶层必须是对象，`version` 与 1 相等，`runs` 是列表。每个有效条目必须有字符串 `multisimulation_location`，面板取其 URL 路径末段为 sim id；未知 sim 不产生新的日志回测。`status` 和两个时间字段供写入方使用，当前读取器不依赖它们。

`progress` 必须是 0–1 的有限数字且非布尔值，否则为 `null`。`children` 必须是全字符串列表，才以其长度计算 `children_total`。若进度和总数均有效，`children_done = min(total, int(progress * total + 1e-9))`，否则为 `null`。这不是逐个子任务完成标记。上述两个子任务、0.375 进度的示例得到完成数 0。同一 sim 重复出现时取最后一个有效条目。

完整文件无效时，面板使用无真实进度的回退状态；不会把估算值当作完成证明。demo 自动在自己的临时根目录生成同名进度表，并忽略外部 `progress_file`。

### 候选台账

每行 JSON 对象至少包含以下非空字符串，其他键忽略：

```jsonl
{"alpha_id":"sample_alpha","expression":"sample_expression_01"}
```

`alpha_id` 与 `expression` 必须能编码为 UTF-8 且去掉首尾空白后非空；保留原字符串内容。坏行、非对象、字段类型错误、空字符串或非法 Unicode 字符串会跳过；最后一行不要求换行。同一 alpha id 后出现的有效记录覆盖前面的记录；多个文件按配置顺序读取。

台账只为快照中已有的 alpha、候选复核项和最佳项补齐表达式，不新增候选或改变日志聚合。demo 始终不读取台账。

## 非 Python 追加示例

以下 Node.js 脚本仅使用内置模块，追加一条虚构相关性结束行。生产接入也应在调用前写开始行；字段及错误行规则见日志规范。

```javascript
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
if (!['1', 'true', 'yes'].includes((process.env.WQ_SPIDER_DISABLE || '').trim().toLowerCase())) {
  const configured = process.env.WQ_SPIDER_DIR || '~/.wq_spider';
  const root = configured === '~' ? os.homedir() : configured.startsWith('~/')
    ? path.join(os.homedir(), configured.slice(2)) : configured;
  const now = new Date();
  const date = [now.getFullYear(), String(now.getMonth()+1).padStart(2, '0'),
                String(now.getDate()).padStart(2, '0')].join('-');
  const row = {v: 1, ts: Math.floor(now.getTime()/1000), t: 'sample_prod', role: 'prod',
               ph: 'end', pid: process.pid, ppid: process.ppid, agent: null,
               ok: true, dur: 0.0, alpha: 'sample_alpha', prod: 0.25};
  const line = Buffer.from(JSON.stringify(row) + '\n', 'utf8');
  if (line.length > 32768) throw new Error('日志行超限');
  fs.mkdirSync(path.join(root, 'log'), {recursive: true});
  const fd = fs.openSync(path.join(root, 'log', date + '.jsonl'), 'a');
  try {
    if (fs.writeSync(fd, line) !== line.length) throw new Error('日志未完整写入');
  } finally {
    fs.closeSync(fd);
  }
}
```

将采集语句放入调用方的独立容错路径，避免日志写入失败改变原工具结果。关闭面板不会关闭其他语言的写入方。
