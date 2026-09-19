import React from 'react';
import DeliveryTemplateEditor from './DeliveryTemplateEditor';

interface DeliveryContentConfigProps {
  /** 表单唯一前缀，用于关联文案输入框。 */
  idPrefix: string;
  /** 关闭时使用备注描述，开启时使用发货详情文案。 */
  enabled: boolean;
  onEnabledChange: (enabled: boolean) => void;
  description: string;
  onDescriptionChange: (value: string) => void;
  template: string;
  onTemplateChange: (value: string) => void;
  images: Record<string, string>;
  onImagesChange: (images: Record<string, string>) => void;
}

/**
 * 卡密发货内容配置：用开关在「原备注描述」和「发货详情文案」之间切换。
 */
const DeliveryContentConfig: React.FC<DeliveryContentConfigProps> = ({
  idPrefix,
  enabled,
  onEnabledChange,
  description,
  onDescriptionChange,
  template,
  onTemplateChange,
  images,
  onImagesChange,
}) => (
  <div className="rounded-md border border-gray-200 bg-gray-50 p-4">
    <div className="flex items-center justify-between gap-4">
      <div>
        <h3 className="font-bold text-gray-900">发货内容</h3>
        <p className="mt-1 text-xs text-gray-500">
          {enabled
            ? '按发货详情文案发送，支持参数、图片和分开发送。'
            : '沿用原备注描述：备注会和卡密内容一起发给买家。'}
        </p>
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={enabled}
        aria-label={enabled ? '切换为原备注描述' : '切换为发货详情文案'}
        title={enabled ? '切换为原备注描述' : '切换为发货详情文案'}
        onClick={() => onEnabledChange(!enabled)}
        className={`relative h-6 w-11 shrink-0 rounded-full transition-colors ${
          enabled ? 'bg-[#ffe100]' : 'bg-gray-300'
        }`}
      >
        <span
          className={`absolute left-1 top-1 block h-4 w-4 rounded-full bg-white shadow-sm transition-transform ${
            enabled ? 'translate-x-5' : ''
          }`}
        />
      </button>
    </div>

    <div className="mt-4">
      {enabled ? (
        <DeliveryTemplateEditor
          id={`${idPrefix}-delivery-template`}
          value={template}
          images={images}
          onChange={onTemplateChange}
          onImagesChange={onImagesChange}
        />
      ) : (
        <div>
          <label className="mb-2 block text-sm font-bold text-gray-700" htmlFor={`${idPrefix}-description`}>
            备注信息
          </label>
          <textarea
            id={`${idPrefix}-description`}
            value={description}
            onChange={(event) => onDescriptionChange(event.target.value)}
            className="ios-input h-32 w-full resize-y rounded-md px-3 py-2.5"
            placeholder="可选的备注信息，发货时会与卡密内容一起发送"
          />
        </div>
      )}
    </div>
  </div>
);

export default DeliveryContentConfig;
