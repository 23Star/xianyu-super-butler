import { useState } from 'react';
import { Equal, Info, MessageSquareText, ShoppingCart, TrendingUp, type LucideIcon } from 'lucide-react';
import {
  DEFAULT_QUOTE_REPLY_TEMPLATES,
  QUOTE_REPLY_TEMPLATE_META,
  type QuoteReplyTemplateKey,
  type QuoteReplyTemplates,
} from '../../services/quoteReply';
import { TEMPLATE_SPLIT_TOKEN } from '../../utils/quoteTemplate';
import { PageTabs, SectionHeader, Tooltip } from '../ui';
import QuoteTemplateEditor from './QuoteTemplateEditor';

interface QuoteReplyTemplatesSectionProps {
  form: QuoteReplyTemplates;
  sampleValues: Record<string, string>;
  onChangeTemplate: (key: QuoteReplyTemplateKey, value: string) => void;
}

interface ScenarioTab {
  id: QuoteReplyTemplateKey;
  label: string;
  icon: LucideIcon;
}

/** 报价主流程的四个场景文案，切换标签编辑同一段配置。 */
const SCENARIO_TABS: ScenarioTab[] = [
  { id: 'quoteMessage', label: QUOTE_REPLY_TEMPLATE_META.quoteMessage.label, icon: MessageSquareText },
  { id: 'diffPositive', label: QUOTE_REPLY_TEMPLATE_META.diffPositive.label, icon: TrendingUp },
  { id: 'diffZero', label: QUOTE_REPLY_TEMPLATE_META.diffZero.label, icon: Equal },
  { id: 'guideOrder', label: QUOTE_REPLY_TEMPLATE_META.guideOrder.label, icon: ShoppingCart },
];

/** AI 回复文案：报价消息与差价、拍下引导等场景文案。 */
const QuoteReplyTemplatesSection = ({
  form,
  sampleValues,
  onChangeTemplate,
}: QuoteReplyTemplatesSectionProps) => {
  const [activeKey, setActiveKey] = useState<QuoteReplyTemplateKey>('quoteMessage');
  const meta = QUOTE_REPLY_TEMPLATE_META[activeKey];

  return (
    <section className="section-panel" aria-labelledby="quote-reply-templates-title">
      <SectionHeader
        title="AI 回复文案"
        description="配置自动报价时 AI 发给买家的文案：先给出报价，再按差价结果回复，并引导买家拍下。"
        icon={MessageSquareText}
      />
      <div className="grid gap-4 p-4">
        <PageTabs
          value={activeKey}
          onChange={setActiveKey}
          items={SCENARIO_TABS.map(({ id, label, icon }) => ({ id, label, icon }))}
          ariaLabel="自动报价回复文案场景"
        />
        <QuoteTemplateEditor
          id={`quote-reply-${activeKey}`}
          label="文案内容"
          hint={meta.hint}
          value={form[activeKey]}
          placeholder={meta.placeholder}
          sampleValues={sampleValues}
          renderTool={(insertText) => (
            <div className="logistics-split-tool">
              <Tooltip
                content="在文案中插入 {分隔符} 标记，发送时按标记拆成多条消息依次发送，不合并成一条"
                side="top"
                align="right"
              >
                <button type="button" className="logistics-split-tool__info" aria-label="分隔符说明">
                  <Info className="h-4 w-4" aria-hidden="true" />
                </button>
              </Tooltip>
              <button
                type="button"
                className="logistics-split-tool__btn"
                onClick={() => insertText(TEMPLATE_SPLIT_TOKEN)}
              >
                插入分隔符
              </button>
            </div>
          )}
          onReset={() => onChangeTemplate(activeKey, DEFAULT_QUOTE_REPLY_TEMPLATES[activeKey])}
          onChange={(value) => onChangeTemplate(activeKey, value)}
        />
      </div>
    </section>
  );
};

export default QuoteReplyTemplatesSection;
