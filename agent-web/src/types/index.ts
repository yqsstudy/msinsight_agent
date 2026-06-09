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
  value: string | number | boolean;
  label: string;
  description?: string;
  metadata?: Record<string, any>;
}

export interface InputFieldOption {
  label: string;
  value: string | number | boolean;
  description?: string;
  metadata?: Record<string, any>;
}

export interface InputField {
  name: string;
  label?: string;
  type?: 'string' | 'select' | 'path' | 'confirm';
  required?: boolean;
  description?: string;
  value?: any;
  options?: InputFieldOption[];
  metadata?: Record<string, any>;
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
  | 'control_flow_waiting'
  | 'control_flow_retrying'
  | 'report_ready'
  | 'analysis_start'
  | 'analysis_step'
  | 'analysis_result'
  | 'analysis_end'
  | 'user_input_required'
  | 'diagnosis_context_updated'
  | 'diagnosis_step_invalidated'
  | 'diagnosis_rollback_detected'
  | 'diagnosis_auto_fill'
  | 'diagnosis_operation_queued'
  | 'diagnosis_operation_updated'
  | 'diagnosis_candidate_set_created'
  | 'diagnosis_candidate_selected'
  | 'diagnosis_reconciliation'
  | 'diagnosis_schema_drift'
  | 'diagnosis_audit_event'
  | 'diagnosis_pending_routed'
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

export interface ParamProvenanceSummary {
  source: string;
  confidence: string;
  source_step_index?: number | null;
  source_tool_name?: string | null;
  source_evidence_id?: string | null;
  user_confirmed?: boolean;
  revision_created?: number;
}

export interface CandidateItemView {
  global_index: number;
  value: any;
  label: string;
  description?: string | null;
  metadata?: Record<string, any>;
}

export interface CandidateSetView {
  candidate_set_id: string;
  type: string;
  source_step_index?: number | null;
  source_tool_name?: string | null;
  status: string;
  candidate_count: number;
  candidates: CandidateItemView[];
  truncated?: boolean;
}

export interface DiagnosisContextSummary {
  diagnosis_id: string;
  session_id?: string;
  plan_id?: string | null;
  status: string;
  revision: number;
  root_message?: string;
  selected_playbook?: string | null;
  playbook_name?: string | null;
  current_step_index?: number | null;
  current_tool_name?: string | null;
  known_params?: Record<string, any>;
  param_sources?: Record<string, ParamProvenanceSummary>;
  completed_steps?: any[];
  invalidated_step_count?: number;
  pending?: any | null;
  active_candidate_set?: CandidateSetView | null;
  effective_evidence_ids?: string[];
  invalidated_evidence_ids?: string[];
  operation_queue_snapshot?: string[];
  total_auto_steps?: number;
}

export interface DiagnosisOperationSummary {
  operation_id: string;
  idempotency_key?: string | null;
  session_id: string;
  diagnosis_id?: string | null;
  type: string;
  status: string;
  target_pending_id?: string | null;
  expected_revision?: number | null;
  created_at?: string;
  started_at?: string | null;
  completed_at?: string | null;
  error?: string | null;
}

export interface PausedDiagnosisSummary {
  diagnosis_id: string;
  root_message: string;
  created_at: string;
  updated_at: string;
  pending?: any | null;
}

export interface DiagnosisAuditEventView {
  id: string;
  session_id: string;
  diagnosis_id?: string | null;
  event_type: string;
  revision?: number | null;
  payload: Record<string, any>;
  created_at: string;
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
  input_type?: 'params' | 'choice' | 'confirmation' | 'continue_confirmation' | 'text' | 'path' | 'confirm';
  question: string;
  options?: Option[];
  reason?: string;
  session_id: string;
  diagnosis_id?: string;
  context_revision?: number;
  known_context?: Record<string, any>;
  missing?: string[];
  candidate_set_id?: string;
  metadata?: {
    fields?: InputField[];
    resolved_arguments?: Record<string, any>;
    param_sources?: Record<string, any>;
    llm_assistance?: {
      status?: 'ok' | 'timeout' | 'error' | 'disabled';
      stage?: string;
      fallback?: string;
      [key: string]: any;
    };
    [key: string]: any;
  };
  impact?: {
    invalidated_steps?: number[];
    [key: string]: any;
  };
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
