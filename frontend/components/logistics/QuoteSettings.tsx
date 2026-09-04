import { useMemo, useState } from 'react';
import { notify, confirmAction } from '../../services/feedback';
import {
  DEFAULT_QUOTE_SETTINGS,
  loadQuoteSettings,
  saveQuoteSettings,
  type QuoteSettings as QuoteSettingsData,
} from '../../services/quoteSettings';
import { sanitizeNumberText } from '../../utils/quoteTemplate';
import QuoteBasicSection from './QuoteBasicSection';
import QuoteScopeSection from './QuoteScopeSection';
import QuoteSmartCalcSection from './QuoteSmartCalcSection';

const QuoteSettings = () => {
  const [form, setForm] = useState<QuoteSettingsData>(() => loadQuoteSettings());
  const [saved, setSaved] = useState<QuoteSettingsData>(() => loadQuoteSettings());

  const dirty = useMemo(() => JSON.stringify(form) !== JSON.stringify(saved), [form, saved]);

  const updateField = <K extends keyof QuoteSettingsData>(field: K, value: QuoteSettingsData[K]) => {
    setForm((prev) => ({ ...prev, [field]: value }));
  };

  const updateNumberField = (field: 'cardFaceValue' | 'platformFaceValue' | 'profitMarkup' | 'continuedMarkup', value: string) => {
    updateField(field, sanitizeNumberText(value));
  };

  const handleSave = () => {
    if (!dirty) return;
    saveQuoteSettings(form);
    setSaved({ ...form });
    notify('报价设置已保存');
  };

  const handleReset = async () => {
    const confirmed = await confirmAction('将把生效商品、智能计算与基础设置恢复为默认值。', { title: '恢复默认设置' });
    if (confirmed) setForm({ ...DEFAULT_QUOTE_SETTINGS });
  };

  return (
    <div className="logistics-page page-stack">
      <QuoteScopeSection
        form={form}
        onChangeScope={(scope) => updateField('scope', scope)}
        onChangeSelectedItems={(keys) => updateField('selectedItemKeys', keys)}
      />
      <QuoteSmartCalcSection form={form} onChangeField={updateField} onNumberFieldChange={updateNumberField} />
      <QuoteBasicSection form={form} onChangeField={updateField} />

      <section className="section-panel">
        <div className="flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-xs leading-relaxed text-[var(--text-muted)]">
            设置保存在本机浏览器，点击保存后立即生效；「恢复默认」会还原全部配置。
          </p>
          <div className="flex flex-wrap gap-2">
            <button type="button" className="ios-btn-secondary rounded-md px-4 py-2 text-sm" onClick={() => void handleReset()}>
              恢复默认
            </button>
            <button
              type="button"
              className="ios-btn-primary flex items-center gap-2 rounded-md px-4 py-2 text-sm disabled:cursor-not-allowed disabled:opacity-45"
              disabled={!dirty}
              onClick={handleSave}
            >
              保存设置
            </button>
          </div>
        </div>
      </section>
    </div>
  );
};

export default QuoteSettings;
