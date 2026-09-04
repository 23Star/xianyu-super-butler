import { FileSpreadsheet, RefreshCw, Trash2 } from 'lucide-react';
import type { LogisticsQuoteBook } from '../../services/api';
import {
  bookKindLabel,
  bookWeightRule,
  formatBookName,
  formatRecognizedAt,
  ruleLabels,
} from '../../services/logisticsQuote';
import { EmptyState, SectionHeader } from '../ui';

interface QuoteBookListProps {
  books: LogisticsQuoteBook[];
  isRefreshing: boolean;
  isDeletingId: number | null;
  onRefresh: () => void;
  onDelete: (bookId: number) => void;
}

/** 已识别的报价表列表：识别结果卡片、刷新与删除。 */
const QuoteBookList = ({ books, isRefreshing, isDeletingId, onRefresh, onDelete }: QuoteBookListProps) => (
  <section className="section-panel" aria-labelledby="rate-book-list-title">
    <SectionHeader
      title="已识别的报价表"
      description="识别结果会自动保存，后续的报价设置与自动报价都会用到这些数据。"
      icon={FileSpreadsheet}
      actions={(
        <>
          {books.length > 0 && (
            <span className="inline-flex items-center rounded-full bg-[var(--surface-strong)] px-2.5 py-1 text-xs font-bold text-[var(--text-muted)]">
              {books.length} 份
            </span>
          )}
          <button
            type="button"
            className="ios-btn-secondary flex items-center gap-2 rounded-md px-3.5 py-2 text-sm disabled:cursor-not-allowed disabled:opacity-45"
            onClick={onRefresh}
            disabled={isRefreshing}
          >
            <RefreshCw className={`h-4 w-4 ${isRefreshing ? 'animate-spin' : ''}`} aria-hidden="true" />
            <span>刷新</span>
          </button>
        </>
      )}
    />
    <div className="flex flex-col gap-3 p-4">
      {books.length === 0 ? (
        <EmptyState
          title="还没有识别记录"
          description="在上方选择报价表文件并点击「开始识别」，识别结果会保存在这里。"
          icon={FileSpreadsheet}
        />
      ) : (
        <div className="flex flex-col gap-3">
          {books.map((book) => (
            <section
              className="rounded-md border border-[var(--border)] bg-[var(--surface-subtle)] p-4"
              key={book.id}
              aria-label="报价表识别结果"
            >
              <div className="grid grid-cols-[40px_minmax(0,1fr)_40px] items-start gap-2.5 sm:grid-cols-[44px_minmax(0,1fr)_44px] sm:gap-3">
                <span className="inline-flex h-10 w-10 items-center justify-center rounded bg-[var(--success-soft)] text-[var(--success)] sm:h-11 sm:w-11">
                  <FileSpreadsheet className="h-5 w-5" aria-hidden="true" />
                </span>
                <div className="min-w-0 pt-px">
                  <div className="flex min-w-0 flex-wrap items-center gap-x-2.5 gap-y-1">
                    <h2 className="min-w-0 truncate text-lg font-bold leading-snug text-[var(--text)]" title={book.filename}>
                      {formatBookName(book.filename)}
                    </h2>
                    <span className="inline-flex min-h-[28px] shrink-0 items-center rounded-sm bg-[var(--success-soft)] px-[7px] py-[3px] text-[13px] font-bold text-[var(--success-ink)]">
                      {bookKindLabel(book.book_kind)}
                    </span>
                  </div>
                  <p className="mt-1 text-sm leading-snug text-[var(--text-soft)] [overflow-wrap:anywhere]">
                    {bookWeightRule(book.book_kind)} · {book.service_count} 个服务 · {book.route_count} 条线路 ·{' '}
                    <time dateTime={book.updated_at ?? undefined}>{formatRecognizedAt(book.updated_at)}</time>
                  </p>
                </div>
                <button
                  type="button"
                  className="inline-flex h-10 w-10 items-center justify-center rounded border border-[color:color-mix(in_srgb,var(--danger)_40%,var(--border))] bg-[var(--surface)] text-[var(--danger)] transition-colors duration-150 hover:border-[var(--danger)] hover:bg-[var(--danger-soft)] disabled:cursor-not-allowed disabled:opacity-50 sm:h-11 sm:w-11 motion-reduce:transition-none"
                  onClick={() => onDelete(book.id)}
                  disabled={isDeletingId === book.id}
                  title="删除这条识别结果"
                  aria-label={`删除 ${book.filename} 的识别结果`}
                >
                  <Trash2 className="h-5 w-5" aria-hidden="true" />
                </button>
              </div>

              <div className="mt-3.5 flex flex-wrap gap-2" aria-label={`${book.service_count} 个服务`}>
                {(book.payload.services ?? []).map((service) => (
                  <span
                    className="rounded-sm bg-[var(--surface-strong)] px-2.5 py-1.5 text-[13px] leading-snug text-[var(--text-muted)] [overflow-wrap:anywhere] sm:text-sm"
                    key={`${service.sheet_name}-${service.name}`}
                  >
                    {service.name} · {ruleLabels[service.rule_type] || '规则待确认'} · {service.route_count}
                  </span>
                ))}
              </div>
            </section>
          ))}
        </div>
      )}
    </div>
  </section>
);

export default QuoteBookList;
