/** Decide whether multiple packages share one quote or keep separate quotes. */
export const meta = Object.freeze({ name: 'logistics_package_plan', version: '1.0.0' });

export function planLogisticsPackages({ weights_kg, first_order_eligible = false } = {}) {
  if (!Array.isArray(weights_kg) || !weights_kg.length || weights_kg.some((w) => !Number.isFinite(w) || w <= 0)) {
    return { success: false, reason: 'invalid_weights', packages: [] };
  }
  const weights = weights_kg.map(Number);
  const total = weights.reduce((sum, weight) => sum + weight, 0);
  const display = Number.isInteger(total) ? String(total) : String(Number(total.toFixed(3)));
  if (total >= 30) return { success: true, mode: 'merge', weight_kg: total, reason: 'total_weight_at_least_30kg', notice: `已合并为${display}kg，按物流报价` };
  if (first_order_eligible && weights.every((weight) => weight <= 30)) return { success: true, mode: 'merge', weight_kg: total, reason: 'first_order_express', notice: `已合并为${display}kg，享首单特惠` };
  return { success: true, mode: 'separate', weight_kg: total, reason: 'separate_packages', packages: weights.map((weight, index) => ({ index: index + 1, weight_kg: weight })) };
}
