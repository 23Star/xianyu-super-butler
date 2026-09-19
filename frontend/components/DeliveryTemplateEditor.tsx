import React, { useMemo, useRef, useState } from 'react';
import { ImagePlus, Scissors, X } from 'lucide-react';
import { uploadImage } from '../services/api';
import { notify } from '../services/feedback';
import {
  buildDeliveryPreviewSegments,
  buildDeliverySampleValues,
  DELIVERY_CONTENT_TOKEN,
  DELIVERY_SPLIT_TOKEN,
  DELIVERY_TEMPLATE_TOKENS,
  LEGACY_DELIVERY_CONTENT_TOKEN,
  nextDeliveryImageKey,
} from '../utils/deliveryTemplate';

interface DeliveryTemplateEditorProps {
  /** 文本框唯一 id，用于把标签关联到输入框。 */
  id: string;
  value: string;
  images: Record<string, string>;
  onChange: (value: string) => void;
  onImagesChange: (images: Record<string, string>) => void;
}

/**
 * 卡密发货详情文案编辑器：参数插入 + 图片上传/粘贴 + 分开发送 + 预览。
 * 样式复用报价模板编辑器的 token 视觉，保证同一套后台观感。
 */
const DeliveryTemplateEditor: React.FC<DeliveryTemplateEditorProps> = ({
  id,
  value,
  images,
  onChange,
  onImagesChange,
}) => {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);

  const sampleValues = useMemo(() => buildDeliverySampleValues(), []);
  const previewSegments = useMemo(
    () => buildDeliveryPreviewSegments(value, images, sampleValues),
    [value, images, sampleValues],
  );
  const imageKeys = useMemo(
    () => Object.keys(images).sort((left, right) => Number(left) - Number(right)),
    [images],
  );
  const hasContentToken = value.includes(DELIVERY_CONTENT_TOKEN)
    || value.includes(LEGACY_DELIVERY_CONTENT_TOKEN);

  const insertText = (text: string) => {
    const element = textareaRef.current;
    if (!element) {
      onChange(`${value}${text}`);
      return;
    }
    const start = element.selectionStart ?? value.length;
    const end = element.selectionEnd ?? start;
    const caret = start + text.length;
    onChange(`${value.slice(0, start)}${text}${value.slice(end)}`);
    requestAnimationFrame(() => {
      element.focus();
      element.setSelectionRange(caret, caret);
    });
  };

  const uploadAndInsert = async (file: File) => {
    setUploading(true);
    try {
      const result = await uploadImage(file);
      const key = nextDeliveryImageKey(images);
      onImagesChange({ ...images, [key]: result.image_url });
      insertText(`{图片${key}}`);
    } catch (error) {
      console.error('上传发货文案图片失败:', error);
      notify('图片上传失败，请重试');
    } finally {
      setUploading(false);
      if (fileInputRef.current) {
        fileInputRef.current.value = '';
      }
    }
  };

  const handleFileChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (file) {
      void uploadAndInsert(file);
    }
  };

  const handlePaste = (event: React.ClipboardEvent<HTMLTextAreaElement>) => {
    const items = event.clipboardData?.items;
    if (!items) return;
    for (let index = 0; index < items.length; index += 1) {
      const item = items[index];
      if (!item.type.startsWith('image/')) continue;
      const file = item.getAsFile();
      if (file) {
        event.preventDefault();
        void uploadAndInsert(file);
        return;
      }
    }
  };

  const removeImage = (key: string) => {
    const nextImages = { ...images };
    delete nextImages[key];
    onImagesChange(nextImages);
    onChange(value.split(`{图片${key}}`).join(''));
  };

  return (
    <div className="delivery-template space-y-3">
      <div className="logistics-editor-head">
        <div className="logistics-editor-head__label">
          <label htmlFor={id}>
            <span className="field-label">发货详情文案</span>
          </label>
          <p className="mt-0.5 mb-1.5 text-xs leading-relaxed text-[var(--text-muted)]">
            点击参数插入，支持 Ctrl+V 粘贴图片；用「分开发送」拆成多条消息依次发送。
          </p>
        </div>
        <div className="logistics-split-tool">
          <input
            ref={fileInputRef}
            type="file"
            accept="image/*"
            className="hidden"
            onChange={handleFileChange}
          />
          <button
            type="button"
            className="logistics-split-tool__btn inline-flex items-center gap-1 disabled:cursor-not-allowed disabled:opacity-60"
            disabled={uploading}
            onClick={() => fileInputRef.current?.click()}
          >
            <ImagePlus className="h-3.5 w-3.5" aria-hidden="true" />
            {uploading ? '上传中...' : '插入图片'}
          </button>
          <button
            type="button"
            className="logistics-split-tool__btn inline-flex items-center gap-1"
            onClick={() => insertText(DELIVERY_SPLIT_TOKEN)}
          >
            <Scissors className="h-3.5 w-3.5" aria-hidden="true" />
            分开发送
          </button>
        </div>
      </div>

      <textarea
        ref={textareaRef}
        id={id}
        value={value}
        rows={6}
        onChange={(event) => onChange(event.target.value)}
        onPaste={handlePaste}
        className="ios-input w-full resize-y rounded-md px-3 py-2.5 text-sm leading-relaxed"
        placeholder={'亲，您的卡密已发货：\n{发货内容}\n如有问题请联系客服。'}
      />

      <div className="logistics-token-tray">
        <div className="logistics-token-tray__head">
          <div className="logistics-token-tray__title">
            <span>点击插入参数</span>
            <small>发送时自动替换为订单真实信息</small>
          </div>
        </div>
        <div className="logistics-token-tray__chips" role="list" aria-label="发货文案可插入参数">
          {DELIVERY_TEMPLATE_TOKENS.map((token) => (
            <div className="logistics-token-item" key={token.label} role="listitem">
              <button
                type="button"
                className="logistics-token-chip"
                onClick={() => insertText(`{${token.label}}`)}
              >
                {`{${token.label}}`}
              </button>
            </div>
          ))}
        </div>
      </div>

      {imageKeys.length > 0 && (
        <div className="delivery-template-images">
          {imageKeys.map((key) => (
            <figure className="delivery-template-image" key={key}>
              <img src={images[key]} alt={`图片${key}`} />
              <figcaption>
                <span>{`{图片${key}}`}</span>
                <button
                  type="button"
                  onClick={() => removeImage(key)}
                  aria-label={`删除图片${key}`}
                  title="删除图片（同时移除文案中的标记）"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              </figcaption>
            </figure>
          ))}
        </div>
      )}

      {!hasContentToken && (
        <p className="text-xs text-amber-600">
          文案里还没有插入 {DELIVERY_CONTENT_TOKEN}，保存时会自动把卡密内容追加到末尾。
        </p>
      )}

      <div className="logistics-form-section__heading">
        <span>发货预览</span>
        <small>参数用示例值演示，实际以订单为准</small>
      </div>
      <div className="delivery-template-preview">
        {previewSegments.length === 0 && (
          <span className="text-xs text-gray-400">文案为空</span>
        )}
        {previewSegments.map((segment, index) => {
          if (segment.type === 'divider') {
            return (
              <div className="delivery-template-divider" key={`divider-${index}`}>
                分开发送
              </div>
            );
          }
          if (segment.type === 'image') {
            return (
              <img
                key={`image-${index}`}
                src={segment.url}
                alt={segment.label}
                className="delivery-template-preview__image"
              />
            );
          }
          return (
            <div key={`text-${index}`} className="logistics-chat-bubble whitespace-pre-wrap">
              {segment.content}
            </div>
          );
        })}
      </div>
    </div>
  );
};

export default DeliveryTemplateEditor;
