import {
  LoginResponse, AccountDetail, Order, PaginatedResponse,
  AdminStats, Card, SystemSettings, ApiResponse, OrderAnalytics,
  Item, AIReplySettings, ShippingRule, ReplyRule, DefaultReply
} from '../types';

type QueryParams = Record<
  string,
  string | number | boolean | null | undefined | Array<string | number | boolean>
>;

const buildUrlWithQuery = (url: string, params?: QueryParams): string => {
  if (!params) return url;
  const searchParams = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === null || value === undefined) continue;
    if (Array.isArray(value)) {
      for (const item of value) searchParams.append(key, String(item));
      continue;
    }
    searchParams.append(key, String(value));
  }
  const queryString = searchParams.toString();
  if (!queryString) return url;
  return `${url}${url.includes('?') ? '&' : '?'}${queryString}`;
};

const parseJsonResponse = async <T>(response: Response): Promise<T> => {
  if (response.status === 204) return undefined as T;
  const contentType = response.headers.get('content-type') || '';
  if (contentType.includes('application/json')) return (await response.json()) as T;
  const text = await response.text();
  try {
    return JSON.parse(text) as T;
  } catch {
    return text as T;
  }
};

const requestJson = async <T>(
  method: 'GET' | 'POST' | 'PUT' | 'DELETE',
  url: string,
  options?: { params?: QueryParams; data?: unknown }
): Promise<T> => {
  const token = localStorage.getItem('auth_token');
  const headers: Record<string, string> = {};
  if (token) headers.Authorization = `Bearer ${token}`;

  const finalUrl = method === 'GET' ? buildUrlWithQuery(url, options?.params) : url;
  const init: RequestInit = { method, headers };

  if (method !== 'GET' && options?.data !== undefined) {
    if (options.data instanceof FormData) {
      init.body = options.data;
    } else {
      headers['Content-Type'] = 'application/json';
      init.body = JSON.stringify(options.data);
    }
  }

  const response = await fetch(finalUrl, init);
  const payload = await parseJsonResponse<T>(response);
  if (!response.ok) throw payload;
  return payload;
};

const get = async <T = unknown>(url: string, params?: QueryParams): Promise<T> => {
  return requestJson<T>('GET', url, { params });
};

const post = async <T = unknown>(url: string, data?: unknown): Promise<T> => {
  return requestJson<T>('POST', url, { data });
};

const put = async <T = unknown>(url: string, data?: unknown): Promise<T> => {
  return requestJson<T>('PUT', url, { data });
};

const del = async <T = unknown>(url: string, data?: unknown): Promise<T> => {
  return requestJson<T>('DELETE', url, { data });
};

// Auth
export const login = async (data: { username?: string; password?: string; email?: string; verification_code?: string }): Promise<LoginResponse> => {
  return post('/login', data);
};

export const verifyToken = async (): Promise<{ authenticated: boolean; user_id?: number; username?: string }> => {
  return get('/verify');
};

export const logout = async (): Promise<ApiResponse> => {
  return post('/logout', {});
};

export const changePassword = async (currentPassword: string, newPassword: string): Promise<ApiResponse> => {
  return post('/change-password', { current_password: currentPassword, new_password: newPassword });
};

// Accounts
export const getAccountDetails = async (): Promise<AccountDetail[]> => {
  const data = await get<any[]>('/cookies/details');
  // Map backend fields to UI fields if necessary
  return data.map(item => ({
    id: item.id,
    value: item.value,
    cookie: item.value,
    enabled: item.enabled,
    auto_confirm: item.auto_confirm,
    remark: item.remark,
    note: item.remark,
    pause_duration: item.pause_duration,
    username: item.username,
    login_password: item.login_password,
    show_browser: item.show_browser,
    nickname: item.remark || `Account ${item.id.substring(0,6)}`, // Fallback for UI
    avatar_url: `https://api.dicebear.com/7.x/avataaars/svg?seed=${item.id}`, // Placeholder avatar
    ai_enabled: false, // 需要从AI设置API获取
  }));
};

export const generateQRLogin = async (): Promise<{ success: boolean; session_id?: string; qr_code_url?: string }> => {
  return post('/qr-login/generate');
};

export const checkQRLoginStatus = async (sessionId: string): Promise<any> => {
  return get(`/qr-login/check/${sessionId}`);
};

export const updateAccountStatus = async (id: string, enabled: boolean): Promise<any> => {
  return put(`/cookies/${id}/status`, { enabled });
};

export const deleteAccount = async (id: string): Promise<any> => {
  return del(`/cookies/${id}`);
};

export const updateAccountRemark = async (id: string, remark: string): Promise<any> => {
  return put(`/cookies/${id}/remark`, { remark });
};

export const updateAccountAutoConfirm = async (id: string, autoConfirm: boolean): Promise<any> => {
  return put(`/cookies/${id}/auto-confirm`, { auto_confirm: autoConfirm });
};

export const updateAccountPauseDuration = async (id: string, pauseDuration: number): Promise<any> => {
  return put(`/cookies/${id}/pause-duration`, { pause_duration: pauseDuration });
};

export const updateAccountCookie = async (id: string, value: string): Promise<any> => {
  return put(`/cookies/${id}`, { id, value });
};

export const updateAccountLoginInfo = async (id: string, data: {
  username?: string;
  login_password?: string;
  show_browser?: boolean;
}): Promise<any> => {
  return put(`/cookies/${id}/login-info`, data);
};

export const getAllAISettings = async (): Promise<Record<string, AIReplySettings>> => {
  return get('/ai-reply-settings');
};

// Orders
export const getOrders = async (
  cookieId?: string,
  status?: string,
  page: number = 1,
  pageSize: number = 20
): Promise<PaginatedResponse<Order>> => {
  const params: any = { page, page_size: pageSize };
  if (cookieId) params.cookie_id = cookieId;
  if (status && status !== 'all') params.status = status;

  const res = await get<any>('/api/orders', params);

  // Handle backend response variations
  const orders = res.orders || res.data || [];
  return {
    success: true,
    data: orders,
    total: res.total || orders.length,
    page: res.page || page,
    page_size: res.page_size || pageSize,
    total_pages: res.total_pages || 1
  };
};

export const getOrderDetail = async (orderId: string): Promise<{ success: boolean; data?: Order }> => {
  const result = await get<{ order?: Order; data?: Order }>(`/api/orders/${orderId}`);
  return {
    success: true,
    data: result.order || result.data
  };
};

export const updateOrder = async (orderId: string, data: Partial<Order>): Promise<ApiResponse> => {
  return put(`/api/orders/${orderId}`, data);
};

export const deleteOrder = async (orderId: string): Promise<ApiResponse> => {
  return del(`/api/orders/${orderId}`);
};

export const syncOrders = async (cookieId?: string, status?: string): Promise<any> => {
  const formData = new FormData();
  if (cookieId) formData.append('cookie_id', cookieId);
  if (status) formData.append('status', status);

  // 使用 fetch 来发送 FormData
  const token = localStorage.getItem('auth_token');
  const response = await fetch('/api/orders/refresh', {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${token}`
    },
    body: formData
  });
  return response.json();
};

export const manualShipOrder = async (orderIds: string[], shipMode: 'status_only' | 'full_delivery', content?: string): Promise<any> => {
    return post('/api/orders/manual-ship', {
        order_ids: orderIds,
        ship_mode: shipMode,
        custom_content: content
    });
}

export const importOrders = async (data: Partial<Order>[] | FormData): Promise<any> => {
  const isFormData = data instanceof FormData;
  const response = await fetch('/api/orders/import', {
    method: 'POST',
    headers: {
      ...(isFormData ? {} : { 'Content-Type': 'application/json' }),
      'Authorization': `Bearer ${localStorage.getItem('auth_token')}`
    },
    body: isFormData ? data : JSON.stringify(data)
  });
  return response.json();
}

// Stats
export const getAdminStats = async (): Promise<AdminStats> => {
  return get('/admin/stats');
};

export const getOrderAnalytics = async (daysOrParams: number | {start_date: string; end_date: string} = 7): Promise<OrderAnalytics> => {
    let params: {start_date: string; end_date: string};

    if (typeof daysOrParams === 'number') {
        const endDate = new Date();
        const startDate = new Date();
        startDate.setDate(startDate.getDate() - daysOrParams);
        params = {
            start_date: startDate.toISOString().split('T')[0],
            end_date: endDate.toISOString().split('T')[0]
        };
    } else {
        params = daysOrParams;
    }

    return get('/analytics/orders', params);
}

export const getValidOrders = async (dateRange: {start_date: string; end_date: string}): Promise<Order[]> => {
    const res = await get<any>('/api/orders', {
        start_date: dateRange.start_date,
        end_date: dateRange.end_date,
        page: 1,
        page_size: 1000
    });
    return res.orders || res.data || [];
}

// Cards
export const getCards = async (): Promise<Card[]> => {
  const res = await get<any>('/cards');
  return Array.isArray(res) ? res : (res.cards || []);
};

export const createCard = async (data: Partial<Card>): Promise<{ id: number; message: string }> => {
  return post('/cards', data);
};

export const updateCard = async (cardId: string | number, data: Partial<Card>): Promise<ApiResponse> => {
  return put(`/cards/${cardId}`, data);
};

export const deleteCard = async (cardId: string | number): Promise<ApiResponse> => {
  return del(`/cards/${cardId}`);
};

export const getCardDetails = async (cardId: string | number): Promise<any> => {
  return get(`/cards/${cardId}/details`);
};

// Items
export const getItems = async (): Promise<Item[]> => {
    const res = await get<any>('/items');
    return Array.isArray(res) ? res : (res.items || []);
}

export const syncItemsFromAccount = async (cookieId: string): Promise<any> => {
    return post('/items/get-all-from-account', { cookie_id: cookieId });
}

export const deleteItem = async (cookieId: string, itemId: string): Promise<any> => {
    return del(`/items/${cookieId}/${itemId}`);
}

export const createItem = async (cookieId: string, data: any): Promise<any> => {
    return post(`/items/${cookieId}`, data);
}

export const updateItem = async (cookieId: string, itemId: string, data: any): Promise<any> => {
    return put(`/items/${cookieId}/${itemId}`, data);
}

// Rules - 发货规则 (使用正确的后端API)
export const getShippingRules = async (): Promise<ShippingRule[]> => {
    const res = await get<any>('/delivery-rules');
    const rules = Array.isArray(res) ? res : (res.data || res.rules || []);
    // 转换后端数据格式到前端格式
    return rules.map((item: any) => ({
        id: String(item.id),
        name: item.description || item.keyword || '',
        item_keyword: item.keyword || '',
        card_group_id: item.card_id || 0,
        card_group_name: item.card_name || '',
        priority: item.delivery_count || 1,
        enabled: item.enabled || false
    }));
}

export const updateShippingRule = async (rule: Partial<ShippingRule>): Promise<any> => {
    const payload = {
        keyword: rule.item_keyword,
        card_id: rule.card_group_id,
        delivery_count: rule.priority,
        enabled: rule.enabled ?? true,
        description: rule.name
    };
    return rule.id ? put(`/delivery-rules/${rule.id}`, payload) : post('/delivery-rules', payload);
}

export const deleteShippingRule = async (id: string): Promise<any> => del(`/delivery-rules/${id}`);

// Rules - 关键词回复规则 (使用关键词API)
export const getReplyRules = async (cookieId?: string): Promise<ReplyRule[]> => {
    if (!cookieId) return [];
    const res = await get<any>(`/keywords-with-item-id/${cookieId}`);
    const keywords = Array.isArray(res) ? res : [];
    return keywords.map((item: any, index: number) => ({
        id: String(index),
        keyword: item.keyword || '',
        reply_content: item.reply || '',
        match_type: 'exact' as const,
        enabled: true
    }));
}

export const updateReplyRule = async (rule: Partial<ReplyRule>, cookieId: string): Promise<any> => {
    // 获取现有关键词
    const existing = await get<any>(`/keywords-with-item-id/${cookieId}`);
    const keywords = Array.isArray(existing) ? existing : [];

    // 更新或添加关键词
    if (rule.id) {
        const index = parseInt(rule.id);
        if (index >= 0 && index < keywords.length) {
            keywords[index] = {
                keyword: rule.keyword,
                reply: rule.reply_content,
                item_id: ''
            };
        }
    } else {
        keywords.push({
            keyword: rule.keyword,
            reply: rule.reply_content,
            item_id: ''
        });
    }

    return post(`/keywords-with-item-id/${cookieId}`, { keywords });
}

export const deleteReplyRule = async (id: string, cookieId: string): Promise<any> => {
    const existing = await get<any>(`/keywords-with-item-id/${cookieId}`);
    const keywords = Array.isArray(existing) ? existing : [];
    const index = parseInt(id);
    if (index >= 0 && index < keywords.length) {
        keywords.splice(index, 1);
    }
    return post(`/keywords-with-item-id/${cookieId}`, { keywords });
}

// Settings
export const getSystemSettings = async (): Promise<SystemSettings> => {
    const res = await get<{data: SystemSettings}>('/system-settings');
    return res.data || res; // handle {success:true, data: {...}} wrapper if exists
};

export const updateSystemSettings = async (settings: Partial<SystemSettings>): Promise<ApiResponse> => {
    // API expects individual PUTs, but we'll loop in the service for convenience or assume bulk endpoint if updated
    // Based on docs 12.2, we iterate.
    const promises = Object.entries(settings).map(([key, value]) => {
         return put(`/system-settings/${key}`, { value: String(value) });
    });
    await Promise.all(promises);
    return { success: true, message: 'Settings saved' };
};

export const getAccountAISettings = async (cookieId: string): Promise<AIReplySettings> => {
    return get(`/ai-reply-settings/${cookieId}`);
}

export const updateAccountAISettings = async (cookieId: string, settings: Partial<AIReplySettings>): Promise<ApiResponse> => {
  const payload = {
    ai_enabled: settings.ai_enabled ?? false,
    model_name: settings.model_name ?? 'qwen-plus',
    api_key: settings.api_key ?? '',
    base_url: settings.base_url ?? 'https://dashscope.aliyuncs.com/compatible-mode/v1',
    max_discount_percent: settings.max_discount_percent ?? 10,
    max_discount_amount: settings.max_discount_amount ?? 100,
    max_bargain_rounds: settings.max_bargain_rounds ?? 3,
    custom_prompts: settings.custom_prompts ?? ''
  };
  return put(`/ai-reply-settings/${cookieId}`, payload);
}

export const testAIConnection = async (cookieId: string): Promise<ApiResponse> => {
  const result = await post<{ success?: boolean; message?: string; reply?: string }>(`/ai-reply-test/${cookieId}`, {
    message: '你好，这是一条测试消息',
  });
  if (result.reply) {
    return { success: true, message: `AI 回复: ${result.reply}` };
  }
  return { success: result.success ?? true, message: result.message || 'AI 连接测试成功' };
}

// Notification Channels
export const getNotificationChannels = async (): Promise<{ success: boolean; data?: any[] }> => {
  const result = await get<any[]>('/notification-channels');
  const channels = (result || []).map((item: any) => {
    let parsedConfig;
    try {
      parsedConfig = JSON.parse(item.config);
    } catch {
      parsedConfig = undefined;
    }
    return {
      id: String(item.id),
      name: item.name,
      type: item.type,
      config: parsedConfig,
      enabled: item.enabled,
      created_at: item.created_at,
      updated_at: item.updated_at,
    };
  });
  return { success: true, data: channels };
}

export const createNotificationChannel = async (data: { name: string; type: string; config: Record<string, unknown> }): Promise<ApiResponse> => {
  return post('/notification-channels', {
    ...data,
    config: JSON.stringify(data.config)
  });
}

export const updateNotificationChannel = async (channelId: string, data: { name?: string; config?: Record<string, unknown>; enabled?: boolean }): Promise<ApiResponse> => {
  const payload: Record<string, unknown> = { ...data };
  if ('config' in data) {
    payload.config = JSON.stringify(data.config);
  }
  return put(`/notification-channels/${channelId}`, payload);
}

export const deleteNotificationChannel = async (channelId: string): Promise<ApiResponse> => {
  return del(`/notification-channels/${channelId}`);
}

// Message Notifications
export const getMessageNotifications = async (): Promise<{ success: boolean; data?: any[] }> => {
  const result = await get<Record<string, any[]>>('/message-notifications');
  const notifications = [];
  for (const [cookieId, channelList] of Object.entries(result || {})) {
    if (Array.isArray(channelList)) {
      for (const item of channelList) {
        notifications.push({
          cookie_id: cookieId,
          channel_id: item.channel_id,
          channel_name: item.channel_name,
          enabled: item.enabled,
        });
      }
    }
  }
  return { success: true, data: notifications };
}

export const setMessageNotification = async (cookieId: string, channelId: number, enabled: boolean): Promise<ApiResponse> => {
  return post(`/message-notifications/${cookieId}`, { channel_id: channelId, enabled });
}

export const deleteMessageNotification = async (notificationId: string): Promise<ApiResponse> => {
  return del(`/message-notifications/${notificationId}`);
}

export const deleteAccountNotifications = async (cookieId: string): Promise<ApiResponse> => {
  return del(`/message-notifications/account/${cookieId}`);
}

// Default Reply
export const getDefaultReplies = async (): Promise<Record<string, DefaultReply>> => {
  return get('/api/default-replies');
};

export const getDefaultReply = async (cookieId: string): Promise<DefaultReply> => {
  const result = await get<any>(`/api/default-reply/${cookieId}`);
  return {
    cookie_id: cookieId,
    enabled: result.enabled || false,
    reply_content: result.reply_content || '',
    reply_once: result.reply_once || false,
    reply_image_url: result.reply_image_url || ''
  };
};

export const updateDefaultReply = async (cookieId: string, data: Partial<DefaultReply>): Promise<ApiResponse> => {
  return put(`/api/default-reply/${cookieId}`, {
    enabled: data.enabled ?? false,
    reply_content: data.reply_content || '',
    reply_once: data.reply_once ?? false,
    reply_image_url: data.reply_image_url || ''
  });
};

export const deleteDefaultReply = async (cookieId: string): Promise<ApiResponse> => {
  return del(`/api/default-reply/${cookieId}`);
};

export const clearDefaultReplyRecords = async (cookieId: string): Promise<ApiResponse> => {
  return post(`/api/default-reply/${cookieId}/clear-records`, {});
};
