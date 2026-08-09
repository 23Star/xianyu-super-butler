import React from 'react';
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
  message: string;
  onClose?: () => void;
}

export const NoticeBanner: React.FC<NoticeBannerProps> = ({
  type,
  message,
  onClose,
}) => {
  const Icon = type === 'success' ? CheckCircle2 : AlertTriangle;
  return (
    <div className={`notice-banner notice-banner--${type}`} role="status">
      <Icon className="h-4 w-4 shrink-0" />
      <span className="min-w-0 flex-1">{message}</span>
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
