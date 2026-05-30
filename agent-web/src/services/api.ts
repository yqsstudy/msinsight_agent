import axios from 'axios';
import type {
  Session,
  SSEEvent,
  SSEEventType,
  CircuitBreakerStatus,
  HealthCheckResult,
  HarnessReport,
} from '../types';

const API_BASE = import.meta.env.VITE_API_BASE;

if (!API_BASE) {
  throw new Error('VITE_API_BASE is required');
}

const api = axios.create({
  baseURL: API_BASE,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Session APIs

export const sessionApi = {
  list: async (): Promise<Session[]> => {
    const response = await api.get('/api/sessions');
    return (response.data.sessions ?? []).map((session: any) => ({
      ...session,
      messages: session.messages ?? [],
    }));
  },

  get: async (id: string): Promise<Session> => {
    const response = await api.get(`/api/sessions/${id}`);
    return {
      ...response.data.session,
      messages: response.data.session?.messages ?? [],
      plans: response.data.plans ?? [],
      evidence: response.data.evidence ?? [],
      reports: response.data.reports ?? [],
      pending_input: response.data.pending_input ?? null,
    };
  },

  create: async (): Promise<Session> => {
    const response = await api.post('/api/sessions');
    return {
      id: response.data.session_id,
      created_at: response.data.created_at,
      updated_at: response.data.created_at,
      state: 'IDLE',
      messages: [],
    };
  },

  delete: async (id: string): Promise<void> => {
    await api.delete(`/api/sessions/${id}`);
  },
};

// Streaming APIs (SSE)

export const streamApi = {
  /**
   * 流式发送消息
   */
  sendMessage: async function* (
    message: string,
    sessionId?: string
  ): AsyncGenerator<SSEEvent> {
    const response = await fetch(`${API_BASE}/api/stream/message`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'text/event-stream',
      },
      body: JSON.stringify({ message, session_id: sessionId }),
    });

    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }

    const reader = response.body?.getReader();
    if (!reader) {
      throw new Error('No response body');
    }

    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });

      const events = parseSSEEvents(buffer);
      buffer = events.remaining;

      for (const event of events.parsed) {
        yield event;
      }
    }

    buffer += decoder.decode();
    const events = parseSSEEvents(buffer, true);
    for (const event of events.parsed) {
      yield event;
    }
  },

  /**
   * 流式继续分析
   */
  continueAnalysis: async function* (
    sessionId: string,
    userInput: any
  ): AsyncGenerator<SSEEvent> {
    const response = await fetch(`${API_BASE}/api/stream/continue`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'text/event-stream',
      },
      body: JSON.stringify({ session_id: sessionId, user_input: userInput }),
    });

    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }

    const reader = response.body?.getReader();
    if (!reader) {
      throw new Error('No response body');
    }

    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });

      const events = parseSSEEvents(buffer);
      buffer = events.remaining;

      for (const event of events.parsed) {
        yield event;
      }
    }

    buffer += decoder.decode();
    const events = parseSSEEvents(buffer, true);
    for (const event of events.parsed) {
      yield event;
    }
  },
};

/**
 * 解析SSE事件
 */
function parseSSEEvents(buffer: string, flush = false): { parsed: SSEEvent[]; remaining: string } {
  const events: SSEEvent[] = [];
  const normalized = buffer.replace(/\r\n/g, '\n').replace(/\r/g, '\n');
  const lines = normalized.split('\n');
  const completeLineCount = flush || normalized.endsWith('\n') ? lines.length : lines.length - 1;
  let currentEvent: SSEEventType | undefined;
  let currentId: string | undefined;
  let dataLines: string[] = [];

  const emit = () => {
    if (!currentEvent || dataLines.length === 0) {
      currentEvent = undefined;
      currentId = undefined;
      dataLines = [];
      return;
    }

    const dataText = dataLines.join('\n');
    let data: any;
    try {
      data = JSON.parse(dataText);
    } catch {
      data = { raw: dataText };
    }

    events.push({ event: currentEvent, data, id: currentId });
    currentEvent = undefined;
    currentId = undefined;
    dataLines = [];
  };

  for (let i = 0; i < completeLineCount; i++) {
    const line = lines[i];
    if (line === '') {
      emit();
      continue;
    }
    if (line.startsWith(':')) {
      continue;
    }

    const separator = line.indexOf(':');
    const field = separator === -1 ? line : line.slice(0, separator);
    const value = separator === -1 ? '' : line.slice(separator + 1).replace(/^ /, '');

    if (field === 'event') {
      currentEvent = value as SSEEventType;
    } else if (field === 'data') {
      dataLines.push(value);
    } else if (field === 'id') {
      currentId = value;
    }
  }

  if (flush) {
    emit();
    return { parsed: events, remaining: '' };
  }

  return { parsed: events, remaining: lines.slice(completeLineCount).join('\n') };
}

// Report APIs

export const reportApi = {
  listBySession: async (sessionId: string): Promise<HarnessReport[]> => {
    const response = await api.get(`/api/reports/sessions/${sessionId}`);
    return response.data.reports;
  },

  get: async (reportId: string): Promise<HarnessReport> => {
    const response = await api.get(`/api/reports/${reportId}`);
    return response.data.report;
  },

  submitFeedback: async (
    reportId: string,
    sessionId: string,
    adopted: boolean | null,
    comment?: string
  ): Promise<void> => {
    await api.post(`/api/reports/${reportId}/feedback`, {
      session_id: sessionId,
      adopted,
      comment,
    });
  },
};

// System Status APIs

export const systemApi = {
  health: async (): Promise<HealthCheckResult> => {
    const response = await api.get('/health');
    return response.data;
  },

  liveness: async (): Promise<{ status: string }> => {
    const response = await api.get('/live');
    return response.data;
  },

  readiness: async (): Promise<{ status: string }> => {
    const response = await api.get('/ready');
    return response.data;
  },

  circuitBreakers: async (): Promise<Record<string, CircuitBreakerStatus>> => {
    try {
      const response = await api.get('/api/error-handling/circuit-breakers');
      return response.data;
    } catch {
      return {};
    }
  },

  resetCircuitBreaker: async (name: string): Promise<void> => {
    await api.post(`/api/error-handling/circuit-breakers/${name}/reset`);
  },

  errorStats: async (): Promise<Record<string, any>> => {
    try {
      const response = await api.get('/api/error-handling/errors/stats');
      return response.data;
    } catch {
      return { counts: {} };
    }
  },
};

export default api;
