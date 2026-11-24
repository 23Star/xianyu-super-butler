import React, { useState } from 'react';
import { createPortal } from 'react-dom';
import { Eye, EyeOff, Key, Loader2, X } from 'lucide-react';
import { loginWithCookie } from '../services/api';
import { notify } from '../services/feedback';

interface Props {
  accountId?: string;
  onClose: () => void;
  onSaved: () => void;
}

const CookieLoginDialog: React.FC<Props> = ({ accountId, onClose, onSaved }) => {
  const [cookie, setCookie] = useState('');
  const [visible, setVisible] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (submitting || !cookie.trim()) return;
    setSubmitting(true);
    setError('');
    try {
      const result = await loginWithCookie(cookie, accountId);
      setCookie('');
      notify(result.message, result.connection_started || !result.enabled ? 'success' : 'info');
      onSaved();
      onClose();
    } catch (failure: any) {
      // Axios 错误对象携带请求体，不能直接记录或展示。
      const detail = failure?.response?.data?.detail;
      setError(typeof detail === 'string' ? detail : '登录请求失败，请稍后重试');
    } finally {
      setSubmitting(false);
    }
  };

  return createPortal(
    <div className="modal-overlay">
      <form onSubmit={submit} className="modal-container" style={{ maxWidth: '32rem' }}
        role="dialog" aria-modal="true" aria-labelledby="cookie-login-title">
        <div className="modal-header flex items-start justify-between gap-4">
          <div>
            <h3 id="cookie-login-title" className="flex items-center gap-2 text-lg font-bold text-gray-900">
              <Key className="h-5 w-5" />{accountId ? '使用 Cookie 重新登录' : 'Cookie 登录'}
            </h3>
            <p className="mt-1 text-xs text-gray-500">自动识别闲鱼账号，同一账号重新登录会保留原有设置。</p>
          </div>
          <button type="button" onClick={onClose} disabled={submitting} aria-label="关闭 Cookie 登录"
            className="rounded-full p-1 text-gray-400 hover:bg-gray-100 disabled:opacity-50">
            <X className="h-5 w-5" />
          </button>
        </div>
        <div className="space-y-4 p-5">
          <ol className="list-inside list-decimal space-y-1 text-xs leading-6 text-gray-500">
            <li>在自己的浏览器登录闲鱼官网，确认可以正常进入聊天页。</li>
            <li>按 F12 打开「网络」，刷新后选择闲鱼请求，复制请求标头中的完整 Cookie。</li>
            <li>粘贴到下方并登录；若官网要求安全验证，请先在官网完成。</li>
          </ol>
          {accountId && <p className="break-all text-xs text-gray-500">当前账号：{accountId}</p>}
          <label htmlFor="cookie-login-input" className="block text-sm font-bold text-gray-700">闲鱼 Cookie</label>
          <div className="flex items-center gap-2">
            <input id="cookie-login-input" type={visible ? 'text' : 'password'} value={cookie}
              onChange={event => setCookie(event.target.value)} autoComplete="off" spellCheck={false}
              autoCapitalize="none" maxLength={32768} required disabled={submitting} autoFocus
              placeholder="粘贴完整 Cookie，包含 unb、cookie2 等字段"
              className="ios-input min-w-0 flex-1 px-3 py-2 text-sm" />
            <button type="button" onClick={() => setVisible(previous => !previous)}
              aria-label={visible ? '隐藏 Cookie' : '显示 Cookie'} className="rounded-md p-2 text-gray-500">
              {visible ? <EyeOff className="h-5 w-5" /> : <Eye className="h-5 w-5" />}
            </button>
          </div>
          <p className="text-xs leading-5 text-gray-400">Cookie 等同于登录凭据，请勿分享给他人。校验失败不会替换原有登录信息。</p>
          {error && <p role="alert" className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}
        </div>
        <div className="modal-footer flex justify-end gap-3">
          <button type="button" onClick={onClose} disabled={submitting} className="ios-btn-secondary rounded-md px-4 py-2 text-sm">取消</button>
          <button type="submit" disabled={submitting || !cookie.trim()}
            className="ios-btn-primary flex items-center gap-2 rounded-md px-4 py-2 text-sm disabled:opacity-50">
            {submitting && <Loader2 className="h-4 w-4 animate-spin" />}
            {submitting ? '正在校验登录状态…' : '登录并保存'}
          </button>
        </div>
      </form>
    </div>, document.body,
  );
};

export default CookieLoginDialog;
