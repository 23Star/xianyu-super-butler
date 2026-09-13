import test from 'node:test';
import assert from 'node:assert/strict';
import { planLogisticsPackages } from './logistics-package-plan.mjs';

test('first order merges small packages', () => assert.equal(planLogisticsPackages({ weights_kg: [23, 5], first_order_eligible: true }).mode, 'merge'));
test('30kg total merges regardless of eligibility', () => assert.equal(planLogisticsPackages({ weights_kg: [23, 130] }).weight_kg, 153));
test('non-first-order small packages stay separate', () => assert.deepEqual(planLogisticsPackages({ weights_kg: [23, 5] }).packages.map((p) => p.weight_kg), [23, 5]));
