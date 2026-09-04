import { ChevronDown, Sparkles } from 'lucide-react';
import {
  SAMPLE_CONTINUED_KG,
  SAMPLE_FREIGHT,
  type QuoteSettings,
} from '../../services/quoteSettings';
import { sampleTotals } from '../../utils/quoteTemplate';
import { SectionHeader } from '../ui';

interface QuoteSmartCalcSectionProps {
  form: QuoteSettings;
  onChangeField: <K extends keyof QuoteSettings>(field: K, value: QuoteSettings[K]) => void;
  onNumberFieldChange: (field: 'cardFaceValue' | 'platformFaceValue' | 'profitMarkup' | 'continuedMarkup', value: string) => void;
}

/** 智能计算：加价参数与示例计费预览。 */
const QuoteSmartCalcSection = ({ form, onChangeField, onNumberFieldChange }: QuoteSmartCalcSectionProps) => {
  const totals = sampleTotals(form);

  return (
    <section className="section-panel" aria-labelledby="smart-calc-title">
      <SectionHeader
        title="智能计算"
        description="配置报价的加价参数：面值、平台支付与各项加价，保存后由智能计算统一套用。"
        icon={Sparkles}
      />
      <div className="grid gap-4 p-4">
        <div className="grid gap-4 sm:grid-cols-2">
          <label>
            <span className="field-label">卡密面值（元）</span>
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
            <span className="field-label">平台支付面值（元）</span>
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
              <span className="text-[13px] font-bold text-[var(--text)]">示例预览</span>
              <span className="truncate text-xs text-[var(--text-muted)]">
                按计费重 3kg（1kg 首重 + {SAMPLE_CONTINUED_KG}kg 续重）示例计算
              </span>
            </span>
            <span className="flex shrink-0 items-center gap-2">
              <span className="text-xs text-[var(--text-muted)]">合计</span>
              <span className="text-[13px] font-bold tabular-nums text-[var(--text)]">¥{totals.total.toFixed(2)}</span>
              <ChevronDown
                className="h-4 w-4 text-[var(--text-soft)] transition-transform duration-150 group-open:rotate-180 motion-reduce:transition-none"
                aria-hidden="true"
              />
            </span>
          </summary>
          <div className="border-t border-[var(--border)] p-3.5">
            <div className="logistics-breakdown" aria-live="polite">
              <div>
                <span>卡密面值</span>
                <strong>¥{totals.card.toFixed(2)}</strong>
              </div>
              <div>
                <span>运费（示例：1kg 首重 ¥12 + {SAMPLE_CONTINUED_KG}kg 续重 × ¥4.8）</span>
                <strong>¥{totals.freight.toFixed(2)}</strong>
              </div>
              <div>
                <span>利润加价</span>
                <strong>+¥{totals.profit.toFixed(2)}</strong>
              </div>
              <div>
                <span>续重加价 +¥{totals.continued.toFixed(2)}/kg × {SAMPLE_CONTINUED_KG}kg</span>
                <strong>+¥{(totals.continued * SAMPLE_CONTINUED_KG).toFixed(2)}</strong>
              </div>
            </div>
            <div className="logistics-total mt-3">
              <div>
                <span>买家应付合计（示例）</span>
                <small>平台支付 ¥{totals.platform.toFixed(2)} · 余款 ¥{totals.remaining.toFixed(2)}，运费实际以已识别报价为准</small>
              </div>
              <strong>¥{totals.total.toFixed(2)}</strong>
            </div>
          </div>
        </details>
      </div>
    </section>
  );
};

export default QuoteSmartCalcSection;
