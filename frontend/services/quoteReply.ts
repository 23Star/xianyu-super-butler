/**
 * 自动报价回复文案
 *
 * 第三步「消息模板设置」的 AI 回复文案配置：数据结构与默认文案、本地持久化。
 * 参数词表与示例计算复用 utils/quoteTemplate，保证预览与第二步口径一致。
 */

/** 回复文案键：报价主消息 → 差价分支 → 引导拍下 → 追问与首次回复。 */
export type QuoteReplyTemplateKey =
  | 'quoteMessage'
  | 'diffPositive'
  | 'diffZero'
  | 'guideOrder'
  | 'missingParams'
  | 'firstReply';

export type QuoteReplyTemplates = Record<QuoteReplyTemplateKey, string>;

export interface QuoteReplyTemplateMeta {
  key: QuoteReplyTemplateKey;
  label: string;
  /** 说明该文案的发送时机，作为编辑器的辅助说明。 */
  hint: string;
  placeholder: string;
  defaultTemplate: string;
}

export const QUOTE_REPLY_TEMPLATE_META: Record<
  QuoteReplyTemplateKey,
  Omit<QuoteReplyTemplateMeta, 'key'>
> = {
  quoteMessage: {
    label: '报价消息',
    hint: '买家询价后自动回复的运费报价说明，告知计费口径与合计金额。',
    placeholder: '如：亲，您的运费报价算好啦……',
    defaultTemplate:
      '亲，您的运费报价算好啦：\n券原价 {券原价} - 优惠券抵扣 {优惠券抵扣} = 报价 {合计}\n（含自定义加价 {利润加价}，续重加价 {续重加价}/kg）\n包裹重量未能识别时，将按{默认重量}计费。',
  },
  diffPositive: {
    label: '差价>0时',
    hint: '合计金额高于平台支付面值时发送，说明需要补足的余款与方式。',
    placeholder: '如：亲，本单需补差价 {余款}……',
    defaultTemplate:
      '亲，本单需要补差价 {余款}，拍下后请稍等，客服会发送补差链接，补齐后马上为您安排发货哦～',
  },
  diffZero: {
    label: '差价=0时',
    hint: '合计金额与平台支付面值一致时发送，告知无需补差价。',
    placeholder: '如：亲，本单无需补差价……',
    defaultTemplate:
      '亲，本单平台支付刚好够用，无需补差价，直接拍下就可以啦～',
  },
  guideOrder: {
    label: '引导拍下',
    hint: '报价确认后发送，引导买家尽快拍下付款。',
    placeholder: '如：确认没问题的话，直接拍下付款哦～',
    defaultTemplate:
      '确认没问题的话，直接拍下并付款哦，客服会第一时间为您安排发货～',
  },
  missingParams: {
    label: '缺少参数追问文案',
    hint: '缺少收货地、重量等计费参数时发送，主动向买家追问。',
    placeholder: '如：亲，麻烦告诉我收货地址和包裹重量哦……',
    defaultTemplate:
      '亲，为了给您准确报价，麻烦告诉我收货地址（省/市）和包裹大概重量哦～重量无法确认时将先按{默认重量}计费。',
  },
  firstReply: {
    label: '首次回复',
    hint: '买家首次发起会话时发送的欢迎语，引导买家提供报价所需信息。',
    placeholder: '如：亲，欢迎咨询！告诉我收货地和重量马上为您报价～',
    defaultTemplate:
      '亲，欢迎咨询！本店支持运费自动报价，告诉我收货地和包裹大概重量，马上为您算出运费哦～',
  },
};

export const DEFAULT_QUOTE_REPLY_TEMPLATES: QuoteReplyTemplates = Object.fromEntries(
  (Object.keys(QUOTE_REPLY_TEMPLATE_META) as QuoteReplyTemplateKey[]).map((key) => [
    key,
    QUOTE_REPLY_TEMPLATE_META[key].defaultTemplate,
  ]),
) as QuoteReplyTemplates;

const STORAGE_KEY = 'logistics_quote_reply_templates_v1';

const TEMPLATE_KEYS = Object.keys(QUOTE_REPLY_TEMPLATE_META) as QuoteReplyTemplateKey[];

export const loadQuoteReplyTemplates = (): QuoteReplyTemplates => {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return { ...DEFAULT_QUOTE_REPLY_TEMPLATES };
    const parsed = JSON.parse(raw) as Partial<Record<QuoteReplyTemplateKey, unknown>> | null;
    return TEMPLATE_KEYS.reduce((result, key) => {
      result[key] = typeof parsed?.[key] === 'string' ? (parsed[key] as string) : DEFAULT_QUOTE_REPLY_TEMPLATES[key];
      return result;
    }, {} as QuoteReplyTemplates);
  } catch {
    return { ...DEFAULT_QUOTE_REPLY_TEMPLATES };
  }
};

export const saveQuoteReplyTemplates = (templates: QuoteReplyTemplates) => {
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(templates));
};
