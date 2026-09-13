export interface LogisticsInput {
  sender?: string;
  receiver?: string;
  weight_kg?: number | null;
  length_cm?: number | null;
  width_cm?: number | null;
  height_cm?: number | null;
  carrier_payment_mode?: 'offline' | 'online';
  quote_config: QuoteConfig;
}

export interface QuoteConfig {
  price_basis?: 'cost' | 'markup';
  carriers: Record<string, CarrierConfig>;
  default_volume_ratios?: Record<string, VolumeRatioRule>;
}

/** 按实重分段；纯体积输入实重取 0。 */
export interface WeightTieredVolumeRatio {
  basis: 'weight';
  threshold_kg: number;
  light: number;
  heavy: number;
}

export interface PaymentTieredVolumeRatio {
  basis: 'payment';
  offline: number;
  online: number;
}

export type VolumeRatioRule = number | WeightTieredVolumeRatio | PaymentTieredVolumeRatio;

export interface CarrierConfig {
  volume_ratio?: number;
  price_table: PriceTable;
  markup_cost?: number;
  markup_manual?: number;
  discount_rate?: number;
  discount_amount?: number;
  payment_mode?: 'direct' | 'smart' | 'supplement';
  coupon_max_amount?: number;
  paid_amount?: number;
}

export interface PriceTable {
  tiers?: Record<number, number>;
  /** tiers 表头为"N KG以内/以下"时按不超过 N 的最小档位计价；默认精确命中。 */
  tiers_up_to?: boolean;
  first_weight?: number;
  first_weight_price?: number;
  continued_unit?: number;
  continued_weight_price?: number;
  /** 分段续重：键为分档上界公斤数，值为该段每公斤价格。 */
  continued_tiers?: Record<number, number>;
  /** 分段区间口径：continued（默认，对续重部分）或 total（对计费总重）。 */
  continued_tiers_basis?: 'continued' | 'total';
  /** 超过最大分段上界时的每公斤价格；使用 continued_tiers 时必填。 */
  overflow_continued_price?: number;
  minimum_price?: number;
  per_kg_price?: number;
}

export interface CarrierQuote {
  carrier: string;
  volume_ratio: number;
  chargeable_weight_kg: number;
  base_price: number;
  markup_cost: number;
  markup_manual: number;
  discount_rate: number;
  discount_amount: number;
  adjusted_price: number;
  total_price: number;
  payment_mode: 'direct' | 'smart' | 'supplement';
  platform_payment: number;
  remaining_payment: number;
}

export interface QuoteResult {
  success: boolean;
  partial: boolean;
  reason?: string;
  message?: string;
  missing_fields?: string[];
  invalid_fields?: string[];
  route_weight_kg?: number;
  category?: 'express' | 'freight';
  quotes: CarrierQuote[];
  errors: Array<{ carrier: string; reason: string; field: string; message: string }>;
}

export const meta: Readonly<{ name: string; version: string; phases: string[] }>;
export function calculateLogisticsQuote(input: LogisticsInput): QuoteResult;
