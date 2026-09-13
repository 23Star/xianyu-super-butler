import { Scale } from 'lucide-react';
import type { QuoteNumberField, QuoteSettings } from '../../services/quoteSettings';
import { parsePositive } from '../../utils/quoteTemplate';
import { SectionHeader } from '../ui';

interface QuoteVolumeRatioSectionProps {
  form: QuoteSettings;
  onNumberFieldChange: (field: QuoteNumberField, value: string) => void;
}

/** 承运商抛比：报价表未单独配置抛比时使用的默认值，可在下方自由调整。 */
const QuoteVolumeRatioSection = ({ form, onNumberFieldChange }: QuoteVolumeRatioSectionProps) => {
  const expressRatio = parsePositive(form.expressVolumeRatio) ?? 8000;
  const sampleVolumeWeight = Number((24000 / expressRatio).toFixed(2));

  return (
    <section className="section-panel" aria-labelledby="volume-ratio-title">
      <SectionHeader
        title="承运商抛比"
        description="包裹按实重与体积重取大计费，体积重 = 长×宽×高(cm) ÷ 抛比；报价表未单独配置抛比的承运商按以下默认值计算。"
        icon={Scale}
      />
      <div className="grid gap-4 p-4">
        <div className="grid gap-4 sm:grid-cols-2">
          <label>
            <span className="field-label">普通快递抛比</span>
            <input
              type="text"
              inputMode="decimal"
              value={form.expressVolumeRatio}
              onChange={(event) => onNumberFieldChange('expressVolumeRatio', event.target.value)}
              placeholder="如 8000"
              className="ios-input w-full rounded-md px-3 py-2.5 text-sm"
            />
          </label>
          <label>
            <span className="field-label">壹米滴答抛比</span>
            <input
              type="text"
              inputMode="decimal"
              value={form.yimididaVolumeRatio}
              onChange={(event) => onNumberFieldChange('yimididaVolumeRatio', event.target.value)}
              placeholder="如 6000"
              className="ios-input w-full rounded-md px-3 py-2.5 text-sm"
            />
          </label>
        </div>

        <div className="rounded-md border border-[var(--border)] bg-[var(--surface-subtle)] p-3.5">
          <span className="field-label">百世快运分段抛比</span>
          <div className="mt-1 grid gap-3 sm:grid-cols-3">
            <label>
              <span className="field-label">计费重分界（kg，含）</span>
              <input
                type="text"
                inputMode="decimal"
                value={form.bestVolumeRatioThreshold}
                onChange={(event) => onNumberFieldChange('bestVolumeRatioThreshold', event.target.value)}
                placeholder="如 70"
                className="ios-input w-full rounded-md px-3 py-2.5 text-sm"
              />
            </label>
            <label>
              <span className="field-label">不超过分界时的抛比</span>
              <input
                type="text"
                inputMode="decimal"
                value={form.bestLightVolumeRatio}
                onChange={(event) => onNumberFieldChange('bestLightVolumeRatio', event.target.value)}
                placeholder="如 7000"
                className="ios-input w-full rounded-md px-3 py-2.5 text-sm"
              />
            </label>
            <label>
              <span className="field-label">超过分界时的抛比</span>
              <input
                type="text"
                inputMode="decimal"
                value={form.bestHeavyVolumeRatio}
                onChange={(event) => onNumberFieldChange('bestHeavyVolumeRatio', event.target.value)}
                placeholder="如 5000"
                className="ios-input w-full rounded-md px-3 py-2.5 text-sm"
              />
            </label>
          </div>
        </div>

        <div className="rounded-md border border-[var(--border)] bg-[var(--surface-subtle)] p-3.5">
          <span className="field-label">顺心捷达分段抛比</span>
          <div className="mt-1 grid gap-3 sm:grid-cols-2">
            <label>
              <span className="field-label">线下支付时抛比</span>
              <input
                type="text"
                inputMode="decimal"
                value={form.shunxinOfflineVolumeRatio}
                onChange={(event) => onNumberFieldChange('shunxinOfflineVolumeRatio', event.target.value)}
                placeholder="如 6000"
                className="ios-input w-full rounded-md px-3 py-2.5 text-sm"
              />
            </label>
            <label>
              <span className="field-label">线上支付时抛比</span>
              <input
                type="text"
                inputMode="decimal"
                value={form.shunxinOnlineVolumeRatio}
                onChange={(event) => onNumberFieldChange('shunxinOnlineVolumeRatio', event.target.value)}
                placeholder="如 5000"
                className="ios-input w-full rounded-md px-3 py-2.5 text-sm"
              />
            </label>
          </div>
          <span className="mt-1 block text-xs leading-relaxed text-[var(--text-muted)]">
            按与承运商结算的支付方式取值，未识别支付方式时按线上抛比计算。
          </span>
        </div>

        <p className="text-xs leading-relaxed text-[var(--text-muted)]">
          体积重示例：40×30×20cm 包裹按普通快递抛比 {expressRatio} 计算，24000÷{expressRatio}≈
          {sampleVolumeWeight}kg，与实重取大后进入运费计算。
        </p>
      </div>
    </section>
  );
};

export default QuoteVolumeRatioSection;
