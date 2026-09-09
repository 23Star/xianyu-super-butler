import { SlidersHorizontal } from 'lucide-react';
import type { QuoteSettings } from '../../services/quoteSettings';
import { SectionHeader } from '../ui';

interface QuoteBasicSectionProps {
  form: QuoteSettings;
  onChangeField: <K extends keyof QuoteSettings>(field: K, value: QuoteSettings[K]) => void;
}

/** 基础设置：仅保留默认计费口径；买家回复文案统一在第三步维护。 */
const QuoteBasicSection = ({ form, onChangeField }: QuoteBasicSectionProps) => (
  <section className="section-panel" aria-labelledby="basic-settings-title">
    <SectionHeader
      title="基础设置"
      description="默认计费口径；买家回复文案请在第三步统一维护。"
      icon={SlidersHorizontal}
    />
    <div className="grid gap-4 p-4">
      <label className="logistics-check-row">
        <span>
          <span className="block text-sm font-bold text-[var(--text)]">未识别重量/体积时默认按 1kg 计费</span>
          <span className="mt-1 block text-xs leading-relaxed text-[var(--text-muted)]">
            买家询价但无法识别包裹重量或体积时，按 1kg 计算运费，并在回复中说明。
          </span>
        </span>
        <input
          type="checkbox"
          checked={form.defaultOneKg}
          onChange={(event) => onChangeField('defaultOneKg', event.target.checked)}
          aria-label="未识别重量或体积时默认按 1kg 计费"
        />
        <span className="logistics-toggle" aria-hidden="true"><i /></span>
      </label>
    </div>
  </section>
);

export default QuoteBasicSection;
