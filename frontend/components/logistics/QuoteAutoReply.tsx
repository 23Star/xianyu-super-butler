import { useEffect, useMemo, useState } from 'react';
import { Bot } from 'lucide-react';
import { notify, confirmAction } from '../../services/feedback';
import { loadQuoteSettings } from '../../services/quoteSettings';
import { listQuoteBooks, type LogisticsQuoteBook } from '../../services/api';
import {
  DEFAULT_QUOTE_REPLY_TEMPLATES,
  loadQuoteReplyTemplates,
  saveQuoteReplyTemplates,
  type QuoteReplyTemplateKey,
  type QuoteReplyTemplates,
} from '../../services/quoteReply';
import { buildSampleValues } from '../../utils/quoteTemplate';
import FloatingSaveButton from '../FloatingSaveButton';
import QuoteFollowUpSection from './QuoteFollowUpSection';
import QuoteReplyTemplatesSection from './QuoteReplyTemplatesSection';

/** 消息模板设置（第三步）：AI 回复文案配置容器，管理表单状态、保存与恢复默认。 */
const QuoteAutoReply = () => {
  const [form, setForm] = useState<QuoteReplyTemplates>(() => loadQuoteReplyTemplates());
  const [saved, setSaved] = useState<QuoteReplyTemplates>(() => loadQuoteReplyTemplates());
  const [latestBook, setLatestBook] = useState<LogisticsQuoteBook | null>(null);

  const dirty = useMemo(() => JSON.stringify(form) !== JSON.stringify(saved), [form, saved]);

  useEffect(() => {
    let active = true;
    void listQuoteBooks().then((response) => {
      if (active) setLatestBook(response.books[0] ?? null);
    }).catch(() => {
      if (active) setLatestBook(null);
    });
    return () => { active = false; };
  }, []);

  const sampleValues = useMemo(() => {
    const row = latestBook?.payload.sample_row;
    return buildSampleValues(loadQuoteSettings(), row ? {
      service: row.carrier,
      route: row.route,
      origin: row.origin || row.origin_province,
      destination: row.destination || row.destination_province,
      firstWeightKg: row.first_weight_kg,
      firstPrice: row.first_price,
      continuedUnitKg: row.continued_unit_kg,
      continuedPrice: row.continued_price,
    } : null);
  }, [latestBook]);

  const updateTemplate = (key: QuoteReplyTemplateKey, value: string) => {
    setForm((prev) => ({ ...prev, [key]: value }));
  };

  const handleSave = () => {
    if (!dirty) return;
    saveQuoteReplyTemplates(form);
    setSaved({ ...form });
    notify('消息模板已保存');
  };

  const handleDiscard = () => {
    setForm({ ...saved });
  };

  const handleReset = async () => {
    const confirmed = await confirmAction('将把 AI 回复文案与追问、首次回复恢复为默认文案。', { title: '恢复默认文案' });
    if (confirmed) setForm({ ...DEFAULT_QUOTE_REPLY_TEMPLATES });
  };

  return (
    <div className="logistics-page page-stack">
      <QuoteReplyTemplatesSection form={form} sampleValues={sampleValues} onChangeTemplate={updateTemplate} />
      <QuoteFollowUpSection form={form} sampleValues={sampleValues} onChangeTemplate={updateTemplate} />

      <section className="section-panel">
        <div className="flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-xs leading-relaxed text-[var(--text-muted)]">
            文案保存在本机浏览器，点击保存后立即生效；「恢复默认」会还原全部消息模板。
          </p>
          <div className="flex flex-wrap gap-2">
            <button type="button" className="ios-btn-secondary rounded-md px-4 py-2 text-sm" onClick={() => void handleReset()}>
              恢复默认
            </button>
          </div>
        </div>
      </section>

      <FloatingSaveButton
        dirty={dirty}
        guardKey="quote-reply-templates"
        guardLabel="消息模板文案"
        label="保存文案"
        onSave={handleSave}
        onDiscard={handleDiscard}
      />
    </div>
  );
};

export default QuoteAutoReply;
