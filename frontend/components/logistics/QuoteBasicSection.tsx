import { useRef } from 'react';
import { SlidersHorizontal } from 'lucide-react';
import type { QuoteSettings } from '../../services/quoteSettings';
import { buildSampleValues, renderTemplate, TOKENS } from '../../utils/quoteTemplate';
import { SectionHeader } from '../ui';

interface QuoteBasicSectionProps {
  form: QuoteSettings;
  onChangeField: <K extends keyof QuoteSettings>(field: K, value: QuoteSettings[K]) => void;
}

/** 基础设置：默认计费口径与买家回复模板（参数插入 + 实时预览）。 */
const QuoteBasicSection = ({ form, onChangeField }: QuoteBasicSectionProps) => {
  const replyRef = useRef<HTMLTextAreaElement>(null);

  const insertToken = (token: string) => {
    const el = replyRef.current;
    if (!el) return;
    const start = el.selectionStart ?? el.value.length;
    const end = el.selectionEnd ?? start;
    const caret = start + token.length;
    const next = `${el.value.slice(0, start)}${token}${el.value.slice(end)}`;
    onChangeField('replyTemplate', next);
    requestAnimationFrame(() => {
      el.focus();
      el.setSelectionRange(caret, caret);
    });
  };

  const renderedReply = renderTemplate(form.replyTemplate, buildSampleValues(form));

  return (
    <section className="section-panel" aria-labelledby="basic-settings-title">
      <SectionHeader
        title="基础设置"
        description="默认计费口径与买家回复模板，未识别重量或体积时也能给出明确报价。"
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

        <label>
          <span className="field-label">回复消息自定义</span>
          <textarea
            ref={replyRef}
            value={form.replyTemplate}
            onChange={(event) => onChangeField('replyTemplate', event.target.value)}
            rows={5}
            placeholder="用于向买家解释报价与计费口径"
            className="ios-input w-full rounded-md px-3 py-2.5 text-sm leading-relaxed"
          />
        </label>
        <div className="logistics-token-row">
          <span>点击插入参数</span>
          {TOKENS.map((token) => (
            <button
              type="button"
              key={token.label}
              onClick={() => insertToken(`{${token.label}}`)}
              aria-label={`插入参数 {${token.label}}`}
            >
              {`{${token.label}}`}
            </button>
          ))}
        </div>
        <div className="logistics-form-section__heading">
          <span>回复预览</span>
          <small>以示例参数代入</small>
        </div>
        <div>
          <div className="logistics-chat-bubble whitespace-pre-wrap">{renderedReply || '回复模板为空'}</div>
        </div>
      </div>
    </section>
  );
};

export default QuoteBasicSection;
