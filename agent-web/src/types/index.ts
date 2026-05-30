// API Types

export interface Session {
  id: string;
  created_at: string;
  updated_at: string;
  state: string;
  messages: Message[];
  plans?: ExecutionPlan[];
  evidence?: Evidence[];
  reports?: any[];
  pending_input?: any | null;
}

export interface Message {
  id: string;
  role: 'user' | 'agent';
  content: string;
  timestamp: string;
  metadata?: Record<string, any>;
}

export interface AnalysisReport {
  id?: string;
  report_id?: string;
  format?: string;
  content?: string;
  evidence_ids?: string[];
  problems?: Problem[];
  diagnosis?: string;
  suggestions?: string[];
  summary?: string;
}

export interface HarnessReport {
  id: string;
  session_id: string;
  format: string;
  content: string;
  evidence_ids: string[];
  metadata: Record<string, any>;
  created_at: string;
}

export interface HarnessTraceEvent {
  id: string;
  event: SSEEventType;
  title: string;
  detail?: string;
  status?: string;
  timestamp: string;
  data: Record<string, any>;
}

export interface Problem {
  type: string;
  severity: 'low' | 'medium' | 'high';
  description: string;
  location?: string;
}

export interface Option {
  value: string;
  label: string;
  description?: string;
}

// SSE Event Types

export type SSEEventType =
  | 'message_start'
  | 'message_delta'
  | 'message_end'
  | 'execution_plan_created'
  | 'execution_step_started'
  | 'execution_step_completed'
  | 'execution_step_failed'
  | 'intent_detected'
  | 'rag_retrieval'
  | 'mcp_tool_start'
  | 'mcp_tool_result'
  | 'report_ready'
  | 'analysis_start'
  | 'analysis_step'
  | 'analysis_result'
  | 'analysis_end'
  | 'user_input_required'
  | 'error'
  | 'heartbeat';

export interface SSEEvent {
  event: SSEEventType;
  data: SSEEventData;
  id?: string;
}

export interface ExecutionStep {
  id: string;
  plan_id: string;
  session_id: string;
  type: string;
  name: string;
  status: string;
  input?: Record<string, any>;
  output?: Record<string, any> | null;
  evidence_ids?: string[];
  error?: Record<string, any> | null;
  started_at?: string | null;
  completed_at?: string | null;
  elapsed_ms?: number | null;
  metadata?: Record<string, any>;
}

export interface ExecutionPlan {
  id: string;
  session_id: string;
  user_message_id?: string | null;
  intent: string;
  status: string;
  goal: string;
  steps: ExecutionStep[];
  current_step_id?: string | null;
  evidence_ids?: string[];
  metadata?: Record<string, any>;
  created_at?: string;
  updated_at?: string;
}

export interface Evidence {
  id: string;
  session_id: string;
  plan_id?: string | null;
  step_id?: string | null;
  type: string;
  source: string;
  content: string;
  summary?: string;
  confidence?: string;
  metadata?: Record<string, any>;
  created_at?: string;
}

export type SSEEventData =
  | MessageStartData
  | MessageDeltaData
  | AnalysisResultData
  | UserInputRequiredData
  | ErrorData
  | Record<string, any>;

export interface MessageStartData {
  session_id: string;
}

export interface MessageDeltaData {
  content: string;
}

export interface AnalysisResultData {
  report?: AnalysisReport;
  summary?: string;
  confidence?: string;
  session_id: string;
}

export interface ReportReadyData {
  report_id: string;
  format: string;
  evidence_ids: string[];
  session_id: string;
}

export interface UserInputRequiredData {
  question: string;
  options: Option[];
  reason: string;
  session_id: string;
}

export interface ErrorData {
  error: string;
  session_id?: string;
}

// Circuit Breaker Types

export type CircuitState = 'closed' | 'open' | 'half_open';

export interface CircuitBreakerStatus {
  name: string;
  state: CircuitState;
  stats: {
    total_calls: number;
    successful_calls: number;
    failed_calls: number;
    consecutive_failures: number;
    last_failure_time: string | null;
    last_failure_error: string | null;
  };
}

// Health Types

export type HealthStatus = 'healthy' | 'degraded' | 'unhealthy';

export interface HealthCheckResult {
  status: HealthStatus;
  timestamp: string;
  uptime_seconds: number;
  components: ComponentHealth[];
}

export interface ComponentHealth {
  name: string;
  status: HealthStatus;
  message: string;
  details?: Record<string, any>;
  latency_ms?: number;
}
