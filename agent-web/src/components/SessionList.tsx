import React, { useEffect } from 'react';
import { List, Card, Button, Empty, Spin, Typography, Tag, Popconfirm } from 'antd';
import { DeleteOutlined, ClockCircleOutlined } from '@ant-design/icons';
import { useSessionListStore } from '../stores';
import { sessionApi } from '../services/api';
import type { Session } from '../types';

const { Text } = Typography;

interface SessionListProps {
  onSelectSession: (session: Session) => void;
}

export const SessionList: React.FC<SessionListProps> = ({ onSelectSession }) => {
  const {
    sessions,
    loading,
    setSessions,
    setLoading,
    setError,
    removeSession,
  } = useSessionListStore();

  useEffect(() => {
    loadSessions();
  }, []);

  const loadSessions = async () => {
    setLoading(true);
    try {
      const data = await sessionApi.list();
      setSessions(data);
    } catch (err: any) {
      setError(err.message || '加载会话列表失败');
    } finally {
      setLoading(false);
    }
  };

  const handleSelect = async (id: string) => {
    setLoading(true);
    try {
      const session = await sessionApi.get(id);
      onSelectSession(session);
    } catch (err: any) {
      setError(err.message || '加载会话详情失败');
    } finally {
      setLoading(false);
    }
  };

  const handleDelete = async (id: string) => {
    try {
      await sessionApi.delete(id);
      removeSession(id);
    } catch (err: any) {
      setError(err.message || '删除失败');
    }
  };

  const formatDate = (dateStr: string) => {
    const date = new Date(dateStr);
    return date.toLocaleString('zh-CN', {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  if (loading) {
    return (
      <div style={{ textAlign: 'center', padding: 40 }}>
        <Spin />
      </div>
    );
  }

  if (sessions.length === 0) {
    return <Empty description="暂无历史会话" />;
  }

  return (
    <List
      dataSource={sessions}
      renderItem={(session) => (
        <List.Item>
          <Card
            size="small"
            style={{ width: '100%', cursor: 'pointer' }}
            onClick={() => handleSelect(session.id)}
            hoverable
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div>
                <Text strong style={{ display: 'block', marginBottom: 4 }}>
                  会话 {session.id.slice(0, 8)}
                </Text>
                <Text type="secondary" style={{ fontSize: 12 }}>
                  <ClockCircleOutlined style={{ marginRight: 4 }} />
                  {formatDate(session.updated_at)}
                </Text>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <Tag>{session.state}</Tag>
                <Text type="secondary" style={{ fontSize: 12 }}>
                  {session.messages?.length || 0} 条消息
                </Text>
                <Popconfirm
                  title="确定删除此会话？"
                  onConfirm={(e) => {
                    e?.stopPropagation();
                    handleDelete(session.id);
                  }}
                  onCancel={(e) => e?.stopPropagation()}
                >
                  <Button
                    type="text"
                    danger
                    icon={<DeleteOutlined />}
                    size="small"
                    onClick={(e) => e.stopPropagation()}
                  />
                </Popconfirm>
              </div>
            </div>
          </Card>
        </List.Item>
      )}
    />
  );
};

export default SessionList;
