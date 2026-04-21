# AI Profiling Agent Web

AI模型训练推理调试工具定制化Agent前端应用。

## 技术栈

- **React 18** + TypeScript
- **Vite** 构建工具
- **Ant Design 5** UI组件库
- **Zustand** 状态管理
- **React Router** 路由
- **Axios** HTTP客户端
- **SSE** 流式通信

## 项目结构

```
agent-web/
├── src/
│   ├── components/          # 组件
│   │   ├── ChatView.tsx     # 对话主界面
│   │   ├── SessionList.tsx  # 会话列表
│   │   └── SystemStatus.tsx # 系统状态
│   ├── services/
│   │   └── api.ts           # API调用 + SSE处理
│   ├── stores/
│   │   └── index.ts         # Zustand状态管理
│   ├── types/
│   │   └── index.ts         # TypeScript类型定义
│   ├── App.tsx              # 主应用
│   └── main.tsx             # 入口
├── .env                     # 环境变量
└── package.json
```

## 快速开始

### 1. 安装依赖

```bash
npm install
```

### 2. 配置环境变量

编辑 `.env`：

```
VITE_API_BASE=http://localhost:8000
```

### 3. 启动开发服务器

```bash
npm run dev
```

访问 http://localhost:5173

### 4. 构建生产版本

```bash
npm run build
```

## 功能页面

### 对话页面 (`/chat`)

- 消息列表展示
- 流式输出显示
- 用户选项选择
- 分析报告展示

### 历史会话 (`/sessions`)

- 会话列表
- 恢复会话
- 删除会话

### 系统状态 (`/status`)

- 健康检查状态
- 熔断器状态
- 错误统计

## SSE流式通信

前端使用 `fetch` + `ReadableStream` 处理SSE事件：

```typescript
import { streamApi } from './services/api';

// 发送消息
for await (const event of streamApi.sendMessage(message, sessionId)) {
  switch (event.event) {
    case 'message_delta':
      // 处理消息片段
      break;
    case 'user_input_required':
      // 显示选项
      break;
    case 'analysis_result':
      // 显示报告
      break;
  }
}
```

## 状态管理

使用Zustand管理全局状态：

```typescript
import { useChatStore } from './stores';

// 在组件中使用
const {
  messages,
  isStreaming,
  addMessage,
  startStreaming,
  appendContent,
} = useChatStore();
```

## API服务

```typescript
import { sessionApi, streamApi, systemApi } from './services/api';

// 会话管理
const sessions = await sessionApi.list();
const session = await sessionApi.create();

// 系统状态
const health = await systemApi.health();
const circuitBreakers = await systemApi.circuitBreakers();
```

## 开发

### 类型检查

```bash
npm run typecheck
```

### 代码风格

```bash
npm run lint
```

## License

MIT
