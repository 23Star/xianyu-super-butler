import type { VolumeRatioRule } from '../utils/logisticsCalculator';

/** 报价生效范围：全部商品统一套用，或仅套用指定的若干商品。 */
export type QuoteScope = 'all' | 'custom';

/** 以数字文本形式编辑的设置字段，输入时统一经 sanitizeNumberText 清洗。 */
export type QuoteNumberField =
  | 'cardFaceValue'
  | 'platformFaceValue'
  | 'profitMarkup'
  | 'continuedMarkup'
  | 'expressVolumeRatio'
  | 'yimididaVolumeRatio'
  | 'bestVolumeRatioThreshold'
  | 'bestLightVolumeRatio'
  | 'bestHeavyVolumeRatio'
  | 'shunxinOfflineVolumeRatio'
  | 'shunxinOnlineVolumeRatio';

const QUOTE_NUMBER_FIELDS: readonly QuoteNumberField[] = [
  'cardFaceValue',
  'platformFaceValue',
  'profitMarkup',
  'continuedMarkup',
  'expressVolumeRatio',
  'yimididaVolumeRatio',
  'bestVolumeRatioThreshold',
  'bestLightVolumeRatio',
  'bestHeavyVolumeRatio',
  'shunxinOfflineVolumeRatio',
  'shunxinOnlineVolumeRatio',
];

export interface QuoteSettings {
  cardFaceValue: string;
  platformFaceValue: string;
  profitMarkup: string;
  continuedMarkup: string;
  /** 普通快递默认抛比：体积重 = 长×宽×高(cm) ÷ 抛比。 */
  expressVolumeRatio: string;
  /** 壹米滴答默认抛比。 */
  yimididaVolumeRatio: string;
  /** 百世快运计费重分界（kg，含）：不高于分界用轻抛比，否则用重抛比。 */
  bestVolumeRatioThreshold: string;
  /** 百世快运不高于分界重量时的抛比。 */
  bestLightVolumeRatio: string;
  /** 百世快运超过分界重量时的抛比。 */
  bestHeavyVolumeRatio: string;
  /** 顺心捷达线下支付时的抛比。 */
  shunxinOfflineVolumeRatio: string;
  /** 顺心捷达线上支付（含未识别支付方式）时的抛比。 */
  shunxinOnlineVolumeRatio: string;
  defaultOneKg: boolean;
  replyTemplate: string;
  scope: QuoteScope;
  /** scope 为 custom 时生效，元素为 `cookie_id:item_id` 的商品键。 */
  selectedItemKeys: string[];
  carrier_config: Record<string, QuoteCarrierConfig>;
}

export interface QuoteCarrierConfig {
  volume_ratio: number | null;
  markup_cost: number;
  markup_manual: number;
  discount_rate: number;
  discount_amount: number;
  quote_line_template: string;
}

const STORAGE_KEY = 'logistics_quote_settings_v1';

export const DEFAULT_QUOTE_SETTINGS: QuoteSettings = {
  cardFaceValue: '100',
  platformFaceValue: '0',
  profitMarkup: '5',
  continuedMarkup: '2',
  expressVolumeRatio: '8000',
  yimididaVolumeRatio: '6000',
  bestVolumeRatioThreshold: '70',
  bestLightVolumeRatio: '7000',
  bestHeavyVolumeRatio: '5000',
  shunxinOfflineVolumeRatio: '6000',
  shunxinOnlineVolumeRatio: '5000',
  defaultOneKg: true,
  scope: 'all',
  selectedItemKeys: [],
  carrier_config: {},
  replyTemplate:
    '亲，运费报价这样算哦：\n券原价 {券原价} - 优惠券抵扣 {优惠券抵扣} = 报价 {合计}\n包裹重量未能识别时，将按{默认重量}计费。',
};

const normalizeScope = (value: unknown): QuoteScope => (value === 'custom' ? 'custom' : 'all');

const normalizeItemKeys = (value: unknown): string[] => {
  if (!Array.isArray(value)) return [];
  return [...new Set(value.filter((key): key is string => typeof key === 'string' && key.trim() !== ''))];
};

const normalizeNumberText = (value: unknown, fallback: string): string => {
  if (typeof value !== 'string') return fallback;
  const cleaned = value.replace(/[^\d.]/g, '');
  const [head, ...restParts] = cleaned.split('.');
  return restParts.length ? `${head}.${restParts.join('')}` : cleaned;
};

export const loadQuoteSettings = (): QuoteSettings => {
  const defaults = { ...DEFAULT_QUOTE_SETTINGS };
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return defaults;
    const parsed = JSON.parse(raw) as Partial<QuoteSettings> | null;
    const merged: QuoteSettings = {
      ...defaults,
      ...parsed,
      scope: normalizeScope(parsed?.scope),
      selectedItemKeys: normalizeItemKeys(parsed?.selectedItemKeys),
      carrier_config: parsed?.carrier_config && typeof parsed.carrier_config === 'object'
        ? parsed.carrier_config as QuoteSettings['carrier_config'] : {},
    };
    for (const field of QUOTE_NUMBER_FIELDS) {
      merged[field] = normalizeNumberText(parsed?.[field], DEFAULT_QUOTE_SETTINGS[field]);
    }
    return merged;
  } catch {
    return defaults;
  }
};

/** 把设置里的抛比文本换算成计费器可用的默认抛比规则，非法或留空时回退内置默认值。 */
export const buildDefaultVolumeRatios = (settings: QuoteSettings): Record<string, VolumeRatioRule> => {
  const positive = (text: string, fallback: number): number => {
    const value = Number(text);
    return Number.isFinite(value) && value > 0 ? value : fallback;
  };
  return {
    普通快递: positive(settings.expressVolumeRatio, Number(DEFAULT_QUOTE_SETTINGS.expressVolumeRatio)),
    壹米滴答: positive(settings.yimididaVolumeRatio, Number(DEFAULT_QUOTE_SETTINGS.yimididaVolumeRatio)),
    百世快运: {
      basis: 'weight',
      threshold_kg: positive(settings.bestVolumeRatioThreshold, Number(DEFAULT_QUOTE_SETTINGS.bestVolumeRatioThreshold)),
      light: positive(settings.bestLightVolumeRatio, Number(DEFAULT_QUOTE_SETTINGS.bestLightVolumeRatio)),
      heavy: positive(settings.bestHeavyVolumeRatio, Number(DEFAULT_QUOTE_SETTINGS.bestHeavyVolumeRatio)),
    },
    顺心捷达: {
      basis: 'payment',
      offline: positive(settings.shunxinOfflineVolumeRatio, Number(DEFAULT_QUOTE_SETTINGS.shunxinOfflineVolumeRatio)),
      online: positive(settings.shunxinOnlineVolumeRatio, Number(DEFAULT_QUOTE_SETTINGS.shunxinOnlineVolumeRatio)),
    },
  };
};

export const saveQuoteSettings = (settings: QuoteSettings) => {
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(settings));
};
