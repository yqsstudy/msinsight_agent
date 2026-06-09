import React, { useState, useRef, useEffect } from 'react';
import { Input, Button, Space, Alert, Card, Typography, Tag, Timeline, Select } from 'antd';
import { SendOutlined, LoadingOutlined, FileTextOutlined, DatabaseOutlined, OrderedListOutlined } from '@ant-design/icons';
import { useChatStore } from '../stores';
import { reportApi, streamApi } from '../services/api';
import type { SSEEvent, Option, InputField, UserInputRequiredData, AnalysisResultData, ReportReadyData, HarnessTraceEvent, DiagnosisContextSummary, CandidateSetView, DiagnosisAuditEventView, DiagnosisOperationSummary } from '../types';

const { TextArea } = Input;
const { Text, Paragraph } = Typography;

const traceTitleMap: Record<string, string> = {
  execution_plan_created: '创建执行计划',
  execution_step_started: '开始执行步骤',
  execution_step_completed: '完成执行步骤',
  execution_step_failed: '执行步骤失败',
  intent_detected: '识别意图',
  rag_retrieval: '检索知识库',
  mcp_tool_start: '开始执行 MCP 工具',
  mcp_tool_result: 'MCP 工具返回结果',
  control_flow_waiting: '等待 MCP 事件',
  control_flow_retrying: '重试 MCP 工具',
  analysis_result: '分析结论',
  report_ready: '报告已生成',
  diagnosis_context_updated: '诊断上下文更新',
  diagnosis_step_invalidated: '诊断步骤失效',
  diagnosis_rollback_detected: '检测到回退',
  diagnosis_auto_fill: '自动补全参数',
  diagnosis_operation_queued: '诊断操作入队',
  diagnosis_operation_updated: '诊断操作更新',
  diagnosis_candidate_set_created: '候选集创建',
  diagnosis_candidate_selected: '候选项已选择',
  diagnosis_reconciliation: 'MCP 状态协调',
  diagnosis_schema_drift: 'Schema 变化',
  diagnosis_audit_event: '诊断审计事件',
  diagnosis_pending_routed: 'Pending 输入路由',
};

export const ChatView: React.FC = () => {
  const [inputValue, setInputValue] = useState('');
  const [fieldValues, setFieldValues] = useState<Record<string, any>>({});
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const {
    sessionId,
    messages,
    isStreaming,
    currentContent,
    waitingForInput,
    inputQuestion,
    inputOptions,
    inputReason,
    report,
    traceEvents,
    diagnosisContext,
    diagnosisOperations,
    activeCandidateSet,
    pausedDiagnoses,
    diagnosisAuditEvents,
    pendingInput,
    error,
    setSessionId,
    addMessage,
    startStreaming,
    stopStreaming,
    appendContent,
    setUserInputRequired,
    clearUserInputRequired,
    setReport,
    upsertPlan,
    updateStep,
    setPendingInput,
    setDiagnosisContext,
    upsertDiagnosisOperation,
    setActiveCandidateSet,
    addDiagnosisAuditEvent,
    addTraceEvent,
    clearTraceEvents,
    setError,
  } = useChatStore();

  // 自动滚动到底部
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, currentContent]);

  // 发送消息
  const handleSend = async () => {
    if (!inputValue.trim() || isStreaming) return;

    const message = inputValue.trim();
    setInputValue('');

    addMessage({
      id: `user-${Date.now()}`,
      role: 'user',
      content: message,
      timestamp: new Date().toISOString(),
    });

    try {
      startStreaming();

      if (waitingForInput && sessionId) {
        clearUserInputRequired();
        for await (const event of streamApi.continueAnalysis(sessionId, message)) {
          handleSSEEvent(event);
        }
      } else {
        clearTraceEvents();
        for await (const event of streamApi.sendMessage(message, sessionId || undefined)) {
          handleSSEEvent(event);
        }
      }

      stopStreaming();
    } catch (err: any) {
      setError(err.message || '发送失败');
      stopStreaming();
    }
  };

  const handleSubmitFields = async () => {
    if (!sessionId || !pendingInput) return;
    const fields = ((pendingInput as UserInputRequiredData).metadata?.fields || []);
    const missingRequired = fields.some((field) => field.required !== false && (fieldValues[field.name] === undefined || fieldValues[field.name] === ''));
    if (missingRequired) {
      setError('请补充必填参数');
      return;
    }

    clearUserInputRequired();
    setFieldValues({});
    addMessage({
      id: `user-${Date.now()}`,
      role: 'user',
      content: fields.map((field) => `${field.label || field.name}: ${String(fieldValues[field.name])}`).join('，'),
      timestamp: new Date().toISOString(),
    });

    try {
      startStreaming();
      for await (const event of streamApi.continueAnalysis(sessionId, fieldValues)) {
        handleSSEEvent(event);
      }
      stopStreaming();
    } catch (err: any) {
      setError(err.message || '继续分析失败');
      stopStreaming();
    }
  };

  // 处理用户选择
  const handleSelectOption = async (option: Option) => {
    if (!sessionId) return;

    clearUserInputRequired();
    addMessage({
      id: `user-${Date.now()}`,
      role: 'user',
      content: option.label,
      timestamp: new Date().toISOString(),
    });

    try {
      startStreaming();

      for await (const event of streamApi.continueAnalysis(sessionId, option.value)) {
        handleSSEEvent(event);
      }

      stopStreaming();
    } catch (err: any) {
      setError(err.message || '继续分析失败');
      stopStreaming();
    }
  };

  // 处理SSE事件
  const handleSSEEvent = (event: SSEEvent) => {
    switch (event.event) {
      case 'message_start':
        if ('session_id' in event.data) {
          setSessionId(event.data.session_id);
        }
        break;

      case 'message_delta':
        if ('content' in event.data) {
          appendContent(event.data.content);
        }
        break;

      case 'execution_plan_created':
        upsertPlan(event.data as any);
        addTraceEvent(buildTraceEvent(event));
        break;

      case 'execution_step_started':
      case 'execution_step_completed':
      case 'execution_step_failed':
        updateStep(event.data as any);
        addTraceEvent(buildTraceEvent(event));
        break;

      case 'intent_detected':
      case 'rag_retrieval':
      case 'mcp_tool_start':
      case 'mcp_tool_result':
      case 'control_flow_waiting':
      case 'control_flow_retrying':
        addTraceEvent(buildTraceEvent(event));
        break;

      case 'user_input_required': {
        const userInputData = event.data as UserInputRequiredData;
        setPendingInput(userInputData);
        const defaults: Record<string, any> = {};
        (userInputData.metadata?.fields || []).forEach((field) => {
          if (field.value !== undefined) defaults[field.name] = field.value;
          else if (field.options?.length === 1) defaults[field.name] = field.options[0].value;
        });
        setFieldValues(defaults);
        setUserInputRequired(
          userInputData.question,
          userInputData.options || [],
          userInputData.reason || ''
        );
        addTraceEvent(buildTraceEvent(event));
        break;
      }

      case 'diagnosis_context_updated':
        setDiagnosisContext(event.data as DiagnosisContextSummary);
        addTraceEvent(buildTraceEvent(event));
        break;

      case 'diagnosis_operation_queued':
      case 'diagnosis_operation_updated':
        upsertDiagnosisOperation(event.data as DiagnosisOperationSummary);
        addTraceEvent(buildTraceEvent(event));
        break;

      case 'diagnosis_candidate_set_created':
        setActiveCandidateSet(event.data as CandidateSetView);
        addTraceEvent(buildTraceEvent(event));
        break;

      case 'diagnosis_candidate_selected':
        setActiveCandidateSet(null);
        addTraceEvent(buildTraceEvent(event));
        break;

      case 'diagnosis_audit_event':
        addDiagnosisAuditEvent(event.data as DiagnosisAuditEventView);
        addTraceEvent(buildTraceEvent(event));
        break;

      case 'diagnosis_step_invalidated':
      case 'diagnosis_rollback_detected':
      case 'diagnosis_auto_fill':
      case 'diagnosis_reconciliation':
      case 'diagnosis_schema_drift':
      case 'diagnosis_pending_routed':
        addTraceEvent(buildTraceEvent(event));
        break;

      case 'analysis_result': {
        const analysisData = event.data as AnalysisResultData;
        if (analysisData.report) {
          setReport(analysisData.report);
        }
        if (analysisData.summary) {
          appendContent(analysisData.summary);
        }
        addTraceEvent(buildTraceEvent(event));
        break;
      }

      case 'report_ready': {
        const reportData = event.data as ReportReadyData;
        addTraceEvent(buildTraceEvent(event));
        if (reportData.report_id) {
          void loadReport(reportData.report_id);
        }
        break;
      }

      case 'error': {
        const errorData = event.data as Record<string, any>;
        setError(errorData.error || errorData.message || errorData.code || '请求处理失败');
        addTraceEvent(buildTraceEvent(event));
        break;
      }
    }
  };

  const loadReport = async (reportId: string) => {
    try {
      const loadedReport = await reportApi.get(reportId);
      setReport({
        id: loadedReport.id,
        report_id: loadedReport.id,
        format: loadedReport.format,
        content: loadedReport.content,
        evidence_ids: loadedReport.evidence_ids,
        summary: loadedReport.content.split('\n').find((line) => line.trim() && !line.startsWith('#')),
      });
    } catch (err: any) {
      setError(err.message || '加载报告失败');
    }
  };

  const buildTraceEvent = (event: SSEEvent): HarnessTraceEvent => {
    const data = event.data as Record<string, any>;
    const title = traceTitleMap[event.event] || event.event;
    const detail = data.name || data.summary || data.reason || data.control_flow?.reason || data.event_name || data.query || data.tool_name || data.report_id || data.intent || data.type;
    return {
      id: event.id || `${event.event}-${Date.now()}-${Math.random()}`,
      event: event.event,
      title,
      detail,
      status: data.status || data.state || (data.error ? 'failed' : undefined),
      timestamp: new Date().toISOString(),
      data,
    };
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      {/* 消息列表 */}
      <div
        style={{
          flex: 1,
          overflow: 'auto',
          padding: '16px',
          backgroundColor: '#f5f5f5',
        }}
      >
        {messages.map((msg) => (
          <div
            key={msg.id}
            style={{
              display: 'flex',
              justifyContent: msg.role === 'user' ? 'flex-end' : 'flex-start',
              marginBottom: '12px',
            }}
          >
            <Card
              size="small"
              style={{
                maxWidth: '70%',
                backgroundColor: msg.role === 'user' ? '#e6f7ff' : '#fff',
              }}
            >
              <Text>{msg.content}</Text>
            </Card>
          </div>
        ))}

        {/* 流式输出内容 */}
        {isStreaming && currentContent && (
          <div style={{ marginBottom: '12px' }}>
            <Card size="small" style={{ maxWidth: '70%', backgroundColor: '#fff' }}>
              <Text>{currentContent}</Text>
              <LoadingOutlined style={{ marginLeft: 8 }} />
            </Card>
          </div>
        )}

        {/* 诊断上下文 */}
        {(diagnosisContext || activeCandidateSet || diagnosisOperations.length > 0 || pausedDiagnoses.length > 0) && (
          <DiagnosisContextPanel
            context={diagnosisContext}
            operations={diagnosisOperations}
            candidateSet={activeCandidateSet}
            pausedDiagnoses={pausedDiagnoses}
            auditEvents={diagnosisAuditEvents}
          />
        )}

        {/* 执行过程 */}
        {traceEvents.length > 0 && <TraceTimeline events={traceEvents} />}

        {/* 用户输入选项 */}
        {waitingForInput && (
          <Card
            size="small"
            style={{ marginBottom: '12px', maxWidth: '70%' }}
          >
            <Paragraph strong>{inputQuestion}</Paragraph>
            {inputReason && (
              <Text type="secondary" style={{ display: 'block', marginBottom: 8 }}>
                💡 {inputReason}
              </Text>
            )}
            <InvalidationImpactDialog impact={(pendingInput as UserInputRequiredData | null)?.impact} />
            {((pendingInput as UserInputRequiredData | null)?.metadata?.param_sources) && (
              <Space direction="vertical" style={{ width: '100%', marginBottom: 8 }}>
                {Object.entries((pendingInput as UserInputRequiredData).metadata?.param_sources || {}).map(([key, source]) => (
                  (source as any)?.display ? <Text key={key} type="secondary">{(source as any).display}</Text> : null
                ))}
              </Space>
            )}
            {(pendingInput as UserInputRequiredData | null)?.metadata?.llm_assistance?.status === 'timeout' && (
              <Alert type="info" showIcon message="智能参数解析超时，已切换为规则解析。" style={{ marginBottom: 8 }} />
            )}
            {((pendingInput as UserInputRequiredData | null)?.metadata?.fields?.length || 0) > 0 ? (
              <FieldInputPanel
                fields={(pendingInput as UserInputRequiredData).metadata?.fields || []}
                values={fieldValues}
                onChange={(name, value) => setFieldValues((prev) => ({ ...prev, [name]: value }))}
                onSubmit={handleSubmitFields}
                disabled={isStreaming}
              />
            ) : (
              <Space direction="vertical" style={{ width: '100%' }}>
                {inputOptions.map((opt, idx) => (
                  <Button
                    key={idx}
                    block
                    onClick={() => handleSelectOption(opt)}
                  >
                    {opt.label}
                    {opt.description && (
                      <Text type="secondary" style={{ marginLeft: 8 }}>
                        - {opt.description}
                      </Text>
                    )}
                  </Button>
                ))}
              </Space>
            )}
          </Card>
        )}

        {/* 分析报告 */}
        {report && <ReportCard report={report} />}

        {/* 错误提示 */}
        {error && (
          <Alert
            message="错误"
            description={error}
            type="error"
            closable
            onClose={() => setError(null)}
            style={{ marginBottom: 12 }}
          />
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* 输入框 */}
      <div style={{ padding: '16px', backgroundColor: '#fff', borderTop: '1px solid #f0f0f0' }}>
        <Space.Compact style={{ width: '100%' }}>
          <TextArea
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            placeholder="输入数据路径或问题描述..."
            autoSize={{ minRows: 1, maxRows: 4 }}
            onPressEnter={(e) => {
              if (!e.shiftKey) {
                e.preventDefault();
                handleSend();
              }
            }}
            disabled={isStreaming}
            style={{ borderRadius: '8px 0 0 8px' }}
          />
          <Button
            type="primary"
            icon={isStreaming ? <LoadingOutlined /> : <SendOutlined />}
            onClick={handleSend}
            disabled={!inputValue.trim() || isStreaming}
            style={{ borderRadius: '0 8px 8px 0', height: 'auto' }}
          />
        </Space.Compact>
      </div>
    </div>
  );
};

const FieldInputPanel: React.FC<{
  fields: InputField[];
  values: Record<string, any>;
  onChange: (name: string, value: any) => void;
  onSubmit: () => void;
  disabled?: boolean;
}> = ({ fields, values, onChange, onSubmit, disabled }) => (
  <Space direction="vertical" style={{ width: '100%' }}>
    {fields.map((field) => (
      <div key={field.name}>
        <Text strong>{field.label || field.name}</Text>
        {field.required !== false && <Text type="danger"> *</Text>}
        {field.description && (
          <Text type="secondary" style={{ display: 'block', marginBottom: 4 }}>
            {field.description}
          </Text>
        )}
        {field.type === 'select' && field.options?.length ? (
          <Select
            style={{ width: '100%' }}
            value={values[field.name]}
            placeholder={`请选择${field.label || field.name}`}
            disabled={disabled}
            onChange={(value) => onChange(field.name, value)}
            options={field.options.map((option) => ({
              label: option.description ? `${option.label} - ${option.description}` : option.label,
              value: option.value as any,
            }))}
          />
        ) : (
          <Input
            value={values[field.name] ?? ''}
            placeholder={field.description || `请输入${field.label || field.name}`}
            disabled={disabled}
            onChange={(event) => onChange(field.name, event.target.value)}
          />
        )}
      </div>
    ))}
    <Button type="primary" onClick={onSubmit} disabled={disabled}>
      提交参数
    </Button>
  </Space>
);

const DiagnosisContextPanel: React.FC<{
  context: DiagnosisContextSummary | null;
  operations: DiagnosisOperationSummary[];
  candidateSet: CandidateSetView | null;
  pausedDiagnoses: any[];
  auditEvents: DiagnosisAuditEventView[];
}> = ({ context, operations, candidateSet, pausedDiagnoses, auditEvents }) => (
  <Card title={<Space><DatabaseOutlined />诊断上下文</Space>} size="small" style={{ marginBottom: 12, maxWidth: '90%' }}>
    {context && (
      <Space direction="vertical" style={{ width: '100%' }}>
        <Space wrap>
          <Tag color="blue">{context.diagnosis_id}</Tag>
          <Tag>{context.status}</Tag>
          <Tag>rev {context.revision}</Tag>
          {context.current_tool_name && <Tag color="purple">{context.current_tool_name}</Tag>}
        </Space>
        {context.known_params && Object.keys(context.known_params).length > 0 && (
          <ParameterProvenancePanel params={context.known_params} sources={context.param_sources || {}} />
        )}
      </Space>
    )}
    {candidateSet && <CandidateSetPanel candidateSet={candidateSet} />}
    {operations.length > 0 && <DiagnosisOperationQueue operations={operations} />}
    {pausedDiagnoses.length > 0 && <PausedDiagnosisList diagnoses={pausedDiagnoses} />}
    {auditEvents.length > 0 && <Text type="secondary">审计事件：{auditEvents.length}</Text>}
  </Card>
);

const ParameterProvenancePanel: React.FC<{ params: Record<string, any>; sources: Record<string, any> }> = ({ params, sources }) => (
  <div>
    <Text strong>参数：</Text>
    <Space size={[4, 4]} wrap style={{ marginLeft: 8 }}>
      {Object.entries(params).map(([key, value]) => (
        <Tag key={key}>{key}={String(value)} · {sources[key]?.source || 'unknown'}</Tag>
      ))}
    </Space>
  </div>
);

const CandidateSetPanel: React.FC<{ candidateSet: CandidateSetView }> = ({ candidateSet }) => (
  <div style={{ marginTop: 8 }}>
    <Text strong><OrderedListOutlined /> 候选集：</Text>
    <Space size={[4, 4]} wrap style={{ marginLeft: 8 }}>
      {candidateSet.candidates.map((item) => (
        <Tag key={item.global_index}>#{item.global_index} {item.label}</Tag>
      ))}
      {candidateSet.truncated && <Tag color="orange">仅展示前 20 / {candidateSet.candidate_count}</Tag>}
    </Space>
  </div>
);

const DiagnosisOperationQueue: React.FC<{ operations: DiagnosisOperationSummary[] }> = ({ operations }) => (
  <div style={{ marginTop: 8 }}>
    <Text strong>操作队列：</Text>
    <Space size={[4, 4]} wrap style={{ marginLeft: 8 }}>
      {operations.slice(-5).map((operation) => (
        <Tag key={operation.operation_id} color={operation.status === 'failed' || operation.status === 'stale' ? 'red' : operation.status === 'completed' ? 'green' : 'blue'}>
          {operation.type}:{operation.status}
        </Tag>
      ))}
    </Space>
  </div>
);

const PausedDiagnosisList: React.FC<{ diagnoses: any[] }> = ({ diagnoses }) => (
  <div style={{ marginTop: 8 }}>
    <Text strong>已暂停诊断：</Text>
    <Space size={[4, 4]} wrap style={{ marginLeft: 8 }}>
      {diagnoses.map((diagnosis) => <Tag key={diagnosis.diagnosis_id}>{diagnosis.diagnosis_id}</Tag>)}
    </Space>
  </div>
);

const InvalidationImpactDialog: React.FC<{ impact?: { invalidated_steps?: number[] } }> = ({ impact }) => {
  if (!impact?.invalidated_steps?.length) return null;
  return <Alert type="warning" message={`将失效步骤：${impact.invalidated_steps.join(', ')}`} />;
};

const TraceTimeline: React.FC<{ events: HarnessTraceEvent[] }> = ({ events }) => (
  <Card title="执行过程" size="small" style={{ marginBottom: 12, maxWidth: '90%' }}>
    <Timeline
      items={events.map((event) => ({
        color: event.event === 'execution_step_failed' || event.status === 'failed' ? 'red' : event.event === 'user_input_required' ? 'orange' : event.event === 'report_ready' || event.status === 'completed' ? 'green' : 'blue',
        children: (
          <div>
            <Space size="small" wrap>
              <Text strong>{event.title}</Text>
              {event.status && <Tag>{event.status}</Tag>}
            </Space>
            {event.detail && (
              <Paragraph type="secondary" style={{ marginBottom: 0 }} ellipsis={{ rows: 2, expandable: true }}>
                {String(event.detail)}
              </Paragraph>
            )}
          </div>
        ),
      }))}
    />
  </Card>
);

// 分析报告卡片
const ReportCard: React.FC<{ report: any }> = ({ report }) => {
  if (!report) return null;

  return (
    <Card
      title={
        <Space>
          <FileTextOutlined />
          <span>分析报告</span>
          {report.report_id && <Tag color="blue">{report.report_id}</Tag>}
        </Space>
      }
      size="small"
      style={{ marginBottom: 12 }}
    >
      {report.content ? (
        <Paragraph style={{ whiteSpace: 'pre-wrap' }}>{report.content}</Paragraph>
      ) : (
        <>
          {report.summary && (
            <Paragraph>{report.summary}</Paragraph>
          )}

          {report.problems?.length > 0 && (
            <>
              <Text strong>发现问题：</Text>
              {report.problems.map((p: any, idx: number) => (
                <div key={idx} style={{ marginBottom: 8 }}>
                  <Tag color={p.severity === 'high' ? 'red' : p.severity === 'medium' ? 'orange' : 'green'}>
                    {p.type}
                  </Tag>
                  <Text>{p.description}</Text>
                </div>
              ))}
            </>
          )}

          {report.suggestions?.length > 0 && (
            <>
              <Text strong>优化建议：</Text>
              <ul style={{ margin: '8px 0', paddingLeft: 20 }}>
                {report.suggestions.map((s: string, idx: number) => (
                  <li key={idx}>{s}</li>
                ))}
              </ul>
            </>
          )}
        </>
      )}

      {report.evidence_ids?.length > 0 && (
        <div style={{ marginTop: 12 }}>
          <Text strong>Evidence：</Text>
          <Space size={[4, 4]} wrap style={{ marginLeft: 8 }}>
            {report.evidence_ids.map((id: string) => <Tag key={id}>{id}</Tag>)}
          </Space>
        </div>
      )}
    </Card>
  );
};

export default ChatView;
