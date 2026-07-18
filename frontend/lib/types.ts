// frontend/lib/types.ts

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  /** Tool progress cards shown inside assistant messages */
  toolStates?: ToolState[];
  /** Validation report shown inside assistant messages */
  report?: Report | null;
}

export interface ToolState {
  name: string;
  label: string;
  status: 'running' | 'success' | 'error';
  result?: string;
  error?: string;
  /** For multi-page OCR progress */
  current?: number;
  total?: number;
}

export interface Report {
  passed: boolean | null;
  amounts?: Record<string, number | string>;
  results?: RuleResult[];
  error?: string;
}

export interface RuleResult {
  rule: string;
  passed: boolean | null;
  detail: string;
}

/** SSE event data types */
export type SseEvent =
  | { type: 'delta'; data: { content: string } }
  | { type: 'tool_start'; data: { tool: string; label: string } }
  | { type: 'tool_progress'; data: { tool: string; current: number; total: number } }
  | { type: 'tool_end'; data: { tool: string; status: 'success' | 'error'; result?: string; error?: string } }
  | { type: 'report'; data: Report }
  | { type: 'done'; data: Record<string, never> }
  | { type: 'error'; data: { error: string } };
