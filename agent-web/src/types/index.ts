// API Types

export interface Session {
  id: string;
  created_at: string;
  updated_at: string;
  state: string;
  messages: Message[];
}

export interface Message {
  id: string;
  role: 'user' | 'agent';
  content: string;
  timestamp: string;
  metadata?: Record<string, any>;
}

export interface AnalysisReport {
  problems: Problem[];
  diagnosis: string;
  suggestions: string[];
  summary?: string;
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
  report: AnalysisReport;
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
