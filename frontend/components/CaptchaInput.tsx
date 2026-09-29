import React from 'react';
import { RefreshCw } from 'lucide-react';

interface CaptchaInputProps {
  /** data:image/png;base64 图片，点击图片或按钮刷新 */
  image: string;
  code: string;
  onCodeChange: (value: string) => void;
  onRefresh: () => void;
  label?: string;
}

/** 图形验证码输入行：输入框 + 验证码图片（点击可换一张）。 */
const CaptchaInput: React.FC<CaptchaInputProps> = ({
  image,
  code,
  onCodeChange,
  onRefresh,
  label = '图形验证码',
}) => (
  <label className="block">
    <span className="mb-1.5 block text-xs font-bold text-gray-600">{label}</span>
    <div className="flex gap-2">
      <input
        type="text"
        placeholder="请输入图中字符"
        value={code}
        onChange={e => onCodeChange(e.target.value)}
        maxLength={4}
        autoComplete="off"
        className="ios-input h-11 w-full rounded-md px-4 text-sm uppercase"
      />
      {image ? (
        <img
          src={image}
          alt="图形验证码，点击换一张"
          title="看不清？点击换一张"
          onClick={onRefresh}
          className="h-11 w-28 shrink-0 cursor-pointer rounded-md border border-gray-200 bg-white"
        />
      ) : (
        <button
          type="button"
          onClick={onRefresh}
          className="h-11 w-28 shrink-0 rounded-md border border-gray-200 bg-gray-50 text-xs text-gray-500"
        >
          点击获取
        </button>
      )}
      <button
        type="button"
        onClick={onRefresh}
        aria-label="刷新图形验证码"
        className="ios-btn-secondary h-11 shrink-0 rounded-md px-2"
      >
        <RefreshCw className="h-4 w-4" />
      </button>
    </div>
  </label>
);

export default CaptchaInput;
