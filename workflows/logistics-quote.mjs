/** Deterministic logistics pricing. All rates are supplied by the caller. */
export const meta = Object.freeze({
  name: 'logistics_quote',
  version: '1.1.0',
  phases: ['Validate', 'Route', 'Calculate', 'Adjust'],
});

const isObject = (value) => value !== null && typeof value === 'object' && !Array.isArray(value);
const own = (object, key) => Object.hasOwn(object, key);

function fail(reason, field, message) {
  throw Object.assign(new Error(message), { reason, field });
}

function number(value, field, minimum = -Infinity, exclusive = false) {
  if (!Number.isFinite(value) || (exclusive ? value <= minimum : value < minimum)) {
    fail('invalid_number', field, `${field} 必须是${minimum === 0 ? (exclusive ? '正' : '非负') : '有限'}数值`);
  }
}

function object(value, field, allowed) {
  if (!isObject(value)) fail('invalid_config', field, `${field} 必须是对象`);
  if (allowed) {
    for (const key of Object.keys(value)) {
      if (!allowed.includes(key)) fail('unknown_field', `${field}.${key}`, `不支持的字段：${key}`);
    }
  }
}

function choice(value, choices, field) {
  if (value !== undefined && !choices.includes(value)) {
    fail('invalid_option', field, `${field} 必须为 ${choices.join(' / ')}`);
  }
}

function money(value) {
  const absolute = Math.abs(value);
  const cents = Math.sign(value) * Math.round((absolute + Number.EPSILON * absolute) * 100);
  if (!Number.isSafeInteger(cents)) fail('calculation_out_of_range', 'amount', '金额超出安全计算范围');
  return cents === 0 ? 0 : cents / 100;
}

function chargeable(weight, volume, ratio) {
  const result = Math.ceil(Math.max(weight, volume / ratio));
  if (!Number.isSafeInteger(result) || result <= 0) {
    fail('calculation_out_of_range', 'chargeable_weight_kg', '计费重量超出安全计算范围');
  }
  return result;
}

function carrierKey(name) {
  const compact = name.replace(/\s+/g, '');
  if (compact.includes('顺心')) return '顺心捷达';
  if (compact === '百世') return '百世快运';
  if (compact === '跨越') return '跨越速运';
  return compact;
}

function validateRatioRule(rule, field) {
  if (typeof rule === 'number') return number(rule, field, 0, true);
  object(rule, field);
  if (rule.basis === 'payment') {
    object(rule, field, ['basis', 'offline', 'online']);
    number(rule.offline, `${field}.offline`, 0, true);
    number(rule.online, `${field}.online`, 0, true);
  } else if (rule.basis === 'weight') {
    object(rule, field, ['basis', 'threshold_kg', 'light', 'heavy']);
    number(rule.threshold_kg, `${field}.threshold_kg`, 0);
    number(rule.light, `${field}.light`, 0, true);
    number(rule.heavy, `${field}.heavy`, 0, true);
  } else {
    fail('invalid_option', `${field}.basis`, '抛比规则必须为 weight 或 payment');
  }
}

function getCarrierRatio(name, weight, config, defaults, paymentMode) {
  if (own(config, 'volume_ratio')) return config.volume_ratio;
  const key = carrierKey(name);
  const rule = defaults && own(defaults, key) ? defaults[key] : undefined;
  if (rule !== undefined) {
    if (typeof rule === 'number') return rule;
    if (rule.basis === 'payment') return paymentMode === 'offline' ? rule.offline : rule.online;
    return weight <= rule.threshold_kg ? rule.light : rule.heavy;
  }
  // Weight tiers use actual weight, matching the existing frontend calculator.
  switch (key) {
    case '普通快递': return 8000;
    case '壹米滴答': return 6000;
    case '百世快运': return weight <= 70 ? 7000 : 5000;
    case '跨越速运': return 6000;
    case '顺心捷达': return paymentMode === 'offline' ? 6000 : 5000;
    default: return 5000;
  }
}

function validateCarrier(config) {
  object(config, 'carrier_config', [
    'volume_ratio', 'price_table', 'markup_cost', 'markup_manual', 'discount_rate',
    'discount_amount', 'payment_mode', 'coupon_max_amount', 'paid_amount',
  ]);
  if (own(config, 'volume_ratio')) number(config.volume_ratio, 'volume_ratio', 0, true);
  for (const key of ['markup_cost', 'markup_manual']) {
    if (own(config, key)) number(config[key], key);
  }
  for (const key of ['discount_rate', 'discount_amount', 'coupon_max_amount', 'paid_amount']) {
    if (own(config, key)) number(config[key], key, 0);
  }
  if (config.discount_rate > 100) fail('invalid_number', 'discount_rate', '折扣百分比不能超过 100');
  choice(config.payment_mode, ['direct', 'smart', 'supplement'], 'payment_mode');
  const required = config.payment_mode === 'smart' ? 'coupon_max_amount'
    : config.payment_mode === 'supplement' ? 'paid_amount' : null;
  if (required && !own(config, required)) fail('missing_payment_amount', required, `缺少 ${required}`);

  const table = config.price_table;
  object(table, 'price_table', [
    'tiers', 'first_weight', 'first_weight_price', 'continued_unit',
    'continued_weight_price', 'minimum_price', 'per_kg_price',
    'continued_tiers', 'overflow_continued_price',
  ]);
  for (const [key, value] of Object.entries(table)) {
    if (key === 'tiers') {
      object(value, 'price_table.tiers');
      for (const [weight, price] of Object.entries(value)) {
        if (!/^[1-9]\d*$/.test(weight) || !Number.isSafeInteger(Number(weight))) {
          fail('price_table_invalid', 'price_table.tiers', '阶梯价重量键必须为正安全整数');
        }
        number(price, `price_table.tiers.${weight}`, 0);
      }
    } else if (key === 'continued_tiers') {
      object(value, 'price_table.continued_tiers');
      for (const [threshold, price] of Object.entries(value)) {
        if (!/^[1-9]\d*$/.test(threshold) || !Number.isSafeInteger(Number(threshold))) {
          fail('price_table_invalid', 'price_table.continued_tiers', '分段续重门槛必须为正安全整数');
        }
        number(price, `price_table.continued_tiers.${threshold}`, 0);
      }
    } else {
      number(value, `price_table.${key}`, 0, key === 'first_weight' || key === 'continued_unit');
    }
  }
  if (own(table, 'continued_tiers')) {
    for (const key of ['first_weight', 'first_weight_price', 'overflow_continued_price']) {
      if (!own(table, key)) {
        fail('price_table_invalid', `price_table.${key}`, `分段续重价格表必须提供 ${key}`);
      }
    }
  }
}

function basePrice(weight, table) {
  if (table.tiers && own(table.tiers, weight)) return money(table.tiers[weight]);
  if (table.continued_tiers) {
    // 分段续重：续重部分 = 计费重 - 首重，按续重部分所在区间取单价。
    if (weight <= table.first_weight) return money(table.first_weight_price);
    const continued = weight - table.first_weight;
    const thresholds = Object.keys(table.continued_tiers).map(Number).sort((a, b) => a - b);
    let rate = table.overflow_continued_price;
    for (const threshold of thresholds) {
      if (continued <= threshold) {
        rate = table.continued_tiers[threshold];
        break;
      }
    }
    const count = Math.ceil(continued / (table.continued_unit ?? 1));
    return money(table.first_weight_price + count * rate);
  }
  if (table.first_weight_price !== undefined && table.continued_weight_price !== undefined) {
    const count = Math.ceil(Math.max(0, weight - (table.first_weight ?? 1)) / (table.continued_unit ?? 1));
    return money(table.first_weight_price + count * table.continued_weight_price);
  }
  if (table.minimum_price !== undefined && table.per_kg_price !== undefined) {
    return money(Math.max(table.minimum_price, weight * table.per_kg_price));
  }
  fail('price_table_invalid', 'price_table', '报价表未覆盖该计费重量，或价格模型不完整');
}

function adjustments(base, config, basis) {
  const markup_cost = basis === 'cost' ? money(config.markup_cost ?? 0) : 0;
  const markup_manual = money(config.markup_manual ?? 0);
  const discount_rate = config.discount_rate ?? 0;
  const discount_amount = money(config.discount_amount ?? 0);
  const adjusted_price = money(Math.max(0, base + markup_cost + markup_manual));
  const total_price = money(Math.max(0, adjusted_price * (1 - discount_rate / 100) - discount_amount));
  const payment_mode = config.payment_mode ?? 'direct';
  const platform_payment = payment_mode === 'smart'
    ? Math.min(total_price, money(config.coupon_max_amount))
    : payment_mode === 'supplement' ? money(config.paid_amount) : total_price;
  return {
    markup_cost, markup_manual, discount_rate, discount_amount, adjusted_price, total_price,
    payment_mode, platform_payment, remaining_payment: money(Math.max(0, total_price - platform_payment)),
  };
}

const failure = (reason, details = {}) => ({ success: false, partial: false, quotes: [], errors: [], reason, ...details });

/** @param {import('./logistics-quote.mjs').LogisticsInput} input */
export function calculateLogisticsQuote(input) {
  try {
    object(input, 'input', ['sender', 'receiver', 'weight_kg', 'length_cm', 'width_cm', 'height_cm', 'carrier_payment_mode', 'quote_config']);
    if (input.quote_config == null) return failure('missing_quote_config', { missing_fields: ['quote_config'] });
    const config = input.quote_config;
    object(config, 'quote_config', ['price_basis', 'carriers', 'default_volume_ratios']);
    choice(config.price_basis, ['cost', 'markup'], 'quote_config.price_basis');
    choice(input.carrier_payment_mode, ['offline', 'online'], 'carrier_payment_mode');
    for (const field of ['sender', 'receiver']) {
      if (own(input, field) && typeof input[field] !== 'string') fail('invalid_input', field, `${field} 必须是字符串`);
    }
    const dimensions = ['length_cm', 'width_cm', 'height_cm'];
    for (const field of ['weight_kg', ...dimensions]) {
      if (input[field] != null) number(input[field], field, 0, true);
    }
    const supplied = dimensions.filter((key) => input[key] != null);
    if (input.weight_kg == null && supplied.length !== 3) {
      return failure('missing_weight_or_volume', { missing_fields: ['weight_kg', ...dimensions] });
    }
    if (supplied.length > 0 && supplied.length < 3) {
      return failure('incomplete_dimensions', { missing_fields: dimensions.filter((key) => input[key] == null) });
    }
    object(config.carriers, 'quote_config.carriers');
    const carriers = Object.entries(config.carriers);
    if (!carriers.length) return failure('missing_carriers', { missing_fields: ['quote_config.carriers'] });
    if (config.default_volume_ratios !== undefined) {
      object(config.default_volume_ratios, 'quote_config.default_volume_ratios');
      for (const [name, rule] of Object.entries(config.default_volume_ratios)) {
        validateRatioRule(rule, `default_volume_ratios.${name}`);
      }
    }
    const weight = input.weight_kg ?? 0;
    const volume = supplied.length === 3 ? input.length_cm * input.width_cm * input.height_cm : 0;
    if (!Number.isFinite(volume) || (supplied.length === 3 && volume === 0)) {
      return failure('calculation_out_of_range', { invalid_fields: dimensions });
    }
    const route_weight_kg = chargeable(weight, volume, 8000);
    const category = route_weight_kg < 30 ? 'express' : 'freight';
    const quotes = [];
    const errors = [];
    for (const [carrier, carrierConfig] of carriers) {
      try {
        if (!carrier.trim()) fail('invalid_carrier', 'carrier', '承运商名称不能为空');
        validateCarrier(carrierConfig);
        const volume_ratio = getCarrierRatio(carrier, weight, carrierConfig, config.default_volume_ratios, input.carrier_payment_mode);
        const chargeable_weight_kg = chargeable(weight, volume, volume_ratio);
        const base_price = basePrice(chargeable_weight_kg, carrierConfig.price_table);
        quotes.push({
          carrier, volume_ratio, chargeable_weight_kg, base_price,
          ...adjustments(base_price, carrierConfig, config.price_basis),
        });
      } catch (error) {
        errors.push({ carrier, reason: error.reason ?? 'calculation_failed', field: error.field ?? 'carrier_config', message: error.message });
      }
    }
    return {
      success: errors.length === 0,
      partial: quotes.length > 0 && errors.length > 0,
      route_weight_kg, category, quotes, errors,
      ...(errors.length ? { reason: quotes.length ? 'partial_quote_failure' : 'no_valid_quotes' } : {}),
    };
  } catch (error) {
    return failure(error.reason ?? 'invalid_input', {
      invalid_fields: [error.field ?? 'input'], message: error.message,
    });
  }
}
