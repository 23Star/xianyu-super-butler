import React, { useEffect, useMemo, useState } from 'react';
import { Box, Check, ChevronDown, Loader2, Search, X } from 'lucide-react';
import { Popover } from './ui';

export interface TagPickerOption {
  /** 唯一标识，选中值集合即由它组成。 */
  value: string;
  /** 主展示文本。 */
  label: string;
  /** 可选缩略图，加载失败或缺失时回退为占位图标。 */
  imageUrl?: string;
  /** 次要说明行，如全称、价格等。 */
  description?: string;
  disabled?: boolean;
}

interface TagPickerProps {
  options: TagPickerOption[];
  /** 当前选中的 value 集合；单选模式数组长度为 0 或 1。 */
  selected: string[];
  onChange: (selected: string[]) => void;
  /** 多选（默认）：下拉内逐项勾选，选中项在触发框内以标签呈现；单选：点击即选中并收起。 */
  multiple?: boolean;
  searchable?: boolean;
  placeholder?: string;
  searchPlaceholder?: string;
  emptyText?: string;
  loading?: boolean;
  loadingText?: string;
  disabled?: boolean;
  ariaLabel?: string;
}

const normalizeImageUrl = (url?: string) => {
  const value = url?.trim();
  if (!value) return '';
  return value.startsWith('//') ? `https:${value}` : value;
};

const OptionImage: React.FC<{ option: TagPickerOption }> = ({ option }) => {
  const src = normalizeImageUrl(option.imageUrl);
  const [failed, setFailed] = useState(false);

  useEffect(() => setFailed(false), [src]);

  if (!src || failed) {
    return (
      <span
        aria-hidden="true"
        className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-[var(--surface-strong)] text-[var(--text-soft)]"
      >
        <Box className="h-4 w-4" />
      </span>
    );
  }

  return (
    <img
      src={src}
      alt=""
      className="h-8 w-8 shrink-0 rounded-md border border-[var(--border)] object-cover"
      loading="lazy"
      referrerPolicy="no-referrer"
      onError={() => setFailed(true)}
    />
  );
};

/**
 * 通用标签选择器：下拉列表 + 可搜索 + 选中项以可移除标签回显。
 * 样式全部基于 Tailwind 与全局设计令牌，供各业务按需组合选项数据复用。
 */
const TagPicker: React.FC<TagPickerProps> = ({
  options,
  selected,
  onChange,
  multiple = true,
  searchable = true,
  placeholder = '请选择',
  searchPlaceholder = '搜索',
  emptyText = '暂无可选项',
  loading = false,
  loadingText = '正在加载',
  disabled = false,
  ariaLabel,
}) => {
  const [open, setOpen] = useState(false);
  const [keyword, setKeyword] = useState('');

  const selectedSet = useMemo(() => new Set(selected), [selected]);

  const filteredOptions = useMemo(() => {
    const text = keyword.trim().toLowerCase();
    if (!text) return options;
    return options.filter(option =>
      `${option.label} ${option.description ?? ''}`.toLowerCase().includes(text),
    );
  }, [options, keyword]);

  // 选中的 value 若已不在 options 中（如商品被删除），仍以原值回显，保证可移除。
  const selectedOptions = useMemo(
    () => selected.map(value => options.find(option => option.value === value) ?? { value, label: value }),
    [options, selected],
  );

  const toggleOpen = () => {
    if (disabled) return;
    setOpen((current) => !current);
  };

  const handleTriggerKeyDown = (event: React.KeyboardEvent) => {
    if (disabled) return;
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      toggleOpen();
    }
  };

  const toggleOption = (value: string) => {
    if (multiple) {
      onChange(selectedSet.has(value) ? selected.filter(current => current !== value) : [...selected, value]);
    } else {
      onChange([value]);
      setOpen(false);
    }
  };

  const removeValue = (event: React.MouseEvent, value: string) => {
    event.stopPropagation();
    event.preventDefault();
    onChange(selected.filter(current => current !== value));
  };

  return (
    <Popover
      open={open}
      onClose={() => setOpen(false)}
      portal
      panelClassName="max-h-80 w-[min(22rem,calc(100vw-3rem))]"
      trigger={(
        <div
          role="button"
          tabIndex={disabled ? -1 : 0}
          aria-haspopup="listbox"
          aria-expanded={open}
          aria-label={ariaLabel}
          aria-disabled={disabled}
          onClick={toggleOpen}
          onKeyDown={handleTriggerKeyDown}
          className={`flex min-h-[42px] w-full cursor-pointer flex-wrap items-center gap-1.5 rounded-md border border-[var(--border)] bg-[var(--surface)] px-3 py-1.5 text-left text-sm transition-colors duration-150 hover:border-[var(--border-strong)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--focus-ring)] motion-reduce:transition-none ${
            disabled ? 'cursor-not-allowed opacity-50' : ''
          }`}
        >
          {selectedOptions.length === 0 ? (
            <span className="flex-1 text-[var(--text-soft)]">{placeholder}</span>
          ) : (
            <span className="flex min-w-0 flex-1 flex-wrap items-center gap-1.5">
              {multiple ? (
                selectedOptions.map(option => (
                  <span
                    key={option.value}
                    className="inline-flex max-w-full items-center gap-1 rounded-full bg-[var(--surface-strong)] py-0.5 pl-2.5 pr-1 text-xs leading-5 text-[var(--text)]"
                  >
                    <span className="min-w-0 max-w-[10rem] truncate" title={option.label}>{option.label}</span>
                    <button
                      type="button"
                      onClick={event => removeValue(event, option.value)}
                      aria-label={`移除 ${option.label}`}
                      className="relative inline-flex h-4 w-4 shrink-0 items-center justify-center rounded-full text-[var(--text-soft)] transition-colors duration-150 after:absolute after:-inset-1.5 after:content-[''] hover:bg-[var(--danger-soft)] hover:text-[var(--danger)] motion-reduce:transition-none"
                    >
                      <X className="h-3 w-3" aria-hidden="true" />
                    </button>
                  </span>
                ))
              ) : (
                <span className="min-w-0 flex-1 truncate text-[var(--text)]" title={selectedOptions[0].label}>
                  {selectedOptions[0].label}
                </span>
              )}
            </span>
          )}
          <ChevronDown
            aria-hidden="true"
            className={`h-4 w-4 shrink-0 text-[var(--text-soft)] transition-transform duration-150 motion-reduce:transition-none ${
              open ? 'rotate-180' : ''
            }`}
          />
        </div>
      )}
    >
      {searchable && (
        <div className="relative mb-1.5">
          <Search
            aria-hidden="true"
            className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--text-soft)]"
          />
          <input
            type="text"
            value={keyword}
            onChange={event => setKeyword(event.target.value)}
            placeholder={searchPlaceholder}
            aria-label={searchPlaceholder}
            className="ios-input w-full rounded-md py-2 pl-8 pr-3 text-sm"
          />
        </div>
      )}

      <div role="listbox" aria-multiselectable={multiple} aria-label={ariaLabel} className="space-y-0.5">
        {loading ? (
          <div className="flex items-center justify-center gap-2 px-2 py-6 text-sm text-[var(--text-muted)]">
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
            {loadingText}
          </div>
        ) : filteredOptions.length === 0 ? (
          <p className="px-2 py-6 text-center text-sm text-[var(--text-muted)]">{emptyText}</p>
        ) : (
          filteredOptions.map(option => {
            const isSelected = selectedSet.has(option.value);
            return (
              <button
                type="button"
                key={option.value}
                role="option"
                aria-selected={isSelected}
                disabled={option.disabled}
                onClick={() => toggleOption(option.value)}
                className={`flex w-full items-center gap-2.5 rounded-md px-2 py-2 text-left transition-colors duration-150 hover:bg-[var(--surface-hover)] disabled:cursor-not-allowed disabled:opacity-50 motion-reduce:transition-none ${
                  isSelected ? 'bg-[var(--brand-50)]' : ''
                }`}
              >
                <OptionImage option={option} />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[13px] font-semibold text-[var(--text)]" title={option.label}>
                    {option.label}
                  </span>
                  {option.description && (
                    <span className="mt-0.5 block truncate text-xs leading-4 text-[var(--text-muted)]">
                      {option.description}
                    </span>
                  )}
                </span>
                {isSelected ? (
                  <Check className="h-4 w-4 shrink-0 text-[var(--brand-text)]" aria-hidden="true" />
                ) : (
                  <span className="h-4 w-4 shrink-0" aria-hidden="true" />
                )}
              </button>
            );
          })
        )}
      </div>

      {multiple && selected.length > 0 && (
        <div className="mt-1.5 flex items-center justify-between border-t border-[var(--border)] pt-1.5">
          <span className="text-xs text-[var(--text-muted)]">已选 {selected.length} 项</span>
          <button
            type="button"
            onClick={() => onChange([])}
            className="rounded-md px-2 py-1 text-xs font-semibold text-[var(--danger-ink)] transition-colors duration-150 hover:bg-[var(--danger-soft)] motion-reduce:transition-none"
          >
            清空
          </button>
        </div>
      )}
    </Popover>
  );
};

export default TagPicker;
