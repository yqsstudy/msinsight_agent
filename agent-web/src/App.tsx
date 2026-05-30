import React from 'react';
import { Layout, Menu, Typography } from 'antd';
import { MessageOutlined, HistoryOutlined, DashboardOutlined } from '@ant-design/icons';
import { Routes, Route, useNavigate, useLocation } from 'react-router-dom';
import ChatView from './components/ChatView';
import SessionList from './components/SessionList';
import SystemStatus from './components/SystemStatus';
import { useChatStore } from './stores';
import type { Session } from './types';
import './App.css';

const { Header, Sider, Content } = Layout;
const { Title } = Typography;

const App: React.FC = () => {
  const navigate = useNavigate();
  const location = useLocation();
  const { loadSession } = useChatStore();

  const menuItems = [
    { key: '/chat', icon: <MessageOutlined />, label: '对话' },
    { key: '/sessions', icon: <HistoryOutlined />, label: '历史会话' },
    { key: '/status', icon: <DashboardOutlined />, label: '系统状态' },
  ];

  const handleMenuClick = ({ key }: { key: string }) => {
    navigate(key);
  };

  const handleSelectSession = (session: Session) => {
    loadSession(session);
    navigate('/chat');
  };

  return (
    <Layout style={{ height: '100vh' }}>
      <Sider width={200} theme="light">
        <div style={{ padding: '16px', textAlign: 'center' }}>
          <Title level={4} style={{ margin: 0 }}>
            AI Profiling Agent
          </Title>
        </div>
        <Menu
          mode="inline"
          selectedKeys={[location.pathname]}
          items={menuItems}
          onClick={handleMenuClick}
          style={{ borderRight: 0 }}
        />
      </Sider>
      <Layout>
        <Header style={{ background: '#fff', padding: '0 24px' }}>
          <Title level={4} style={{ margin: 0, lineHeight: '64px' }}>
            {menuItems.find((item) => item.key === location.pathname)?.label || 'AI Profiling Agent'}
          </Title>
        </Header>
        <Content style={{ margin: '16px', overflow: 'auto' }}>
          <div
            style={{
              padding: 24,
              background: '#fff',
              height: '100%',
              borderRadius: 8,
            }}
          >
            <Routes>
              <Route path="/" element={<ChatView />} />
              <Route path="/chat" element={<ChatView />} />
              <Route
                path="/sessions"
                element={<SessionList onSelectSession={handleSelectSession} />}
              />
              <Route path="/status" element={<SystemStatus />} />
            </Routes>
          </div>
        </Content>
      </Layout>
    </Layout>
  );
};

export default App;
