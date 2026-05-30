import { create } from 'zustand';
import type { Message, Option, AnalysisReport, Session, HarnessTraceEvent, ExecutionPlan, Evidence } from '../types';

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
  traceEvents: HarnessTraceEvent[];
  plans: ExecutionPlan[];
  evidence: Evidence[];
  reports: any[];
  pendingInput: any | null;

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
  setPlans: (plans: ExecutionPlan[]) => void;
  upsertPlan: (plan: ExecutionPlan) => void;
  updateStep: (step: any) => void;
  setEvidence: (evidence: Evidence[]) => void;
  setReports: (reports: any[]) => void;
  setPendingInput: (pendingInput: any | null) => void;
  addTraceEvent: (event: HarnessTraceEvent) => void;
  clearTraceEvents: () => void;
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
  traceEvents: [],
  plans: [],
  evidence: [],
  reports: [],
  pendingInput: null,
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

  setPlans: (plans) => set({ plans }),

  upsertPlan: (plan) => set((state) => ({
    plans: state.plans.some((item) => item.id === plan.id)
      ? state.plans.map((item) => (item.id === plan.id ? plan : item))
      : [...state.plans, plan],
  })),

  updateStep: (step) => set((state) => ({
    plans: state.plans.map((plan) => {
      if (plan.id !== step.plan_id) return plan;
      const steps = plan.steps.some((item) => item.id === step.id)
        ? plan.steps.map((item) => (item.id === step.id ? { ...item, ...step } : item))
        : [...plan.steps, step];
      return { ...plan, steps };
    }),
  })),

  setEvidence: (evidence) => set({ evidence }),

  setReports: (reports) => set({ reports }),

  setPendingInput: (pendingInput) => set({ pendingInput }),

  addTraceEvent: (event) => set((state) => ({
    traceEvents: [...state.traceEvents, event],
  })),

  clearTraceEvents: () => set({ traceEvents: [] }),

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
    traceEvents: [],
    plans: [],
    evidence: [],
    reports: [],
    pendingInput: null,
    error: null,
  }),

  loadSession: (session) => {
    const latestReport = session.reports?.[0];
    set({
      sessionId: session.id,
      messages: session.messages ?? [],
      isStreaming: false,
      currentContent: '',
      report: latestReport
        ? {
            id: latestReport.id,
            report_id: latestReport.id,
            format: latestReport.format,
            content: latestReport.content,
            evidence_ids: latestReport.evidence_ids ?? [],
            summary: latestReport.content?.split('\n').find((line: string) => line.trim() && !line.startsWith('#')),
          }
        : null,
      traceEvents: [],
      plans: session.plans ?? [],
      evidence: session.evidence ?? [],
      reports: session.reports ?? [],
      pendingInput: session.pending_input ?? null,
      inputQuestion: session.pending_input?.question ?? '',
      inputOptions: session.pending_input?.options ?? [],
      inputReason: session.pending_input?.reason ?? '',
      error: null,
      waitingForInput: session.state === 'WAITING_INPUT' || Boolean(session.pending_input),
    });
  },
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
