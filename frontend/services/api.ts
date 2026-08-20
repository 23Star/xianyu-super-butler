import { get, post, put, del } from '../lib/request';
import {
  LoginResponse, AccountDetail, Order, PaginatedResponse,
  AdminStats, Card, SystemSettings, ApiResponse, OrderAnalytics,
  Item, ItemDeliveryConfig, ItemDeliveryConfigSummary,
  ProductVariantBinding, AIReplySettings, ShippingRule, ReplyRule, DefaultReply,
  DeliveryBlockRule, PersonalBlacklistEntry, MessageNotification,
  NotificationChannel, NotificationChannelType, RiskControlLog, SystemLog,
  MessageFilter, MessageFilterType, AutoReplyLog
  , ChatAccount, ChatConversation, ChatMessage, ProductMaterial,
  ProductFilterRule, ProductDeleteRule, AutomationTaskRun,
  ProductAutomationResult, ProductDeletePreview, QuickPhrase,
  AnnouncementPayload
} from '../types';

// Auth
export const login = async (data: { username?: string; password?: string; email?: string; verification_code?: string }): Promise<LoginResponse> => {
  return post('/login', data);
};

/** 登录页需要的开关，未登录也能取。 */
export const getPublicSettings = async (): Promise<{
  registration_enabled?: string;
  show_default_login_info?: string;
  login_captcha_enabled?: string;
  email_verification_enabled?: string;
}> => {
  return get('/system-settings/public');
};

export const register = async (data: {
  username: string;
  email: string;
  password: string;
  verification_code?: string;
}): Promise<ApiResponse> => {
  return post('/register', data);
};

/** 发送邮箱验证码。type 区分注册和登录场景。 */
export const sendVerificationCode = async (email: string, type: 'register' | 'login' = 'register'): Promise<ApiResponse> => {
  return post('/send-verification-code', { email, type });
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
  // 只发一次请求。原实现拿到账号列表后，再逐个请求 /cookie/{id}/details 补
  // username/password/show_browser —— 而列表接口内部本来就查了同一份详情，
  // 等于对同一份数据做 N+1。页面上有 7 处组件各自调用本函数，账号一多首屏
  // 就被这些重复请求拖慢；现在列表接口直接返回这几个字段。
  const data = await get<any[]>('/cookies/details');
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
    nickname: item.nickname || item.remark || item.username || `账号 ${item.id.substring(0, 6)}`,
    avatar_url: item.avatar_url,
    location: item.location,
    bio: item.bio,
    followers: item.followers,
    following: item.following,
    profile_updated_at: item.profile_updated_at,
    runtime_state: item.runtime_state,
    ai_enabled: false,
  })) as AccountDetail[];
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
    total_pages: res.total_pages || 1,
    status_counts: res.status_counts
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

// 卖家端订单同步与互动
export const syncSoldOrders = async (cookieId?: string, days = 7): Promise<any> => {
  const formData = new FormData();
  if (cookieId) formData.append('cookie_id', cookieId);
  formData.append('days', String(days));

  const response = await fetch('/api/orders/sync-sold', {
    method: 'POST',
    headers: { 'Authorization': `Bearer ${localStorage.getItem('auth_token')}` },
    body: formData
  });
  return response.json();
};

export const getOrderRefundRecord = async (orderId: string): Promise<any> => {
  return get(`/api/orders/${orderId}/refund-record`);
};

// 快捷短语：人工客服常用话术
export const getQuickPhrases = async (includeDisabled = false): Promise<QuickPhrase[]> => {
  const res = await get<{ success: boolean; data: QuickPhrase[] }>(
    '/quick-phrases', { include_disabled: includeDisabled }
  );
  return res.data || [];
};

export const createQuickPhrase = async (
  title: string, content: string, category = '默认', sortOrder = 0
): Promise<any> => {
  const formData = new FormData();
  formData.append('title', title);
  formData.append('content', content);
  formData.append('category', category);
  formData.append('sort_order', String(sortOrder));

  const response = await fetch('/quick-phrases', {
    method: 'POST',
    headers: { 'Authorization': `Bearer ${localStorage.getItem('auth_token')}` },
    body: formData
  });
  return response.json();
};

export const updateQuickPhrase = async (
  id: number, fields: Partial<Pick<QuickPhrase, 'title' | 'content' | 'category' | 'sort_order' | 'enabled'>>
): Promise<any> => {
  const formData = new FormData();
  Object.entries(fields).forEach(([key, value]) => {
    if (value !== undefined && value !== null) formData.append(key, String(value));
  });

  const response = await fetch(`/quick-phrases/${id}`, {
    method: 'PUT',
    headers: { 'Authorization': `Bearer ${localStorage.getItem('auth_token')}` },
    body: formData
  });
  return response.json();
};

export const deleteQuickPhrase = async (id: number): Promise<any> => {
  return del(`/quick-phrases/${id}`);
};

export const useQuickPhrase = async (id: number): Promise<any> => {
  return post(`/quick-phrases/${id}/use`);
};

// 风控熔断状态：命中平台风控后账号会暂停请求
export const getRiskControlStatus = async (): Promise<{
  success: boolean;
  blocked_count: number;
  accounts: Array<{
    cookie_id: string;
    blocked: boolean;
    remaining_seconds: number;
    consecutive_hits: number;
    reason: string;
    verification_type: 'none' | 'slider' | 'face' | 'qr' | 'risk_control';
    verification_message: string;
    verification_url?: string;
    latest_event: string;
    latest_event_at?: string;
  }>;
}> => {
  return get('/api/risk-control/status');
};

// 实时取一个新鲜的验证链接。punish 链接的 x5secdata 只能用一次、约 1 小时失效，
// 直接用风控日志里的历史链接打开只会看到「抱歉，页面访问出现了问题」。
export const requestFreshCaptchaUrl = async (cookieId: string): Promise<{
  success: boolean;
  need_verify: boolean;
  verification_url?: string;
  message: string;
}> => {
  return post(`/api/risk-control/${encodeURIComponent(cookieId)}/fresh-captcha-url`);
};

export const startManualCaptchaSession = async (
  cookieId: string,
  timeout: number = 300,
): Promise<{
  success: boolean;
  message: string;
  session_id: string;
}> => {
  const formData = new FormData();
  formData.append('cookie_id', cookieId);
  formData.append('timeout', String(timeout));
  return post('/api/captcha/manual-session', formData, { timeout: (timeout + 30) * 1000 });
};

// 商品擦亮：重新获取搜索曝光，平台对每日次数有限制
export const polishItems = async (cookieId?: string, itemIds?: string[]): Promise<any> => {
  const formData = new FormData();
  if (cookieId) formData.append('cookie_id', cookieId);
  if (itemIds?.length) formData.append('item_ids', itemIds.join(','));

  const response = await fetch('/api/items/polish', {
    method: 'POST',
    headers: { 'Authorization': `Bearer ${localStorage.getItem('auth_token')}` },
    body: formData
  });
  return response.json();
};

// 物流轨迹
export const getOrderLogistics = async (orderId: string): Promise<any> => {
  return get(`/api/orders/${orderId}/logistics`);
};

// 发货信息：规格、收货信息、支持的发货方式
export const getOrderConsignInfo = async (orderId: string): Promise<any> => {
  return get(`/api/orders/${orderId}/consign-info`);
};

// 会向买家发送消息，需先在设置中开启
export const requireOrderFlower = async (orderId: string): Promise<any> => {
  return post(`/api/orders/${orderId}/require-flower`);
};

// 买家互动开关状态。开关按账号存，accounts 是逐账号的映射；
// 顶层两个布尔表示「是否有任意账号开启」，用于决定整块入口要不要出现。
export interface BuyerInteractionFlags {
  auto_rate_enabled: boolean;
  auto_flower_enabled: boolean;
  /** 确认收货后自动给买家发一条致谢文本 */
  auto_thanks_enabled: boolean;
}

export const getSellerFeatureFlags = async (): Promise<{
  accounts?: Record<string, BuyerInteractionFlags>;
  auto_rate_enabled: boolean;
  auto_flower_enabled: boolean;
  auto_rate_template?: string;
}> => {
  return get('/api/seller-features');
};

// 按账号更新评价/求花开关
export const updateSellerFeatureFlags = async (
  cookieId: string,
  payload: Partial<BuyerInteractionFlags>,
): Promise<BuyerInteractionFlags> => {
  return put(`/api/seller-features/${cookieId}`, payload);
};

// 评价提交后不可撤销，需先在设置中开启
export const rateOrders = async (
  orderIds: string[],
  feedback: string,
  rate: 1 | 0 | -1 = 1,
  anonymous = false
): Promise<any> => {
  const formData = new FormData();
  formData.append('order_ids', orderIds.join(','));
  formData.append('feedback', feedback);
  formData.append('rate', String(rate));
  formData.append('anonymous', String(anonymous));

  const response = await fetch('/api/orders/rate', {
    method: 'POST',
    headers: { 'Authorization': `Bearer ${localStorage.getItem('auth_token')}` },
    body: formData
  });
  return response.json();
};

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

export const createManualItem = async (data: {
  cookie_id: string;
  item_id: string;
  title: string;
  price?: string;
  image_url?: string;
  description?: string;
  detail?: string;
}): Promise<{ success: boolean; message: string; item?: Item }> => {
  return post('/items', data);
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

export const getItemDeliveryConfigs = async (): Promise<ItemDeliveryConfigSummary[]> => {
  const response = await get<{ configs?: ItemDeliveryConfigSummary[] }>('/item-delivery-configs');
  return response.configs || [];
}

export const getItemDeliveryConfig = async (
  cookieId: string,
  itemId: string,
): Promise<ItemDeliveryConfig> => {
  return get(`/items/${encodeURIComponent(cookieId)}/${encodeURIComponent(itemId)}/delivery-config`);
}

export const saveItemDeliveryConfig = async (
  cookieId: string,
  itemId: string,
  config: {
    enabled: boolean;
    is_multi_spec: boolean;
    variants: Array<Pick<
      ProductVariantBinding,
      | 'display_name'
      | 'spec_text'
      | 'spec_payload'
      | 'platform_sku_id'
      | 'card_id'
      | 'delivery_count'
      | 'enabled'
      | 'binding_enabled'
      | 'source'
    >>;
  },
): Promise<{ success: boolean; message: string; config: ItemDeliveryConfig }> => {
  return put(
    `/items/${encodeURIComponent(cookieId)}/${encodeURIComponent(itemId)}/delivery-config`,
    config,
  );
}

// Product Automation
export const getProductMaterials = async (cookieId?: string): Promise<ProductMaterial[]> => {
  const response = await get<{ success: boolean; data: ProductMaterial[] }>(
    '/product-automation/materials',
    cookieId ? { cookie_id: cookieId } : undefined,
  );
  return response.data || [];
};

export const updateProductMaterial = async (
  materialId: number,
  changes: Partial<ProductMaterial>,
): Promise<ProductMaterial> => {
  const response = await put<{ success: boolean; data: ProductMaterial }>(
    `/product-automation/materials/${materialId}`,
    changes,
  );
  return response.data;
};

export const deleteProductMaterial = async (materialId: number): Promise<void> => {
  await del(`/product-automation/materials/${materialId}`);
};

export const getProductFilterRules = async (): Promise<ProductFilterRule[]> => {
  const response = await get<{ success: boolean; data: ProductFilterRule[] }>(
    '/product-automation/filter-rules',
  );
  return response.data || [];
};

export const saveProductFilterRule = async (
  data: Partial<ProductFilterRule> & { cookie_id: string; name: string },
): Promise<ProductFilterRule> => {
  const response = data.id
    ? await put<{ success: boolean; data: ProductFilterRule }>(
        `/product-automation/filter-rules/${data.id}`,
        data,
      )
    : await post<{ success: boolean; data: ProductFilterRule }>(
        '/product-automation/filter-rules',
        data,
      );
  return response.data;
};

export const deleteProductFilterRule = async (ruleId: number): Promise<void> => {
  await del(`/product-automation/filter-rules/${ruleId}`);
};

export const runProductFilterRule = async (ruleId: number): Promise<ProductAutomationResult> => {
  const response = await post<{ success: boolean; data: ProductAutomationResult }>(
    `/product-automation/filter-rules/${ruleId}/run`,
    {},
  );
  return response.data;
};

export const getProductDeleteRules = async (): Promise<ProductDeleteRule[]> => {
  const response = await get<{ success: boolean; data: ProductDeleteRule[] }>(
    '/product-automation/delete-rules',
  );
  return response.data || [];
};

export const saveProductDeleteRule = async (
  data: Partial<ProductDeleteRule> & { cookie_id: string; name: string },
): Promise<ProductDeleteRule> => {
  const response = data.id
    ? await put<{ success: boolean; data: ProductDeleteRule }>(
        `/product-automation/delete-rules/${data.id}`,
        data,
      )
    : await post<{ success: boolean; data: ProductDeleteRule }>(
        '/product-automation/delete-rules',
        data,
      );
  return response.data;
};

export const deleteProductDeleteRule = async (ruleId: number): Promise<void> => {
  await del(`/product-automation/delete-rules/${ruleId}`);
};

export const previewProductDeleteRule = async (ruleId: number): Promise<ProductDeletePreview> => {
  const response = await post<{ success: boolean; data: ProductDeletePreview }>(
    `/product-automation/delete-rules/${ruleId}/preview`,
    {},
  );
  return response.data;
};

export const getProductAutomationRuns = async (limit: number = 50): Promise<AutomationTaskRun[]> => {
  const response = await get<{ success: boolean; data: AutomationTaskRun[] }>(
    '/product-automation/runs',
    { limit },
  );
  return response.data || [];
};

const runProductRepair = async (path: string): Promise<ProductAutomationResult> => {
  const response = await post<{ success: boolean; data: ProductAutomationResult }>(path, {});
  return response.data;
};

export const repairPublishedProductIds = () => runProductRepair('/product-automation/repairs/published-ids');
export const repairProductShortLinks = () => runProductRepair('/product-automation/repairs/short-links');
export const compensateProductCards = () => runProductRepair('/product-automation/repairs/cards');

// Rules - 发货规则 (使用正确的后端API)
export const getShippingRules = async (): Promise<ShippingRule[]> => {
    const res = await get<any>('/delivery-rules');
    const rules = Array.isArray(res) ? res : (res.data || res.rules || []);
    // 转换后端数据格式到前端格式
    return rules.map((item: any) => ({
        id: String(item.id),
        name: item.description || item.keyword || '',
        item_keyword: item.keyword || '',
        cookie_id: item.cookie_id || undefined,
        item_id: item.item_id || undefined,
        item_title: item.item_title || undefined,
        card_group_id: item.card_id || 0,
        card_group_name: item.card_name || '',
        priority: item.delivery_count || 1,
        enabled: Boolean(item.enabled),
        delivery_times: item.delivery_times || 0
    }));
}

export const updateShippingRule = async (rule: Partial<ShippingRule>): Promise<any> => {
    const payload = {
        keyword: rule.item_keyword,
        card_id: rule.card_group_id,
        delivery_count: rule.priority,
        enabled: rule.enabled ?? true,
        description: rule.name,
        cookie_id: rule.cookie_id || null,
        item_id: rule.item_id || null
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
    context_enabled: settings.context_enabled ?? true,
    context_message_limit: settings.context_message_limit ?? 12,
    context_expire_minutes: settings.context_expire_minutes ?? 120,
    custom_prompts: settings.custom_prompts ?? ''
  };
  return put(`/ai-reply-settings/${cookieId}`, payload);
}

export const testAIConnection = async (
  cookieId: string,
  payload: {
    message?: string;
    item_title?: string;
    item_price?: number;
    item_desc?: string;
  } = {},
): Promise<ApiResponse & { reply?: string }> => {
  const result = await post<{ success?: boolean; message?: string; reply?: string }>(
    `/ai-reply-test/${cookieId}`,
    { message: '你好，这是一条测试消息', ...payload },
  );
  return {
    success: result.success ?? true,
    message: result.message || 'AI 连接测试成功',
    reply: result.reply,
  };
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

// Message Filters
export const getMessageFilters = async (params: {
  cookie_id?: string;
  filter_type?: MessageFilterType;
} = {}): Promise<MessageFilter[]> => {
  const response = await get<{ success: boolean; data: MessageFilter[] }>('/message-filters', params);
  return response.data || [];
};

export const createMessageFilter = async (data: {
  cookie_id: string;
  keyword: string;
  filter_type: MessageFilterType;
  enabled?: boolean;
}): Promise<MessageFilter> => {
  const response = await post<{ success: boolean; data: MessageFilter }>('/message-filters', data);
  return response.data;
};

export const batchCreateMessageFilters = async (data: {
  cookie_id: string;
  keywords: string[];
  filter_type: MessageFilterType;
  enabled?: boolean;
}): Promise<{ success: boolean; created: number; skipped: number }> => {
  return post('/message-filters/batch-create', data);
};

export const updateMessageFilter = async (
  filterId: number,
  data: Partial<Pick<MessageFilter, 'keyword' | 'filter_type' | 'enabled'>>
): Promise<MessageFilter> => {
  const response = await put<{ success: boolean; data: MessageFilter }>(
    `/message-filters/${filterId}`,
    data
  );
  return response.data;
};

export const toggleMessageFilter = async (filterId: number): Promise<MessageFilter> => {
  const response = await put<{ success: boolean; data: MessageFilter }>(
    `/message-filters/${filterId}/toggle`,
    {}
  );
  return response.data;
};

export const deleteMessageFilter = async (filterId: number): Promise<void> => {
  await del(`/message-filters/${filterId}`);
};

export const batchDeleteMessageFilters = async (ids: number[]): Promise<number> => {
  const response = await post<{ success: boolean; deleted: number }>(
    '/message-filters/batch-delete',
    { ids }
  );
  return response.deleted;
};

// Auto Reply Decision Logs
export const getAutoReplyLogs = async (params: {
  cookie_id?: string;
  process_status?: string;
  reply_strategy?: string;
  send_status?: string;
  keyword?: string;
  page?: number;
  page_size?: number;
} = {}): Promise<PaginatedResponse<AutoReplyLog>> => {
  return get('/auto-reply-logs', params);
};

// Xianyu IM
export const getChatAccounts = async (): Promise<ChatAccount[]> => {
  const response = await get<{ success: boolean; data: ChatAccount[] }>('/chat/accounts');
  return response.data || [];
};

export const getChatConversations = async (
  cookieId: string,
  cursor?: number,
  limit: number = 30
): Promise<{ conversations: ChatConversation[]; hasMore: boolean; nextCursor?: number }> => {
  const response = await get<{
    success: boolean;
    data: { conversations: ChatConversation[]; hasMore: boolean; nextCursor?: number };
  }>(`/chat/conversations/${encodeURIComponent(cookieId)}`, { cursor, limit });
  return response.data;
};

export const getChatMessages = async (
  cookieId: string,
  cid: string,
  cursor?: number,
  limit: number = 50
): Promise<{ messages: ChatMessage[]; hasMore: boolean; nextCursor?: number }> => {
  const response = await get<{
    success: boolean;
    data: { messages: ChatMessage[]; hasMore: boolean; nextCursor?: number };
  }>(
    `/chat/messages/${encodeURIComponent(cookieId)}/${encodeURIComponent(cid)}`,
    { cursor, limit }
  );
  return response.data;
};

export const markChatConversationRead = async (
  cookieId: string,
  data: { cid: string; message_id: string }
): Promise<{ success: boolean; message: string; data?: { cid?: string } }> => {
  return post(`/chat/read/${encodeURIComponent(cookieId)}`, data);
};

export const sendChatMessage = async (
  cookieId: string,
  data: { cid: string; to_user_id: string; text: string }
): Promise<{ success: boolean; message: string; data?: { messageId?: string } }> => {
  return post(`/chat/send/${encodeURIComponent(cookieId)}`, data);
};

export const sendChatImage = async (
  cookieId: string,
  data: { cid: string; to_user_id: string; image: File }
): Promise<{ success: boolean; message: string; data?: { messageId?: string; imageUrl?: string } }> => {
  const form = new FormData();
  form.append('cid', data.cid);
  form.append('to_user_id', data.to_user_id);
  form.append('image', data.image);
  return post(`/chat/send-image/${encodeURIComponent(cookieId)}`, form, { timeout: 60000 });
};

export const sendChatVideo = async (
  cookieId: string,
  data: { cid: string; to_user_id: string; video: File }
): Promise<{ success: boolean; message: string; data?: { messageId?: string; videoUrl?: string } }> => {
  const form = new FormData();
  form.append('cid', data.cid);
  form.append('to_user_id', data.to_user_id);
  form.append('video', data.video);
  return post(`/chat/send-video/${encodeURIComponent(cookieId)}`, form, { timeout: 120000 });
};

export const getPlayableAudio = async (url: string): Promise<Blob> => {
  return post('/chat/media/audio', { url }, { responseType: 'blob', timeout: 60000 });
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

// 全局公告与版本检查：后端代拉公网 JSON 并缓存，force 用于「立即检查更新」
export const getAnnouncement = async (force = false): Promise<AnnouncementPayload> => {
  return get('/api/announcement', force ? { force: true } : undefined);
};
