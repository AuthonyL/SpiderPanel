# SpiderPanel

用于观察本地 WorldQuant BRAIN alpha 挖掘会话的回环仪表盘，支持日志回放和独立演示。

![](docs/screenshot.png)

本项目非 WorldQuant 官方项目，与 WorldQuant 无关联。面板只监听 `127.0.0.1`，不访问 WQ 平台，不上传任何数据。前端使用原生 JavaScript 和本地 SVG，无构建步骤或外部资源依赖；运行时使用 Python >= 3.11 标准库；系统还须提供含 `America/New_York` 的 IANA 时区数据库，macOS 和多数 Linux 通常已具备。缺少该数据库时需先配置系统时区数据。

## 快速开始

将仓库克隆到名为 `SpiderPanel` 的目录，并从它的上一级目录启动：

```bash
git clone https://github.com/AuthonyL/SpiderPanel SpiderPanel
python -m SpiderPanel.server --demo --open
```

也可以安装后启动：

```bash
pip install git+https://github.com/AuthonyL/SpiderPanel
spiderpanel --demo --open
```

终端打印实际地址，默认是 `http://127.0.0.1:8788/`。`--open` 打开本机浏览器；Ctrl+C 或 SIGTERM 停止服务和后台线程。

## 运行模式

```bash
python -m SpiderPanel.server                     # live：加载当前 WQ 日并持续跟踪
python -m SpiderPanel.server --day 2026-01-15    # replay：固定日志读取边界，不跟踪新增内容
python -m SpiderPanel.server --demo --open       # demo：独立临时目录中的合成数据
python -m SpiderPanel.server --port 0            # 由系统分配端口
```

`--demo` 与 `--day` 互斥。端口优先级为 `--port`、`WQ_PANEL_PORT`、默认 8788。端口范围为 0–65535；监听失败会输出中文错误并退出。

WQ 日按 `America/New_York` 午夜切换；live 自动换日，replay 保持所选日期。日志文件按本地自然日期保存，面板按时间戳过滤 WQ 日窗口。demo 提供约三小时历史并持续追加事件，使用自己的进度注册表且忽略外部台账；在 WQ 日开始的前三小时，演示时钟会向前偏移三小时，使用上一窗口。演示结束后临时目录可能仍存在，可自行删除。

## 接入方式

### Python 工具装饰器

在工具进程中导入装饰器。容错导入可以避免面板未安装时影响工具启动：

```python
try:
    from SpiderPanel.tracker import track
except Exception:
    def track(fn=None, *, role=None):
        return fn if fn is not None else lambda function: function

@mcp.tool()
@track(role="prod")
def inspect_correlation(alpha_id: str):
    return {"prod": 0.25}  # 合成示例；实际工具自行取得结果
```

`@mcp.tool()` 在上，`@track` 在下。装饰器保留原函数元数据、返回对象和异常；采集失败只会尝试输出一次警告。异步函数同样支持。

以下内置函数名可直接使用无参数的 `@track`。其他名称需指定角色；未指定角色的其他函数保持原样，未知角色在装饰时抛出 `ValueError`。

| 内置函数名 | 角色 |
| --- | --- |
| `wqb_create_multi_simulation` | `simulate` |
| `local_wait_multi_simulation` | `result` |
| `evaluate_simulation_alphas` | `evaluate` |
| `check_alpha_prod_correlation` | `prod` |
| `save_candidate_alpha` | `save` |
| `check_expression_group_diversity` | `precheck` |

角色仅选择摘要提取方式，日志的 `t` 始终是实际函数名。参数名及结果结构见[接入文档](docs/integration.md)。

采集进程与面板须使用相同的 `WQ_SPIDER_DIR`，默认 `~/.wq_spider`。将工具进程的 `WQ_SPIDER_DISABLE` 设置为 `1`、`true` 或 `yes` 可停用采集，忽略大小写和首尾空白。关闭面板不会停止采集。

### 任意语言写日志

按 [JSONL v1 规范](docs/log-format.md)向日志目录追加完整行即可，无需 Python 装饰器或 MCP。接入文档提供非 Python 示例。

## 配置

配置查找顺序：`--config FILE` > `SPIDERPANEL_CONFIG` > `<WQ_SPIDER_DIR 或 ~/.wq_spider>/config.json`。只读取选中的文件，不合并多份配置；默认文件缺失时使用空配置。显式文件缺失、JSON 无效或配置字段类型错误时输出中文错误并退出。

配置键均可省略，未知键忽略：

| 键 | 含义 |
| --- | --- |
| `progress_file` | 回测进度注册表的只读路径 |
| `candidate_files` | 候选台账只读路径列表；按顺序合并，后出现的有效记录覆盖同一 id |
| `thresholds` | 展示阈值对象；无效或缺失时快照为 `null` |
| `daily_goal` | 每个 WQ 日的候选目标，正整数，默认 5 |

路径展开 `~`；配置内的相对路径以配置文件所在目录为基准。CLI 的相对路径以当前工作目录为基准：

```bash
python -m SpiderPanel.server --config SpiderPanel/examples/config.example.json
python -m SpiderPanel.server --progress-file data/progress.json \
  --candidates-file data/candidates.jsonl --candidates-file data/other.jsonl \
  --thresholds display-thresholds.json
```

CLI 路径覆盖对应配置；重复的 `--candidates-file` 组成新的完整列表。`--thresholds` 文件直接包含阈值对象，无需外层 `thresholds` 键。示例见 [examples/config.example.json](examples/config.example.json)。标准档和高档在示例中使用相同的公开指标，避免把自定义高档条件误写成平台要求；阈值只用于展示。Prod 判定沿用 `rules.PROD_LIMIT`，仅 `prod < 0.7` 通过。

未配置进度表和台账时，这两项功能关闭，不读取任何默认数据源。其余面板照常工作。demo 始终只使用临时目录内的进度表，候选路径为空，但仍可使用配置的阈值和每日目标。

进度表是含 `version: 1` 与 `runs` 数组的 JSON；台账是含 `alpha_id`、`expression` 的 JSONL。格式和缺失字段处理见[接入文档](docs/integration.md#可选数据源)。两者每 5 秒读取一次，不导入写入方代码，不修改数据源；缺失、损坏或不可读时忽略。

## 数据与隐私

日志为 `<WQ_SPIDER_DIR>/log/YYYY-MM-DD.jsonl`。只采集白名单字段：时间、函数名、角色、调用阶段、耗时、进程与父进程 id、解析出的 agent 名称，以及表达式文本与哈希、回测和 alpha id、S/F/T、检查结果摘要、Prod 和本地保存状态。开始行只额外含参数标识或条数，结束行才含结果。

不记录完整工具返回、`details`、`raw`、完整检查结果、PnL 数组或父进程命令行。错误摘要最多 200 字，表达式每条最多 4000 字；超出行预算时进一步裁剪，规则见日志规范。白名单文本可能含调用方放入的私有内容；分享日志前应自行检查。

日志保留期为 7 天：启动时仅清理文件名严格匹配 `YYYY-MM-DD.jsonl` 且日期早于本地今天减 7 天的文件，边界日期保留；replay 同样执行清理。其他文件不删除。

本地候选表示等待人工复核，不代表平台已提交。未送入工具的表达式不会出现，面板也不会从平台补取缺失信息。

## 开发与测试

仓库目录名须保持 `SpiderPanel`。从上一级目录执行：

```bash
python -m pip install pytest "mcp<2"
python -m pytest SpiderPanel/test -q
```

`mcp<2`（1.x，测试使用 FastMCP）是可选测试依赖，未安装或缺少 `mcp.server.fastmcp` 时跳过对应装饰器测试。Node.js 用于无依赖的前端结构测试，未找到时跳过；可选的 Playwright 测试需要安装相应 Python 包与 Chromium，缺失时跳过。HTTP 集成测试在沙箱禁止监听时也会跳过；无需监听的请求处理测试仍会执行。

`SPIDERPANEL_SERVER_FILE` 可指定外部工具服务器的 Python 文件，用 AST 检查六个内置函数的装饰器范围与顺序；不设置时跳过，不会导入或执行该文件。pytest 中只有显式设置 `WQ_SPIDER_DIR` 才会记录日志，防止测试污染默认目录。

安装包包含 Python 模块和 `web/*` 静态文件；测试、文档和配置示例不作为包数据安装。画面、事件动画与状态 API 见[设计文档](docs/design.md)。截图文件将另行添加。

## 许可证

[MIT](LICENSE)。
