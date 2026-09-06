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
  first_weight?: number;
  first_weight_price?: number;
  continued_unit?: number;
  continued_weight_price?: number;
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
