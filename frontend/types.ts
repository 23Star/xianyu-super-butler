
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
  // 各状态的全量条数，不受分页和筛选影响
  status_counts?: Record<string, number>;
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
  runtime_state?: 'running' | 'stopped' | 'cancelled' | 'failed';
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
  buy_num?: number;
  auction_price?: string;
  confirm_fee?: string;
  refund_fee?: string;
  post_fee?: string;
  status: OrderStatus;
  order_status?: OrderStatus;
  receiver_name?: string;
  receiver_phone?: string;
  receiver_address?: string;
  created_at?: string;
  updated_at?: string;
}

// 快捷短语：人工客服常用话术
export interface QuickPhrase {
  id: number;
  category: string;
  title: string;
  content: string;
  sort_order: number;
  enabled: boolean;
  use_count: number;
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

export interface ProductVariantBinding {
  id?: number;
  binding_id?: number;
  display_name: string;
  spec_text: string;
  spec_payload?: Record<string, string>;
  canonical_spec_key?: string;
  platform_sku_id: string;
  card_id: number;
  card_name?: string;
  card_type?: Card['type'];
  card_enabled?: boolean;
  stock_count?: number | null;
  delivery_count: number;
  delivery_times?: number;
  enabled: boolean;
  binding_enabled: boolean;
  source?: string;
}

export interface ItemDeliveryConfigSummary {
  cookie_id: string;
  item_id: string;
  enabled: boolean;
  is_multi_spec: boolean;
  variant_count: number;
  configured_count: number;
  complete: boolean;
  delivery_times: number;
}

export interface ItemDeliveryConfig extends ItemDeliveryConfigSummary {
  configured: boolean;
  variants: ProductVariantBinding[];
}

export type ProductPublishStatus = 'draft' | 'published' | 'failed' | string;

export interface ProductMaterial {
  id: number;
  user_id: number;
  cookie_id: string;
  rule_id?: number;
  source_item_id: string;
  title: string;
  description: string;
  category: string;
  price?: number;
  images: string[];
  source_url: string;
  short_url: string;
  delivery_content: string;
  publish_status: ProductPublishStatus;
  published_item_id: string;
  publish_trace_code: string;
  auto_card_id?: number;
  created_at?: string;
  updated_at?: string;
}

export interface ProductFilterRule {
  id: number;
  user_id: number;
  cookie_id: string;
  name: string;
  include_keywords: string[];
  exclude_keywords: string[];
  min_price?: number;
  max_price?: number;
  category: string;
  daily_limit: number;
  enabled: boolean;
  today_count: number;
  total_count: number;
  counter_date?: string;
  last_run_at?: string;
  last_run_status?: string;
  created_at?: string;
  updated_at?: string;
}

export interface ProductDeleteRule {
  id: number;
  user_id: number;
  cookie_id: string;
  name: string;
  min_publish_days: number;
  daily_limit: number;
  skip_reply_activity: boolean;
  skip_order_activity: boolean;
  enabled: boolean;
  execution_mode: 'dry_run';
  last_run_at?: string;
  last_run_status?: string;
  created_at?: string;
  updated_at?: string;
}

export interface AutomationTaskRun {
  id: number;
  user_id: number;
  cookie_id?: string;
  task_type: string;
  rule_id?: number;
  execution_mode: string;
  checked_count: number;
  matched_count: number;
  changed_count: number;
  failed_count: number;
  summary: string;
  details: Array<Record<string, unknown>>;
  error_message?: string;
  created_at: string;
}

export interface ProductAutomationResult {
  run_id: number;
  summary: string;
  details?: Array<Record<string, unknown>>;
}

export interface ProductDeletePreview extends ProductAutomationResult {
  mode: 'dry_run';
  candidates: Array<{
    item_id: string;
    item_title?: string;
    created_at?: string;
    age_days?: number;
    reason: string;
  }>;
  skipped: Array<{
    item_id: string;
    item_title?: string;
    created_at?: string;
    age_days?: number;
    reason: string;
  }>;
}

// Rules
export interface ShippingRule {
  id: string;
  name: string;
  item_keyword: string; // Matches item title
  cookie_id?: string;
  item_id?: string;
  item_title?: string;
  card_group_id: number; // ID from Card list
  card_group_name?: string; // UI helper
  priority: number;
  enabled: boolean;
  delivery_times?: number;
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

export type MessageFilterType = 'skip_reply' | 'skip_notify';

export interface MessageFilter {
  id: number;
  cookie_id: string;
  keyword: string;
  filter_type: MessageFilterType;
  enabled: boolean;
  created_at?: string;
  updated_at?: string;
}

export interface AutoReplyLog {
  id: number;
  cookie_id: string;
  chat_id?: string;
  item_id?: string;
  source_message_id?: string;
  sender_user_id?: string;
  sender_user_name?: string;
  source_message?: string;
  process_status: 'success' | 'skipped' | 'failed' | string;
  decision_reason?: string;
  reply_strategy: 'keyword' | 'ai' | 'default' | 'api' | 'none' | string;
  matched_keyword?: string;
  reply_text?: string;
  error_message?: string;
  send_status: 'success' | 'failed' | 'unknown' | string;
  created_at?: string;
  updated_at?: string;
}

export interface ChatAccount {
  accountId: string;
  displayName: string;
  avatarUrl?: string;
  connected: boolean;
  xianyuUserId?: string;
}

export interface ChatConversation {
  cid: string;
  rawCid: string;
  otherUserId: string;
  otherUserName: string;
  otherUserAvatar?: string;
  itemId?: string;
  itemTitle?: string;
  itemImage?: string;
  lastMessageSummary: string;
  lastMessageTime: number;
  unreadCount: number;
}

export interface ChatMessage {
  messageId: string;
  senderId: string;
  senderName: string;
  isSelf: boolean;
  type: 'text' | 'image' | 'system' | 'card';
  text: string;
  images: string[];
  time: number;
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
    avg_amount?: number;
    unique_buyers?: number;
    unique_items?: number;
    // 确认收货后卖家实收，退款订单为 0
    confirmed_amount?: number;
    refunded_amount?: number;
    total_items_sold?: number;
    // 全部状态的口径，与订单页数字一致
    all_orders?: number;
    all_amount?: number;
  };
  daily_stats: Array<{
    date: string;
    amount: number;
    order_count?: number;
    confirmed_amount?: number;
    refunded_amount?: number;
  }>;
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
  // 注册是否必须填邮箱验证码。没配 SMTP 时关掉，否则注册会卡在收不到验证码
  email_verification_enabled?: boolean;
  // 定时从卖家端拉取订单，默认开启
  order_sync_enabled?: boolean;
  order_sync_interval?: number;
  // 商品擦亮，默认关闭
  auto_polish_enabled?: boolean;
  auto_polish_interval?: number;
  // 对买家产生实际动作，默认关闭
  auto_rate_enabled?: boolean;
  auto_flower_enabled?: boolean;
  // 公告与更新：地址存为字符串，开关也用字符串以复用通用设置接口
  announcement_source_url?: string;
  announcement_enabled?: string;
  smtp_server?: string;
  [key: string]: any;
}

export interface AIReplySettings {
  ai_enabled: boolean;
  model_name: string;
  api_key: string;
  api_key_configured?: boolean;
  base_url: string;
  max_discount_percent: number;
  max_discount_amount?: number;
  max_bargain_rounds: number;
  context_enabled: boolean;
  context_message_limit: number;
  context_expire_minutes: number;
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

// 全局公告与版本检查
export interface AnnouncementItem {
  id: string;
  title: string;
  content: string;
  level: 'info' | 'warning' | 'danger';
  published_at: string;
}

export interface AnnouncementPayload {
  local_version: string;
  latest_version: string;
  download_url: string;
  release_notes: string;
  has_update: boolean;
  source_configured: boolean;
  error: string;
  announcements: AnnouncementItem[];
}
