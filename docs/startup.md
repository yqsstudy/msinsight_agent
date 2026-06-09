# 项目启动指南

本文档说明如何在本地启动完整的 Agent Harness 项目。

完整链路包含：

1. **MS-RAG 服务**：知识检索服务（位于 `rag_code/ms_rag`）
2. **MSInsight MCP 服务**：profiling 工具网关（位于 `mcp_service_code/ms_mcp`）
3. **msinsight_agent**：
   - `agent-service` 后端
   - `agent-web` 前端

建议至少打开 3 个终端窗口分别启动 RAG、Agent 后端和 Agent 前端。当前 MCP 默认使用 `stdio` 模式，通常由 Agent 后端按需拉起，不需要单独作为 HTTP 服务长期运行。

---

## 1. 项目路径

当前 Agent 项目根目录：

```bash
/Users/ye/yangqisheng/msinsight_agent
```

集成在项目内的依赖子项目：

```bash
/Users/ye/yangqisheng/msinsight_agent/rag_code/ms_rag
/Users/ye/yangqisheng/msinsight_agent/mcp_service_code/ms_mcp
```

---

## 2. 启动 MS-RAG 服务

打开第 1 个终端：

```bash
cd rag_code/ms_rag
```

首次启动前安装依赖：

```bash
pip install -r requirements.txt
```

启动 RAG 服务：

```bash
python3 -m uvicorn src.main:app --reload --port 8001
```

可用以下命令验证健康状态：

```bash
curl http://127.0.0.1:8001/api/v1/health
```

---

## 3. MSInsight MCP 服务准备

MCP 采用 `stdio` 模式，由后端直接拉起，无需手动启动服务，但**必须确保依赖完整**。

打开终端并执行：

```bash
cd mcp_service_code/ms_mcp
pip install -r requirements.txt
# 必须安装官方 MCP SDK
pip install mcp
```

### 验证 MCP 是否可运行

```bash
python3 main.py
```

终端应处于等待输入状态（不会立即报错退出），这说明 MCP 逻辑正常。

---

## 4. 启动 Agent 后端

打开第 2 个终端：

```bash
cd agent-service
```

首次启动前安装依赖（**必须包含 mcp SDK**）：

```bash
pip install -r requirements.txt
pip install mcp
```

启动后端服务：

```bash
python3 -m uvicorn src.main:app --reload --port 8000
```

可用以下命令验证：

```bash
curl http://127.0.0.1:8000/health
```

---

## 5. 启动 Agent 前端

打开第 3 个终端：

```bash
cd agent-web
npm install
npm run dev
```

访问地址：[http://localhost:5173](http://localhost:5173)

---

## 6. 验证端到端流转

### 6.1 验证知识问答
在前端输入：“如何分析通信慢？”。
*   **期望结果**：前端展示 `rag_retrieval` 事件并返回知识库摘要。

### 6.2 验证性能诊断 (多 Agent 协作)
在前端输入：“帮我分析性能问题”。
1.  **挂起阶段**：Agent 应回复要求提供路径（如：*Please provide the path for diagnosis.*）。
2.  **恢复阶段**：在输入框补充路径（如：`/home/work/data/prof_0530`）。
3.  **完成阶段**：Agent 调用 MCP 执行诊断并输出结论。

---

## 7. 常见问题排查

### 7.1 ModuleNotFoundError: mcp
如果后端报错找不到 `mcp` 模块，请重新运行 `pip install mcp`。这是 stdio 传输层运行的基础。

### 7.2 路径无效
确保 `agent-service/config/config.yaml` 中的 `mcp.cwd` 指向的是绝对路径 `/Users/ye/yangqisheng/msinsight_agent/mcp_service_code/ms_mcp`。

### 7.3 RAG 连接超时
如果 RAG 服务没能在 8001 端口正常启动，后端会触发降级逻辑。请检查 RAG 终端的输出日志。
