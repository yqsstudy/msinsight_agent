import React, { useEffect, useState } from 'react';
import { Card, Descriptions, Tag, Spin, Alert, Button, Space, Statistic, Row, Col } from 'antd';
import { CheckCircleOutlined, CloseCircleOutlined, ExclamationCircleOutlined, ReloadOutlined } from '@ant-design/icons';
import { systemApi } from '../services/api';
import type { HealthCheckResult, CircuitBreakerStatus, HealthStatus } from '../types';

export const SystemStatus: React.FC = () => {
  const [health, setHealth] = useState<HealthCheckResult | null>(null);
  const [circuitBreakers, setCircuitBreakers] = useState<Record<string, CircuitBreakerStatus>>({});
  const [errorStats, setErrorStats] = useState<Record<string, any>>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadStatus = async () => {
    setLoading(true);
    setError(null);
    try {
      const [healthData, cbData, statsData] = await Promise.all([
        systemApi.health(),
        systemApi.circuitBreakers(),
        systemApi.errorStats(),
      ]);
      setHealth(healthData);
      setCircuitBreakers(cbData);
      setErrorStats(statsData);
    } catch (err: any) {
      setError(err.message || '加载状态失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadStatus();
    // 每30秒刷新
    const interval = setInterval(loadStatus, 30000);
    return () => clearInterval(interval);
  }, []);

  const handleResetCircuitBreaker = async (name: string) => {
    try {
      await systemApi.resetCircuitBreaker(name);
      loadStatus();
    } catch (err: any) {
      setError(err.message || '重置失败');
    }
  };

  const getStatusIcon = (status: HealthStatus) => {
    switch (status) {
      case 'healthy':
        return <CheckCircleOutlined style={{ color: '#52c41a' }} />;
      case 'degraded':
        return <ExclamationCircleOutlined style={{ color: '#faad14' }} />;
      case 'unhealthy':
        return <CloseCircleOutlined style={{ color: '#ff4d4f' }} />;
    }
  };

  const getStatusTag = (status: HealthStatus) => {
    const colors = {
      healthy: 'success',
      degraded: 'warning',
      unhealthy: 'error',
    };
    return <Tag color={colors[status]}>{status}</Tag>;
  };

  const getCircuitStateTag = (state: string) => {
    const colors: Record<string, string> = {
      closed: 'success',
      open: 'error',
      half_open: 'warning',
    };
    return <Tag color={colors[state] || 'default'}>{state}</Tag>;
  };

  if (loading && !health) {
    return (
      <div style={{ textAlign: 'center', padding: 40 }}>
        <Spin />
      </div>
    );
  }

  return (
    <div>
      {error && (
        <Alert
          message="错误"
          description={error}
          type="error"
          closable
          onClose={() => setError(null)}
          style={{ marginBottom: 16 }}
        />
      )}

      {/* 健康状态 */}
      <Card title="服务健康状态" extra={<Button icon={<ReloadOutlined />} onClick={loadStatus} />}>
        {health && (
          <>
            <Row gutter={16} style={{ marginBottom: 16 }}>
              <Col span={8}>
                <Statistic
                  title="整体状态"
                  value={health.status}
                  prefix={getStatusIcon(health.status)}
                />
              </Col>
              <Col span={8}>
                <Statistic
                  title="运行时间"
                  value={Math.floor(health.uptime_seconds / 3600)}
                  suffix="小时"
                />
              </Col>
              <Col span={8}>
                <Statistic
                  title="组件数"
                  value={health.components?.length || 0}
                />
              </Col>
            </Row>

            <Descriptions title="组件状态" bordered size="small" column={1}>
              {health.components?.map((comp) => (
                <Descriptions.Item
                  key={comp.name}
                  label={comp.name}
                >
                  <Space>
                    {getStatusTag(comp.status)}
                    <span>{comp.message}</span>
                    {comp.latency_ms && (
                      <Tag>{comp.latency_ms.toFixed(0)}ms</Tag>
                    )}
                  </Space>
                </Descriptions.Item>
              ))}
            </Descriptions>
          </>
        )}
      </Card>

      {/* 熔断器状态 */}
      <Card title="熔断器状态" style={{ marginTop: 16 }}>
        {Object.keys(circuitBreakers).length === 0 ? (
          <span>暂无熔断器</span>
        ) : (
          <Descriptions bordered size="small" column={1}>
            {Object.entries(circuitBreakers).map(([name, cb]) => (
              <Descriptions.Item key={name} label={name}>
                <Space direction="vertical" style={{ width: '100%' }}>
                  <Space>
                    {getCircuitStateTag(cb.state)}
                    <span>
                      成功: {cb.stats.successful_calls} / 失败: {cb.stats.failed_calls}
                    </span>
                    {cb.state === 'open' && (
                      <Button
                        size="small"
                        onClick={() => handleResetCircuitBreaker(name)}
                      >
                        重置
                      </Button>
                    )}
                  </Space>
                  {cb.stats.last_failure_error && (
                    <span style={{ color: '#ff4d4f', fontSize: 12 }}>
                      最后错误: {cb.stats.last_failure_error}
                    </span>
                  )}
                </Space>
              </Descriptions.Item>
            ))}
          </Descriptions>
        )}
      </Card>

      {/* 错误统计 */}
      <Card title="错误统计" style={{ marginTop: 16 }}>
        {Object.keys(errorStats.counts || {}).length === 0 ? (
          <span>暂无错误记录</span>
        ) : (
          <Descriptions bordered size="small" column={2}>
            {Object.entries(errorStats.counts || {}).map(([type, count]) => (
              <Descriptions.Item key={type} label={type}>
                <Tag color="red">{String(count)} 次</Tag>
              </Descriptions.Item>
            ))}
          </Descriptions>
        )}
      </Card>
    </div>
  );
};

export default SystemStatus;
