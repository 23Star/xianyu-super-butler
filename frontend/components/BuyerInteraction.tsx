import React, { useEffect, useState } from 'react';
import { Star, Flower2, Save, RefreshCw, ShieldAlert } from 'lucide-react';

import { getSystemSettings, updateSystemSettings, getSellerFeatureFlags } from '../services/api';
import { notify } from '../services/feedback';
import { SystemSettings } from '../types';
import { NoticeBanner, PageHeader, PageLoading, SectionHeader } from './ui';

const MAX_TEMPLATE_LENGTH = 200;

const DEFAULT_TEMPLATE = '宝贝收到了，很满意，感谢老板，欢迎下次再来！';

/** 后端把开关存成 'true' / 'false' 字符串，直接当布尔用会把 'false' 判成真。 */
const toBool = (value: unknown, fallback = false): boolean => {
  if (typeof value === 'boolean') return value;
  if (typeof value === 'string') {
    const normalized = value.trim().toLowerCase();
    if (!normalized) return fallback;
    return !['false', '0', 'no'].includes(normalized);
  }
  if (value === undefined || value === null) return fallback;
  return Boolean(value);
};

interface ToggleRowProps {
  title: string;
  description: string;
  checked: boolean;
  onChange: () => void;
}

const ToggleRow: React.FC<ToggleRowProps> = ({ title, description, checked, onChange }) => (
  <div className="flex items-center justify-between gap-4 border-b border-gray-100 px-4 py-3 last:border-b-0">
    <div className="min-w-0">
      <p className="text-sm font-bold text-gray-900">{title}</p>
      <p className="mt-1 text-xs leading-5 text-gray-500">{description}</p>
    </div>
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      onClick={onChange}
      className={`relative h-6 w-11 shrink-0 rounded-full transition-colors ${
        checked ? 'bg-[#ffe100]' : 'bg-gray-300'
      }`}
    >
      <span
        className={`absolute left-1 top-1 h-4 w-4 rounded-full bg-white transition-transform ${
          checked ? 'translate-x-5' : ''
        }`}
      />
    </button>
  </div>
);

/**
 * 买家互动。
 *
 * 评价和求花会对买家产生真实且不可撤销的动作，之前藏在系统设置的一个分区里，
 * 用起来不好找。单独成页，顺便把默认评价文案也放进来——原先每单都要重新手打。
 */
const BuyerInteraction: React.FC = () => {
  const [settings, setSettings] = useState<SystemSettings | null>(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);

  const load = () => {
    setLoading(true);
    Promise.all([
      getSystemSettings(),
      // 模板有内置默认值，只存在于接口返回里，系统设置接口可能还没有这一项
      getSellerFeatureFlags().catch(() => null),
    ])
      .then(([base, flags]) => {
        setSettings({
          ...base,
          auto_rate_template:
            (base.auto_rate_template ?? '').trim() || flags?.auto_rate_template || DEFAULT_TEMPLATE,
        });
      })
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, []);

  const handleSave = async () => {
    if (!settings) return;
    const template = (settings.auto_rate_template || '').trim();
    if (!template) {
      notify('默认评价内容不能为空');
      return;
    }
    if (template.length > MAX_TEMPLATE_LENGTH) {
      notify(`默认评价内容不能超过 ${MAX_TEMPLATE_LENGTH} 字`);
      return;
    }

    setSaving(true);
    try {
      await updateSystemSettings({
        auto_rate_enabled: settings.auto_rate_enabled,
        auto_flower_enabled: settings.auto_flower_enabled,
        auto_rate_template: template,
      });
      notify('买家互动配置已保存');
    } catch (error) {
      notify(`保存失败：${(error as Error).message}`);
    } finally {
      setSaving(false);
    }
  };

  if (!settings) return <PageLoading label="正在加载买家互动配置" />;

  const rateEnabled = toBool(settings.auto_rate_enabled, false);
  const flowerEnabled = toBool(settings.auto_flower_enabled, false);
  const template = settings.auto_rate_template ?? '';

  return (
    <div className="page-stack animate-fade-in">
      <PageHeader
        title="买家互动"
        description="评价买家与索要小红花。这两项会对买家产生实际动作，开启前请确认。"
        icon={Star}
        actions={(
          <>
            <button
              type="button"
              onClick={load}
              disabled={loading}
              className="ios-btn-secondary flex items-center justify-center gap-2 rounded-md px-4 py-2 text-sm"
            >
              <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
              刷新
            </button>
            <button
              type="button"
              onClick={() => void handleSave()}
              disabled={saving}
              className="ios-btn-primary flex items-center justify-center gap-2 rounded-md px-4 py-2 text-sm"
            >
              <Save className="h-4 w-4" />
              {saving ? '保存中' : '保存设置'}
            </button>
          </>
        )}
      />

      <NoticeBanner
        type="warning"
        message="评价提交后无法撤销，求花会向买家发送一条消息。建议先用测试订单验证效果。"
      />

      <div className="grid gap-4 xl:grid-cols-2">
        <section className="section-panel">
          <SectionHeader
            title="功能开关"
            description="关闭后，订单页不再显示对应入口，后端也会拒绝相关请求。"
            icon={ShieldAlert}
          />
          <ToggleRow
            title="允许提交买家评价"
            description="开启后订单页可给买家评价。评价提交后无法撤销。"
            checked={rateEnabled}
            onChange={() => setSettings({ ...settings, auto_rate_enabled: !rateEnabled })}
          />
          <ToggleRow
            title="允许索要小红花"
            description="开启后订单页可发起求花，会向买家发送一条消息。"
            checked={flowerEnabled}
            onChange={() => setSettings({ ...settings, auto_flower_enabled: !flowerEnabled })}
          />
        </section>

        <section className="section-panel">
          <SectionHeader
            title="默认评价内容"
            description="订单页打开评价框时自动填入，仍可逐单修改后再提交。"
            icon={Flower2}
          />
          <div className="px-4 py-3">
            <label className="field-label">评价文案</label>
            <textarea
              value={template}
              onChange={e => setSettings({ ...settings, auto_rate_template: e.target.value })}
              maxLength={MAX_TEMPLATE_LENGTH}
              placeholder={DEFAULT_TEMPLATE}
              className="ios-input mt-1 min-h-28 w-full resize-y rounded-md px-3 py-2.5 text-sm"
              disabled={!rateEnabled}
            />
            <div className="mt-1 flex items-center justify-between">
              <span className="text-xs text-gray-500">
                {rateEnabled ? '闲鱼对评价内容有长度和内容限制，过长可能被拒绝。' : '开启「允许提交买家评价」后可编辑。'}
              </span>
              <span className="text-xs text-gray-400">{template.length}/{MAX_TEMPLATE_LENGTH}</span>
            </div>
          </div>
        </section>
      </div>
    </div>
  );
};

export default BuyerInteraction;
