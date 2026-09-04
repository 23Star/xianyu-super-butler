/**
 * 报价模板与示例计算
 *
 * 回复模板的参数词表、渲染，以及示例计费的唯一数据源。
 * QuoteSettings 的示例预览与回复预览都从这里取数，避免两处公式漂移。
 */

import {
  SAMPLE_CONTINUED_KG,
  SAMPLE_FREIGHT,
  type QuoteSettings,
} from '../services/quoteSettings';

export const TOKENS = [
  { label: '卡密面值' },
  { label: '平台支付面值' },
  { label: '运费' },
  { label: '利润加价' },
  { label: '续重加价' },
  { label: '续重' },
  { label: '合计' },
  { label: '余款' },
  { label: '默认重量' },
] as const;

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

export interface QuoteSampleTotals {
  card: number;
  platform: number;
  profit: number;
  continued: number;
  freight: number;
  continuedKg: number;
  total: number;
  remaining: number;
}

/** 按示例口径（3kg 计费重 = 1kg 首重 + 2kg 续重）计算一次，供各处预览共用。 */
export const sampleTotals = (form: QuoteSettings): QuoteSampleTotals => {
  const card = parsePositive(form.cardFaceValue) ?? 100;
  const platform = parsePositive(form.platformFaceValue) ?? 100;
  const profit = parsePositive(form.profitMarkup) ?? 5;
  const continued = parsePositive(form.continuedMarkup) ?? 2;
  const total = card + SAMPLE_FREIGHT + profit + continued * SAMPLE_CONTINUED_KG;
  return {
    card,
    platform,
    profit,
    continued,
    freight: SAMPLE_FREIGHT,
    continuedKg: SAMPLE_CONTINUED_KG,
    total,
    remaining: Math.max(0, total - platform),
  };
};

export const buildSampleValues = (form: QuoteSettings): Record<string, string> => {
  const totals = sampleTotals(form);
  return {
    卡密面值: `¥${totals.card.toFixed(2)}`,
    平台支付面值: `¥${totals.platform.toFixed(2)}`,
    运费: `¥${totals.freight.toFixed(2)}`,
    利润加价: `¥${totals.profit.toFixed(2)}`,
    续重加价: `¥${totals.continued.toFixed(2)}`,
    续重: `${totals.continuedKg}`,
    合计: `¥${totals.total.toFixed(2)}`,
    余款: `¥${totals.remaining.toFixed(2)}`,
    默认重量: '1kg',
  };
};

export const renderTemplate = (template: string, values: Record<string, string>) =>
  template.replace(/\{([^{}]+)\}/g, (match, name: string) => values[name.trim()] ?? match);
