import { useEffect, useMemo, useState } from 'react';
import { Boxes } from 'lucide-react';
import { notify } from '../../services/feedback';
import { getItems } from '../../services/api';
import type { Item } from '../../types';
import type { QuoteScope, QuoteSettings } from '../../services/quoteSettings';
import TagPicker, { type TagPickerOption } from '../TagPicker';
import { SectionHeader } from '../ui';

/** 选项与标签里展示的简写标题长度，完整标题放入次行与悬浮提示。 */
const SHORT_TITLE_MAX = 14;

const shortenTitle = (raw: string) => {
  const title = raw.trim().replace(/\s+/g, ' ');
  if (!title) return '';
  return title.length > SHORT_TITLE_MAX ? `${title.slice(0, SHORT_TITLE_MAX)}…` : title;
};

const itemKeyOf = (item: Pick<Item, 'cookie_id' | 'item_id'>) => `${item.cookie_id}:${item.item_id}`;

interface QuoteScopeSectionProps {
  form: QuoteSettings;
  onChangeScope: (scope: QuoteScope) => void;
  onChangeSelectedItems: (keys: string[]) => void;
}

/** 生效商品：拉取在售商品库并选择报价设置的适用范围。 */
const QuoteScopeSection = ({ form, onChangeScope, onChangeSelectedItems }: QuoteScopeSectionProps) => {
  const [items, setItems] = useState<Item[]>([]);
  const [itemsLoading, setItemsLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    const loadItems = async () => {
      setItemsLoading(true);
      try {
        const data = await getItems();
        if (!cancelled) setItems(data);
      } catch {
        if (!cancelled) notify('商品列表加载失败，请稍后重试');
      } finally {
        if (!cancelled) setItemsLoading(false);
      }
    };
    void loadItems();
    return () => { cancelled = true; };
  }, []);

  const itemOptions = useMemo<TagPickerOption[]>(() => items.map(item => {
    const fullTitle = (item.item_title || '').trim();
    const shortTitle = shortenTitle(fullTitle);
    const price = (item.item_price || '').trim().replace(/^[¥￥]\s*/, '');
    const description = [
      fullTitle && fullTitle !== shortTitle ? fullTitle : '',
      price ? `¥${price}` : '',
    ].filter(Boolean).join(' · ');
    return {
      value: itemKeyOf(item),
      label: shortTitle || `商品 ${item.item_id}`,
      imageUrl: item.item_image,
      description: description || undefined,
    };
  }), [items]);

  return (
    <section className="section-panel" aria-labelledby="quote-scope-title">
      <SectionHeader
        title="生效商品"
        description="选择报价设置套用的商品范围：全部商品统一配置报价识别，或者指定商品配置报价识别。"
        icon={Boxes}
      />
      <div className="grid gap-4 p-4">
        <div className="flex flex-wrap items-center gap-3">
          <div
            role="radiogroup"
            aria-label="报价生效范围"
            className="inline-flex rounded-full border border-[var(--border)] bg-[var(--surface-strong)] p-1"
          >
            {([
              { value: 'all', label: '全部商品' },
              { value: 'custom', label: '指定商品' },
            ] as Array<{ value: QuoteScope; label: string }>).map(option => {
              const active = form.scope === option.value;
              return (
                <button
                  type="button"
                  key={option.value}
                  role="radio"
                  aria-checked={active}
                  onClick={() => onChangeScope(option.value)}
                  className={`rounded-full px-4 py-1.5 text-sm font-semibold transition-colors duration-150 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--focus-ring)] motion-reduce:transition-none ${
                    active
                      ? 'bg-[var(--brand)] text-[var(--brand-ink)] shadow-sm'
                      : 'text-[var(--text-muted)] hover:text-[var(--text)]'
                  }`}
                >
                  {option.label}
                </button>
              );
            })}
          </div>
          <span className="text-xs leading-relaxed text-[var(--text-muted)]">
            {form.scope === 'all'
              ? '全部商品均按当前配置进行报价识别。'
              : form.selectedItemKeys.length > 0
                ? `已选择 ${form.selectedItemKeys.length} 件商品。`
                : '尚未选择商品。'}
          </span>
        </div>

        {form.scope === 'custom' && (
          <div>
            <span className="field-label">选择商品</span>
            <TagPicker
              options={itemOptions}
              selected={form.selectedItemKeys}
              onChange={onChangeSelectedItems}
              multiple
              searchable
              placeholder="选择一个或多个商品"
              searchPlaceholder="搜索商品标题"
              emptyText={items.length === 0 ? '暂无商品，请先在「商品与发货」页同步商品' : '没有匹配的商品'}
              loading={itemsLoading}
              loadingText="正在加载商品"
              ariaLabel="选择报价生效商品"
            />
            <span className="mt-1.5 block text-xs leading-relaxed text-[var(--text-muted)]">
              支持单选与多选；仅所选商品会使用当前报价设置，其余商品不受影响。
            </span>
            {form.selectedItemKeys.length === 0 && (
              <p
                role="status"
                className="mt-2 rounded-md border border-[var(--border)] bg-[var(--warning-soft)] px-3 py-2 text-xs leading-relaxed text-[var(--warning-ink)]"
              >
                尚未选择任何商品，当前报价设置暂时不会作用于任何商品。
              </p>
            )}
          </div>
        )}
      </div>
    </section>
  );
};

export default QuoteScopeSection;
