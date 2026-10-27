# 搜索问答助手

基于 LangGraph ReAct 的本地搜索问答应用，提供多轮对话、联网搜索、执行过程展示和 SQLite 历史恢复。开源来源见文末，安装入口见 [README](README.md)，实际界面见 [效果展示](docs/DEMO.md)。

## 使用

按 README 安装依赖并构建前端后，在 Windows 双击项目目录的 **`start-app.cmd`**。

- 页面：<http://127.0.0.1:3000>
- 自定义 API 文档：<http://127.0.0.1:8000/docs>
- 保持启动窗口开启，按 Ctrl+C 停止。
- 原有 `start-original.cmd` 仍可启动 Studio，端口为 2024。新的网页应用使用 3000/8000。

使用项目根目录已有的 `.env`：`MODEL`、`OPENAI_API_KEY`、`OPENAI_API_BASE`、`TAVILY_API_KEY`。更改后重启后端。模型需要支持工具调用。

## 已实现的功能

- 直接输入文字，多轮问答由服务端恢复上下文。
- 输入框下方可切换联网搜索：默认开启，由模型按需调用 Tavily；关闭时本条消息不提供搜索工具，工具执行入口也会阻止外部搜索。开关偏好保存在当前浏览器，每条消息记录其实际设置，失败重试沿用原设置。
- 回答支持 Markdown、复制和来源链接。
- 搜索来源卡片展示真实搜索工具返回的标题、URL 和摘要；这些卡片是检索结果，不代表每个结果都被回答引用。
- 展开工具记录可查看实际调用的搜索词、成功/失败状态与结果摘要。
- ReAct 执行步骤按图消息顺序显示“收到问题 → 模型选择 → 执行工具 → 观察结果 → 再次判断 → 最终回答”，多次调用会逐轮列出。运行中约每秒读取检查点更新，完成后仍能在历史中查看；这是可观察的节点与工具记录，不是模型内部思维全文。
- 新建、切换会话，历史弹窗可按标题搜索。
- 页面刷新或应用重启后恢复会话。
- 空输入验证、请求超时、失败重试；同一消息重试使用原消息 ID，避免重复写入。
- 桌面与窄屏页面布局。

最终回答在完整生成后显示，不包含逐字流式输出；执行步骤会在运行期间自动更新。非常快的节点可能在同一次刷新中一起出现。

## 结构与数据

```text
frontend/                    Next.js 页面和 React 组件
src/react_agent/web.py        FastAPI 接口、会话管理和页面数据转换
src/react_agent/graph.py      原有图逻辑，增加可传 checkpointer 的编译入口
scripts/run_app.py           本机启动器
data/assistant.sqlite3        会话元数据与 LangGraph 检查点（本地生成）
tests/unit_tests/test_web.py  持久化、隔离、失败重试、来源转换测试
```

SQLite 的 `sessions` 表保存会话 ID、访客标识、标题、创建与更新时间、失败重试状态；LangGraph 的 AsyncSqliteSaver 保存消息与执行状态。数据库连接随 FastAPI 生命周期创建与关闭。

浏览器持有随机 HttpOnly 访客 Cookie。服务端根据访客标识筛选历史及校验会话归属。它是本机演示用的匿名会话管理，没有账号系统。浏览器清除 Cookie 后无法自动找回原访客的记录。使用 `127.0.0.1` 与 `localhost` 会有不同的浏览器 Cookie，请固定使用同一个地址。

`localStorage` 只保存当前会话 ID，不保存消息正文。API 密钥只在后端读取。前端通过 Next.js 的 `/api` 同源代理调用 FastAPI。

`data/`、`.env`、`frontend/.next` 和 `node_modules` 已加入忽略规则。备份会话数据时，先停止应用，再复制数据库文件；勿直接删除运行中的数据库或其 WAL 文件。

## API

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | `/api/health` | 服务与配置状态，只返回密钥是否配置 |
| GET / POST | `/api/sessions` | 列出当前访客的会话 / 创建会话 |
| GET | `/api/sessions/{id}` | 读取会话消息、搜索来源、工具记录及失败重试状态 |
| POST | `/api/sessions/{id}/messages` | 提交 `{content, message_id, search_enabled}`，返回更新后的对话；`search_enabled` 默认 `true` |

## 开发和验证

后端：

```powershell
# 在项目根目录运行
$env:PYTHONUTF8 = '1'
& '.\.venv\Scripts\python.exe' -m uvicorn react_agent.web:app --host 127.0.0.1 --port 8000 --reload
```

前端（另开终端）：

```powershell
cd frontend
pnpm dev
```

测试和构建：

```powershell
& '.\.venv\Scripts\python.exe' -m pytest tests/unit_tests -q
# 在 frontend 目录运行
pnpm build
```

修改前端后，重新构建再使用 `start-app.cmd`。测试使用真实 FastAPI、ReAct 图和临时 SQLite，仅以确定性本地模型代替付费模型。

在新环境安装：先用 Python 3.11+ 建 `.venv` 并运行 `pip install -e .`；进入 `frontend`，用 Node.js 20.9+ 和 pnpm 执行 `pnpm install --frozen-lockfile`，然后 `pnpm build`。开发测试另装 `pytest`。

## 来源

- Agent 模板：<https://github.com/langchain-ai/react-agent>，保留原 MIT License。
- 前端学习参考：<https://github.com/joylibo/zero-to-tech-demos>。本项目重新实现页面和组件，没有整包复制课程代码。
- SQLite 检查点：<https://github.com/langchain-ai/langgraph/tree/main/libs/checkpoint-sqlite>。
