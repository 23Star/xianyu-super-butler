import React, { useEffect, useState } from 'react';
import {
  Database,
  Eye,
  EyeOff,
  Mail,
  RefreshCw,
  Save,
  Settings as SettingsIcon,
  ShieldCheck,
  Sparkles,
  UserRound,
} from 'lucide-react';

import { getSystemSettings, updateSystemSettings } from '../services/api';
import { notify } from '../services/feedback';
import { SystemSettings } from '../types';
import {
  NoticeBanner,
  PageHeader,
  PageLoading,
  PageTabs,
  SectionHeader,
} from './ui';

type SettingsSection = 'general' | 'ai' | 'email';

interface SettingToggleProps {
  title: string;
  description: string;
  checked: boolean;
  onChange: () => void;
}

const SettingToggle: React.FC<SettingToggleProps> = ({
  title,
  description,
  checked,
  onChange,
}) => (
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

const Settings: React.FC = () => {
  const [settings, setSettings] = useState<SystemSettings | null>(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [activeSection, setActiveSection] = useState<SettingsSection>('general');
  const [showApiKey, setShowApiKey] = useState(false);
  const [showSmtpPassword, setShowSmtpPassword] = useState(false);

  useEffect(() => {
    loadSettings();
  }, []);

  const loadSettings = () => {
    setLoading(true);
    getSystemSettings().then(setSettings).finally(() => setLoading(false));
  };

  const handleSave = async () => {
    if (!settings) return;
    setSaving(true);
    try {
      await updateSystemSettings(settings);
      notify('系统配置已保存');
    } catch (error) {
      notify(`保存失败：${(error as Error).message}`);
    } finally {
      setSaving(false);
    }
  };

  if (!settings) return <PageLoading label="正在加载系统设置" />;

  return (
    <div className="page-stack animate-fade-in">
      <PageHeader
        title="系统设置"
        description="配置管理端访问、商品同步、默认 AI 参数和邮件服务。"
        icon={SettingsIcon}
        actions={(
          <>
            <button
              type="button"
              onClick={loadSettings}
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

      <PageTabs
        value={activeSection}
        onChange={setActiveSection}
        ariaLabel="系统设置分区"
        items={[
          { id: 'general', label: '账号与同步', icon: UserRound },
          { id: 'ai', label: '默认 AI 配置', icon: Sparkles },
          { id: 'email', label: '邮件服务', icon: Mail },
        ]}
      />

      {activeSection === 'general' && (
        <div className="grid gap-4 xl:grid-cols-2">
          <section className="section-panel">
            <SectionHeader
              title="访问与安全"
              description="控制后台注册入口、登录提示和验证码策略。"
              icon={ShieldCheck}
            />
            <SettingToggle
              title="允许用户注册"
              description="开启后允许新用户从登录页创建管理账号。"
              checked={settings.registration_enabled}
              onChange={() => setSettings({
                ...settings,
                registration_enabled: !settings.registration_enabled,
              })}
            />
            <SettingToggle
              title="显示默认登录信息"
              description="仅建议在本地调试环境显示默认账号提示。"
              checked={settings.show_default_login_info}
              onChange={() => setSettings({
                ...settings,
                show_default_login_info: !settings.show_default_login_info,
              })}
            />
            <SettingToggle
              title="登录滑动验证码"
              description="账号密码登录前要求完成滑动验证。"
              checked={settings.login_captcha_enabled}
              onChange={() => setSettings({
                ...settings,
                login_captcha_enabled: !settings.login_captcha_enabled,
              })}
            />
          </section>

          <section className="section-panel">
            <SectionHeader
              title="商品同步"
              description="设置后台定时获取闲鱼商品的频率和单次范围。"
              icon={Database}
            />
            <SettingToggle
              title="启用商品自动同步"
              description="定时将账号商品更新到本地商品库。"
              checked={settings.item_sync_enabled}
              onChange={() => setSettings({
                ...settings,
                item_sync_enabled: !settings.item_sync_enabled,
              })}
            />
            <div className="grid gap-4 p-4 sm:grid-cols-2">
              <label>
                <span className="field-label">同步间隔（分钟）</span>
                <input
                  type="number"
                  value={Math.round((settings.item_sync_interval || 600) / 60)}
                  onChange={(event) => {
                    const minutes = parseInt(event.target.value, 10) || 10;
                    setSettings({ ...settings, item_sync_interval: minutes * 60 });
                  }}
                  className="ios-input w-full rounded-md px-3 py-2.5"
                  min="1"
                  max="1440"
                />
                <span className="mt-1 block text-xs text-gray-500">建议 10 至 60 分钟。</span>
              </label>
              <label>
                <span className="field-label">每次最多同步页数</span>
                <input
                  type="number"
                  value={settings.item_sync_max_pages || 5}
                  onChange={(event) => setSettings({
                    ...settings,
                    item_sync_max_pages: parseInt(event.target.value, 10) || 5,
                  })}
                  className="ios-input w-full rounded-md px-3 py-2.5"
                  min="1"
                  max="50"
                />
                <span className="mt-1 block text-xs text-gray-500">闲鱼接口通常每页返回 20 件商品。</span>
              </label>
            </div>
          </section>
        </div>
      )}

      {activeSection === 'ai' && (
        <section className="section-panel">
          <SectionHeader
            title="默认 AI 配置"
            description="作为账号未单独配置时使用的全局模型与回复内容。"
            icon={Sparkles}
          />
          <div className="grid gap-4 p-4 lg:grid-cols-2">
            <label>
              <span className="field-label">API 地址</span>
              <input
                type="text"
                value={settings.ai_api_url || 'https://dashscope.aliyuncs.com/compatible-mode/v1'}
                onChange={(event) => setSettings({ ...settings, ai_api_url: event.target.value })}
                className="ios-input w-full rounded-md px-3 py-2.5 text-sm"
                placeholder="https://api.openai.com/v1"
              />
              <span className="mt-1 block text-xs text-gray-500">
                填写兼容 OpenAI 协议的服务根地址，无需补全 `/chat/completions`。
              </span>
            </label>

            <label>
              <span className="field-label">API Key</span>
              <div className="relative">
                <input
                  type={showApiKey ? 'text' : 'password'}
                  value={settings.ai_api_key || ''}
                  onChange={(event) => setSettings({ ...settings, ai_api_key: event.target.value })}
                  className="ios-input w-full rounded-md px-3 py-2.5 pr-11 font-mono text-sm"
                  placeholder="sk-..."
                />
                <button
                  type="button"
                  onClick={() => setShowApiKey(!showApiKey)}
                  className="absolute right-2 top-1/2 -translate-y-1/2 rounded-md p-2 text-gray-400 hover:bg-gray-100 hover:text-gray-600"
                  aria-label={showApiKey ? '隐藏 API Key' : '显示 API Key'}
                >
                  {showApiKey ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </button>
              </div>
            </label>

            <label>
              <span className="field-label">默认模型</span>
              <select
                value={settings.ai_model || 'qwen-plus'}
                onChange={(event) => setSettings({ ...settings, ai_model: event.target.value })}
                className="ios-input w-full rounded-md px-3 py-2.5"
              >
                <option value="qwen-plus">通义千问 Plus</option>
                <option value="qwen-turbo">通义千问 Turbo</option>
                <option value="gpt-3.5-turbo">GPT-3.5 Turbo</option>
                <option value="gpt-4">GPT-4</option>
              </select>
            </label>

            <label className="lg:col-span-2">
              <span className="field-label">默认自动回复内容</span>
              <textarea
                className="ios-input min-h-28 w-full resize-y rounded-md px-3 py-2.5 text-sm"
                value={settings.default_reply || ''}
                onChange={(event) => setSettings({ ...settings, default_reply: event.target.value })}
                placeholder="设置默认的自动回复内容..."
              />
            </label>

            <div className="lg:col-span-2">
              <NoticeBanner type="info">
                常用兼容服务包括阿里云 DashScope 和 OpenAI。API Key 仅保存在当前系统配置中。
              </NoticeBanner>
            </div>
          </div>
        </section>
      )}

      {activeSection === 'email' && (
        <section className="section-panel">
          <SectionHeader
            title="SMTP 邮件服务"
            description="用于发送注册验证码和系统邮件通知。"
            icon={Mail}
          />
          <div className="grid gap-4 p-4 lg:grid-cols-2">
            <label>
              <span className="field-label">SMTP 服务器</span>
              <input
                type="text"
                value={settings.smtp_server || ''}
                onChange={(event) => setSettings({ ...settings, smtp_server: event.target.value })}
                placeholder="smtp.qq.com"
                className="ios-input w-full rounded-md px-3 py-2.5 text-sm"
              />
            </label>

            <label>
              <span className="field-label">SMTP 端口</span>
              <input
                type="number"
                value={settings.smtp_port || 587}
                onChange={(event) => setSettings({
                  ...settings,
                  smtp_port: parseInt(event.target.value, 10),
                })}
                placeholder="587"
                className="ios-input w-full rounded-md px-3 py-2.5 text-sm"
              />
            </label>

            <label>
              <span className="field-label">发件邮箱</span>
              <input
                type="email"
                value={settings.smtp_user || ''}
                onChange={(event) => setSettings({ ...settings, smtp_user: event.target.value })}
                placeholder="your-email@qq.com"
                className="ios-input w-full rounded-md px-3 py-2.5 text-sm"
              />
            </label>

            <label>
              <span className="field-label">邮箱密码或授权码</span>
              <div className="relative">
                <input
                  type={showSmtpPassword ? 'text' : 'password'}
                  value={settings.smtp_password || ''}
                  onChange={(event) => setSettings({ ...settings, smtp_password: event.target.value })}
                  placeholder="输入密码或授权码"
                  className="ios-input w-full rounded-md px-3 py-2.5 pr-11 text-sm"
                />
                <button
                  type="button"
                  onClick={() => setShowSmtpPassword(!showSmtpPassword)}
                  className="absolute right-2 top-1/2 -translate-y-1/2 rounded-md p-2 text-gray-400 hover:bg-gray-100 hover:text-gray-600"
                  aria-label={showSmtpPassword ? '隐藏邮箱授权码' : '显示邮箱授权码'}
                >
                  {showSmtpPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </button>
              </div>
              <span className="mt-1 block text-xs text-gray-500">QQ 邮箱等服务通常要求填写授权码。</span>
            </label>

            <label className="lg:col-span-2">
              <span className="field-label">发件人显示名</span>
              <input
                type="text"
                value={settings.smtp_from || ''}
                onChange={(event) => setSettings({ ...settings, smtp_from: event.target.value })}
                placeholder="闲鱼自动回复系统"
                className="ios-input w-full rounded-md px-3 py-2.5 text-sm"
              />
            </label>
          </div>
        </section>
      )}
    </div>
  );
};

export default Settings;
