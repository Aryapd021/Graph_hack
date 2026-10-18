import type { paths, components } from './schema';

export type HealthResponse = paths['/api/health']['get']['responses'][200]['content']['application/json'];
export type GraphPayload = components['schemas']['GraphPayload'];
export type GraphNode = components['schemas']['GraphNode'];
export type GraphEdge = components['schemas']['GraphEdge'];
export type NodeLabel = components['schemas']['GraphNode']['label'];
export type Highlight = components['schemas']['Highlight'];
export type Evidence = components['schemas']['Evidence'];
export type TraceStep = components['schemas']['TraceStep'];
export type ChatRequest = components['schemas']['ChatRequest'];
export type ChatResponse = components['schemas']['ChatResponse'];
export type ChatTurn = components['schemas']['ChatTurn'];
export type NodeDetail = components['schemas']['NodeDetail'];
export type DecisionSummary = components['schemas']['DecisionSummary'];
export type ModuleSummary = components['schemas']['ModuleSummary'];
export type ReviewRequestOut = components['schemas']['ReviewRequestOut'];
export type ToolResult = components['schemas']['ToolResult'];
export type SimulatePRResponse = components['schemas']['SimulatePRResponse'];
export type ResetDemoResponse = components['schemas']['ResetDemoResponse'];

export type ErrorCode =
  | 'BAD_REQUEST'
  | 'NOT_FOUND'
  | 'RATE_LIMITED'
  | 'GRAPH_UNAVAILABLE'
  | 'LLM_ERROR'
  | 'INTERNAL';

export interface ErrorResponse {
  error: {
    code: ErrorCode;
    message: string;
  };
}

export class ApiError extends Error {
  code: ErrorCode | 'UNKNOWN';
  status: number;

  constructor(status: number, code: ErrorCode | 'UNKNOWN', message: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
  }
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...init?.headers,
    },
  });

  if (!res.ok) {
    let code: ErrorCode | 'UNKNOWN' = 'UNKNOWN';
    let message = `Request failed with status ${res.status}`;
    try {
      const data = (await res.json()) as ErrorResponse;
      if (data?.error?.code) {
        code = data.error.code;
      }
      if (data?.error?.message) {
        message = data.error.message;
      }
    } catch {
      // Fallback message
    }
    throw new ApiError(res.status, code, message);
  }

  return (await res.json()) as T;
}

export const api = {
  getHealth(): Promise<HealthResponse> {
    return request<HealthResponse>('/api/health');
  },

  getModules(): Promise<ModuleSummary[]> {
    return request<ModuleSummary[]>('/api/modules');
  },

  getGraphOverview(limit: number = 150): Promise<GraphPayload> {
    return request<GraphPayload>(`/api/graph/overview?limit=${limit}`);
  },

  getGraphNeighborhood(nodeId: string, limit: number = 60): Promise<GraphPayload> {
    return request<GraphPayload>(`/api/graph/neighborhood/${encodeURIComponent(nodeId)}?limit=${limit}`);
  },

  getNodeDetail(nodeId: string): Promise<NodeDetail> {
    return request<NodeDetail>(`/api/node/${encodeURIComponent(nodeId)}`);
  },

  getDecisions(): Promise<DecisionSummary[]> {
    return request<DecisionSummary[]>('/api/decisions');
  },

  traceDecision(decisionId: string): Promise<ToolResult> {
    return request<ToolResult>(`/api/decisions/${encodeURIComponent(decisionId)}/trace`);
  },

  flagDecision(decisionId: string, note: string): Promise<{ review_request_id: string; assigned_to: Array<{ id: string; display: string }>; already_open: boolean }> {
    return request(`/api/decisions/${encodeURIComponent(decisionId)}/flag`, {
      method: 'POST',
      body: JSON.stringify({ note }),
    });
  },

  getReviews(): Promise<ReviewRequestOut[]> {
    return request<ReviewRequestOut[]>('/api/reviews');
  },

  simulatePR(moduleId: string, title: string): Promise<SimulatePRResponse> {
    return request<SimulatePRResponse>('/api/demo/simulate-pr', {
      method: 'POST',
      body: JSON.stringify({ module_id: moduleId, title }),
    });
  },

  resetDemo(): Promise<ResetDemoResponse> {
    return request<ResetDemoResponse>('/api/demo/reset', {
      method: 'POST',
    });
  },

  refreshIngest(): Promise<{ new_prs: number; new_files: number }> {
    return request<{ new_prs: number; new_files: number }>('/api/ingest/refresh', {
      method: 'POST',
    });
  },

  sendChat(req: ChatRequest): Promise<ChatResponse> {
    return request<ChatResponse>('/api/chat', {
      method: 'POST',
      body: JSON.stringify(req),
    });
  },
};
