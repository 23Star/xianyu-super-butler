import React, { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import {
  AlertTriangle,
  CheckCircle2,
  Inbox,
  Loader2,
  LucideIcon,
  X,
} from 'lucide-react';

interface PageHeaderProps {
  title: string;
  description?: string;
  icon?: LucideIcon;
  badge?: React.ReactNode;
  actions?: React.ReactNode;
}

export const PageHeader: React.FC<PageHeaderProps> = ({
  title,
  description,
  icon: Icon,
  badge,
  actions,
}) => (
  <header className="page-header">
    <div className="page-header__identity">
      {Icon && (
        <span className="page-header__icon" aria-hidden="true">
          <Icon className="h-5 w-5" />
        </span>
      )}
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <h1 className="page-title">{title}</h1>
          {badge}
        </div>
        {description && <p className="page-description">{description}</p>}
      </div>
    </div>
    {actions && <div className="page-actions">{actions}</div>}
  </header>
);

interface PageTabsProps<T extends string> {
  value: T;
  onChange: (value: T) => void;
  items: Array<{
    id: T;
    label: string;
    icon?: LucideIcon;
    count?: number;
  }>;
  ariaLabel?: string;
}

export const PageTabs = <T extends string>({
  value,
  onChange,
  items,
  ariaLabel = '页面分区',
}: PageTabsProps<T>) => (
  <div className="page-tabs" role="tablist" aria-label={ariaLabel}>
    {items.map((item) => {
      const Icon = item.icon;
      const active = value === item.id;
      return (
        <button
          key={item.id}
          type="button"
          role="tab"
          aria-selected={active}
          onClick={() => onChange(item.id)}
          className={`page-tab ${active ? 'page-tab--active' : ''}`}
        >
          {Icon && <Icon className="h-4 w-4 shrink-0" />}
          <span>{item.label}</span>
          {item.count !== undefined && <span className="page-tab__count">{item.count}</span>}
        </button>
      );
    })}
  </div>
);

interface SectionHeaderProps {
  title: string;
  description?: string;
  icon?: LucideIcon;
  actions?: React.ReactNode;
}

export const SectionHeader: React.FC<SectionHeaderProps> = ({
  title,
  description,
  icon: Icon,
  actions,
}) => (
  <div className="section-panel__header">
    <div className="flex min-w-0 items-start gap-3">
      {Icon && (
        <span className="section-header__icon" aria-hidden="true">
          <Icon className="h-4 w-4" />
        </span>
      )}
      <div className="min-w-0">
        <h2 className="section-title">{title}</h2>
        {description && <p className="section-description">{description}</p>}
      </div>
    </div>
    {actions && <div className="section-header__actions">{actions}</div>}
  </div>
);

interface NoticeBannerProps {
  type: 'success' | 'error' | 'warning' | 'info';
  message?: string;
  onClose?: () => void;
  children?: React.ReactNode;
}

export const NoticeBanner: React.FC<NoticeBannerProps> = ({
  type,
  message,
  onClose,
  children,
}) => {
  const Icon = type === 'success' ? CheckCircle2 : AlertTriangle;
  return (
    <div className={`notice-banner notice-banner--${type}`} role="status">
      <Icon className="h-4 w-4 shrink-0" />
      {/* 同时接受 message 与 children：只认 message 时，写成子元素的文案会被
          静默丢掉，页面上只剩一个感叹号图标，而 TS 不会报错（FC 隐式允许 children） */}
      <span className="min-w-0 flex-1">{message ?? children}</span>
      {onClose && (
        <button type="button" onClick={onClose} aria-label="关闭提示">
          <X className="h-4 w-4" />
        </button>
      )}
    </div>
  );
};

interface EmptyStateProps {
  title: string;
  description?: string;
  icon?: LucideIcon;
  action?: React.ReactNode;
  compact?: boolean;
}

export const EmptyState: React.FC<EmptyStateProps> = ({
  title,
  description,
  icon: Icon = Inbox,
  action,
  compact = false,
}) => (
  <div className={`empty-state ${compact ? 'empty-state--compact' : ''}`}>
    <span className="empty-state__icon" aria-hidden="true">
      <Icon className="h-6 w-6" />
    </span>
    <h3>{title}</h3>
    {description && <p>{description}</p>}
    {action && <div className="mt-4">{action}</div>}
  </div>
);

export const PageLoading: React.FC<{ label?: string }> = ({ label = '正在加载' }) => (
  <div className="page-loading" role="status">
    <Loader2 className="h-5 w-5 animate-spin" />
    <span>{label}</span>
  </div>
);

interface PopoverProps {
  open: boolean;
  onClose: () => void;
  trigger: React.ReactNode;
  placement?: 'top' | 'bottom';
  align?: 'left' | 'right';
  panelClassName?: string;
  children: React.ReactNode;
  /** 面板挂载到 body 并按触发器定位：父级存在 overflow 裁剪或滚动容器时开启，避免下拉被截断。 */
  portal?: boolean;
}

export const Popover: React.FC<PopoverProps> = ({
  open,
  onClose,
  trigger,
  placement = 'bottom',
  align = 'left',
  panelClassName = 'max-h-72 w-80',
  children,
  portal = false,
}) => {
  const rootRef = useRef<HTMLDivElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const [coords, setCoords] = useState<{ top: number; left: number; minWidth: number } | null>(null);

  useEffect(() => {
    if (!open) return undefined;
    const handlePointerDown = (event: MouseEvent) => {
      const target = event.target as Node;
      if (rootRef.current?.contains(target)) return;
      if (panelRef.current?.contains(target)) return;
      onClose();
    };
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    document.addEventListener('mousedown', handlePointerDown);
    document.addEventListener('keydown', handleKeyDown);
    return () => {
      document.removeEventListener('mousedown', handlePointerDown);
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [open, onClose]);

  // portal 模式下面板挂到 body：按触发器实时定位，空间不足时自动翻转到另一侧，
  // 并在页面滚动、缩放时跟随，保证下拉始终完整可见。
  useLayoutEffect(() => {
    if (!open || !portal) return undefined;
    const update = () => {
      const rect = rootRef.current?.getBoundingClientRect();
      if (!rect) return;
      const margin = 8;
      const panelHeight = panelRef.current?.offsetHeight ?? 0;
      const panelWidth = panelRef.current?.offsetWidth ?? 0;
      const spaceBelow = window.innerHeight - rect.bottom - margin;
      const spaceAbove = rect.top - margin;
      const resolved: 'top' | 'bottom' = placement === 'top'
        ? (spaceAbove >= panelHeight || spaceAbove >= spaceBelow ? 'top' : 'bottom')
        : (spaceBelow >= panelHeight || spaceBelow >= spaceAbove ? 'bottom' : 'top');
      const top = resolved === 'top' ? rect.top - panelHeight - margin : rect.bottom + margin;
      const left = align === 'left'
        ? Math.min(rect.left, Math.max(margin, window.innerWidth - panelWidth - margin))
        : Math.max(margin, Math.min(rect.right - panelWidth, window.innerWidth - panelWidth - margin));
      setCoords({ top, left, minWidth: rect.width });
    };
    update();
    let frame = 0;
    const requestUpdate = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(update);
    };
    window.addEventListener('resize', requestUpdate);
    window.addEventListener('scroll', requestUpdate, true);
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener('resize', requestUpdate);
      window.removeEventListener('scroll', requestUpdate, true);
    };
  }, [open, portal, placement, align, children]);

  const panelNode = (
    <div
      ref={panelRef}
      className={`overflow-y-auto rounded-lg border border-[var(--border)] bg-[var(--surface)] p-2 shadow-lg ${
        portal
          ? 'fixed z-50'
          : `absolute z-20 ${placement === 'top' ? 'bottom-8' : 'top-8'} ${align === 'left' ? 'left-0' : 'right-0'}`
      } ${panelClassName}`}
      style={portal && coords ? { top: coords.top, left: coords.left, minWidth: coords.minWidth } : undefined}
    >
      {children}
    </div>
  );

  return (
    <div ref={rootRef} className="relative">
      {trigger}
      {open && (portal ? createPortal(panelNode, document.body) : panelNode)}
    </div>
  );
};
