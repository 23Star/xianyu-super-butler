import { get, post, put, del } from '../lib/request';
import {
  LoginResponse, AccountDetail, Order, PaginatedResponse,
  AdminStats, Card, SystemSettings, ApiResponse, OrderAnalytics,
  Item, AIReplySettings, ShippingRule, ReplyRule, DefaultReply,
  DeliveryBlockRule, PersonalBlacklistEntry, MessageNotification,
  NotificationChannel, NotificationChannelType, RiskControlLog, SystemLog
} from '../types';

// Auth
export const login = async (data: { username?: string; password?: string; email?: string; verification_code?: string }): Promise<LoginResponse> => {
  return post('/login', data);
};

export const verifyToken = async (): Promise<{ authenticated: boolean; user_id?: number; username?: string; is_admin?: boolean }> => {
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
  return Promise.all(data.map(async item => {
    let details: any = {};
    try {
      details = await get(`/cookie/${item.id}/details`);
    } catch {
      // 详情加载失败时保留基础账号数据，避免整页不可用。
    }

    return {
      ...details,
      id: item.id,
      value: item.value,
      cookie: item.value,
      enabled: item.enabled,
      auto_confirm: item.auto_confirm,
      remark: item.remark,
      note: item.remark,
      pause_duration: item.pause_duration,
      username: details.username,
      login_password: details.password || details.login_password,
      show_browser: details.show_browser,
      nickname: item.nickname || details.nickname || item.remark || details.username || `账号 ${item.id.substring(0, 6)}`,
      avatar_url: item.avatar_url || details.avatar_url,
      location: item.location || details.location,
      bio: item.bio || details.bio,
      followers: item.followers ?? details.followers,
      following: item.following ?? details.following,
      profile_updated_at: item.profile_updated_at || details.profile_updated_at,
      ai_enabled: false,
    };
  }));
};

export const refreshAccountProfile = async (id: string): Promise<{ success: boolean; profile?: Partial<AccountDetail> }> => {
  return post(`/cookies/${id}/refresh-profile`);
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
const normalizeOrder = (order: any): Order => {
  const normalizedStatus = order?.order_status || order?.status || 'processing';
  return {
    ...order,
    status: normalizedStatus,
    order_status: normalizedStatus,
  };
};

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
  const orders = (res.orders || res.data || []).map(normalizeOrder);
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
  const order = result.order || result.data;
  return {
    success: true,
    data: order ? normalizeOrder(order) : undefined
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

export const syncSingleOrder = async (orderId: string): Promise<any> => {
  return post(`/api/orders/${orderId}/refresh`);
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
    const res = await get<any>('/analytics/orders/valid', {
        start_date: dateRange.start_date,
        end_date: dateRange.end_date
    });
    return res.orders || [];
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
  return get(`/cards/${cardId}`);
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

export const updateItemDetail = async (cookieId: string, itemId: string, itemDetail: string): Promise<any> => {
    return put(`/items/${cookieId}/${itemId}`, { item_detail: itemDetail });
}

export const updateItemMultiSpec = async (cookieId: string, itemId: string, enabled: boolean): Promise<any> => {
    return put(`/items/${cookieId}/${itemId}/multi-spec`, { is_multi_spec: enabled });
}

export const updateItemMultiQuantity = async (cookieId: string, itemId: string, enabled: boolean): Promise<any> => {
    return put(`/items/${cookieId}/${itemId}/multi-quantity-delivery`, { multi_quantity_delivery: enabled });
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

export const getDeliveryBlockRules = async (cookieId: string): Promise<DeliveryBlockRule[]> => {
  const response = await get<{ success: boolean; rules: DeliveryBlockRule[] }>(
    `/delivery-block-rules/${cookieId}`
  );
  return response.rules;
};

export const updateDeliveryBlockRule = async (
  cookieId: string,
  ruleCode: string,
  changes: Partial<DeliveryBlockRule>
): Promise<DeliveryBlockRule> => {
  const response = await put<{ success: boolean; rule: DeliveryBlockRule }>(
    `/delivery-block-rules/${cookieId}/${ruleCode}`,
    changes
  );
  return response.rule;
};

export const getPersonalBlacklist = async (cookieId?: string): Promise<PersonalBlacklistEntry[]> => {
  const response = await get<{ success: boolean; entries: PersonalBlacklistEntry[] }>(
    '/blacklist',
    cookieId ? { cookie_id: cookieId } : undefined
  );
  return response.entries;
};

export const createPersonalBlacklist = async (
  item: Partial<PersonalBlacklistEntry> & { buyer_id: string }
): Promise<PersonalBlacklistEntry> => {
  const response = await post<{ success: boolean; entry: PersonalBlacklistEntry }>(
    '/blacklist',
    item
  );
  return response.entry;
};

export const updatePersonalBlacklist = async (
  entryId: number,
  changes: Partial<PersonalBlacklistEntry>
): Promise<PersonalBlacklistEntry> => {
  const response = await put<{ success: boolean; entry: PersonalBlacklistEntry }>(
    `/blacklist/${entryId}`,
    changes
  );
  return response.entry;
};

export const deletePersonalBlacklist = async (entryId: number): Promise<void> => {
  await del(`/blacklist/${entryId}`);
};

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
export const getNotificationChannels = async (): Promise<{ success: boolean; data: NotificationChannel[] }> => {
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
      type: item.type as NotificationChannelType,
      config: parsedConfig || {},
      enabled: item.enabled,
      created_at: item.created_at,
      updated_at: item.updated_at,
    };
  });
  return { success: true, data: channels };
}

export const createNotificationChannel = async (data: { name: string; type: NotificationChannelType; config: Record<string, unknown> }): Promise<ApiResponse> => {
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
export const getMessageNotifications = async (): Promise<{ success: boolean; data: MessageNotification[] }> => {
  const result = await get<Record<string, any[]>>('/message-notifications');
  const notifications: MessageNotification[] = [];
  for (const [cookieId, channelList] of Object.entries(result || {})) {
    if (Array.isArray(channelList)) {
      for (const item of channelList) {
        notifications.push({
          id: String(item.id),
          cookie_id: cookieId,
          channel_id: item.channel_id,
          channel_name: item.channel_name,
          channel_type: item.channel_type,
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

export const getRiskControlLogs = async (params: {
  cookie_id?: string;
  processing_status?: string;
  limit?: number;
  offset?: number;
} = {}): Promise<{ success: boolean; data: RiskControlLog[]; total: number; limit: number; offset: number }> => {
  return get('/risk-control-logs', params);
};

export const deleteRiskControlLog = async (logId: number): Promise<ApiResponse> => {
  return del(`/risk-control-logs/${logId}`);
};

export const getSystemLogs = async (params: {
  lines?: number;
  level?: string;
  source?: string;
} = {}): Promise<{ success: boolean; logs: SystemLog[]; message?: string }> => {
  return get('/logs', params);
};

// Default Reply
export const getDefaultReplies = async (): Promise<Record<string, DefaultReply>> => {
  return get('/default-replies');
};

export const getDefaultReply = async (cookieId: string): Promise<DefaultReply> => {
  const result = await get<any>(`/default-replies/${cookieId}`);
  return {
    cookie_id: cookieId,
    enabled: result.enabled || false,
    reply_content: result.reply_content || '',
    reply_once: result.reply_once || false,
    reply_image_url: result.reply_image_url || ''
  };
};

export const updateDefaultReply = async (cookieId: string, data: Partial<DefaultReply>): Promise<ApiResponse> => {
  return put(`/default-replies/${cookieId}`, {
    enabled: data.enabled ?? false,
    reply_content: data.reply_content || '',
    reply_once: data.reply_once ?? false,
    reply_image_url: data.reply_image_url || ''
  });
};

export const deleteDefaultReply = async (cookieId: string): Promise<ApiResponse> => {
  return del(`/default-replies/${cookieId}`);
};

export const clearDefaultReplyRecords = async (cookieId: string): Promise<ApiResponse> => {
  return post(`/default-replies/${cookieId}/clear-records`, {});
};
