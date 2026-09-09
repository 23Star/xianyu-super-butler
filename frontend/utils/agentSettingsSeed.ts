/**
 * 第二/三步配置 → 第五步 Agent 配置的带入映射。
 *
 * 第二步（报价设置）与第三步（消息模板）保存在浏览器本地；第五步配置保存在
 * 服务端。首次进入第五步或手动点击带入时，把金额构成、抛比规则、模板与商品
 * 范围映射成 Agent 配置草稿，口径与第二/三步一致，保存前可继续编辑。
 */

import type { AgentSettings } from '../services/logisticsAgent';
import {
  DEFAULT_QUOTE_SETTINGS,
  buildDefaultVolumeRatios,
  loadQuoteSettings,
  type QuoteSettings,
} from '../services/quoteSettings';
import {
  DEFAULT_QUOTE_REPLY_TEMPLATES,
  loadQuoteReplyTemplates,
  type QuoteReplyTemplateKey,
} from '../services/quoteReply';

export interface AgentSettingsSeed {
  pricing: Partial<AgentSettings['pricing']>;
  default_volume_ratios: Record<string, unknown>;
  templates: Partial<AgentSettings['templates']>;
  carrier_config: AgentSettings['carrier_config'];
  item_scope?: AgentSettings['item_scope'];
  item_ids?: string[];
}

/** 金额构成：第二步字段 → 第五步 pricing 字段。 */
const PRICING_FIELDS: ReadonlyArray<[keyof QuoteSettings, keyof AgentSettings['pricing']]> = [
  ['cardFaceValue', 'card_face_value'],
  ['platformFaceValue', 'coupon_discount'],
  ['profitMarkup', 'profit_markup'],
  ['continuedMarkup', 'continued_markup'],
];

/** 抛比规则字段（含按重量/支付方式分段的承运商）。 */
const RATIO_FIELDS: ReadonlyArray<keyof QuoteSettings> = [
  'expressVolumeRatio',
  'yimididaVolumeRatio',
  'bestVolumeRatioThreshold',
  'bestLightVolumeRatio',
  'bestHeavyVolumeRatio',
  'shunxinOfflineVolumeRatio',
  'shunxinOnlineVolumeRatio',
];

/** 回复模板：第三步字段 → 第五步模板字段（无线路/失败文案保留 Agent 默认）。 */
const TEMPLATE_FIELDS: ReadonlyArray<[keyof AgentSettings['templates'], QuoteReplyTemplateKey]> = [
  ['quote_message', 'quoteMessage'],
  ['diff_positive', 'diffPositive'],
  ['diff_zero', 'diffZero'],
  ['guide_order', 'guideOrder'],
  ['missing_params', 'missingParams'],
  ['first_reply', 'firstReply'],
];

const toAmount = (text: string): number => {
  const value = Number(text);
  return Number.isFinite(value) && value > 0 ? value : 0;
};

/** 判断第二/三步是否有店家用过（与内置默认值不同）的配置。 */
export const hasLegacyQuoteConfig = (): boolean => {
  const settings = loadQuoteSettings();
  const numbersChanged = [...PRICING_FIELDS.map(([source]) => source), ...RATIO_FIELDS]
    .some((field) => settings[field] !== DEFAULT_QUOTE_SETTINGS[field]);
  const scopeChanged =
    settings.scope !== DEFAULT_QUOTE_SETTINGS.scope || settings.selectedItemKeys.length > 0;
  const oneKgChanged = settings.defaultOneKg !== DEFAULT_QUOTE_SETTINGS.defaultOneKg;
  const carrierConfigChanged = Object.keys(settings.carrier_config).length > 0;
  const templates = loadQuoteReplyTemplates();
  const templatesChanged = TEMPLATE_FIELDS.some(
    ([, source]) => templates[source] !== DEFAULT_QUOTE_REPLY_TEMPLATES[source],
  );
  return numbersChanged || scopeChanged || oneKgChanged || templatesChanged || carrierConfigChanged;
};

/** 把第二/三步配置映射为第五步 Agent 配置草稿；没有可带入内容时返回 null。 */
export const buildAgentSeed = (cookieId: string): AgentSettingsSeed | null => {
  if (!hasLegacyQuoteConfig()) return null;
  const settings = loadQuoteSettings();
  const templates = loadQuoteReplyTemplates();
  const seed: AgentSettingsSeed = {
    pricing: {
      card_face_value: toAmount(settings.cardFaceValue),
      platform_face_value: toAmount(settings.platformFaceValue),
      profit_markup: toAmount(settings.profitMarkup),
      continued_markup: toAmount(settings.continuedMarkup),
      default_one_kg: settings.defaultOneKg,
    },
    default_volume_ratios: buildDefaultVolumeRatios(settings),
    templates: Object.fromEntries(
      TEMPLATE_FIELDS.map(([target, source]) => [target, templates[source]]),
    ) as AgentSettingsSeed['templates'],
    carrier_config: settings.carrier_config as AgentSettingsSeed['carrier_config'],
  };
  if (settings.scope === 'custom' && cookieId) {
    const prefix = `${cookieId}:`;
    const items = settings.selectedItemKeys
      .filter((key) => key.startsWith(prefix))
      .map((key) => key.slice(prefix.length))
      .filter(Boolean);
    if (items.length) {
      seed.item_scope = 'custom';
      seed.item_ids = [...new Set(items)];
    }
  }
  return seed;
};
