# 寻知 · LangGraph 搜索问答助手

基于 **LangGraph + FastAPI + Next.js + SQLite** 的本地搜索问答应用。用户可以连续追问、按需联网检索、核验搜索来源，并回看工具执行过程与历史会话。

[效果展示](docs/DEMO.md) · [接口与存储说明](WEB_APP.md) · [上游模板说明](docs/UPSTREAM_README.md)

![聊天首页](docs/images/home.png)

## 项目场景

资料查询往往需要在搜索、阅读与追问之间切换。本项目将问答、搜索材料、工具记录与会话历史集中到同一页面，支持查看回答依据并继续已有对话。

## 主要功能

| 能力 | 实现方式 |
| --- | --- |
| ReAct 搜索问答 | 模型通过 Tool Calling 按需选择 Tavily 搜索，读取结果后继续调用或输出回答 |
| 联网控制 | 每条消息携带联网设置；关闭时不绑定搜索工具，执行入口同时校验 |
| 多轮与历史恢复 | 会话表管理元数据，AsyncSqliteSaver 持久化消息与执行检查点，thread_id 关联上下文 |
| 执行步骤 | 运行中轮询检查点，显示模型选择、工具参数、调用状态与结果摘要 |
| 来源核验 | 展示实际搜索返回的标题、链接和摘要 |
| 会话管理 | 新建、切换与标题搜索；刷新或服务重启后恢复历史 |
| 异常恢复 | 请求超时、失败重试、消息 ID 幂等校验与单会话并发控制 |

## 效果展示

完整截图与复现步骤见 **[效果展示](docs/DEMO.md)**。

![ReAct 执行步骤](docs/images/react-trace.png)

![搜索来源和工具记录](docs/images/search-answer.png)

## 快速运行

需要 Python 3.11+、Node.js 20.9+ 和 pnpm，以及支持工具调用的模型接口和 Tavily 密钥。

### 1. 安装依赖

```powershell
git clone https://github.com/Qin-Yuu/react-agent.git
cd react-agent
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
cd frontend
pnpm install --frozen-lockfile
pnpm build
cd ..
```

### 2. 配置环境

复制 `.env.example` 为 `.env`，填写真实配置：

```dotenv
MODEL=openai/your-model-id
OPENAI_API_KEY=your-model-api-key
OPENAI_API_BASE=https://your-provider.example/v1
TAVILY_API_KEY=your-tavily-key
LANGSMITH_TRACING=false
```

`openai/` 表示兼容接口协议，模型 ID 和 Base URL 按服务商说明填写。密钥只在后端读取，`.env` 与本地数据库均已加入 Git 忽略规则。

### 3. 启动

Windows 双击 `start-app.cmd`，保持终端运行。

- 聊天页面：<http://127.0.0.1:3000>
- API 文档：<http://127.0.0.1:8000/docs>

开发时分别启动两个终端：

```powershell
# 项目根目录
.\.venv\Scripts\python.exe -m uvicorn react_agent.web:app --host 127.0.0.1 --port 8000 --reload
```

```powershell
cd frontend
pnpm dev
```

macOS/Linux 可创建并激活 Python 虚拟环境，安装相同依赖后分别运行 `python -m uvicorn ...` 与 `pnpm dev`。Windows 启动器不适用于这些系统。

## 架构与代码入口

```text
Next.js 聊天页面
       │ 同源 /api 代理
       ▼
FastAPI：会话归属、消息校验、重试与并发控制
       │ thread_id + 本次消息 + 联网设置
       ▼
LangGraph：call_model ⇄ tools(search) → 最终回答
       │
       ▼
SQLite：sessions 表 + AsyncSqliteSaver 检查点
```

```text
src/react_agent/graph.py          ReAct 模型/工具循环
src/react_agent/tools.py          Tavily 搜索工具
src/react_agent/web.py            FastAPI 接口与页面数据投影
frontend/components/              聊天、执行步骤、历史会话组件
scripts/run_app.py                Windows 本地启动器
tests/unit_tests/                 API、检查点、工具与恢复测试
docs/DEMO.md                     实际界面展示
```

## 验证

```powershell
.\.venv\Scripts\python.exe -m pip install pytest ruff mypy
.\.venv\Scripts\python.exe -m pytest tests/unit_tests -q
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m mypy --strict src/
cd frontend
pnpm build
```

当前测试集包含 20 项自动化测试，覆盖多轮与历史恢复、访客隔离、重试幂等、联网策略、ReAct 多次调用、执行中进度和工具错误。测试使用真实 FastAPI、LangGraph 和临时 SQLite，以确定性模型和工具替代付费服务。

## 使用范围

会话保存在 `data/assistant.sqlite3`。当前采用本机匿名访客 Cookie，没有账号系统；清除 Cookie 或更换浏览器后不会自动显示原访客会话。最终回答完整生成后显示，执行步骤通过轮询更新。

本仓库提供本地应用与截图展示，运行需自行配置模型和搜索服务。LangGraph Studio 调试入口与上游说明见 [原模板文档](docs/UPSTREAM_README.md)。

## 开源来源

- [langchain-ai/react-agent](https://github.com/langchain-ai/react-agent)：ReAct 图、状态与搜索工具模板，保留 MIT License
- [joylibo/zero-to-tech-demos](https://github.com/joylibo/zero-to-tech-demos)：前端组件组织、请求与历史弹窗的学习参考
- [LangGraph SQLite checkpointer](https://github.com/langchain-ai/langgraph/tree/main/libs/checkpoint-sqlite)：会话检查点持久化

项目使用 [MIT License](LICENSE)。
