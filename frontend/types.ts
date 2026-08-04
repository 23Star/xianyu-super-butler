
// API Response Bases
export interface ApiResponse {
  success?: boolean;
  message?: string;
  msg?: string;
}

export interface PaginatedResponse<T> {
  success: boolean;
  data: T[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

// Auth
export interface LoginResponse {
  success: boolean;
  token?: string;
  message?: string;
  user_id?: number;
  username?: string;
  is_admin?: boolean;
}

// Accounts
export interface AccountDetail {
  id: string;
  value?: string; // cookie value from backend
  cookie?: string; // alias for value
  enabled: boolean;
  auto_confirm: boolean;
  remark?: string;
  note?: string; // alias for remark
  pause_duration?: number;
  // 登录信息
  username?: string;
  login_password?: string;
  show_browser?: boolean;
  // Frontend helpers
  nickname?: string;
  avatar_url?: string;
  location?: string;
  bio?: string;
  followers?: number;
  following?: number;
  profile_updated_at?: string;
  // AI设置
  ai_enabled?: boolean;
  max_discount_percent?: number;
  max_discount_amount?: number;
  max_bargain_rounds?: number;
  custom_prompts?: string;
}

// Orders
export type OrderStatus = 
  | 'processing'      
  | 'pending_ship'    
  | 'shipped'         
  | 'completed'       
  | 'cancelled'       
  | 'refunding';

export interface Order {
  id: string;
  order_id: string;
  cookie_id: string;
  item_id: string;
  item_title?: string;
  item_image?: string;
  item_price?: string;
  buyer_id: string;
  quantity: number;
  amount: string;
  status: OrderStatus;
  order_status?: OrderStatus;
  receiver_name?: string;
  receiver_phone?: string;
  receiver_address?: string;
  created_at?: string;
  updated_at?: string;
}

// Cards
export interface Card {
  id: number;
  name: string;
  type: 'api' | 'text' | 'data' | 'image';
  description?: string;
  enabled: boolean;
  // 文本类型
  text_content?: string;
  // 批量数据类型
  data_content?: string;
  // API 类型配置
  api_config?: {
    url: string;
    method: 'GET' | 'POST';
    timeout?: number;
    headers?: string;
    params?: string;
  };
  // 图片类型
  image_url?: string;
  // 通用配置
  delay_seconds?: number;
  // 多规格配置
  is_multi_spec?: boolean;
  spec_name?: string;
  spec_value?: string;
  created_at: string;
  updated_at: string;
}

// Items
export interface Item {
  id: string | number;
  cookie_id: string;
  item_id: string;
  item_title?: string;
  item_description?: string;
  item_detail?: string;
  item_price?: string;
  item_image?: string; // Inferred from common usage, though not explicitly in list model sometimes
  item_category?: string;
  is_multi_spec?: number | boolean;
  multi_quantity_delivery?: number | boolean;
  created_at?: string;
  updated_at?: string;
}

// Rules
export interface ShippingRule {
  id: string;
  name: string;
  item_keyword: string; // Matches item title
  card_group_id: number; // ID from Card list
  card_group_name?: string; // UI helper
  priority: number;
  enabled: boolean;
}

export interface DeliveryBlockRule {
  rule_code: string;
  rule_name: string;
  rule_description: string;
  enabled: boolean;
  priority: number;
  block_reason: string;
  auto_close_order: boolean;
  only_card_after_close: boolean;
  excluded_item_ids: string[];
  config: Record<string, unknown>;
}

export interface PersonalBlacklistEntry {
  id: number;
  owner_id: number;
  account_id?: string;
  buyer_id: string;
  buyer_nick: string;
  item_id?: string;
  reason: string;
  is_enabled: boolean;
  created_at?: string;
  updated_at?: string;
}

export type NotificationChannelType =
  | 'dingtalk'
  | 'feishu'
  | 'bark'
  | 'email'
  | 'webhook'
  | 'wechat'
  | 'telegram';

export interface NotificationChannel {
  id: string;
  name: string;
  type: NotificationChannelType;
  config: Record<string, unknown>;
  enabled: boolean;
  created_at?: string;
  updated_at?: string;
}

export interface MessageNotification {
  id: string;
  cookie_id: string;
  channel_id: number;
  channel_name: string;
  channel_type?: NotificationChannelType;
  enabled: boolean;
}

export interface RiskControlLog {
  id: number;
  cookie_id: string;
  cookie_name?: string;
  event_type: string;
  event_description?: string;
  processing_result?: string;
  processing_status: 'processing' | 'success' | 'failed' | string;
  error_message?: string;
  created_at: string;
  updated_at?: string;
}

export interface SystemLog {
  timestamp: string;
  level: string;
  source: string;
  function?: string;
  line?: number;
  message: string;
}

export interface ReplyRule {
  id: string;
  keyword: string;
  reply_content: string;
  match_type: 'exact' | 'fuzzy';
  enabled: boolean;
}

// Stats
export interface AdminStats {
  total_users: number;
  total_cookies: number;
  active_cookies: number;
  total_cards: number;
  total_keywords: number;
  total_orders: number;
}

export interface OrderAnalytics {
  revenue_stats: {
    total_amount: number;
    total_orders: number;
  };
  daily_stats: Array<{ date: string; amount: number }>;
  item_stats?: Array<{
    item_id: string;
    order_count: number;
    total_amount: number;
    avg_amount: number;
  }>;
}

// Settings
export interface SystemSettings {
  ai_model?: string;
  ai_api_key?: string;
  ai_base_url?: string;
  default_reply?: string;
  registration_enabled?: boolean;
  smtp_server?: string;
  [key: string]: any;
}

export interface AIReplySettings {
  ai_enabled: boolean;
  model_name: string;
  api_key: string;
  base_url: string;
  max_discount_percent: number;
  max_discount_amount?: number;
  max_bargain_rounds: number;
  custom_prompts: string;
}

// Default Reply
export interface DefaultReply {
  cookie_id: string;
  enabled: boolean;
  reply_content: string;
  reply_once: boolean;
  reply_image_url?: string;
}
