import { CircleHelp } from 'lucide-react';
import {
  DEFAULT_QUOTE_REPLY_TEMPLATES,
  QUOTE_REPLY_TEMPLATE_META,
  type QuoteReplyTemplateKey,
  type QuoteReplyTemplates,
} from '../../services/quoteReply';
import { SectionHeader } from '../ui';
import QuoteTemplateEditor from './QuoteTemplateEditor';

interface QuoteFollowUpSectionProps {
  form: QuoteReplyTemplates;
  sampleValues: Record<string, string>;
  onChangeTemplate: (key: QuoteReplyTemplateKey, value: string) => void;
}

/** 追问与首次回复：两条独立发送时机的文案，逐条编辑。 */
const QuoteFollowUpSection = ({ form, sampleValues, onChangeTemplate }: QuoteFollowUpSectionProps) => (
  <section className="section-panel" aria-labelledby="quote-follow-up-title">
    <SectionHeader
      title="追问与首次回复"
      description="缺少计费参数时自动追问，买家首次进店时自动打招呼，帮报价补齐信息。"
      icon={CircleHelp}
    />
    <div className="grid gap-5 p-4">
      <QuoteTemplateEditor
        id="quote-reply-missing-params"
        label={QUOTE_REPLY_TEMPLATE_META.missingParams.label}
        hint={QUOTE_REPLY_TEMPLATE_META.missingParams.hint}
        value={form.missingParams}
        placeholder={QUOTE_REPLY_TEMPLATE_META.missingParams.placeholder}
        rows={3}
        sampleValues={sampleValues}
        showTokens={false}
        onReset={() => onChangeTemplate('missingParams', DEFAULT_QUOTE_REPLY_TEMPLATES.missingParams)}
        onChange={(value) => onChangeTemplate('missingParams', value)}
      />
      <QuoteTemplateEditor
        id="quote-reply-first-reply"
        label={QUOTE_REPLY_TEMPLATE_META.firstReply.label}
        hint={QUOTE_REPLY_TEMPLATE_META.firstReply.hint}
        value={form.firstReply}
        placeholder={QUOTE_REPLY_TEMPLATE_META.firstReply.placeholder}
        rows={3}
        sampleValues={sampleValues}
        showTokens={false}
        onReset={() => onChangeTemplate('firstReply', DEFAULT_QUOTE_REPLY_TEMPLATES.firstReply)}
        onChange={(value) => onChangeTemplate('firstReply', value)}
      />
    </div>
  </section>
);

export default QuoteFollowUpSection;
