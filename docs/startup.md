# 项目启动指南

本文档说明如何在本地启动完整的 Agent Harness 项目。

完整链路包含：

1. MS-RAG 服务：知识检索服务
2. MSInsight MCP 服务：profiling 工具网关
3. msinsight_agent：
   - `agent-service` 后端
   - `agent-web` 前端

建议至少打开 3 个终端窗口分别启动 RAG、Agent 后端和 Agent 前端。当前 MCP 默认使用 `stdio` 模式，通常由 Agent 后端按需拉起，不需要单独作为 HTTP 服务长期运行。

## 1. 项目路径

当前 Agent 项目：

```bash
D:/Project/msinsight_agent
```

外部依赖项目：

```bash
D:/Project/ms_rag
D:/Project/新建文件夹/mcp
```

## 2. 启动 MS-RAG 服务

打开第 1 个终端：

```bash
cd /d/Project/ms_rag
```

首次启动前安装依赖：

```bash
pip install -r requirements.txt
```

启动 RAG 服务：

```bash
uvicorn src.main:app --reload --port 8001
```

启动成功后应看到类似输出：

```text
Uvicorn running on http://127.0.0.1:8001
```

Agent 当前配置中的 RAG 地址为：

```yaml
rag:
  base_url: "http://127.0.0.1:8001"
  retrieve_path: "/api/v1/retrieve"
```

因此 RAG 服务需要监听 `8001` 端口。

可用以下命令验证：

```bash
curl http://127.0.0.1:8001/docs
```

如果能打开 Swagger 文档，说明 RAG 服务已启动。

## 3. MSInsight MCP 服务说明

MCP 项目路径：

```bash
cd "/d/Project/新建文件夹/mcp"
```

首次使用前安装依赖：

```bash
pip install -r requirements.txt
```

Agent 当前配置为：

```yaml
mcp:
  transport: "stdio"
  command: "python"
  args: ["main.py", "--transport", "stdio"]
  cwd: "D:/Project/新建文件夹/mcp"
```

### 推荐方式：不单独启动 MCP

当前 MCP 使用 `stdio` 模式，通常由 Agent 后端通过 MCP Client 按配置启动：

```bash
python main.py --transport stdio
```

因此正常本地联调时，不需要额外开一个长期运行的 MCP 服务。只需要确保：

- MCP 项目路径存在
- MCP 项目依赖已安装
- `agent-service/config/config.yaml` 中的 `mcp.cwd` 指向正确目录

### 手动调试 MCP

如果需要单独确认 MCP 入口是否能运行，可以执行：

```bash
cd "/d/Project/新建文件夹/mcp"
python main.py --transport stdio
```

`stdio` 模式通常会等待 MCP 协议输入，因此终端看起来“卡住”不一定是异常。

如果后续需要更方便地人工调试 MCP，可以切换到 `sse` 或 `websocket` 模式，但当前 Agent 默认配置是 `stdio`。

## 4. 启动 Agent 后端

打开第 2 个终端：

```bash
cd /d/Project/msinsight_agent/agent-service
```

首次启动前安装依赖：

```bash
pip install -r requirements.txt
```

启动后端：

```bash
uvicorn src.main:app --reload --port 8000
```

启动成功后应看到类似输出：

```text
Uvicorn running on http://127.0.0.1:8000
```

可用以下命令验证：

```bash
curl http://127.0.0.1:8000/health
```

也可以在浏览器打开：

```text
http://127.0.0.1:8000/docs
```

## 5. 启动 Agent 前端

打开第 3 个终端：

```bash
cd /d/Project/msinsight_agent/agent-web
```

首次启动前安装依赖：

```bash
npm install
```

启动前端：

```bash
npm run dev
```

启动成功后通常会看到：

```text
Local: http://localhost:5173/
```

在浏览器打开：

```text
http://localhost:5173/
```

## 6. 推荐启动顺序

建议按以下顺序启动：

```text
1. MS-RAG      -> 8001
2. Agent 后端 -> 8000
3. Agent 前端 -> 5173
```

MCP 当前是 `stdio` 模式，通常由 Agent 后端按需拉起，不需要单独长期运行。

## 7. 完整链路验证

### 7.1 验证知识检索

前端启动后，在输入框中输入：

```text
如何分析通信慢？
```

正常情况下，前端应展示类似事件流程：

```text
message_start
intent_detected
rag_retrieval
message_delta
message_end
```

如果 RAG 正常，会返回知识库检索摘要。

### 7.2 验证 profiling 诊断

输入带 profiling 文件路径的诊断请求：

```text
帮我分析 D:/your/profiling/file/path 性能问题
```

或者先输入不带路径的请求：

```text
帮我分析性能问题
```

如果没有路径，前端应提示：

```text
请提供 profiling 文件的绝对路径。
```

补充路径后，Agent 会继续调用 MCP，前端应展示类似流程：

```text
mcp_tool_start
mcp_tool_result
analysis_result
report_ready
```

前端会展示：

- 执行过程 Timeline
- RAG 检索结果
- MCP 工具执行结果
- Markdown 报告
- Evidence IDs

## 8. 常见问题排查

### 8.1 RAG 不可用

现象：前端或后端出现类似错误：

```text
RAG_UNAVAILABLE
```

检查 RAG 是否启动：

```bash
curl http://127.0.0.1:8001/docs
```

如果没有响应，重新启动：

```bash
cd /d/Project/ms_rag
uvicorn src.main:app --reload --port 8001
```

### 8.2 MCP 调用失败

检查 Agent 配置：

```yaml
mcp:
  transport: "stdio"
  command: "python"
  args: ["main.py", "--transport", "stdio"]
  cwd: "D:/Project/新建文件夹/mcp"
```

确认 MCP 目录存在：

```bash
ls "/d/Project/新建文件夹/mcp"
```

确认 MCP 入口能运行：

```bash
cd "/d/Project/新建文件夹/mcp"
python main.py --transport stdio
```

如果终端停住等待输入，不一定是错误；`stdio` 模式通常就是等待 MCP Client 通信。

### 8.3 前端请求后端失败

确认后端服务在 `8000` 端口：

```bash
curl http://127.0.0.1:8000/health
```

前端默认 API 地址为：

```text
http://localhost:8000
```

如需修改，可在 `agent-web/.env` 中配置：

```bash
VITE_API_BASE=http://localhost:8000
```

修改后需要重启前端：

```bash
npm run dev
```

### 8.4 端口冲突

如果 Agent 后端 `8000` 端口被占用，可以改用：

```bash
uvicorn src.main:app --reload --port 8002
```

同时修改 `agent-web/.env`：

```bash
VITE_API_BASE=http://localhost:8002
```

如果 RAG 的 `8001` 端口被占用，可以换端口，但需要同步修改：

```yaml
rag:
  base_url: "http://127.0.0.1:8001"
```

配置文件路径：

```text
agent-service/config/config.yaml
```

## 9. 最小启动命令汇总

### 终端 1：RAG

```bash
cd /d/Project/ms_rag
pip install -r requirements.txt
uvicorn src.main:app --reload --port 8001
```

### 终端 2：Agent 后端

```bash
cd /d/Project/msinsight_agent/agent-service
pip install -r requirements.txt
uvicorn src.main:app --reload --port 8000
```

### 终端 3：Agent 前端

```bash
cd /d/Project/msinsight_agent/agent-web
npm install
npm run dev
```

MCP 当前为 `stdio` 模式，一般不需要单独启动，只要路径和依赖正确即可。
