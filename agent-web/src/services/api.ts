import axios from 'axios';
import type {
  Session,
  Message,
  SSEEvent,
  SSEEventType,
  CircuitBreakerStatus,
  HealthCheckResult,
} from '../types';

const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000';

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
    return response.data;
  },

  get: async (id: string): Promise<Session> => {
    const response = await api.get(`/api/sessions/${id}`);
    return response.data;
  },

  create: async (): Promise<Session> => {
    const response = await api.post('/api/sessions');
    return response.data;
  },

  delete: async (id: string): Promise<void> => {
    await api.delete(`/api/sessions/${id}`);
  },
};

// Message APIs

export const messageApi = {
  send: async (sessionId: string, message: string): Promise<Message> => {
    const response = await api.post(`/api/sessions/${sessionId}/messages`, {
      content: message,
    });
    return response.data;
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

      // Parse SSE events
      const events = parseSSEEvents(buffer);
      buffer = events.remaining;

      for (const event of events.parsed) {
        yield event;
      }
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
  },
};

/**
 * 解析SSE事件
 */
function parseSSEEvents(buffer: string): { parsed: SSEEvent[]; remaining: string } {
  const events: SSEEvent[] = [];
  const lines = buffer.split('\n');
  let remaining = '';
  let currentEvent: Partial<SSEEvent> = {};

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];

    if (line === '') {
      // Empty line signals end of event
      if (currentEvent.event && currentEvent.data) {
        events.push({
          event: currentEvent.event as SSEEventType,
          data: currentEvent.data,
          id: currentEvent.id,
        });
      }
      currentEvent = {};
    } else if (line.startsWith('event: ')) {
      currentEvent.event = line.slice(7) as SSEEventType;
    } else if (line.startsWith('data: ')) {
      try {
        currentEvent.data = JSON.parse(line.slice(6));
      } catch {
        currentEvent.data = { raw: line.slice(6) };
      }
    } else if (line.startsWith('id: ')) {
      currentEvent.id = line.slice(4);
    } else {
      // Incomplete line, keep for next iteration
      remaining = line;
    }
  }

  return { parsed: events, remaining };
}

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
    const response = await api.get('/api/error-handling/circuit-breakers');
    return response.data;
  },

  resetCircuitBreaker: async (name: string): Promise<void> => {
    await api.post(`/api/error-handling/circuit-breakers/${name}/reset`);
  },

  errorStats: async (): Promise<Record<string, any>> => {
    const response = await api.get('/api/error-handling/errors/stats');
    return response.data;
  },
};

export default api;
