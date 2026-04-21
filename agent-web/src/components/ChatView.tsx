import React, { useState, useRef, useEffect } from 'react';
import { Input, Button, Space, Alert, Card, Typography, Tag } from 'antd';
import { SendOutlined, LoadingOutlined } from '@ant-design/icons';
import { useChatStore } from '../stores';
import { streamApi } from '../services/api';
import type { SSEEvent, Option, UserInputRequiredData, AnalysisResultData } from '../types';

const { TextArea } = Input;
const { Text, Paragraph } = Typography;

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
    error,
    setSessionId,
    addMessage,
    startStreaming,
    stopStreaming,
    appendContent,
    setUserInputRequired,
    clearUserInputRequired,
    setReport,
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

    // 添加用户消息
    addMessage({
      id: `user-${Date.now()}`,
      role: 'user',
      content: message,
      timestamp: new Date().toISOString(),
    });

    try {
      startStreaming();

      // 流式发送
      for await (const event of streamApi.sendMessage(message, sessionId || undefined)) {
        handleSSEEvent(event);
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

      case 'user_input_required':
        const userInputData = event.data as UserInputRequiredData;
        setUserInputRequired(
          userInputData.question,
          userInputData.options,
          userInputData.reason
        );
        break;

      case 'analysis_result':
        const analysisData = event.data as AnalysisResultData;
        setReport(analysisData.report);
        break;

      case 'error':
        if ('error' in event.data) {
          setError(event.data.error);
        }
        break;
    }
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
            disabled={isStreaming || waitingForInput}
            style={{ borderRadius: '8px 0 0 8px' }}
          />
          <Button
            type="primary"
            icon={isStreaming ? <LoadingOutlined /> : <SendOutlined />}
            onClick={handleSend}
            disabled={!inputValue.trim() || isStreaming || waitingForInput}
            style={{ borderRadius: '0 8px 8px 0', height: 'auto' }}
          />
        </Space.Compact>
      </div>
    </div>
  );
};

// 分析报告卡片
const ReportCard: React.FC<{ report: any }> = ({ report }) => {
  if (!report) return null;

  return (
    <Card
      title="分析报告"
      size="small"
      style={{ marginBottom: 12 }}
    >
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
    </Card>
  );
};

export default ChatView;
