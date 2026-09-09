import { RotateCcw } from 'lucide-react';
import { useMemo, useRef, useState, type DragEvent, type KeyboardEvent, type ReactNode } from 'react';
import { confirmAction } from '../../services/feedback';
import { Tooltip } from '../ui';
import {
  DEFAULT_TOKEN_ORDER,
  loadTokenOrder,
  renderTemplate,
  saveTokenOrder,
  TOKENS,
} from '../../utils/quoteTemplate';

interface QuoteTemplateEditorProps {
  /** 文本框唯一 id，用于把标签与参数按钮关联到输入框。 */
  id: string;
  label: string;
  /** 发送时机等辅助说明，显示在标签下方。 */
  hint?: string;
  value: string;
  placeholder?: string;
  rows?: number;
  /** 代入预览的示例参数，统一由 utils/quoteTemplate 提供。 */
  sampleValues: Record<string, string>;
  previewLabel?: string;
  emptyPreviewText?: string;
  /** 是否展示参数插入按钮行；纯问候类文案可关闭。 */
  showTokens?: boolean;
  /** 编辑器插入能力插槽：外层组合独立控件（如分隔符），插入位置跟随光标。 */
  renderTool?: (insertText: (text: string) => void) => ReactNode;
  /** 传入后展示「恢复默认模板」按钮，确认后恢复该条文案的默认模板。 */
  onReset?: () => void;
  onChange: (value: string) => void;
}

/**
 * 回复模板编辑器：文本框 + 参数插入 + 实时预览。
 * 第三步消息模板编辑器：统一处理参数插入、预览和恢复默认。
 */
const QuoteTemplateEditor = ({
  id,
  label,
  hint,
  value,
  placeholder,
  rows = 4,
  sampleValues,
  previewLabel = '回复预览',
  emptyPreviewText = '回复模板为空',
  showTokens = true,
  renderTool,
  onReset,
  onChange,
}: QuoteTemplateEditorProps) => {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const [tokenOrder, setTokenOrder] = useState<string[]>(() => loadTokenOrder());
  const [draggingLabel, setDraggingLabel] = useState<string | null>(null);
  const [dropTarget, setDropTarget] = useState<{ label: string; position: 'before' | 'after' } | null>(null);
  const [orderStatus, setOrderStatus] = useState('');
  const dragMovedRef = useRef(false);

  const orderedTokens = useMemo(() => {
    const tokenMap = new Map(TOKENS.map((token) => [token.label, token] as const));
    return tokenOrder
      .map((label) => tokenMap.get(label))
      .filter((token): token is (typeof TOKENS)[number] => Boolean(token));
  }, [tokenOrder]);

  const insertToken = (token: string) => {
    const el = textareaRef.current;
    if (!el) return;
    const start = el.selectionStart ?? el.value.length;
    const end = el.selectionEnd ?? start;
    const caret = start + token.length;
    const next = `${el.value.slice(0, start)}${token}${el.value.slice(end)}`;
    onChange(next);
    requestAnimationFrame(() => {
      el.focus();
      el.setSelectionRange(caret, caret);
    });
  };

  const persistTokenOrder = (nextOrder: string[], message: string) => {
    setTokenOrder(nextOrder);
    saveTokenOrder(nextOrder);
    setOrderStatus(message);
  };

  const moveToken = (label: string, offset: -1 | 1) => {
    const index = tokenOrder.indexOf(label);
    const nextIndex = index + offset;
    if (index < 0 || nextIndex < 0 || nextIndex >= tokenOrder.length) return;
    const nextOrder = [...tokenOrder];
    [nextOrder[index], nextOrder[nextIndex]] = [nextOrder[nextIndex], nextOrder[index]];
    persistTokenOrder(nextOrder, `${label}已移至第 ${nextIndex + 1} 项`);
  };

  const handleTokenKeyDown = (event: KeyboardEvent<HTMLButtonElement>, label: string) => {
    if (!event.altKey || (event.key !== 'ArrowUp' && event.key !== 'ArrowDown')) return;
    event.preventDefault();
    moveToken(label, event.key === 'ArrowUp' ? -1 : 1);
  };

  const handleDragStart = (event: DragEvent<HTMLDivElement>, label: string) => {
    dragMovedRef.current = true;
    event.dataTransfer.effectAllowed = 'move';
    event.dataTransfer.setData('text/plain', label);
    setDraggingLabel(label);
    setDropTarget(null);
  };

  const handleDragOver = (event: DragEvent<HTMLDivElement>, label: string) => {
    if (!draggingLabel || draggingLabel === label) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = 'move';
    const rect = event.currentTarget.getBoundingClientRect();
    setDropTarget({ label, position: event.clientY < rect.top + rect.height / 2 ? 'before' : 'after' });
  };

  const handleDrop = (event: DragEvent<HTMLDivElement>, targetLabel: string) => {
    event.preventDefault();
    const sourceLabel = event.dataTransfer.getData('text/plain') || draggingLabel;
    const position = dropTarget?.label === targetLabel ? dropTarget.position : 'before';
    if (!sourceLabel || sourceLabel === targetLabel) {
      setDraggingLabel(null);
      setDropTarget(null);
      return;
    }

    const nextOrder = tokenOrder.filter((label) => label !== sourceLabel);
    const targetIndex = nextOrder.indexOf(targetLabel);
    if (targetIndex < 0) {
      setDraggingLabel(null);
      setDropTarget(null);
      return;
    }
    nextOrder.splice(position === 'after' ? targetIndex + 1 : targetIndex, 0, sourceLabel);
    persistTokenOrder(nextOrder, `${sourceLabel}已调整到第 ${nextOrder.indexOf(sourceLabel) + 1} 项`);
    setDraggingLabel(null);
    setDropTarget(null);
  };

  const handleDragEnd = () => {
    setDraggingLabel(null);
    setDropTarget(null);
    window.setTimeout(() => {
      dragMovedRef.current = false;
    }, 0);
  };

  const resetTokenOrder = () => {
    persistTokenOrder([...DEFAULT_TOKEN_ORDER], '参数顺序已恢复默认');
  };

  const handleReset = async () => {
    if (!onReset) return;
    const confirmed = await confirmAction('将把当前文案恢复为默认模板，未保存的修改会丢失。', {
      title: '恢复默认模板',
    });
    if (confirmed) {
      onReset();
      resetTokenOrder();
    }
  };

  const preview = renderTemplate(value, sampleValues);

  return (
    <div>
      <div className="logistics-editor-head">
        <div className="logistics-editor-head__label">
          <label htmlFor={id}>
            <span className="field-label">{label}</span>
          </label>
          {hint && (
            <p className="mt-0.5 mb-1.5 text-xs leading-relaxed text-[var(--text-muted)]">{hint}</p>
          )}
        </div>
        {renderTool?.(insertToken)}
      </div>
      <textarea
        ref={textareaRef}
        id={id}
        value={value}
        rows={rows}
        placeholder={placeholder}
        onChange={(event) => onChange(event.target.value)}
        className="ios-input w-full rounded-md px-3 py-2.5 text-sm leading-relaxed"
      />
      {showTokens && (
        <div className="logistics-token-tray">
          <div className="logistics-token-tray__head">
            <div className="logistics-token-tray__title">
              <span>点击插入参数</span>
              <small>拖动调整顺序</small>
            </div>
            <div className="logistics-token-tray__actions">
              <Tooltip
                content="把参数按钮恢复为默认排列，只影响插入按钮的顺序，不改已写好的模板文字"
                side="top"
                align="right"
              >
                <button
                  type="button"
                  className="logistics-token-order-reset"
                  onClick={resetTokenOrder}
                  aria-label="恢复参数默认顺序"
                >
                  <RotateCcw className="h-3.5 w-3.5" aria-hidden="true" />
                  恢复顺序
                </button>
              </Tooltip>
              {onReset && (
                <button
                  type="button"
                  className="logistics-token-reset"
                  onClick={() => void handleReset()}
                  aria-label="恢复默认模板"
                >
                  恢复默认模板
                </button>
              )}
            </div>
          </div>
          <div className="logistics-token-tray__chips" role="list" aria-label="可插入参数，支持排序">
            {orderedTokens.map((token, index) => {
              const isDragging = draggingLabel === token.label;
              const isDropTarget = dropTarget?.label === token.label;
              return (
                <div
                  className={`logistics-token-item${isDragging ? ' is-dragging' : ''}${isDropTarget ? ` is-drop-${dropTarget.position}` : ''}`}
                  key={token.label}
                  role="listitem"
                  draggable
                  onDragStart={(event) => handleDragStart(event, token.label)}
                  onDragOver={(event) => handleDragOver(event, token.label)}
                  onDrop={(event) => handleDrop(event, token.label)}
                  onDragEnd={handleDragEnd}
                >
                  <button
                    type="button"
                    className="logistics-token-chip"
                    onClick={() => {
                      if (dragMovedRef.current) {
                        dragMovedRef.current = false;
                        return;
                      }
                      insertToken(`{${token.label}}`);
                    }}
                    onKeyDown={(event) => handleTokenKeyDown(event, token.label)}
                    aria-label={`插入参数 {${token.label}}，当前第 ${index + 1} 项`}
                    aria-keyshortcuts="Alt+ArrowUp Alt+ArrowDown"
                    title="点击插入，拖动排序；Alt+上/下调整位置"
                  >
                    {`{${token.label}}`}
                  </button>
                </div>
              );
            })}
          </div>
          <span className="sr-only" aria-live="polite">{orderStatus}</span>
        </div>
      )}
      {!showTokens && onReset && (
        <div className="logistics-token-solo">
          <button
            type="button"
            className="logistics-token-reset"
            onClick={() => void handleReset()}
            aria-label="恢复默认模板"
          >
            恢复默认模板
          </button>
        </div>
      )}
      <div className="logistics-form-section__heading">
        <span>{previewLabel}</span>
        <small>已识别样本或待输入状态预览，实际发送以买家消息识别结果填充</small>
      </div>
      <div>
        <div className="logistics-chat-bubble whitespace-pre-wrap">{preview || emptyPreviewText}</div>
      </div>
    </div>
  );
};

export default QuoteTemplateEditor;
