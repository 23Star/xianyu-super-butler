import React, { useEffect, useState } from 'react';
import {
  Database,
  Eye,
  EyeOff,
  KeyRound,
  Mail,
  Megaphone,
  RefreshCw,
  Save,
  Settings as SettingsIcon,
  ShieldCheck,
  Sparkles,
  UserRound,
  Zap,
} from 'lucide-react';

import {
  changePassword,
  createQuickPhrase,
  deleteQuickPhrase,
  getQuickPhrases,
  getSystemSettings,
  updateQuickPhrase,
  updateSystemSettings,
} from '../services/api';
import { notify } from '../services/feedback';
import { QuickPhrase, SystemSettings } from '../types';
import {
  NoticeBanner,
  PageHeader,
  PageLoading,
  PageTabs,
  SectionHeader,
} from './ui';

type SettingsSection = 'general' | 'ai' | 'email' | 'phrases' | 'notice';

/**
 * 把后端的开关值转成布尔。
 *
 * 后端统一把开关存成 'true' / 'false' 字符串。直接拿来当布尔用会踩坑：
 * 'false' 本身是 truthy，关掉的开关在界面上仍显示开启；再点一次取反得到的
 * 还是 false，于是开关一旦关闭就再也打不开。
 */
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
  // 快捷短语：人工客服常用话术
  const [phrases, setPhrases] = useState<QuickPhrase[]>([]);
  const [phraseForm, setPhraseForm] = useState({ category: '默认', title: '', content: '' });

  const loadPhrases = () => {
    getQuickPhrases(true).then(setPhrases).catch(() => setPhrases([]));
  };

  useEffect(() => { loadPhrases(); }, []);

  const handleAddPhrase = async () => {
    if (!phraseForm.title.trim() || !phraseForm.content.trim()) return;
    await createQuickPhrase(phraseForm.title.trim(), phraseForm.content.trim(), phraseForm.category.trim() || '默认');
    setPhraseForm({ category: phraseForm.category, title: '', content: '' });
    loadPhrases();
  };

  const handleTogglePhrase = async (phrase: QuickPhrase) => {
    await updateQuickPhrase(phrase.id, { enabled: !phrase.enabled });
    loadPhrases();
  };

  const handleDeletePhrase = async (id: number) => {
    await deleteQuickPhrase(id);
    loadPhrases();
  };

  const [showApiKey, setShowApiKey] = useState(false);
  const [showSmtpPassword, setShowSmtpPassword] = useState(false);

  // 修改登录密码。与页面顶部的「保存设置」互不影响：这里改的是当前账号的凭据，
  // 走的是独立接口，成功后立刻生效。
  const [passwordForm, setPasswordForm] = useState({ current: '', next: '', confirm: '' });
  const [showPasswordFields, setShowPasswordFields] = useState(false);
  const [changingPassword, setChangingPassword] = useState(false);

  const handleChangePassword = async () => {
    const { current, next, confirm } = passwordForm;
    if (!current || !next) {
      notify('请填写当前密码和新密码');
      return;
    }
    if (next.length < 6) {
      notify('新密码至少 6 位');
      return;
    }
    if (next !== confirm) {
      notify('两次输入的新密码不一致');
      return;
    }
    if (next === current) {
      notify('新密码不能与当前密码相同');
      return;
    }

    setChangingPassword(true);
    try {
      const result = await changePassword(current, next);
      // 后端对「当前密码错误」这类校验失败也返回 200，要看 success 字段
      if (result?.success === false) {
        notify(result.message || '密码修改失败');
        return;
      }
      setPasswordForm({ current: '', next: '', confirm: '' });
      notify('密码已修改，下次登录请使用新密码');
    } catch (error) {
      notify(`密码修改失败：${(error as Error).message}`);
    } finally {
      setChangingPassword(false);
    }
  };

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
          { id: 'phrases', label: '快捷短语', icon: Zap },
          { id: 'notice', label: '公告与更新', icon: Megaphone },
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
              checked={toBool(settings.registration_enabled, true)}
              onChange={() => setSettings({
                ...settings,
                registration_enabled: !toBool(settings.registration_enabled, true),
              })}
            />
            <SettingToggle
              title="注册邮箱验证"
              description="要求注册时填写邮箱验证码。未配置下方「邮件服务」时请关闭，否则用户收不到验证码、无法完成注册。"
              checked={toBool(settings.email_verification_enabled, true)}
              onChange={() => setSettings({
                ...settings,
                email_verification_enabled: !toBool(settings.email_verification_enabled, true),
              })}
            />
            <SettingToggle
              title="显示默认登录信息"
              description="仅建议在本地调试环境显示默认账号提示。"
              checked={toBool(settings.show_default_login_info, true)}
              onChange={() => setSettings({
                ...settings,
                show_default_login_info: !toBool(settings.show_default_login_info, true),
              })}
            />
            <SettingToggle
              title="登录滑动验证码"
              description="账号密码登录前要求完成滑动验证。"
              checked={toBool(settings.login_captcha_enabled, true)}
              onChange={() => setSettings({
                ...settings,
                login_captcha_enabled: !toBool(settings.login_captcha_enabled, true),
              })}
            />
          </section>

          <section className="section-panel">
            <SectionHeader
              title="修改登录密码"
              description="修改当前登录账号的密码，保存后立即生效。"
              icon={KeyRound}
            />
            <div className="grid gap-4 p-4">
              <label>
                <span className="field-label">当前密码</span>
                <div className="relative">
                  <input
                    type={showPasswordFields ? 'text' : 'password'}
                    value={passwordForm.current}
                    onChange={e => setPasswordForm({ ...passwordForm, current: e.target.value })}
                    autoComplete="current-password"
                    placeholder="请输入当前密码"
                    className="ios-input w-full rounded-md px-3 py-2.5 pr-11 text-sm"
                  />
                  <button
                    type="button"
                    onClick={() => setShowPasswordFields(!showPasswordFields)}
                    className="absolute right-2 top-1/2 -translate-y-1/2 rounded-md p-2 text-gray-400 hover:bg-gray-100 hover:text-gray-600"
                    aria-label={showPasswordFields ? '隐藏密码' : '显示密码'}
                  >
                    {showPasswordFields ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                  </button>
                </div>
              </label>

              <div className="grid gap-4 sm:grid-cols-2">
                <label>
                  <span className="field-label">新密码</span>
                  <input
                    type={showPasswordFields ? 'text' : 'password'}
                    value={passwordForm.next}
                    onChange={e => setPasswordForm({ ...passwordForm, next: e.target.value })}
                    autoComplete="new-password"
                    placeholder="至少 6 位"
                    className="ios-input w-full rounded-md px-3 py-2.5 text-sm"
                  />
                </label>
                <label>
                  <span className="field-label">确认新密码</span>
                  <input
                    type={showPasswordFields ? 'text' : 'password'}
                    value={passwordForm.confirm}
                    onChange={e => setPasswordForm({ ...passwordForm, confirm: e.target.value })}
                    autoComplete="new-password"
                    placeholder="再次输入新密码"
                    className="ios-input w-full rounded-md px-3 py-2.5 text-sm"
                  />
                </label>
              </div>

              <div className="flex justify-end">
                <button
                  type="button"
                  onClick={() => void handleChangePassword()}
                  disabled={changingPassword}
                  className="ios-btn-primary flex items-center justify-center gap-2 rounded-md px-4 py-2 text-sm disabled:opacity-60"
                >
                  <KeyRound className="h-4 w-4" />
                  {changingPassword ? '修改中' : '修改密码'}
                </button>
              </div>
            </div>
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
              checked={toBool(settings.item_sync_enabled, true)}
              onChange={() => setSettings({
                ...settings,
                item_sync_enabled: !toBool(settings.item_sync_enabled, true),
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

          <section className="section-panel">
            <SectionHeader
              title="订单同步"
              description="定时从卖家端拉取订单，补齐监听离线期间产生的订单。"
              icon={Database}
            />
            <SettingToggle
              title="启用订单自动同步"
              description="关闭后只能在订单页手动点「拉取卖出订单」。"
              checked={settings.order_sync_enabled !== false}
              onChange={() => setSettings({
                ...settings,
                order_sync_enabled: settings.order_sync_enabled === false,
              })}
            />
            <div className="grid gap-4 p-4 sm:grid-cols-2">
              <label>
                <span className="field-label">同步间隔（分钟）</span>
                <input
                  type="number"
                  value={Math.round((settings.order_sync_interval || 1800) / 60)}
                  onChange={(event) => {
                    const minutes = parseInt(event.target.value, 10) || 30;
                    setSettings({ ...settings, order_sync_interval: minutes * 60 });
                  }}
                  className="ios-input w-full rounded-md px-3 py-2.5"
                  min="5"
                  max="1440"
                />
                <span className="mt-1 block text-xs text-gray-500">最低 5 分钟，建议 30 分钟。</span>
              </label>
            </div>
          </section>

          <section className="section-panel">
            <SectionHeader
              title="商品擦亮"
              description="定时擦亮商品重新获取搜索曝光，平台对每日次数有限制。"
              icon={Database}
            />
            <SettingToggle
              title="启用自动擦亮"
              description="开启后按下方间隔自动擦亮全部商品。也可在商品页手动触发。"
              checked={settings.auto_polish_enabled === true}
              onChange={() => setSettings({
                ...settings,
                auto_polish_enabled: settings.auto_polish_enabled !== true,
              })}
            />
            <div className="grid gap-4 p-4 sm:grid-cols-2">
              <label>
                <span className="field-label">擦亮间隔（小时）</span>
                <input
                  type="number"
                  value={Math.round((settings.auto_polish_interval || 21600) / 3600)}
                  onChange={(event) => {
                    const hours = parseInt(event.target.value, 10) || 6;
                    setSettings({ ...settings, auto_polish_interval: hours * 3600 });
                  }}
                  className="ios-input w-full rounded-md px-3 py-2.5"
                  min="1"
                  max="24"
                />
                <span className="mt-1 block text-xs text-gray-500">最短 1 小时，建议 6 小时。</span>
              </label>
            </div>
          </section>

        </div>
      )}

      {activeSection === 'notice' && (
        <div className="grid gap-4 xl:grid-cols-2">
          <section className="section-panel">
            <SectionHeader
              title="公告与更新"
              description="填入你的公网 JSON 地址后，系统会定时拉取公告并检查新版本。"
              icon={Megaphone}
            />
            <SettingToggle
              title="启用公告与更新检查"
              description="关闭后不再拉取远端公告，也不提示新版本。"
              checked={settings.announcement_enabled !== 'false'}
              onChange={() => setSettings({
                ...settings,
                announcement_enabled: settings.announcement_enabled === 'false' ? 'true' : 'false',
              })}
            />
            <SettingToggle
              title="展示公告"
              description="关闭后顶部横幅和「关于」页都不再显示公告内容，仍会正常检查新版本。"
              checked={toBool(settings.announcement_show_notice, true)}
              onChange={() => setSettings({
                ...settings,
                announcement_show_notice: !toBool(settings.announcement_show_notice, true),
              })}
            />
            <SettingToggle
              title="展示版本更新提示"
              description="关闭后不再弹出新版本横幅，公告照常显示。适合不希望团队成员自行升级的场景。"
              checked={toBool(settings.announcement_show_update, true)}
              onChange={() => setSettings({
                ...settings,
                announcement_show_update: !toBool(settings.announcement_show_update, true),
              })}
            />
            <div className="px-4 py-3">
              <label className="field-label">公告 JSON 地址</label>
              <input
                type="url"
                value={settings.announcement_source_url || ''}
                onChange={e => setSettings({
                  ...settings,
                  announcement_source_url: e.target.value,
                })}
                placeholder="https://connect.corleom.com/announcement.json（留空即用此地址）"
                className="ios-input mt-1 w-full rounded-md px-3 py-2 text-sm"
              />
              <p className="mt-1.5 text-xs text-gray-500">
                留空则使用官方公告源，可填入自建地址替换。
                后端每 10 分钟拉取一次并缓存；远端不可用时沿用上次结果。
                在「关于」页可手动点「检查更新」立即刷新。
              </p>
            </div>
          </section>
        </div>
      )}

      {activeSection === 'phrases' && (
        <section className="section-panel">
          <SectionHeader
            title="快捷短语"
            description="人工客服常用话术，在消息管理页可一键插入到输入框。"
            icon={Zap}
          />
          <div className="grid gap-3 p-4 sm:grid-cols-[140px_200px_1fr_auto]">
            <input
              value={phraseForm.category}
              onChange={(e) => setPhraseForm({ ...phraseForm, category: e.target.value })}
              placeholder="分类"
              className="ios-input rounded-md px-3 py-2.5"
            />
            <input
              value={phraseForm.title}
              onChange={(e) => setPhraseForm({ ...phraseForm, title: e.target.value })}
              placeholder="标题"
              className="ios-input rounded-md px-3 py-2.5"
            />
            <input
              value={phraseForm.content}
              onChange={(e) => setPhraseForm({ ...phraseForm, content: e.target.value })}
              placeholder="话术内容"
              className="ios-input rounded-md px-3 py-2.5"
            />
            <button
              type="button"
              onClick={() => void handleAddPhrase()}
              disabled={!phraseForm.title.trim() || !phraseForm.content.trim()}
              className="ios-btn-primary rounded-md px-4 py-2.5 text-sm disabled:opacity-60"
            >
              添加
            </button>
          </div>
          <div className="divide-y divide-gray-100 border-t border-gray-100">
            {phrases.length === 0 ? (
              <p className="px-4 py-6 text-center text-sm text-gray-500">还没有快捷短语</p>
            ) : (
              phrases.map((phrase) => (
                <div key={phrase.id} className="flex items-center gap-3 px-4 py-3">
                  <span className="w-20 shrink-0 text-xs text-gray-500">{phrase.category}</span>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-semibold text-gray-800">{phrase.title}</p>
                    <p className="truncate text-xs text-gray-500">{phrase.content}</p>
                  </div>
                  <span className="shrink-0 text-xs text-gray-400">用了 {phrase.use_count} 次</span>
                  <button
                    type="button"
                    onClick={() => void handleTogglePhrase(phrase)}
                    className="shrink-0 text-xs text-blue-600 hover:underline"
                  >
                    {phrase.enabled ? '停用' : '启用'}
                  </button>
                  <button
                    type="button"
                    onClick={() => void handleDeletePhrase(phrase.id)}
                    className="shrink-0 text-xs text-red-500 hover:underline"
                  >
                    删除
                  </button>
                </div>
              ))
            )}
          </div>
        </section>
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
              <NoticeBanner
                type="info"
                message="常用兼容服务包括阿里云 DashScope 和 OpenAI。API Key 仅保存在当前系统配置中。"
              />
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
