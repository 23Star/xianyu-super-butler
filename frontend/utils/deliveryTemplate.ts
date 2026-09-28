/**
 * 卡密发货详情文案：参数词表、图片标记与预览。
 *
 * 文案用 `{参数}` 占位，发送时由后端 app/delivery_template.py 填充真实订单信息；
 * `{分隔符}` 拆分多条消息，`{图片N}` 从图片映射取真实图片消息，
 * 卖家不需要在文案里直接维护图片 URL。
 */

import { MESSAGE_SPLIT_TOKEN } from './messageTemplate';

export const DELIVERY_SPLIT_TOKEN = MESSAGE_SPLIT_TOKEN;

export const DELIVERY_CONTENT_TOKEN = '{发货内容}';

/** 旧版备注使用的英文变量，继续识别但不再作为插入按钮展示。 */
export const LEGACY_DELIVERY_CONTENT_TOKEN = '{DELIVERY_CONTENT}';

export interface DeliveryTemplateToken {
  label: string;
  sample: string;
}

/** 可插入参数：label 即 `{label}` 占位符，sample 仅用于预览。 */
export const DELIVERY_TEMPLATE_TOKENS: DeliveryTemplateToken[] = [
  { label: '发货内容', sample: 'CARD-1234-5678' },
  { label: '订单号', sample: '2409123456789' },
  { label: '商品标题', sample: '示例商品' },
  { label: '商品ID', sample: '123456789' },
  { label: '买家ID', sample: '987654321' },
  { label: '规格名称', sample: '套餐' },
  { label: '规格值', sample: '月卡' },
  { label: '发货数量', sample: '1' },
];

export const buildDeliverySampleValues = (): Record<string, string> =>
  Object.fromEntries(DELIVERY_TEMPLATE_TOKENS.map(({ label, sample }) => [label, sample]));

/** 取下一个图片映射键（纯数字字符串），配合 `{图片N}` 标记使用。 */
export const nextDeliveryImageKey = (images: Record<string, string>): string => {
  const used = Object.keys(images)
    .map((key) => Number(key))
    .filter((value) => Number.isFinite(value));
  return String(Math.max(0, ...used) + 1);
};

export const renderDeliveryTemplate = (
  template: string,
  values: Record<string, string>,
): string => template.replace(/\{([^{}]+)\}/g, (match, name: string) => values[name.trim()] ?? match);

export type DeliveryPreviewSegment =
  | { type: 'text'; content: string }
  | { type: 'image'; url: string; label: string }
  | { type: 'divider' };

const MARKER_RE = /\{图片(\d+)\}|\{分隔符\}/g;

/** 按发送语义拆分预览：参数先用示例值渲染，再拆成文本/图片/分条。 */
export const buildDeliveryPreviewSegments = (
  template: string,
  images: Record<string, string>,
  values: Record<string, string>,
): DeliveryPreviewSegment[] => {
  const rendered = renderDeliveryTemplate(template || '', values);
  const segments: DeliveryPreviewSegment[] = [];
  let buffer = '';
  let position = 0;

  const flush = () => {
    const text = buffer.trim();
    buffer = '';
    if (text) segments.push({ type: 'text', content: text });
  };

  for (const match of rendered.matchAll(MARKER_RE)) {
    const index = match.index ?? 0;
    buffer += rendered.slice(position, index);
    position = index + match[0].length;

    if (match[0] === DELIVERY_SPLIT_TOKEN) {
      flush();
      segments.push({ type: 'divider' });
      continue;
    }

    const key = match[1];
    const url = images[key] || images[`图片${key}`];
    if (url) {
      flush();
      segments.push({ type: 'image', url, label: `图片${key}` });
    } else {
      buffer += match[0];
    }
  }

  buffer += rendered.slice(position);
  flush();
  return segments;
};
