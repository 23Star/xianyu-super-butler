import { SlidersHorizontal } from 'lucide-react';
import type { QuoteCarrierConfig, QuoteSettings } from '../../services/quoteSettings';
import { SectionHeader } from '../ui';

const DEFAULT_LINE = '{渠道}：{运费}元（{计费规则}）';
const CARRIERS = ['极兔', '申通', '圆通', '中通', '韵达', '顺丰', '百世快运', '顺心捷达', '壹米滴答'];
const emptyConfig = (): QuoteCarrierConfig => ({ volume_ratio: null, markup_cost: 0, markup_manual: 0, discount_rate: 0, discount_amount: 0, quote_line_template: DEFAULT_LINE });

interface Props { form: QuoteSettings; onChange: (value: QuoteSettings['carrier_config']) => void }

const QuoteCarrierConfigSection = ({ form, onChange }: Props) => {
  const names = [...new Set([...CARRIERS, ...Object.keys(form.carrier_config)])].sort();
  const update = (carrier: string, patch: Partial<QuoteCarrierConfig>) => {
    const current = form.carrier_config[carrier] || emptyConfig();
    onChange({ ...form.carrier_config, [carrier]: { ...current, ...patch } });
  };
  return (
    <section className="section-panel" aria-labelledby="carrier-settings-title">
      <SectionHeader title="渠道配置" description="在第二步统一维护渠道抛比、加价、折扣和报价展示格式，保存后自动衔接第五步。" icon={SlidersHorizontal} />
      <div className="grid gap-4 p-4">
        {names.map((carrier) => {
          const config = form.carrier_config[carrier] || emptyConfig();
          return (
            <details key={carrier} className="rounded-md border border-[var(--border)] bg-[var(--surface-subtle)] p-3.5">
              <summary className="cursor-pointer text-sm font-bold text-[var(--text)]">{carrier}</summary>
              <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {([
                  ['volume_ratio', '抛比', '1'], ['markup_cost', '成本加价（元）', '0.01'], ['markup_manual', '人工加价（元）', '0.01'],
                  ['discount_rate', '折扣减免（%）', '0.01'], ['discount_amount', '固定减免（元）', '0.01'],
                ] as const).map(([key, label, step]) => (
                  <label key={key}><span className="field-label">{label}</span><input type="number" min={key === 'volume_ratio' ? 1 : 0} step={step} value={config[key] ?? ''} placeholder={key === 'volume_ratio' ? '报价表默认值' : '0'} onChange={(event) => update(carrier, { [key]: event.target.value === '' && key === 'volume_ratio' ? null : Number(event.target.value) })} className="ios-input w-full rounded-md px-3 py-2 text-sm" /></label>
                ))}
                <label className="sm:col-span-2 lg:col-span-3"><span className="field-label">渠道报价格式</span><textarea rows={2} value={config.quote_line_template || DEFAULT_LINE} onChange={(event) => update(carrier, { quote_line_template: event.target.value })} className="ios-input w-full rounded-md px-3 py-2 text-sm" /><span className="mt-1 block text-xs text-[var(--text-muted)]">必填：{'{渠道}'}、{'{运费}'}；可用：{'{计费规则}'}、{'{计费重量}'}、{'{线路}'}</span></label>
              </div>
            </details>
          );
        })}
      </div>
    </section>
  );
};

export default QuoteCarrierConfigSection;
