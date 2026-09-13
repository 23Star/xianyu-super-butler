export interface ParsedBuyerMessage {
  origin: string | null;
  destination: string | null;
  weightKg: number | null;
  dimensions: { lengthCm: number; widthCm: number; heightCm: number } | null;
  paymentMode: 'offline' | 'online' | null;
  carrier: string | null;
  missing: string[];
}

const clean = (value?: string) => value?.replace(/[“”"'‘’]/g, '').trim() || null;
const locationStop = '，,。；;、\\s';

const first = (text: string, patterns: RegExp[]) => {
  for (const pattern of patterns) {
    const match = text.match(pattern);
    const value = clean(match?.[1]);
    if (value) return value;
  }
  return null;
};

const parseWeight = (text: string): number | null => {
  const match = text.match(/(?:重量|实重|大约|大概)?\s*(\d+(?:\.\d+)?)\s*(公斤|千克|kg|KG|斤|克|g|G)(?![a-zA-Z])/);
  if (!match) return null;
  const value = Number(match[1]);
  if (!Number.isFinite(value) || value <= 0) return null;
  if (match[2] === '斤') return value * 0.5;
  if (match[2] === '克' || match[2].toLowerCase() === 'g') return value / 1000;
  return value;
};

const parseDimensions = (text: string): ParsedBuyerMessage['dimensions'] => {
  const compact = text.replace(/厘米|公分/g, 'cm');
  const triplet = compact.match(/(\d+(?:\.\d+)?)\s*(?:cm)?\s*[x×*＊]\s*(\d+(?:\.\d+)?)\s*(?:cm)?\s*[x×*＊]\s*(\d+(?:\.\d+)?)/i);
  const named = compact.match(/长\s*(\d+(?:\.\d+)?)\s*(?:cm)?[，,、x×*＊\s]+宽\s*(\d+(?:\.\d+)?)\s*(?:cm)?[，,、x×*＊\s]+高\s*(\d+(?:\.\d+)?)/i);
  const match = triplet ?? named;
  if (!match) return null;
  const values = match.slice(1, 4).map(Number);
  if (values.some((value) => !Number.isFinite(value) || value <= 0)) return null;
  return { lengthCm: values[0], widthCm: values[1], heightCm: values[2] };
};

export const parseBuyerMessage = (message: string): ParsedBuyerMessage => {
  const text = message.replace(/[\r\n]/g, ' ').trim();
  const origin = first(text, [
    new RegExp(`(?:发货地|始发地|发件地|寄件地)[:：]?\\s*([^${locationStop}]{2,16})`, 'i'),
    /(?:从|由)\s*([^到至发往，,。；;、\s]{2,16})\s*(?:发往|发到|到|至)/i,
  ]);
  const destination = first(text, [
    new RegExp(`(?:收货地|目的地|送到|寄到|发往|到)[:：]?\\s*([^${locationStop}]{2,16})`, 'i'),
    /(?:从|由)\s*[^到至发往，,。；;、\s]{2,16}\s*(?:发往|发到|到|至)\s*([^，,。；;、\s]{2,16})/i,
  ]);
  const weightKg = parseWeight(text);
  const dimensions = parseDimensions(text);
  const paymentMode = /线下|现金|到付/.test(text) ? 'offline' : /线上|支付宝|平台支付|闲鱼支付/.test(text) ? 'online' : null;
  const carrier = /顺心捷达|顺心/.test(text) ? '顺心捷达' : /百世快运|百世/.test(text) ? '百世快运' : /壹米滴答|壹米/.test(text) ? '壹米滴答' : /跨越速运|跨越/.test(text) ? '跨越速运' : null;
  const missing: string[] = [];
  if (!destination) missing.push('收货地');
  if (weightKg === null && dimensions === null) missing.push('重量或长宽高');
  return { origin, destination, weightKg, dimensions, paymentMode, carrier, missing };
};

export const calculateSampleFreight = (
  parsed: ParsedBuyerMessage,
  sample: { first_weight_kg?: number | null; first_price?: number | null; continued_unit_kg?: number | null; continued_price?: number | null; quote?: number | null } | null | undefined,
  volumeRatio = 8000,
) => {
  if (!sample) return { chargeableWeightKg: null, volumeWeightKg: null, freight: null };
  const volumeWeightKg = parsed.dimensions ? (parsed.dimensions.lengthCm * parsed.dimensions.widthCm * parsed.dimensions.heightCm) / volumeRatio : null;
  const routeWeight = Math.max(parsed.weightKg ?? 0, volumeWeightKg ?? 0);
  if (routeWeight <= 0) return { chargeableWeightKg: null, volumeWeightKg, freight: null };
  const chargeableWeightKg = Math.ceil(routeWeight);
  const firstWeight = sample.first_weight_kg && sample.first_weight_kg > 0 ? sample.first_weight_kg : 1;
  const firstPrice = typeof sample.first_price === 'number' ? sample.first_price : null;
  const continuedUnit = sample.continued_unit_kg && sample.continued_unit_kg > 0 ? sample.continued_unit_kg : 1;
  const continuedPrice = typeof sample.continued_price === 'number' ? sample.continued_price : null;
  let freight = typeof sample.quote === 'number' ? sample.quote : null;
  if (firstPrice !== null) freight = firstPrice + (continuedPrice === null ? 0 : Math.ceil(Math.max(0, chargeableWeightKg - firstWeight) / continuedUnit) * continuedPrice);
  return { chargeableWeightKg, volumeWeightKg, freight };
};
