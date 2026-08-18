import React, { useEffect, useMemo, useState } from 'react';
import {
  Bot,
  CheckCircle2,
  Eye,
  EyeOff,
  ExternalLink,
  Loader2,
  MessageSquareText,
  Play,
  Save,
  ShieldCheck,
} from 'lucide-react';
import { AccountDetail, AIReplySettings } from '../types';
import {
  getAccountAISettings,
  getAccountDetails,
  testAIConnection,
  updateAccountAISettings,
} from '../services/api';
import { notify } from '../services/feedback';
import { EmptyState, PageHeader, PageLoading, SectionHeader } from './ui';

// 自建中转，兼容 OpenAI 接口，每天可领免费额度，省去用户自己找服务商配密钥。
const FREE_TOKEN_BASE_URL = 'https://ai.corleom.com/v1';
const FREE_TOKEN_HOME = 'https://ai.corleom.com';

const defaultSettings: AIReplySettings = {
  ai_enabled: false,
  model_name: 'qwen-plus',
  api_key: '',
  api_key_configured: false,
  base_url: FREE_TOKEN_BASE_URL,
  max_discount_percent: 10,
  max_discount_amount: 100,
  max_bargain_rounds: 3,
  context_enabled: true,
  context_message_limit: 12,
  context_expire_minutes: 120,
  custom_prompts: '',
};

const AIReply: React.FC = () => {
  const [accounts, setAccounts] = useState<AccountDetail[]>([]);
  const [selectedAccountId, setSelectedAccountId] = useState('');
  const [settings, setSettings] = useState<AIReplySettings>(defaultSettings);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [showApiKey, setShowApiKey] = useState(false);
  const [testMessage, setTestMessage] = useState('你好，这个商品现在还能买吗？');
  const [testReply, setTestReply] = useState('');

  const selectedAccount = useMemo(
    () => accounts.find(account => account.id === selectedAccountId),
    [accounts, selectedAccountId],
  );

  useEffect(() => {
    getAccountDetails()
      .then(data => {
        setAccounts(data);
        setSelectedAccountId(data[0]?.id || '');
      })
      .catch(error => notify(error instanceof Error ? error.message : '账号加载失败', 'error'))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (!selectedAccountId) return;
    setLoading(true);
    setTestReply('');
    setShowApiKey(false);
    getAccountAISettings(selectedAccountId)
      .then(data => setSettings({ ...defaultSettings, ...data, api_key: '' }))
      .catch(error => notify(error instanceof Error ? error.message : 'AI配置加载失败', 'error'))
      .finally(() => setLoading(false));
  }, [selectedAccountId]);

  const updateSetting = <K extends keyof AIReplySettings>(key: K, value: AIReplySettings[K]) => {
    setSettings(current => ({ ...current, [key]: value }));
  };

  const handleSave = async () => {
    if (!selectedAccountId) {
      notify('请先选择账号', 'warning');
      return;
    }
    if (!settings.model_name.trim() || !settings.base_url.trim()) {
      notify('模型名称和接口地址不能为空', 'warning');
      return;
    }

    setSaving(true);
    try {
      await updateAccountAISettings(selectedAccountId, settings);
      const refreshed = await getAccountAISettings(selectedAccountId);
      setSettings({ ...defaultSettings, ...refreshed, api_key: '' });
      notify('人工智能回复配置已保存', 'success');
    } catch (error) {
      notify(error instanceof Error ? error.message : 'AI配置保存失败', 'error');
    } finally {
      setSaving(false);
    }
  };

  const handleTest = async () => {
    if (!selectedAccountId || !testMessage.trim()) {
      notify('请选择账号并输入测试消息', 'warning');
      return;
    }
    setTesting(true);
    setTestReply('');
    try {
      const result = await testAIConnection(selectedAccountId, {
        message: testMessage.trim(),
        item_title: '测试商品',
        item_price: 100,
        item_desc: '仅用于测试人工智能回复，不会发送到闲鱼。',
      });
      setTestReply(result.reply || result.message || '测试完成');
      notify('AI回复测试完成', 'success');
    } catch (error) {
      notify(error instanceof Error ? error.message : 'AI回复测试失败', 'error');
    } finally {
      setTesting(false);
    }
  };

  if (loading && accounts.length === 0) {
    return <PageLoading label="正在加载 AI 回复配置" />;
  }

  return (
    <div className="page-stack animate-fade-in">
      <PageHeader
        title="AI 回复"
        description="按账号配置模型连接、上下文记忆、议价边界和业务回复规则。"
        icon={Bot}
        actions={(
          <div className="flex min-w-0 flex-wrap items-end gap-2">
            <label className="min-w-0 sm:w-72">
              <span className="field-label">当前账号</span>
              <select
                value={selectedAccountId}
                onChange={event => setSelectedAccountId(event.target.value)}
                className="ios-input w-full rounded-md px-3 py-2 text-sm font-semibold"
              >
                {accounts.map(account => (
                  <option key={account.id} value={account.id}>
                    {account.nickname || account.remark || `账号 ${account.id.slice(0, 8)}`}
                  </option>
                ))}
              </select>
            </label>
            <button
              type="button"
              onClick={handleSave}
              disabled={saving || !selectedAccountId}
              className="ios-btn-primary flex items-center justify-center gap-2 rounded-md px-4 py-2 text-sm"
            >
              {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
              {saving ? '保存中' : '保存配置'}
            </button>
          </div>
        )}
      />

      {!selectedAccountId ? (
        <EmptyState
          icon={Bot}
          title="暂无可配置账号"
          description="请先在账号管理中添加并登录闲鱼账号。"
        />
      ) : (
        <>
          <section className="section-panel grid gap-4 p-4 lg:grid-cols-[1fr_auto] lg:items-center">
            <div>
              <div className="flex items-center gap-2 font-bold text-gray-900">
                <MessageSquareText className="h-5 w-5" />
                {selectedAccount?.nickname || selectedAccount?.remark || selectedAccountId}
              </div>
              <p className="mt-1 text-sm text-gray-500">
                回复优先级：关键词回复 → 人工智能回复 → 默认回复。AI失败时不会中断消息处理。
              </p>
            </div>
            <label className="flex cursor-pointer items-center gap-3">
              <span className="text-sm font-bold text-gray-700">
                {settings.ai_enabled ? '已启用' : '已停用'}
              </span>
              <input
                type="checkbox"
                checked={settings.ai_enabled}
                onChange={event => updateSetting('ai_enabled', event.target.checked)}
                className="h-5 w-5 accent-yellow-400"
              />
            </label>
          </section>

          <div className="grid gap-6 xl:grid-cols-[minmax(0,1.35fr)_minmax(340px,0.65fr)]">
            <div className="space-y-6">
              <section className="section-panel">
                <SectionHeader
                  title="模型连接"
                  description="支持 OpenAI 兼容接口；密钥留空时保留服务器中已有配置。"
                  icon={Bot}
                />
                <div className="grid gap-4 p-5 md:grid-cols-2">
                  <div className="md:col-span-2 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-brand-200 bg-brand-50 px-4 py-3">
                    <div className="min-w-0">
                      <p className="text-sm font-semibold text-gray-800">
                        没有 API Key？每天可免费领取额度
                      </p>
                      <p className="mt-0.5 text-xs text-gray-600">
                        兼容 OpenAI 接口，注册后把密钥填到下方即可直接用。
                      </p>
                    </div>
                    <div className="flex shrink-0 items-center gap-2">
                      <a
                        href={FREE_TOKEN_HOME}
                        target="_blank"
                        rel="noreferrer noopener"
                        className="inline-flex items-center gap-1 rounded-md bg-brand-500 px-3 py-1.5 text-xs font-semibold text-brand-ink hover:bg-brand-600"
                      >
                        免费领取 token
                        <ExternalLink className="h-3.5 w-3.5" />
                      </a>
                    </div>
                  </div>
                  <label>
                    <span className="mb-1.5 block text-sm font-semibold text-gray-700">接口地址</span>
                    <input
                      value={settings.base_url}
                      onChange={event => updateSetting('base_url', event.target.value)}
                      className="ios-input w-full rounded-md px-3 py-2.5 text-sm"
                      placeholder={FREE_TOKEN_BASE_URL}
                    />
                  </label>
                  <label>
                    <span className="mb-1.5 block text-sm font-semibold text-gray-700">模型名称</span>
                    <input
                      value={settings.model_name}
                      onChange={event => updateSetting('model_name', event.target.value)}
                      className="ios-input w-full rounded-md px-3 py-2.5 text-sm"
                      placeholder="qwen-plus"
                    />
                  </label>
                  <label className="md:col-span-2">
                    <span className="mb-1.5 flex items-center justify-between gap-3 text-sm font-semibold text-gray-700">
                      API Key
                      {settings.api_key_configured && !settings.api_key && (
                        <span className="flex items-center gap-1 text-xs font-medium text-emerald-700">
                          <CheckCircle2 className="h-3.5 w-3.5" />
                          已配置，留空保持不变
                        </span>
                      )}
                    </span>
                    <div className="relative">
                      <input
                        type={showApiKey ? 'text' : 'password'}
                        value={settings.api_key}
                        onChange={event => updateSetting('api_key', event.target.value)}
                        className="ios-input w-full rounded-md px-3 py-2.5 pr-10 text-sm"
                        placeholder={settings.api_key_configured ? '输入新密钥以替换' : '请输入 API Key'}
                        autoComplete="new-password"
                      />
                      <button
                        type="button"
                        onClick={() => setShowApiKey(value => !value)}
                        className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-1 text-gray-500 hover:bg-gray-100"
                        title={showApiKey ? '隐藏密钥' : '显示密钥'}
                      >
                        {showApiKey ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                      </button>
                    </div>
                  </label>
                </div>
              </section>

              <section className="section-panel">
                <SectionHeader
                  title="回复策略"
                  description="约束议价空间，并补充账号专属的语气、承诺和售后规则。"
                  icon={MessageSquareText}
                />
                <div className="grid gap-4 p-5 sm:grid-cols-3">
                  <label>
                    <span className="mb-1.5 block text-sm font-semibold text-gray-700">最大折扣比例</span>
                    <input
                      type="number"
                      min={0}
                      max={100}
                      value={settings.max_discount_percent}
                      onChange={event => updateSetting('max_discount_percent', Number(event.target.value))}
                      className="ios-input w-full rounded-md px-3 py-2.5 text-sm"
                    />
                  </label>
                  <label>
                    <span className="mb-1.5 block text-sm font-semibold text-gray-700">最大折扣金额</span>
                    <input
                      type="number"
                      min={0}
                      value={settings.max_discount_amount ?? 0}
                      onChange={event => updateSetting('max_discount_amount', Number(event.target.value))}
                      className="ios-input w-full rounded-md px-3 py-2.5 text-sm"
                    />
                  </label>
                  <label>
                    <span className="mb-1.5 block text-sm font-semibold text-gray-700">最大议价轮次</span>
                    <input
                      type="number"
                      min={1}
                      max={10}
                      value={settings.max_bargain_rounds}
                      onChange={event => updateSetting('max_bargain_rounds', Number(event.target.value))}
                      className="ios-input w-full rounded-md px-3 py-2.5 text-sm"
                    />
                  </label>
                  <label className="sm:col-span-3">
                    <span className="mb-1.5 block text-sm font-semibold text-gray-700">回复风格与业务规则</span>
                    <textarea
                      value={settings.custom_prompts}
                      onChange={event => updateSetting('custom_prompts', event.target.value)}
                      className="ios-input min-h-36 w-full resize-y rounded-md px-3 py-2.5 text-sm leading-6"
                      placeholder="例如：语气简洁，不承诺未确认的库存；涉及售后时引导买家说明订单号。"
                    />
                  </label>
                </div>
              </section>

              <section className="section-panel">
                <SectionHeader
                  title="上下文对话"
                  description="控制单个买家会话中可用于连续回复的近期消息范围。"
                  icon={ShieldCheck}
                />
                <div className="grid gap-4 p-5 sm:grid-cols-2">
                  <label className="flex items-center justify-between gap-4 sm:col-span-2">
                    <span>
                      <span className="block text-sm font-semibold text-gray-700">记住近期对话</span>
                      <span className="mt-1 block text-xs leading-5 text-gray-500">
                        上下文按账号、会话和商品隔离，切换商品不会混入旧商品内容。
                      </span>
                    </span>
                    <input
                      type="checkbox"
                      checked={settings.context_enabled}
                      onChange={event => updateSetting('context_enabled', event.target.checked)}
                      className="h-5 w-5 shrink-0 accent-yellow-400"
                    />
                  </label>
                  <label>
                    <span className="mb-1.5 block text-sm font-semibold text-gray-700">记忆消息数</span>
                    <input
                      type="number"
                      min={2}
                      max={30}
                      disabled={!settings.context_enabled}
                      value={settings.context_message_limit}
                      onChange={event => updateSetting('context_message_limit', Number(event.target.value))}
                      className="ios-input w-full rounded-md px-3 py-2.5 text-sm disabled:bg-gray-100"
                    />
                  </label>
                  <label>
                    <span className="mb-1.5 block text-sm font-semibold text-gray-700">上下文有效期（分钟）</span>
                    <input
                      type="number"
                      min={5}
                      max={1440}
                      disabled={!settings.context_enabled}
                      value={settings.context_expire_minutes}
                      onChange={event => updateSetting('context_expire_minutes', Number(event.target.value))}
                      className="ios-input w-full rounded-md px-3 py-2.5 text-sm disabled:bg-gray-100"
                    />
                  </label>
                  <p className="text-xs leading-5 text-gray-500 sm:col-span-2">
                    付款、发货、退款、收货等系统事件不会交给大模型，将继续由订单状态和自动发货规则处理。
                  </p>
                </div>
              </section>
            </div>

            <aside className="space-y-5">
              <section className="section-panel">
                <SectionHeader
                  title="回复测试"
                  description="只生成文本，不会发送到闲鱼会话。"
                  icon={Play}
                />
                <div className="p-5">
                  <textarea
                    value={testMessage}
                    onChange={event => setTestMessage(event.target.value)}
                    className="ios-input min-h-24 w-full resize-y rounded-md px-3 py-2.5 text-sm"
                  />
                  <button
                    type="button"
                    onClick={handleTest}
                    disabled={testing || !settings.ai_enabled}
                    className="ios-btn-primary mt-3 flex w-full items-center justify-center gap-2 rounded-md px-4 py-2.5 text-sm"
                  >
                    {testing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
                    {testing ? '生成中' : '测试回复'}
                  </button>
                  {testReply && (
                    <div className="mt-4 border-l-4 border-yellow-400 bg-yellow-50 px-4 py-3 text-sm leading-6 text-gray-800">
                      {testReply}
                    </div>
                  )}
                </div>
              </section>

              <section className="section-panel p-5">
                <div className="flex items-start gap-3">
                  <ShieldCheck className="mt-0.5 h-5 w-5 shrink-0 text-emerald-700" />
                  <div>
                    <h2 className="text-sm font-bold text-gray-900">运行保护</h2>
                    <p className="mt-1 text-xs leading-5 text-gray-500">
                      密钥不会回传到浏览器；接口超时、空回复或格式异常时，系统会自动继续使用默认回复。
                    </p>
                  </div>
                </div>
              </section>
            </aside>
          </div>

        </>
      )}
    </div>
  );
};

export default AIReply;
