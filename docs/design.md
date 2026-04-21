# AI Profiling MCP 定制化Agent - 系统设计文档

## 1. 系统架构总览

```
┌─────────────────────────────────────────────────────────────────────────┐
│                              用户层                                      │
│                    ┌─────────────────────────┐                          │
│                    │    React Web Frontend   │                          │
│                    │  ┌───────────────────┐  │                          │
│                    │  │  对话界面         │  │                          │
│                    │  │  报告展示         │  │                          │
│                    │  │  会话历史         │  │                          │
│                    │  │  系统状态         │  │                          │
│                    │  └───────────────────┘  │                          │
│                    └────────────┬────────────┘                          │
└─────────────────────────────────┼───────────────────────────────────────┘
                                  │ HTTP/SSE (流式输出)
┌─────────────────────────────────┼───────────────────────────────────────┐
│                         Agent服务层                                      │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │                      Agent Core (DAG引擎)                          │  │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐   │  │
│  │  │ DAG引擎     │  │ 意图识别器   │  │     报告生成器           │   │  │
│  │  │ DAGEngine   │  │ IntentRec   │  │   ReportGenerator       │   │  │
│  │  └─────────────┘  └─────────────┘  └─────────────────────────┘   │  │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐   │  │
│  │  │ 状态机      │  │ 步骤执行器   │  │     SSE流式输出          │   │  │
│  │  │ StateMachine│  │ Executors   │  │   SSEStreamer           │   │  │
│  │  └─────────────┘  └─────────────┘  └─────────────────────────┘   │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │                      错误处理层                                    │  │
│  │  ┌───────────┐  ┌───────────┐  ┌───────────┐  ┌───────────────┐  │  │
│  │  │ 重试机制   │  │ 熔断器    │  │ 错误处理器 │  │ 降级策略      │  │  │
│  │  │ Retry     │  │CircuitBreak│  │ Handler   │  │ Fallback     │  │  │
│  │  └───────────┘  └───────────┘  └───────────┘  └───────────────┘  │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │                      可观测性层                                    │  │
│  │  ┌───────────┐  ┌───────────┐  ┌───────────┐                      │  │
│  │  │ 结构化日志 │  │Prometheus │  │ 健康检查   │                      │  │
│  │  │ Logging   │  │ Metrics   │  │ Health    │                      │  │
│  │  └───────────┘  └───────────┘  └───────────┘                      │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │                      LLM适配层                                     │  │
│  │  ┌───────────┐  ┌───────────┐  ┌───────────┐  ┌───────────────┐  │  │
│  │  │ Claude    │  │ OpenAI    │  │ Local     │  │ LLMRouter     │  │  │
│  │  │ Adapter   │  │ Adapter   │  │ Adapter   │  │ (配置驱动)    │  │  │
│  │  └───────────┘  └───────────┘  └───────────┘  └───────────────┘  │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │                      MCP客户端层                                   │  │
│  │  ┌───────────┐  ┌───────────┐  ┌───────────┐  ┌───────────────┐  │  │
│  │  │ HTTP      │  │ Stdio     │  │ SSE       │  │ WebSocket     │  │  │
│  │  │ Transport │  │ Transport │  │ Transport │  │ Transport     │  │  │
│  │  └───────────┘  └───────────┘  └───────────┘  └───────────────┘  │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │                      知识层                                        │  │
│  │  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐   │  │
│  │  │ 知识库检索器     │  │ 案例库管理器     │  │ 向量存储        │   │  │
│  │  │ KnowledgeRetriever│ │ CaseLibManager  │  │ VectorStore    │   │  │
│  │  └─────────────────┘  └─────────────────┘  └─────────────────┘   │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │                      持久化层                                      │  │
│  │  ┌─────────────────┐  ┌─────────────────────────────────────┐    │  │
│  │  │ 会话存储        │  │ 配置存储 (API Token/URL)            │    │  │
│  │  │ SessionStore   │  │ ConfigStore                        │    │  │
│  │  └─────────────────┘  └─────────────────────────────────────┘    │  │
│  └───────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────┬───────────────────────────────────────┘
                                  │ MCP Protocol
┌─────────────────────────────────┼───────────────────────────────────────┐
│                         MCP服务层                                       │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │  解析工具  │  概览工具  │  快慢卡分析  │  内存分析  │  ...        │  │
│  └───────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 2. 核心组件设计

### 2.1 对话管理器 (DialogManager)

```python
class DialogManager:
    """管理用户对话上下文和多轮交互"""

    def __init__(self, session_store: SessionStore):
        self.session_store = session_store
        self.current_session: Session = None

    def start_session(self, user_id: str) -> Session:
        """创建新会话"""

    def resume_session(self, session_id: str) -> Session:
        """恢复历史会话"""

    def process_message(self, message: UserMessage) -> AgentResponse:
        """处理用户消息，返回响应"""

    def ask_user(self, question: str, options: List[Option], reason: str) -> None:
        """向用户提问，附带选项和原因说明"""

    def receive_user_choice(self, choice: str) -> None:
        """接收用户选择，继续流程"""
```

### 2.2 意图识别器 (IntentRecognizer)

```python
class IntentRecognizer:
    """识别用户意图"""

    INTENT_TYPES = [
        "FULL_ANALYSIS",      # 全量分析
        "TARGETED_ANALYSIS",  # 定向分析（指定问题类型）
        "CONTINUE",           # 继续上次分析
        "FEEDBACK",           # 反馈/采纳建议
        "QUESTION",           # 一般性问题
    ]

    def recognize(self, message: str, context: DialogContext) -> Intent:
        """识别用户意图"""
        # 返回: Intent(type, target_problem=None, data_path=None)
```

### 2.3 工具编排器 (ToolOrchestrator)

```python
class ToolOrchestrator:
    """MCP工具编排执行"""

    # 分析流程定义
    ANALYSIS_FLOW = {
        "FULL_ANALYSIS": [
            "parse_data",
            "get_overview",
            "detect_problem_type",
            "select_tools",      # 动态决策点
            "execute_analysis",
            "generate_report"
        ],
        "MEMORY_ANALYSIS": [
            "parse_data",
            "analyze_memory",
            "generate_report"
        ],
        "COMMUNICATION_ANALYSIS": [
            "parse_data",
            "get_comm_domains",  # 可能需要用户选择
            "analyze_slow_cards",
            "generate_report"
        ]
    }

    def __init__(self, mcp_client: MCPClient, state_machine: StateMachine):
        self.mcp = mcp_client
        self.state_machine = state_machine

    async def execute_flow(self, flow_name: str, params: dict) -> FlowResult:
        """执行分析流程"""

    async def call_tool(self, tool_name: str, params: dict) -> ToolResult:
        """调用单个MCP工具"""

    def get_next_step(self, current_result: Any) -> str:
        """根据当前结果决定下一步（LLM辅助决策）"""
```

### 2.4 状态机 (AnalysisStateMachine)

```python
class AnalysisStateMachine:
    """分析流程状态机"""

    STATES = [
        "IDLE",           # 空闲
        "PARSING",        # 解析数据中
        "DETECTING",      # 检测问题类型中
        "WAITING_INPUT",  # 等待用户输入
        "ANALYZING",      # 分析执行中
        "REPORTING",      # 生成报告中
        "COMPLETED",      # 完成
        "ERROR"           # 错误状态
    ]

    TRANSITIONS = {
        ("IDLE", "start"): "PARSING",
        ("PARSING", "success"): "DETECTING",
        ("PARSING", "error"): "ERROR",
        ("DETECTING", "need_input"): "WAITING_INPUT",
        ("DETECTING", "proceed"): "ANALYZING",
        ("WAITING_INPUT", "received"): "ANALYZING",
        ("ANALYZING", "success"): "REPORTING",
        ("ANALYZING", "error"): "ERROR",
        ("REPORTING", "success"): "COMPLETED",
    }

    def __init__(self):
        self.current_state = "IDLE"
        self.context: dict = {}

    def transition(self, event: str) -> str:
        """状态转换"""

    def get_context(self) -> dict:
        """获取当前上下文"""
```

### 2.5 知识库检索器 (KnowledgeRetriever)

```python
class KnowledgeRetriever:
    """混合检索：关键词 + 向量相似"""

    def __init__(self, vector_store: VectorStore, documents: List[Document]):
        self.vector_store = vector_store
        self.keyword_index = self._build_keyword_index(documents)

    def retrieve(self, query: str, problem_type: str, top_k: int = 3) -> List[KnowledgeChunk]:
        """检索相关知识"""
        # 1. 关键词检索（基于问题类型）
        keyword_results = self._keyword_search(query, problem_type)

        # 2. 向量相似检索
        vector_results = self.vector_store.similarity_search(query, top_k)

        # 3. 混合排序
        return self._merge_results(keyword_results, vector_results)

    def _build_keyword_index(self, documents: List[Document]) -> dict:
        """构建关键词索引"""
```

### 2.6 案例库管理器 (CaseLibManager)

```python
class CaseLibManager:
    """案例库管理"""

    def __init__(self, storage_path: str, vector_store: VectorStore):
        self.storage_path = storage_path
        self.vector_store = vector_store

    def save_case(self, case: AnalysisCase) -> str:
        """保存案例"""
        # case包含：问题描述、分析过程、诊断结果、优化建议、用户采纳情况

    def find_similar_cases(self, problem_description: str, top_k: int = 5) -> List[AnalysisCase]:
        """查找相似案例"""

    def update_feedback(self, case_id: str, adopted: bool, user_comment: str = None):
        """更新用户反馈"""
```

---

## 3. 数据模型设计

### 3.1 会话模型

```python
@dataclass
class Session:
    id: str
    created_at: datetime
    updated_at: datetime
    messages: List[Message]
    state: str  # 状态机当前状态
    context: AnalysisContext

@dataclass
class Message:
    id: str
    role: str  # "user" | "agent"
    content: str
    timestamp: datetime
    metadata: dict  # 存储意图、工具调用等信息

@dataclass
class AnalysisContext:
    data_path: Optional[str]
    data_type: Optional[str]
    problem_type: Optional[str]
    analysis_results: dict
    pending_choices: Optional[List[Option]]  # 待用户选择的选项
```

### 3.2 分析结果模型

```python
@dataclass
class AnalysisReport:
    session_id: str
    data_info: DataInfo
    problems: List[Problem]
    diagnosis: Diagnosis
    suggestions: List[Suggestion]
    knowledge_refs: List[KnowledgeRef]  # 引用的知识库内容
    similar_cases: List[CaseRef]        # 相似案例

@dataclass
class Problem:
    type: str  # "communication" | "memory" | "compute" | ...
    severity: str  # "high" | "medium" | "low"
    description: str
    location: str  # 问题位置（如：哪个卡、哪个迭代）

@dataclass
class Diagnosis:
    root_cause: str
    evidence: List[str]
    analysis_process: List[ToolCallRecord]

@dataclass
class Suggestion:
    description: str
    priority: int
    expected_improvement: str
    action_items: List[str]
    knowledge_source: Optional[str]  # 建议来源（知识库/案例库/LLM生成）
```

### 3.3 案例模型

```python
@dataclass
class AnalysisCase:
    id: str
    created_at: datetime
    problem_description: str
    problem_type: str
    diagnosis: Diagnosis
    suggestions: List[Suggestion]
    adopted: bool
    user_feedback: Optional[str]
    embedding: Optional[List[float]]  # 向量嵌入
```

### 3.4 配置模型

```python
@dataclass
class LLMConfig:
    provider: str  # "claude" | "openai" | "local"
    api_key: str
    api_url: str
    model_name: str
    parameters: dict  # temperature, max_tokens等

@dataclass
class AgentConfig:
    llm: LLMConfig
    mcp_server_url: str
    knowledge_base_path: str
    case_lib_path: str
    session_storage_path: str
```

---

## 4. 工具编排流程设计

### 4.1 全量分析流程

```
┌─────────────────────────────────────────────────────────────────────┐
│                        全量分析流程                                   │
└─────────────────────────────────────────────────────────────────────┘
                                │
                                ▼
                    ┌───────────────────────┐
                    │  1. 解析数据           │
                    │  parse_data(path)     │
                    └───────────┬───────────┘
                                │
                                ▼
                    ┌───────────────────────┐
                    │  2. 获取数据概览       │
                    │  get_overview()       │
                    └───────────┬───────────┘
                                │
                                ▼
                    ┌───────────────────────┐
                    │  3. 检测问题类型       │
                    │  detect_problems()    │
                    │  → [通信, 内存, 计算]  │
                    └───────────┬───────────┘
                                │
                    ┌───────────┴───────────┐
                    │                       │
                    ▼                       ▼
          ┌─────────────────┐     ┌─────────────────┐
          │ 通信问题分支     │     │ 内存问题分支     │
          └────────┬────────┘     └────────┬────────┘
                   │                       │
                   ▼                       ▼
          ┌─────────────────┐     ┌─────────────────┐
          │ 获取通信域列表   │     │ 调用内存分析     │
          │ get_comm_domains│     │ analyze_memory  │
          └────────┬────────┘     └────────┬────────┘
                   │                       │
                   ▼                       │
          ┌─────────────────┐              │
          │ 多个通信域?      │              │
          └────────┬────────┘              │
                   │                       │
         ┌─────────┴─────────┐             │
         │Yes                │No           │
         ▼                   ▼             │
┌─────────────────┐ ┌─────────────────┐   │
│ 询问用户选择     │ │ 直接分析        │   │
│ + 提供原因说明   │ │                 │   │
└────────┬────────┘ └────────┬────────┘   │
         │                   │            │
         └─────────┬─────────┘            │
                   ▼                      │
          ┌─────────────────┐             │
          │ 快慢卡分析       │             │
          │ analyze_slow    │             │
          │ _cards(domain)  │             │
          └────────┬────────┘             │
                   │                      │
                   └──────────┬───────────┘
                              │
                              ▼
                    ┌───────────────────────┐
                    │  4. 检索知识库         │
                    │  retrieve_knowledge   │
                    └───────────┬───────────┘
                                │
                                ▼
                    ┌───────────────────────┐
                    │  5. 查找相似案例       │
                    │  find_similar_cases   │
                    └───────────┬───────────┘
                                │
                                ▼
                    ┌───────────────────────┐
                    │  6. 生成诊断报告       │
                    │  generate_report      │
                    └───────────┬───────────┘
                                │
                                ▼
                    ┌───────────────────────┐
                    │  7. 返回报告给用户     │
                    │  + 询问是否采纳建议    │
                    └───────────────────────┘
```

### 4.2 工具调用依赖关系

```yaml
tools:
  parse_data:
    description: "解析profiling数据"
    input: { data_path: str }
    output: { data_id: str, data_type: str, summary: dict }

  get_overview:
    description: "获取数据概览"
    depends_on: [parse_data]
    input: { data_id: str }
    output: { problem_types: List[str], metrics: dict }

  get_comm_domains:
    description: "获取通信域列表"
    depends_on: [parse_data]
    input: { data_id: str }
    output: { domains: List[CommDomain] }

  analyze_slow_cards:
    description: "快慢卡分析"
    depends_on: [parse_data, get_comm_domains]
    input: { data_id: str, domain: str }
    output: { slow_cards: List[CardInfo], analysis: dict }

  analyze_memory:
    description: "内存问题分析"
    depends_on: [parse_data]
    input: { data_id: str }
    output: { memory_issues: List[MemoryIssue], analysis: dict }
```

---

## 5. API接口设计

### 5.1 Agent服务API

```yaml
# 会话管理
POST /api/sessions
  request: { user_id: str }
  response: { session_id: str, created_at: datetime }

GET /api/sessions/{session_id}
  response: { session: Session }

GET /api/sessions
  request: { user_id: str, limit: int }
  response: { sessions: List[SessionSummary] }

DELETE /api/sessions/{session_id}
  response: { success: bool }

# 对话交互
POST /api/sessions/{session_id}/messages
  request: { content: str }
  response: {
    response: str,
    state: str,
    report: Optional[AnalysisReport],
    options: Optional[List[Option]]  # 如果需要用户选择
  }

# 配置管理
GET /api/config
  response: { config: AgentConfig }

PUT /api/config/llm
  request: { provider: str, api_key: str, api_url: str, model_name: str }
  response: { success: bool }

# 反馈
POST /api/cases/{case_id}/feedback
  request: { adopted: bool, comment: Optional[str] }
  response: { success: bool }
```

### 5.2 WebSocket事件（可选，用于流式响应）

```yaml
# 客户端 → 服务端
message:
  type: "user_message"
  session_id: str
  content: str

choice:
  type: "user_choice"
  session_id: str
  choice: str

# 服务端 → 客户端
progress:
  type: "progress"
  step: str
  message: str

response:
  type: "response"
  content: str
  report: Optional[AnalysisReport]

ask:
  type: "ask_user"
  question: str
  options: List[Option]
  reason: str
```

---

## 6. 前端集成设计

### 6.1 组件结构

```
src/
├── components/
│   ├── Chat/
│   │   ├── ChatContainer.tsx      # 对话容器
│   │   ├── MessageList.tsx        # 消息列表
│   │   ├── MessageItem.tsx        # 单条消息
│   │   ├── InputBox.tsx           # 输入框
│   │   └── OptionSelector.tsx     # 选项选择器
│   ├── Report/
│   │   ├── ReportViewer.tsx       # 报告展示
│   │   ├── ProblemCard.tsx        # 问题卡片
│   │   ├── DiagnosisSection.tsx   # 诊断部分
│   │   └── SuggestionList.tsx     # 建议列表
│   ├── Session/
│   │   ├── SessionList.tsx        # 会话历史列表
│   │   └── SessionItem.tsx        # 会话项
│   └── Config/
│       └── LLMConfigForm.tsx      # LLM配置表单
├── hooks/
│   ├── useChat.ts                 # 对话逻辑
│   ├── useSession.ts              # 会话管理
│   └── useWebSocket.ts            # WebSocket连接
├── services/
│   ├── api.ts                     # API调用
│   └── websocket.ts               # WebSocket服务
└── types/
    └── index.ts                   # 类型定义
```

### 6.2 关键组件设计

```tsx
// OptionSelector.tsx - 用户选择交互
interface OptionSelectorProps {
  question: string;
  reason: string;  // 为什么这么问
  options: Option[];
  onSelect: (choice: string) => void;
}

const OptionSelector: React.FC<OptionSelectorProps> = ({
  question, reason, options, onSelect
}) => (
  <div className="option-selector">
    <p className="question">{question}</p>
    <p className="reason">💡 {reason}</p>
    <div className="options">
      {options.map((opt, idx) => (
        <button key={idx} onClick={() => onSelect(opt.value)}>
          <span className="label">{opt.label}</span>
          <span className="desc">{opt.description}</span>
        </button>
      ))}
    </div>
  </div>
);

// ReportViewer.tsx - 报告展示
interface ReportViewerProps {
  report: AnalysisReport;
  onAdopt: (suggestionId: string) => void;
}

const ReportViewer: React.FC<ReportViewerProps> = ({ report, onAdopt }) => (
  <div className="report-viewer">
    <section className="problems">
      <h3>检测到的问题</h3>
      {report.problems.map(p => <ProblemCard problem={p} />)}
    </section>
    <section className="diagnosis">
      <h3>根因分析</h3>
      <DiagnosisSection diagnosis={report.diagnosis} />
    </section>
    <section className="suggestions">
      <h3>优化建议</h3>
      <SuggestionList
        suggestions={report.suggestions}
        onAdopt={onAdopt}
      />
    </section>
  </div>
);
```

---

## 7. 配置文件设计

```yaml
# config.yaml
llm:
  default_provider: "claude"
  providers:
    claude:
      api_key: "${CLAUDE_API_KEY}"
      api_url: "https://api.anthropic.com"
      model: "claude-sonnet-4-6"
      parameters:
        temperature: 0.7
        max_tokens: 4096
    openai:
      api_key: "${OPENAI_API_KEY}"
      api_url: "https://api.openai.com/v1"
      model: "gpt-4"
      parameters:
        temperature: 0.7
        max_tokens: 4096
    local:
      api_url: "http://localhost:8000/v1"
      model: "local-model"
      parameters:
        temperature: 0.7
        max_tokens: 4096

mcp:
  server_url: "http://localhost:5000"
  timeout: 30

knowledge:
  documents_path: "./knowledge/docs"
  vector_store_path: "./knowledge/vectors"
  retrieval:
    keyword_weight: 0.4
    vector_weight: 0.6
    top_k: 3

case_lib:
  storage_path: "./cases"

session:
  storage_path: "./sessions"
  max_history: 100

analysis:
  default_flow: "FULL_ANALYSIS"
  retry_count: 1
  timeout: 30
```

---

## 8. 目录结构

```
agent-service/
├── src/
│   ├── core/                    # 核心组件
│   │   ├── dag/                 # DAG工作流引擎
│   │   │   ├── engine.py        # 核心引擎
│   │   │   ├── executors.py     # 步骤执行器
│   │   │   └── dag_engine.py    # DAG引擎主类
│   │   ├── intent_recognizer.py # 意图识别
│   │   ├── state_machine.py     # 状态机
│   │   └── report_generator.py  # 报告生成
│   ├── llm/                     # LLM适配层
│   │   ├── base.py
│   │   ├── claude_adapter.py
│   │   ├── openai_adapter.py
│   │   ├── local_adapter.py
│   │   └── llm_router.py
│   ├── mcp/                     # MCP客户端
│   │   ├── client.py
│   │   └── transports/          # 多传输支持
│   │       ├── http_transport.py
│   │       ├── stdio_transport.py
│   │       ├── sse_transport.py
│   │       └── websocket_transport.py
│   ├── knowledge/               # 知识库
│   │   ├── retriever.py
│   │   └── vector_store.py
│   ├── case_lib/                # 案例库
│   │   └── manager.py
│   ├── error_handling/          # 错误处理
│   │   ├── retry.py             # 重试机制
│   │   ├── circuit_breaker.py   # 熔断器
│   │   ├── handler.py           # 错误处理器
│   │   └── fallback.py          # 降级策略
│   ├── observability/           # 可观测性
│   │   ├── logging_config.py    # 结构化日志
│   │   ├── metrics.py           # Prometheus指标
│   │   └── health.py            # 健康检查
│   ├── storage/                 # 存储
│   │   ├── session_store.py
│   │   └── config_store.py
│   ├── api/                     # API路由
│   │   ├── routes/
│   │   │   ├── sessions.py
│   │   │   ├── messages.py
│   │   │   ├── config.py
│   │   │   ├── feedback.py
│   │   │   ├── streaming.py     # SSE流式API
│   │   │   └── error_handling.py
│   │   ├── sse.py               # SSE工具
│   │   └── websocket.py
│   ├── models/                  # 数据模型
│   │   ├── session.py
│   │   ├── report.py
│   │   ├── case.py
│   │   └── config.py
│   └── main.py
├── config/
│   ├── config.yaml              # 主配置
│   └── flows.yaml               # DAG流程定义
├── knowledge/                   # 知识文档
├── cases/                       # 案例库
├── sessions/                    # 会话存储
├── tests/
├── requirements.txt
└── README.md

agent-web/                       # 前端应用
├── src/
│   ├── components/
│   │   ├── ChatView.tsx         # 对话主界面
│   │   ├── SessionList.tsx      # 会话列表
│   │   └── SystemStatus.tsx     # 系统状态
│   ├── services/
│   │   └── api.ts               # API调用 + SSE
│   ├── stores/
│   │   └── index.ts             # Zustand状态
│   ├── types/
│   │   └── index.ts             # TypeScript类型
│   ├── App.tsx
│   └── main.tsx
├── .env
└── package.json
```

---

## 9. 技术选型

| 组件 | 技术 | 说明 |
|-----|------|------|
| 后端框架 | FastAPI | 异步、高性能 |
| LLM SDK | anthropic / openai | 多提供商支持 |
| 向量存储 | ChromaDB | 轻量本地存储 |
| 会话存储 | JSON文件 | 简单可靠 |
| 前端 | React + TypeScript | 类型安全 |
| 前端状态 | Zustand | 轻量级 |
| 前端HTTP | Axios + fetch | SSE支持 |
| 流式通信 | SSE | 单向推送 |
| 错误处理 | 自研 | 重试+熔断+降级 |
| 可观测性 | Prometheus | 指标监控 |

---

## 10. SSE流式通信

### 事件类型

| 事件 | 说明 | 数据 |
|-----|------|------|
| `message_start` | 消息开始 | `{session_id}` |
| `message_delta` | 消息片段 | `{content}` |
| `message_end` | 消息结束 | `{}` |
| `analysis_result` | 分析结果 | `{report}` |
| `user_input_required` | 需要用户输入 | `{question, options, reason}` |
| `error` | 错误 | `{error}` |

### 前端处理

```typescript
for await (const event of streamApi.sendMessage(message)) {
  switch (event.event) {
    case 'message_delta':
      appendContent(event.data.content);
      break;
    case 'user_input_required':
      showOptions(event.data.options);
      break;
  }
}
```

---

## 11. 错误处理机制

### 重试策略

- 指数退避：`delay = base_delay * 2^(attempt-1)`
- 最大重试次数：3次
- 可重试错误：超时、连接错误、限流

### 熔断器

- 状态：CLOSED → OPEN → HALF_OPEN
- 失败阈值：5次连续失败
- 超时时间：30秒

### 降级策略

- MCP工具失败：返回默认结果
- LLM失败：返回空决策
- 分析失败：返回基础报告
