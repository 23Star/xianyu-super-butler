/** 报价生效范围：全部商品统一套用，或仅套用指定的若干商品。 */
export type QuoteScope = 'all' | 'custom';

export interface QuoteSettings {
  cardFaceValue: string;
  platformFaceValue: string;
  profitMarkup: string;
  continuedMarkup: string;
  defaultOneKg: boolean;
  replyTemplate: string;
  scope: QuoteScope;
  /** scope 为 custom 时生效，元素为 `cookie_id:item_id` 的商品键。 */
  selectedItemKeys: string[];
}

const STORAGE_KEY = 'logistics_quote_settings_v1';

export const SAMPLE_CONTINUED_KG = 2;
export const SAMPLE_FREIGHT = 21.6;

export const DEFAULT_QUOTE_SETTINGS: QuoteSettings = {
  cardFaceValue: '100',
  platformFaceValue: '100',
  profitMarkup: '5',
  continuedMarkup: '2',
  defaultOneKg: true,
  scope: 'all',
  selectedItemKeys: [],
  replyTemplate:
    '亲，运费报价这样算哦：\n卡密面值 {卡密面值} + 运费 {运费} = 合计 {合计}\n平台支付 {平台支付面值}，余款 {余款} 拍下后联系客服补差～\n包裹重量未能识别时，将按{默认重量}计费。',
};

const normalizeScope = (value: unknown): QuoteScope => (value === 'custom' ? 'custom' : 'all');

const normalizeItemKeys = (value: unknown): string[] => {
  if (!Array.isArray(value)) return [];
  return [...new Set(value.filter((key): key is string => typeof key === 'string' && key.trim() !== ''))];
};

export const loadQuoteSettings = (): QuoteSettings => {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return { ...DEFAULT_QUOTE_SETTINGS };
    const parsed = JSON.parse(raw) as Partial<QuoteSettings> | null;
    return {
      ...DEFAULT_QUOTE_SETTINGS,
      ...parsed,
      scope: normalizeScope(parsed?.scope),
      selectedItemKeys: normalizeItemKeys(parsed?.selectedItemKeys),
    };
  } catch {
    return { ...DEFAULT_QUOTE_SETTINGS };
  }
};

export const saveQuoteSettings = (settings: QuoteSettings) => {
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(settings));
};
