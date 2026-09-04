import type { LogisticsQuoteBook } from './api';

/** 物流报价模块的展示与领域辅助：文件约束、规则文案、识别结果格式化。 */

export const supportedQuoteFilePattern = /\.(xlsx|xlsm|xls|csv)$/i;

export const ruleLabels: Record<string, string> = {
  first_additional: '首重续重',
  fixed_tiers: '固定重量档',
  fixed_tiers_overflow: '重量档+续重',
  banded_additional: '分段续重',
  minimum_then_per_kg: '最低价+超重按总公斤',
  mixed: '混合规则',
  unknown: '规则待确认',
};

export const bookKindLabel = (bookKind: LogisticsQuoteBook['book_kind']) => {
  if (bookKind === 'logistics') return '大件物流';
  if (bookKind === 'express') return '普通快递';
  return '报价表';
};

export const bookWeightRule = (bookKind: LogisticsQuoteBook['book_kind']) => {
  if (bookKind === 'logistics') return '30kg及以上使用';
  if (bookKind === 'express') return '30kg以下使用';
  return '重量规则待确认';
};

export const formatBookName = (filename: string) =>
  filename.replace(/\.(xlsx|xlsm|xls|csv)$/i, '') || filename;

export const formatRecognizedAt = (value: string | null) => {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString('zh-CN', {
    year: 'numeric',
    month: 'numeric',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  });
};

export const extractParseError = (error: unknown): string => {
  const detail = (error as { response?: { data?: { detail?: unknown } } } | undefined)
    ?.response?.data?.detail;
  if (typeof detail === 'string' && detail.trim()) return detail.trim();
  if (Array.isArray(detail)) {
    const message = detail
      .map((item) => typeof item === 'string' ? item : (item as { msg?: unknown })?.msg)
      .find((item): item is string => typeof item === 'string' && item.trim().length > 0);
    if (message) return message;
  }
  return '报价表识别失败，请检查文件后重试';
};
