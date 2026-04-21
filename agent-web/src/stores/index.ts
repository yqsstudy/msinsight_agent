import { create } from 'zustand';
import type { Message, Option, AnalysisReport, Session } from '../types';

interface ChatState {
  // 当前会话
  sessionId: string | null;
  messages: Message[];

  // 流式输出状态
  isStreaming: boolean;
  currentContent: string;

  // 用户输入请求
  waitingForInput: boolean;
  inputQuestion: string;
  inputOptions: Option[];
  inputReason: string;

  // 分析报告
  report: AnalysisReport | null;

  // 错误
  error: string | null;

  // Actions
  setSessionId: (id: string) => void;
  addMessage: (message: Message) => void;
  updateLastMessage: (content: string) => void;
  startStreaming: () => void;
  stopStreaming: () => void;
  appendContent: (content: string) => void;
  clearContent: () => void;
  setUserInputRequired: (question: string, options: Option[], reason: string) => void;
  clearUserInputRequired: () => void;
  setReport: (report: AnalysisReport) => void;
  setError: (error: string | null) => void;
  reset: () => void;
  loadSession: (session: Session) => void;
}

export const useChatStore = create<ChatState>((set, get) => ({
  // Initial state
  sessionId: null,
  messages: [],
  isStreaming: false,
  currentContent: '',
  waitingForInput: false,
  inputQuestion: '',
  inputOptions: [],
  inputReason: '',
  report: null,
  error: null,

  // Actions
  setSessionId: (id) => set({ sessionId: id }),

  addMessage: (message) => set((state) => ({
    messages: [...state.messages, message],
  })),

  updateLastMessage: (content) => set((state) => {
    const messages = [...state.messages];
    if (messages.length > 0) {
      messages[messages.length - 1] = {
        ...messages[messages.length - 1],
        content,
      };
    }
    return { messages };
  }),

  startStreaming: () => set({ isStreaming: true, currentContent: '' }),

  stopStreaming: () => {
    const state = get();
    // 将流式内容添加为消息
    if (state.currentContent) {
      set({
        isStreaming: false,
        messages: [
          ...state.messages,
          {
            id: `agent-${Date.now()}`,
            role: 'agent',
            content: state.currentContent,
            timestamp: new Date().toISOString(),
          },
        ],
        currentContent: '',
      });
    } else {
      set({ isStreaming: false, currentContent: '' });
    }
  },

  appendContent: (content) => set((state) => ({
    currentContent: state.currentContent + content,
  })),

  clearContent: () => set({ currentContent: '' }),

  setUserInputRequired: (question, options, reason) => set({
    waitingForInput: true,
    inputQuestion: question,
    inputOptions: options,
    inputReason: reason,
  }),

  clearUserInputRequired: () => set({
    waitingForInput: false,
    inputQuestion: '',
    inputOptions: [],
    inputReason: '',
  }),

  setReport: (report) => set({ report }),

  setError: (error) => set({ error }),

  reset: () => set({
    sessionId: null,
    messages: [],
    isStreaming: false,
    currentContent: '',
    waitingForInput: false,
    inputQuestion: '',
    inputOptions: [],
    inputReason: '',
    report: null,
    error: null,
  }),

  loadSession: (session) => set({
    sessionId: session.id,
    messages: session.messages,
    report: null,
    error: null,
    waitingForInput: session.state === 'WAITING_INPUT',
  }),
}));

// Session List Store

interface SessionListState {
  sessions: Session[];
  loading: boolean;
  error: string | null;
  setSessions: (sessions: Session[]) => void;
  setLoading: (loading: boolean) => void;
  setError: (error: string | null) => void;
  removeSession: (id: string) => void;
}

export const useSessionListStore = create<SessionListState>((set) => ({
  sessions: [],
  loading: false,
  error: null,
  setSessions: (sessions) => set({ sessions }),
  setLoading: (loading) => set({ loading }),
  setError: (error) => set({ error }),
  removeSession: (id) => set((state) => ({
    sessions: state.sessions.filter((s) => s.id !== id),
  })),
}));
