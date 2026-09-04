import { Bot, FileSpreadsheet, SlidersHorizontal, type LucideIcon } from 'lucide-react';

export type StepId = 'recognition' | 'settings' | 'apply';

export interface WorkflowStep {
  id: StepId;
  label: string;
  description: string;
  icon: LucideIcon;
  implemented: boolean;
}

// 后续新增步骤时在这里加一项并实现对应的工作区渲染即可，布局骨架不用动。
export const workflowSteps: WorkflowStep[] = [
  {
    id: 'recognition',
    label: '识别报价表',
    description: '上传 Excel / CSV 报价表，自动提取承运商、线路与计价规则',
    icon: FileSpreadsheet,
    implemented: true,
  },
  {
    id: 'settings',
    label: '报价设置',
    description: '配置智能计算参数、计价公式与买家回复等基础设置',
    icon: SlidersHorizontal,
    implemented: true,
  },
  {
    id: 'apply',
    label: '自动报价',
    description: '把识别结果接入 AI 回复与自动发货，由 AI 按报价自动回复买家',
    icon: Bot,
    implemented: false,
  },
];

interface StepCardProps {
  step: WorkflowStep;
  index: number;
  active: boolean;
  onSelect: (id: StepId) => void;
}

export const StepCard = ({ step, index, active, onSelect }: StepCardProps) => {
  const Icon = step.icon;
  return (
      <button
        type="button"
        disabled={!step.implemented}
        onClick={() => onSelect(step.id)}
        className={[
          'flex h-full w-full items-start gap-3 rounded-lg border p-3.5 text-left shadow-soft',
          'transition-all duration-150 motion-reduce:transition-none',
          active
            ? 'border-[color:color-mix(in_srgb,var(--brand)_55%,var(--border))] bg-[linear-gradient(135deg,var(--brand-soft),var(--surface)_55%)]'
            : 'border-[var(--border)] bg-[var(--surface)]',
          step.implemented
            ? 'cursor-pointer enabled:hover:-translate-y-px enabled:hover:border-[var(--border-strong)] enabled:hover:bg-[var(--surface-hover)]'
            : 'cursor-default border-dashed bg-[var(--surface-subtle)] shadow-none',
        ].join(' ')}
      >
        <span
          className={`inline-flex h-[34px] w-[34px] shrink-0 items-center justify-center rounded-md text-[13px] font-extrabold ${
            active
              ? 'bg-[linear-gradient(140deg,var(--brand-300),var(--brand))] text-brand-ink shadow-brand'
              : 'bg-[var(--surface-strong)] text-[var(--text-muted)]'
          }`}
          aria-hidden="true"
        >
          {String(index + 1).padStart(2, '0')}
        </span>
        <span className="flex min-w-0 flex-col gap-[3px]">
          <span className="flex items-center gap-[7px] text-sm font-bold text-[var(--text)]">
            <Icon className={`h-4 w-4 shrink-0 ${active ? 'text-[var(--brand-text)]' : 'text-[var(--text-soft)]'}`} aria-hidden="true" />
            {step.label}
            {!step.implemented && (
              <span className="shrink-0 rounded-full bg-[var(--surface-strong)] px-2 py-0.5 text-[11px] font-bold text-[var(--text-muted)]">
                即将上线
              </span>
            )}
          </span>
          <span className="text-xs leading-relaxed text-[var(--text-muted)]">{step.description}</span>
        </span>
      </button>
  );
};
