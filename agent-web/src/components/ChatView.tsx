import React, { useState, useRef, useEffect } from 'react';
import { Input, Button, Space, Alert, Card, Typography, Tag, Timeline } from 'antd';
import { SendOutlined, LoadingOutlined, FileTextOutlined } from '@ant-design/icons';
import { useChatStore } from '../stores';
import { reportApi, streamApi } from '../services/api';
import type { SSEEvent, Option, UserInputRequiredData, AnalysisResultData, ReportReadyData, HarnessTraceEvent } from '../types';

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
  analysis_result: '分析结论',
  report_ready: '报告已生成',
};

export const ChatView: React.FC = () => {
  const [inputValue, setInputValue] = useState('');
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
        addTraceEvent(buildTraceEvent(event));
        break;

      case 'user_input_required': {
        const userInputData = event.data as UserInputRequiredData;
        setPendingInput(userInputData);
        setUserInputRequired(
          userInputData.question,
          userInputData.options || [],
          userInputData.reason
        );
        addTraceEvent(buildTraceEvent(event));
        break;
      }

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
    const detail = data.name || data.summary || data.reason || data.query || data.tool_name || data.report_id || data.intent || data.type;
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
