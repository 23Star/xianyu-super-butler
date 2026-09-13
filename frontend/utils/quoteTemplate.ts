/**
 * 报价模板与预览值
 *
 * 回复模板的参数词表、渲染，以及识别样本预览值。
 */

import type { QuoteSettings } from '../services/quoteSettings';

export const TOKENS = [
  { label: '发货省' },
  { label: '收货省' },
  { label: '重量' },
  { label: '实重' },
  { label: '计费重量' },
  { label: '体积重' },
  { label: '体积算式' },
  { label: '体积重行' },
  { label: '长宽高' },
  { label: '渠道报价行' },
  { label: '渠道报价提示' },
  { label: '最优渠道' },
  { label: '快递总价' },
  { label: '闲鱼已付' },
  { label: '卡密面值' },
  { label: '补差价' },
] as const;

export const DEFAULT_TOKEN_ORDER = TOKENS.map(({ label }) => label);

const TOKEN_ORDER_STORAGE_KEY = 'logistics_quote_token_order_v1';

const normalizeTokenOrder = (value: unknown): string[] => {
  const knownLabels = new Set<string>(DEFAULT_TOKEN_ORDER);
  const persisted = Array.isArray(value)
    ? value.filter((label): label is string => typeof label === 'string' && knownLabels.has(label))
    : [];
  const unique = [...new Set(persisted)];
  return [...unique, ...DEFAULT_TOKEN_ORDER.filter((label) => !unique.includes(label))];
};

export const loadTokenOrder = (): string[] => {
  if (typeof window === 'undefined') return [...DEFAULT_TOKEN_ORDER];
  try {
    const raw = window.localStorage.getItem(TOKEN_ORDER_STORAGE_KEY);
    return raw ? normalizeTokenOrder(JSON.parse(raw)) : [...DEFAULT_TOKEN_ORDER];
  } catch {
    return [...DEFAULT_TOKEN_ORDER];
  }
};

export const saveTokenOrder = (order: string[]) => {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(TOKEN_ORDER_STORAGE_KEY, JSON.stringify(normalizeTokenOrder(order)));
  } catch {
    // 本地存储不可用时仍保留当前页面内的排序。
  }
};

/** 消息分隔符：模板中按此标记拆分，发送时拆成多条消息依次发送，不合并为一条。 */
export const TEMPLATE_SPLIT_TOKEN = '{分隔符}';

export const sanitizeNumberText = (raw: string) => {
  const cleaned = raw.replace(/[^\d.]/g, '');
  const [head, ...restParts] = cleaned.split('.');
  return restParts.length ? `${head}.${restParts.join('')}` : cleaned;
};

export const parsePositive = (text: string): number | null => {
  if (!text) return null;
  const value = Number(text);
  return Number.isFinite(value) && value > 0 ? value : null;
};

export interface QuotePreviewContext {
  service?: string | null;
  route?: string | null;
  origin?: string | null;
  destination?: string | null;
  freight?: number | null;
  firstWeightKg?: number | null;
  firstPrice?: number | null;
  continuedUnitKg?: number | null;
  continuedPrice?: number | null;
}

/**
 * 回复预览只展示已识别报价表样本或明确的待输入状态，不生成业务数据。
 */
export const buildSampleValues = (
  form: QuoteSettings,
  context?: QuotePreviewContext | null,
): Record<string, string> => {
  const platform = parsePositive(form.platformFaceValue);
  const profit = parsePositive(form.profitMarkup);
  const continuedMarkup = parsePositive(form.continuedMarkup);
  const freight = typeof context?.freight === 'number' && Number.isFinite(context.freight)
    ? context.freight
    : null;
  const total = freight === null || profit === null ? null : Math.max(0, freight + profit - (platform || 0));
  const remaining = total;
  const formatMoney = (value: number | null) => value === null ? '待核价' : `¥${value.toFixed(2)}`;
  const service = context?.service?.trim() || '已识别报价服务';
  const route = context?.route?.trim() || [context?.origin, context?.destination].filter(Boolean).join('→');
  const firstPrice = typeof context?.firstPrice === 'number'
    ? `首重${context.firstWeightKg ? `${context.firstWeightKg}kg ` : ''}${context.firstPrice}元`
    : '首重价格待确认';
  const continuedPrice = typeof context?.continuedPrice === 'number'
    ? `续重${context.continuedPrice}元/${context.continuedUnitKg || 1}kg`
    : '续重价格待确认';
  return {
    发货省: context?.origin?.trim() || '待买家提供',
    收货省: context?.destination?.trim() || '待买家提供',
    重量: '待买家提供',
    实重: '待买家提供',
    计费重量: '待核价',
    体积重: '待买家提供',
    体积算式: '待买家提供长宽高',
    体积重行: '待买家提供长宽高后计算体积重',
    长宽高: '待买家提供',
    渠道报价行: context ? `${service}${route ? `（${route}）` : ''}：${firstPrice}，${continuedPrice}` : '待识别报价表并输入买家信息',
    渠道报价提示: context ? '以上内容来自已识别报价表样本，正式报价需结合买家重量核价' : '识别报价表后将按实际线路核价',
    最优渠道: context ? `${service} ${formatMoney(freight)}` : '待核价',
    快递总价: formatMoney(freight),
    闲鱼已付: platform === null ? '待配置' : `¥${platform.toFixed(2)}`,
    卡密面值: freight === null ? '待核价' : `¥${freight.toFixed(2)}`,
    券原价: freight === null ? '待核价' : `¥${freight.toFixed(2)}`,
    优惠券抵扣: platform === null ? '待配置' : `¥${platform.toFixed(2)}`,
    补差价: formatMoney(remaining),
    分隔符: '\n―――――――\n',
    平台支付面值: platform === null ? '待配置' : `¥${platform.toFixed(2)}`,
    运费: formatMoney(freight),
    利润加价: profit === null ? '待配置' : `¥${profit.toFixed(2)}`,
    续重加价: continuedMarkup === null ? '待配置' : `¥${continuedMarkup.toFixed(2)}`,
    续重: '待核价',
    合计: formatMoney(total),
    余款: formatMoney(remaining),
    默认重量: form.defaultOneKg ? '1kg' : '待配置',
  };
};

export const renderTemplate = (template: string, values: Record<string, string>) =>
  template.replace(/\{([^{}]+)\}/g, (match, name: string) => values[name.trim()] ?? match);
