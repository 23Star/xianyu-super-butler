import { ChevronDown, Sparkles } from 'lucide-react';
import {
  type QuoteNumberField,
  type QuoteSettings,
} from '../../services/quoteSettings';
import { parsePositive } from '../../utils/quoteTemplate';
import { SectionHeader } from '../ui';

interface QuoteSmartCalcSectionProps {
  form: QuoteSettings;
  onChangeField: <K extends keyof QuoteSettings>(field: K, value: QuoteSettings[K]) => void;
  onNumberFieldChange: (field: QuoteNumberField, value: string) => void;
}

/** 智能计算：加价参数与真实报价核价前置状态。 */
const QuoteSmartCalcSection = ({ form, onChangeField, onNumberFieldChange }: QuoteSmartCalcSectionProps) => {
  const card = parsePositive(form.cardFaceValue);
  const platform = parsePositive(form.platformFaceValue);
  const profit = parsePositive(form.profitMarkup);
  const continued = parsePositive(form.continuedMarkup);
  const money = (value: number | null) => value === null ? '待配置' : `¥${value.toFixed(2)}`;

  return (
    <section className="section-panel" aria-labelledby="smart-calc-title">
      <SectionHeader
        title="智能计算"
        description="报价表提供券原价；这里设置优惠券抵扣与加价，最终报价为券原价加价后减去抵扣。"
        icon={Sparkles}
      />
      <div className="grid gap-4 p-4">
        <div className="grid gap-4 sm:grid-cols-2">
          <label>
            <span className="field-label">券原价预览（元，实际来自报价表）</span>
            <input
              type="text"
              inputMode="decimal"
              value={form.cardFaceValue}
              onChange={(event) => onNumberFieldChange('cardFaceValue', event.target.value)}
              placeholder="如 100"
              className="ios-input w-full rounded-md px-3 py-2.5 text-sm"
            />
          </label>
          <label>
            <span className="field-label">优惠券抵扣（元）</span>
            <input
              type="text"
              inputMode="decimal"
              value={form.platformFaceValue}
              onChange={(event) => onNumberFieldChange('platformFaceValue', event.target.value)}
              placeholder="如 100"
              className="ios-input w-full rounded-md px-3 py-2.5 text-sm"
            />
          </label>
          <label>
            <span className="field-label">利润加价（元）</span>
            <input
              type="text"
              inputMode="decimal"
              value={form.profitMarkup}
              onChange={(event) => onNumberFieldChange('profitMarkup', event.target.value)}
              placeholder="如 5"
              className="ios-input w-full rounded-md px-3 py-2.5 text-sm"
            />
          </label>
          <label>
            <span className="field-label">续重加价（元/kg）</span>
            <input
              type="text"
              inputMode="decimal"
              value={form.continuedMarkup}
              onChange={(event) => onNumberFieldChange('continuedMarkup', event.target.value)}
              placeholder="如 2"
              className="ios-input w-full rounded-md px-3 py-2.5 text-sm"
            />
            <span className="mt-1.5 block text-xs leading-relaxed text-[var(--text-muted)]">
              按超出首重的每公斤加价，叠加在运费与利润加价之上。
            </span>
          </label>
        </div>

        <details className="group overflow-hidden rounded-md border border-[var(--border)] bg-[var(--surface-subtle)]">
          <summary className="flex cursor-pointer select-none list-none flex-wrap items-center justify-between gap-2 rounded-md px-3.5 py-3 text-left transition-colors duration-150 hover:bg-[var(--surface-hover)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--focus-ring)] motion-reduce:transition-none [&::-webkit-details-marker]:hidden">
            <span className="flex min-w-0 items-baseline gap-2">
              <span className="text-[13px] font-bold text-[var(--text)]">计算预览</span>
              <span className="truncate text-xs text-[var(--text-muted)]">
                等待已识别报价表与买家重量/体积
              </span>
            </span>
            <span className="flex shrink-0 items-center gap-2">
              <span className="text-xs text-[var(--text-muted)]">合计</span>
              <span className="text-[13px] font-bold tabular-nums text-[var(--text)]">待核价</span>
              <ChevronDown
                className="h-4 w-4 text-[var(--text-soft)] transition-transform duration-150 group-open:rotate-180 motion-reduce:transition-none"
                aria-hidden="true"
              />
            </span>
          </summary>
          <div className="border-t border-[var(--border)] p-3.5">
            <div className="logistics-breakdown" aria-live="polite">
              <div>
                <span>券原价（来自报价表）</span>
                <strong>{money(card)}</strong>
              </div>
              <div>
                <span>报价表运费 / 券原价（需结合买家信息核价）</span>
                <strong>待核价</strong>
              </div>
              <div>
                <span>自定义加价</span>
                <strong>{profit === null ? '待配置' : `+¥${profit.toFixed(2)}`}</strong>
              </div>
              <div>
                <span>续重加价（需要买家计费重量）</span>
                <strong>{continued === null ? '待配置' : `+¥${continued.toFixed(2)}/kg`}</strong>
              </div>
            </div>
            <div className="logistics-total mt-3">
              <div>
                <span>买家应付报价</span>
                <small>优惠券抵扣 {money(platform)}；券原价加价后扣除抵扣</small>
              </div>
              <strong>待核价</strong>
            </div>
          </div>
        </details>
      </div>
    </section>
  );
};

export default QuoteSmartCalcSection;
