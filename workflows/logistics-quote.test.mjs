import test from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { fileURLToPath } from 'node:url';
import { calculateLogisticsQuote } from './logistics-quote.mjs';

/**
 * 物流报价 Workflow 测试用例
 *
 * 覆盖场景：
 * - 纯实重
 * - 纯体积
 * - 实重+体积
 * - 30kg 分界
 * - 承运商不同抛比
 * - 阶梯价
 * - 首重续重
 * - 加价折扣
 * - 三种支付模式
 * - 配置缺失
 */

// 测试用例 1：纯实重，快递分流
export const test1_pure_weight_express = {
  input: {
    weight_kg: 5,
    quote_config: {
      price_basis: 'cost',
      carriers: {
        中通快递: {
          volume_ratio: 8000,
          price_table: {
            first_weight: 1,
            first_weight_price: 12,
            continued_unit: 1,
            continued_weight_price: 4.8,
          },
          markup_cost: 2,
          discount_rate: 10,
          payment_mode: 'direct',
        },
      },
    },
  },
  expected: {
    success: true,
    route_weight_kg: 5,
    category: 'express',
    quotes: [
      {
        carrier: '中通快递',
        chargeable_weight_kg: 5,
        base_price: 31.2, // 12 + 4 * 4.8 = 31.2
        markup_cost: 2,
        adjusted_price: 33.2,
        total_price: 29.88, // 33.2 * 0.9 = 29.88
        platform_payment: 29.88,
        remaining_payment: 0,
      },
    ],
  },
};

// 测试用例 2：纯体积，物流分流
export const test2_pure_volume_freight = {
  input: {
    length_cm: 80,
    width_cm: 60,
    height_cm: 120,
    quote_config: {
      carriers: {
        壹米滴答: {
          volume_ratio: 6000,
          price_table: {
            first_weight: 5,
            first_weight_price: 28,
            continued_unit: 1,
            continued_weight_price: 2.6,
          },
          payment_mode: 'direct',
        },
      },
    },
  },
  expected: {
    success: true,
    route_weight_kg: 72, // 576000 / 8000 = 72
    category: 'freight',
    quotes: [
      {
        carrier: '壹米滴答',
        volume_ratio: 6000,
        chargeable_weight_kg: 96, // ceil(576000 / 6000) = 96
        base_price: 264.6, // 28 + 91 * 2.6 = 264.6
      },
    ],
  },
};

// 测试用例 3：实重 + 体积，体积重更大
export const test3_weight_volume_max = {
  input: {
    weight_kg: 3,
    length_cm: 50,
    width_cm: 40,
    height_cm: 30,
    quote_config: {
      carriers: {
        顺丰标快: {
          volume_ratio: 8000,
          price_table: {
            first_weight: 1,
            first_weight_price: 18,
            continued_weight_price: 7.5,
          },
          markup_manual: 5,
          discount_amount: 2,
          payment_mode: 'direct',
        },
      },
    },
  },
  expected: {
    success: true,
    route_weight_kg: 8, // ceil(60000 / 8000) = 8，大于实重 3
    category: 'express',
    quotes: [
      {
        carrier: '顺丰标快',
        chargeable_weight_kg: 8,
        base_price: 70.5, // 18 + 7 * 7.5 = 70.5
        markup_manual: 5,
        adjusted_price: 75.5,
        total_price: 73.5, // 75.5 - 2 = 73.5
      },
    ],
  },
};

// 测试用例 4：30kg 分界测试
export const test4_boundary_30kg = {
  input: {
    weight_kg: 29.5,
    quote_config: {
      carriers: {
        测试承运商: {
          price_table: {
            minimum_price: 50,
            per_kg_price: 2.5,
          },
          payment_mode: 'direct',
        },
      },
    },
  },
  expected: {
    success: true,
    route_weight_kg: 30, // ceil(29.5) = 30
    category: 'freight', // >= 30kg 进入物流
  },
};

// 测试用例 5：阶梯价模式
export const test5_tier_pricing = {
  input: {
    weight_kg: 12,
    quote_config: {
      carriers: {
        阶梯价承运商: {
          price_table: {
            tiers: {
              10: 80,
              11: 85,
              12: 90,
              13: 95,
            },
          },
          payment_mode: 'direct',
        },
      },
    },
  },
  expected: {
    success: true,
    quotes: [
      {
        carrier: '阶梯价承运商',
        chargeable_weight_kg: 12,
        base_price: 90,
        total_price: 90,
      },
    ],
  },
};

// 测试用例 6：Smart 支付模式
export const test6_smart_payment = {
  input: {
    weight_kg: 4,
    quote_config: {
      carriers: {
        智慧付承运商: {
          price_table: {
            first_weight_price: 20,
            continued_weight_price: 5,
          },
          payment_mode: 'smart',
          coupon_max_amount: 30,
        },
      },
    },
  },
  expected: {
    success: true,
    quotes: [
      {
        carrier: '智慧付承运商',
        base_price: 35, // 20 + 3 * 5 = 35
        total_price: 35,
        platform_payment: 30, // min(35, 30) = 30
        remaining_payment: 5, // 35 - 30 = 5
      },
    ],
  },
};

// 测试用例 7：Supplement 支付模式
export const test7_supplement_payment = {
  input: {
    weight_kg: 2,
    quote_config: {
      carriers: {
        补充付承运商: {
          price_table: {
            first_weight_price: 15,
            continued_weight_price: 6,
          },
          payment_mode: 'supplement',
          paid_amount: 10,
        },
      },
    },
  },
  expected: {
    success: true,
    quotes: [
      {
        carrier: '补充付承运商',
        base_price: 21, // 15 + 1 * 6 = 21
        total_price: 21,
        platform_payment: 10,
        remaining_payment: 11, // 21 - 10 = 11
      },
    ],
  },
};

// 测试用例 8：参数缺失
export const test8_missing_params = {
  input: {
    // 既没有实重，也没有完整尺寸
    length_cm: 50,
    width_cm: 40,
    // height_cm 缺失
    quote_config: {
      carriers: {},
    },
  },
  expected: {
    success: false,
    reason: 'missing_weight_or_volume',
    missing_fields: ['weight_kg', 'length_cm', 'width_cm', 'height_cm'],
  },
};

// 测试用例 9：百世快运动态抛比
export const test9_dynamic_ratio = {
  input: {
    weight_kg: 80,
    length_cm: 100,
    width_cm: 80,
    height_cm: 100,
    quote_config: {
      carriers: {
        百世快运: {
          // 实重 80kg > 70kg，应使用抛比 5000
          price_table: {
            first_weight: 5,
            first_weight_price: 30,
            continued_weight_price: 3,
          },
          payment_mode: 'direct',
        },
      },
    },
  },
  expected: {
    success: true,
    route_weight_kg: 100, // ceil(800000 / 8000) = 100
    category: 'freight',
    quotes: [
      {
        carrier: '百世快运',
        volume_ratio: 5000, // 实重 80 > 70，使用 5000
        chargeable_weight_kg: 160, // ceil(800000 / 5000) = 160
        base_price: 495, // 30 + 155 * 3 = 495
      },
    ],
  },
};

// 测试用例 10：复合场景（规格文档示例）
export const test10_complex_scenario = {
  input: {
    weight_kg: 10,
    quote_config: {
      carriers: {
        示例承运商: {
          volume_ratio: 8000,
          price_table: {
            first_weight: 1,
            first_weight_price: 30,
            continued_weight_price: 4,
          },
          markup_manual: 2,
          discount_rate: 10,
          payment_mode: 'direct',
        },
      },
    },
  },
  expected: {
    success: true,
    route_weight_kg: 10,
    category: 'express',
    quotes: [
      {
        carrier: '示例承运商',
        chargeable_weight_kg: 10,
        base_price: 66, // 30 + 9 * 4 = 66
        markup_manual: 2,
        adjusted_price: 68,
        total_price: 61.2, // 68 * 0.9 = 61.2
        platform_payment: 61.2,
        remaining_payment: 0,
      },
    ],
  },
};

// 测试用例 11：分段续重（百世快运式：首重30KG + 续重部分分档计价）
export const test11_banded_continued_tiers = {
  input: {
    weight_kg: 35,
    quote_config: {
      carriers: {
        百世快运: {
          price_table: {
            first_weight: 30,
            first_weight_price: 42,
            continued_unit: 1,
            continued_tiers: { 100: 1.36, 500: 1.28 },
            overflow_continued_price: 1.18,
          },
          payment_mode: 'direct',
        },
      },
    },
  },
  expected: {
    success: true,
    route_weight_kg: 35,
    category: 'freight',
    quotes: [
      {
        carrier: '百世快运',
        chargeable_weight_kg: 35,
        base_price: 48.8, // 续重部分 5kg ≤ 100，42 + 5 * 1.36 = 48.8
      },
    ],
  },
};

function assertExpected(actual, expected) {
  if (expected !== null && typeof expected === 'object') {
    assert.ok(actual !== null && typeof actual === 'object');
    if (Array.isArray(expected)) assert.equal(actual.length, expected.length);
    for (const key of Object.keys(expected)) assertExpected(actual[key], expected[key]);
  } else {
    assert.equal(actual, expected);
  }
}

for (const [name, sample] of Object.entries({
  test1_pure_weight_express, test2_pure_volume_freight, test3_weight_volume_max,
  test4_boundary_30kg, test5_tier_pricing, test6_smart_payment, test7_supplement_payment,
  test8_missing_params, test9_dynamic_ratio, test10_complex_scenario,
  test11_banded_continued_tiers,
})) {
  test(name, () => assertExpected(calculateLogisticsQuote(sample.input), sample.expected));
}

test('banded continued tiers select rates by continued weight and overflow', () => {
  const build = (weight_kg, dims = {}) => calculateLogisticsQuote({
    weight_kg, ...dims,
    quote_config: {
      carriers: {
        百世快运: {
          price_table: {
            first_weight: 30, first_weight_price: 42, continued_unit: 1,
            continued_tiers: { 100: 1.36, 500: 1.28 }, overflow_continued_price: 1.18,
          },
          payment_mode: 'direct',
        },
      },
    },
  });
  assert.equal(build(30).quotes[0].base_price, 42); // 计费重等于首重，不加续重
  assert.equal(build(120).quotes[0].base_price, 164.4); // 续重 90 ≤ 100 → 42 + 90 * 1.36
  assert.equal(build(200).quotes[0].base_price, 259.6); // 续重 170 ≤ 500 → 42 + 170 * 1.28
  assert.equal(build(600).quotes[0].base_price, 714.6); // 续重 570 > 500 → 42 + 570 * 1.18
  const volumed = build(80, { length_cm: 100, width_cm: 80, height_cm: 100 });
  assert.equal(volumed.quotes[0].chargeable_weight_kg, 160); // ceil(800000 / 5000)，实重 80 > 70 用重抛比
  assert.equal(volumed.quotes[0].base_price, 208.4); // 续重 130 ≤ 500 → 42 + 130 * 1.28
});

test('exact tier still wins over banded continued at same weight', () => {
  const result = calculateLogisticsQuote(input({
    price_table: {
      tiers: { 5: 20 },
      first_weight: 2, first_weight_price: 10,
      continued_tiers: { 100: 2 }, overflow_continued_price: 3,
    },
  }));
  assert.equal(result.quotes[0].base_price, 20); // 计费重 5 命中精确档
  assert.equal(calculateLogisticsQuote(input({
    price_table: {
      tiers: { 5: 20 },
      first_weight: 2, first_weight_price: 10,
      continued_tiers: { 100: 2 }, overflow_continued_price: 3,
    },
  }, { weight_kg: 7 })).quotes[0].base_price, 20); // 续重 5 → 10 + 5 * 2
});

const input = (carrier = {}, shipment = {}) => ({
  weight_kg: 5, ...shipment,
  quote_config: { carriers: { 普通快递: { price_table: { first_weight_price: 12, continued_weight_price: 4.8 }, ...carrier } } },
});

test('repeated calls are identical and do not mutate input', () => {
  const request = input({ markup_cost: 2, discount_rate: 10 });
  const before = structuredClone(request);
  const result = calculateLogisticsQuote(request);
  assert.deepEqual(calculateLogisticsQuote(request), result);
  assert.deepEqual(request, before);
  assert.equal(result.quotes[0].total_price, 28.08);
});

test('cent rounding and payment subtraction', () => {
  const result = calculateLogisticsQuote(input({
    price_table: { minimum_price: 1.005, per_kg_price: 0 }, payment_mode: 'supplement', paid_amount: 0.7,
  }));
  assert.equal(result.quotes[0].base_price, 1.01);
  assert.equal(result.quotes[0].remaining_payment, 0.31);
  const signed = calculateLogisticsQuote(input({ markup_manual: -1.005 }));
  assert.equal(signed.quotes[0].markup_manual, -1.01);
  assert.equal(signed.quotes[0].adjusted_price, 30.19);
  assert.equal(calculateLogisticsQuote(input({ markup_manual: -0.001 })).quotes[0].markup_manual, 0);
});

test('minimum pricing and continued units', () => {
  assert.equal(calculateLogisticsQuote(input({ price_table: { minimum_price: 50, per_kg_price: 2 } })).quotes[0].total_price, 50);
  assert.equal(calculateLogisticsQuote(input({ price_table: { first_weight: 2, first_weight_price: 10, continued_unit: 2, continued_weight_price: 3 } })).quotes[0].total_price, 16);
});

test('route threshold uses rounded route weight', () => {
  for (const [weight_kg, category] of [[29, 'express'], [29.01, 'freight'], [30, 'freight']]) {
    assert.equal(calculateLogisticsQuote(input({}, { weight_kg })).category, category);
  }
});

test('zero-price rates and full discount are valid', () => {
  assert.equal(calculateLogisticsQuote(input({ discount_rate: 100 })).quotes[0].total_price, 0);
  assert.equal(calculateLogisticsQuote(input({ price_table: { first_weight_price: 0, continued_weight_price: 0 } })).quotes[0].total_price, 0);
});

test('smart amount above total and overpayment never produce negative balance', () => {
  const smart = calculateLogisticsQuote(input({ payment_mode: 'smart', coupon_max_amount: 100 })).quotes[0];
  assert.equal(smart.platform_payment, 31.2);
  const supplement = calculateLogisticsQuote(input({ payment_mode: 'supplement', paid_amount: 100 })).quotes[0];
  assert.equal(supplement.platform_payment, 100);
  assert.equal(supplement.remaining_payment, 0);
});

test('configured ratios, aliases, weight and payment rules', () => {
  const request = { weight_kg: 70, length_cm: 100, width_cm: 100, height_cm: 100,
    quote_config: { carriers: { 百世: { price_table: { minimum_price: 0, per_kg_price: 1 } } } } };
  assert.equal(calculateLogisticsQuote(request).quotes[0].volume_ratio, 7000);
  request.weight_kg = 70.01;
  assert.equal(calculateLogisticsQuote(request).quotes[0].volume_ratio, 5000);
  request.quote_config.default_volume_ratios = { 百世快运: { basis: 'weight', threshold_kg: 80, light: 9000, heavy: 4000 } };
  assert.equal(calculateLogisticsQuote(request).quotes[0].volume_ratio, 9000);
  request.quote_config.carriers.百世.volume_ratio = 8000;
  assert.equal(calculateLogisticsQuote(request).quotes[0].volume_ratio, 8000);
  request.quote_config = { carriers: { 顺心: { price_table: { minimum_price: 0, per_kg_price: 1 } } } };
  assert.equal(calculateLogisticsQuote(request).quotes[0].volume_ratio, 5000);
  request.carrier_payment_mode = 'offline';
  assert.equal(calculateLogisticsQuote(request).quotes[0].volume_ratio, 6000);
  request.quote_config.default_volume_ratios = { 顺心捷达: { basis: 'payment', offline: 9000, online: 8000 } };
  assert.equal(calculateLogisticsQuote(request).quotes[0].volume_ratio, 9000);
  request.carrier_payment_mode = 'online';
  assert.equal(calculateLogisticsQuote(request).quotes[0].volume_ratio, 8000);
});

for (const value of [null, undefined, [], '5', 5]) {
  test(`reject invalid input root: ${String(value)}`, () => assert.equal(calculateLogisticsQuote(value).success, false));
}

for (const value of [0, -1, '5', NaN, Infinity, true]) {
  test(`reject invalid weight: ${String(value)}`, () => assert.equal(calculateLogisticsQuote(input({}, { weight_kg: value })).success, false));
}

for (const carrier of [
  null, [], { volume_ratio: 0 }, { volume_ratio: '8000' }, { volumeRatio: 8000 },
  { discount_rate: 101 }, { discount_amount: -1 }, { paid_amount: NaN }, { payment_mode: 'unknown' },
  { payment_mode: 'smart' }, { payment_mode: 'supplement' },
  { price_table: {} }, { price_table: { minimum_price: -1, per_kg_price: 2 } },
  { price_table: { tiers: { '2.5': 10 } } }, { price_table: { tiers: { 3: 10 } } },
  { price_table: { first_weight_price: 5, continued_weight_price: 1, continued_unit: 0 } },
  { price_table: { continued_tiers: { '2.5': 10 }, first_weight: 30, first_weight_price: 40, overflow_continued_price: 1 } },
  { price_table: { continued_tiers: { 100: '1.3' }, first_weight: 30, first_weight_price: 40, overflow_continued_price: 1 } },
  { price_table: { continued_tiers: { 100: 1.3 } } },
  { price_table: { continued_tiers: { 100: 1.3 }, first_weight: 30, first_weight_price: 40 } },
]) {
  test(`reject invalid carrier: ${JSON.stringify(carrier)}`, () => {
    const request = input(carrier);
    if (carrier === null || Array.isArray(carrier)) request.quote_config.carriers.普通快递 = carrier;
    const result = calculateLogisticsQuote(request);
    assert.equal(result.success, false);
    assert.equal(result.quotes.length, 0);
    assert.equal(result.errors.length, 1);
  });
}

test('missing config, empty carriers and incomplete dimensions fail explicitly', () => {
  assert.equal(calculateLogisticsQuote({ weight_kg: 5 }).reason, 'missing_quote_config');
  assert.equal(calculateLogisticsQuote({ weight_kg: 5, quote_config: { carriers: {} } }).reason, 'missing_carriers');
  assert.equal(calculateLogisticsQuote(input({}, { length_cm: 20 })).reason, 'incomplete_dimensions');
  assert.equal(calculateLogisticsQuote(input({}, { length_cm: -1, width_cm: -1, height_cm: 3 })).success, false);
});

test('overflow and invalid default rules fail before returning prices', () => {
  assert.equal(calculateLogisticsQuote(input({}, { length_cm: 1e308, width_cm: 1e308, height_cm: 1e308 })).success, false);
  const request = input();
  request.quote_config.default_volume_ratios = { 普通快递: { basis: 'payment', offline: 0, online: 8000 } };
  assert.equal(calculateLogisticsQuote(request).success, false);
  assert.equal(calculateLogisticsQuote(input({ price_table: { first_weight_price: 1e308, continued_weight_price: 1e308 } })).success, false);
});

test('partial failure retains valid quotes and never reports complete success', () => {
  const request = input();
  request.quote_config.carriers.坏配置 = { price_table: {} };
  const result = calculateLogisticsQuote(request);
  assert.equal(result.success, false);
  assert.equal(result.partial, true);
  assert.equal(result.reason, 'partial_quote_failure');
  assert.equal(result.quotes.length, 1);
  assert.equal(result.errors[0].carrier, '坏配置');
});

const cliPath = fileURLToPath(new URL('./logistics-quote.cli.mjs', import.meta.url));
const cli = (args = [], source) => spawnSync(process.execPath, [cliPath, ...args], { encoding: 'utf8', input: source, cwd: tmpdir() });

test('CLI file and stdin calls match function output, including UTF-8 BOM', () => {
  const file = fileURLToPath(new URL('./logistics-quote.example.json', import.meta.url));
  const source = readFileSync(file, 'utf8');
  for (const call of [cli([file]), cli([], source), cli(['-'], `\uFEFF${source}`)]) {
    assert.equal(call.status, 0, call.stderr);
    assert.equal(call.stderr, '');
    assert.deepEqual(JSON.parse(call.stdout), calculateLogisticsQuote(JSON.parse(source)));
    assert.equal(call.stdout.trim().split('\n').length, 1);
  }
});

test('CLI failure is machine-readable and uses exit codes 1/2', () => {
  assert.equal(cli([], '{}').status, 1);
  const invalid = cli([], '{broken');
  assert.equal(invalid.status, 2);
  assert.equal(JSON.parse(invalid.stdout).reason, 'invalid_json');
  assert.equal(cli(['--unknown']).status, 2);
  assert.equal(cli(['one', 'two']).status, 2);
  const missing = cli([`${cliPath}.missing`]);
  assert.equal(missing.status, 2);
  assert.equal(JSON.parse(missing.stdout).reason, 'input_read_failed');
});

test('CLI exposes tool schema from any working directory', () => {
  const call = cli(['--schema']);
  assert.equal(call.status, 0);
  const tool = JSON.parse(call.stdout);
  assert.equal(tool.name, 'logistics_quote');
  assert.equal(tool.parameters.properties.quote_config.properties.carriers.type, 'object');
});
