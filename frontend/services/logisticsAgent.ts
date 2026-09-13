/**
 * 物流 Agent（第五步）服务端接口
 *
 * 配置、启用前检测、线路明细导入与试算均走服务端；
 * 浏览器本地存储不参与 Agent 运行时决策。
 */

export type AgentRecommendMode = 'lowest' | 'all';
export type AgentNoRoutePolicy = 'manual' | 'silent';
export type AgentItemScope = 'all' | 'custom';

export interface AgentCarrierPricingConfig {
  volume_ratio: number | null;
  markup_cost: number;
  markup_manual: number;
  discount_rate: number;
  discount_amount: number;
  quote_line_template?: string;
}

export interface AgentPricingConfig {
  card_face_value: number;
  platform_face_value: number;
  coupon_discount?: number | null;
  profit_markup: number;
  continued_markup: number;
  default_one_kg: boolean;
}

export interface AgentReplyTemplates {
  quote_message: string;
  diff_positive: string;
  diff_zero: string;
  guide_order: string;
  missing_params: string;
  first_reply: string;
  no_route: string;
  failure: string;
}

export interface AgentSettings {
  enabled: boolean;
  model_name: string;
  book_ids: number[];
  auto_send: boolean;
  recommend_mode: AgentRecommendMode;
  no_route_policy: AgentNoRoutePolicy;
  item_scope: AgentItemScope;
  item_ids: string[];
  carrier_config: Record<string, AgentCarrierPricingConfig>;
  default_volume_ratios: Record<string, unknown>;
  pricing: AgentPricingConfig;
  templates: AgentReplyTemplates;
}

export interface AgentRouteImport {
  id: number;
  filename: string;
  file_type: string;
  size_bytes: number;
  sha256: string;
  book_kind: 'express' | 'logistics' | null;
  service_count: number;
  route_count: number;
  status: string;
  warnings: string[];
  carriers?: string[];
  created_at: string | null;
}

export interface AgentStatusCheck {
  key: string;
  label: string;
  passed: boolean;
  detail: string;
}

export interface AgentStatus {
  ready: boolean;
  enabled: boolean;
  auto_send: boolean;
  checks: AgentStatusCheck[];
}

export interface AgentTestDecision {
  action: 'reply' | 'draft' | 'manual' | 'ignore';
  messages: string[];
  reason: string;
  intent: string;
  fields: Record<string, unknown>;
  routes: Array<{
    carrier: string;
    match_level: string;
    match_level_label: string;
    origin: Record<string, string>;
    destination: Record<string, string>;
  }>;
  quotes: Array<Record<string, unknown>>;
  channel_results?: Array<{
    carrier: string;
    status: 'quoted' | 'missing_city' | 'no_route' | 'pricing_failed';
    rule: string;
    total_price: number | null;
    chargeable_weight_kg: number | null;
  }>;
  missing_fields: string[];
  state_version: number;
  session_status: string;
}

export interface AgentChatMessage {
  role: 'buyer' | 'agent';
  content: string;
  id: string;
}

export interface AgentAuditEvent {
  node: string;
  message_id: string;
  state_version: number;
  detail: string;
  error: string;
  elapsed_ms: number;
}

export interface AgentTestResponse {
  handled: boolean;
  thread_id: string;
  detail?: string;
  decision?: AgentTestDecision;
  state?: Record<string, unknown>;
  messages?: AgentChatMessage[];
  events?: AgentAuditEvent[];
}

export interface AgentThreadSnapshot {
  exists: boolean;
  thread_id: string;
  cookie_id?: string;
  chat_id?: string;
  item_id?: string;
  round_id?: number;
  state_version?: number;
  status?: string;
  missing_fields?: string[];
  last_action?: string;
  last_reason?: string;
  session?: Record<string, unknown> | null;
  decision?: AgentTestDecision | null;
  messages: AgentChatMessage[];
  events: AgentAuditEvent[];
}

const jsonHeaders = () => ({
  'Content-Type': 'application/json',
  ...(localStorage.getItem('auth_token')
    ? { Authorization: `Bearer ${localStorage.getItem('auth_token')}` }
    : {}),
});

const authHeaders = () => ({
  ...(localStorage.getItem('auth_token')
    ? { Authorization: `Bearer ${localStorage.getItem('auth_token')}` }
    : {}),
});

const request = async <T>(url: string, init?: RequestInit): Promise<T> => {
  const response = await fetch(url, { ...init, headers: { ...authHeaders(), ...init?.headers } });
  if (!response.ok) {
    let detail = `请求失败（${response.status}）`;
    try {
      const body = await response.json();
      if (typeof body?.detail === 'string') detail = body.detail;
      else if (Array.isArray(body?.detail)) detail = body.detail.map((item: { msg: string }) => item.msg).join('；');
    } catch {
      // 保持默认错误文案
    }
    throw new Error(detail);
  }
  return response.json() as Promise<T>;
};

export const listRouteImports = async (): Promise<{ imports: AgentRouteImport[] }> => {
  const response = await request<{ success: boolean; imports: AgentRouteImport[] }>('/api/logistics/routes/imports');
  return { imports: response.imports };
};

export const importRouteBook = async (file: File): Promise<{ success: boolean; import: AgentRouteImport }> => {
  const formData = new FormData();
  formData.append('file', file);
  const response = await fetch('/api/logistics/routes/import', {
    method: 'POST',
    headers: authHeaders(),
    body: formData,
  });
  if (!response.ok) {
    let detail = `导入失败（${response.status}）`;
    try {
      const body = await response.json();
      if (typeof body?.detail === 'string') detail = body.detail;
    } catch {
      // 保持默认错误文案
    }
    throw new Error(detail);
  }
  return response.json();
};

export const deleteRouteImport = async (importId: number): Promise<void> => {
  await request(`/api/logistics/routes/imports/${importId}`, { method: 'DELETE' });
};

export const getAgentSettings = async (
  cookieId: string,
): Promise<{
  settings: AgentSettings;
  available_books: AgentRouteImport[];
  has_saved_settings: boolean;
}> =>
  request(`/api/logistics/agent/settings/${encodeURIComponent(cookieId)}`);

export const saveAgentSettings = async (cookieId: string, settings: AgentSettings): Promise<{ settings: AgentSettings }> =>
  request(`/api/logistics/agent/settings/${encodeURIComponent(cookieId)}`, {
    method: 'PUT',
    headers: jsonHeaders(),
    body: JSON.stringify(settings),
  });

export const getAgentStatus = async (cookieId: string): Promise<AgentStatus> =>
  request(`/api/logistics/agent/status/${encodeURIComponent(cookieId)}`);

export const runAgentTest = async (payload: {
  cookie_id: string;
  message: string;
  thread_id?: string;
  chat_id?: string;
  item_id?: string;
  message_id?: string;
  reset?: boolean;
}): Promise<AgentTestResponse> =>
  request('/api/logistics/agent/test', {
    method: 'POST',
    headers: jsonHeaders(),
    body: JSON.stringify(payload),
  });

/** 新建测试会话：返回服务端生成的 thread_id。 */
export const createAgentThread = async (cookieId: string): Promise<{ thread_id: string }> =>
  request('/api/logistics/agent/threads', {
    method: 'POST',
    headers: jsonHeaders(),
    body: JSON.stringify({ cookie_id: cookieId }),
  });

/** 读取测试会话快照与消息记录（刷新/重新挂载后恢复上下文）。 */
export const fetchAgentThread = async (threadId: string, cookieId: string): Promise<AgentThreadSnapshot> =>
  request(`/api/logistics/agent/threads/${encodeURIComponent(threadId)}?cookie_id=${encodeURIComponent(cookieId)}`);

/** 清空指定测试会话（状态与消息记录一并删除）。 */
export const deleteAgentThread = async (threadId: string, cookieId: string): Promise<void> => {
  await request(
    `/api/logistics/agent/threads/${encodeURIComponent(threadId)}?cookie_id=${encodeURIComponent(cookieId)}`,
    { method: 'DELETE' },
  );
};

export interface AgentTrainingMessage {
  role: 'buyer' | 'agent';
  content: string;
  position: number;
  decision?: AgentTestDecision;
}

export interface AgentTrainingRound {
  id: string;
  thread_id: string;
  name: string;
  messages: AgentTrainingMessage[];
  created_at: string;
  status: 'collected';
}

export const saveAgentTrainingRound = async (
  cookieId: string,
  payload: Pick<AgentTrainingRound, 'id' | 'thread_id' | 'name' | 'messages'>,
): Promise<{ success: boolean; round: AgentTrainingRound; created: boolean }> => request(
  `/api/logistics/agent/training-rounds?cookie_id=${encodeURIComponent(cookieId)}`,
  { method: 'POST', headers: jsonHeaders(), body: JSON.stringify(payload), signal: AbortSignal.timeout(30000) },
);

export const listAgentTrainingRounds = async (cookieId: string): Promise<{ rounds: AgentTrainingRound[] }> =>
  request(`/api/logistics/agent/training-rounds?cookie_id=${encodeURIComponent(cookieId)}`);

export const exportAgentTrainingRound = async (cookieId: string, roundId: string): Promise<{ messages: Array<{ role: string; content: string }> }> =>
  request(`/api/logistics/agent/training-rounds/${encodeURIComponent(roundId)}/export?cookie_id=${encodeURIComponent(cookieId)}`);
