import React, { useEffect, useMemo, useState } from 'react';
import {
  Activity,
  BellRing,
  ChevronLeft,
  ChevronRight,
  Edit3,
  Link2,
  Loader2,
  Plus,
  RefreshCw,
  Save,
  ShieldAlert,
  Trash2,
  X,
} from 'lucide-react';

import {
  AccountDetail,
  MessageNotification,
  NotificationChannel,
  NotificationChannelType,
  RiskControlLog,
  SystemLog,
} from '../types';
import {
  createNotificationChannel,
  deleteMessageNotification,
  deleteNotificationChannel,
  deleteRiskControlLog,
  getAccountDetails,
  getMessageNotifications,
  getNotificationChannels,
  getRiskControlLogs,
  getSystemLogs,
  setMessageNotification,
  updateNotificationChannel,
} from '../services/api';
import { confirmAction, notify } from '../services/feedback';
import { EmptyState, PageHeader, PageTabs, SectionHeader } from './ui';

type PageTab = 'channels' | 'bindings' | 'risk' | 'system';

interface NotificationsAndLogsProps {
  isAdmin: boolean;
}

interface ChannelDefinition {
  label: string;
  fields: Array<{
    key: string;
    label: string;
    placeholder?: string;
    type?: 'text' | 'password' | 'number' | 'textarea' | 'select';
    options?: string[];
    optional?: boolean;
  }>;
  defaults: Record<string, unknown>;
}

const CHANNEL_DEFINITIONS: Record<NotificationChannelType, ChannelDefinition> = {
  dingtalk: {
    label: '钉钉',
    fields: [
      { key: 'webhook_url', label: 'Webhook 地址', placeholder: 'https://oapi.dingtalk.com/robot/send?...' },
      { key: 'secret', label: '加签密钥', type: 'password', optional: true },
    ],
    defaults: {},
  },
  feishu: {
    label: '飞书',
    fields: [
      { key: 'webhook_url', label: 'Webhook 地址', placeholder: 'https://open.feishu.cn/open-apis/bot/v2/hook/...' },
      { key: 'secret', label: '签名密钥', type: 'password', optional: true },
    ],
    defaults: {},
  },
  bark: {
    label: 'Bark',
    fields: [
      { key: 'device_key', label: 'Device Key', type: 'password' },
      { key: 'server_url', label: '服务器地址', placeholder: 'https://api.day.app', optional: true },
    ],
    defaults: { server_url: 'https://api.day.app' },
  },
  email: {
    label: '邮件',
    fields: [
      { key: 'smtp_server', label: 'SMTP 服务器', placeholder: 'smtp.example.com' },
      { key: 'smtp_port', label: 'SMTP 端口', type: 'number' },
      { key: 'email_user', label: '发件邮箱' },
      { key: 'email_password', label: '邮箱密码或授权码', type: 'password' },
      { key: 'recipient_email', label: '接收邮箱' },
    ],
    defaults: { smtp_port: 587 },
  },
  webhook: {
    label: 'Webhook',
    fields: [
      { key: 'webhook_url', label: 'Webhook 地址' },
      { key: 'http_method', label: '请求方法', type: 'select', options: ['POST', 'PUT'] },
      { key: 'headers', label: '请求头 JSON', type: 'textarea', placeholder: '{"Authorization":"Bearer ..."}', optional: true },
    ],
    defaults: { http_method: 'POST', headers: '{}' },
  },
  wechat: {
    label: '企业微信',
    fields: [
      { key: 'webhook_url', label: '机器人 Webhook 地址' },
    ],
    defaults: {},
  },
  telegram: {
    label: 'Telegram',
    fields: [
      { key: 'bot_token', label: 'Bot Token', type: 'password' },
      { key: 'chat_id', label: 'Chat ID' },
    ],
    defaults: {},
  },
};

const PAGE_SIZE = 20;

const accountLabel = (account: AccountDetail) =>
  account.nickname || account.remark || account.id;

const formatTime = (value?: string) => {
  if (!value) return '-';
  const date = new Date(value.includes('T') ? value : value.replace(' ', 'T'));
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN');
};

const NotificationsAndLogs: React.FC<NotificationsAndLogsProps> = ({ isAdmin }) => {
  const [activeTab, setActiveTab] = useState<PageTab>('channels');
  const [accounts, setAccounts] = useState<AccountDetail[]>([]);
  const [channels, setChannels] = useState<NotificationChannel[]>([]);
  const [bindings, setBindings] = useState<MessageNotification[]>([]);
  const [loadingBase, setLoadingBase] = useState(true);
  const [editorOpen, setEditorOpen] = useState(false);
  const [editingChannel, setEditingChannel] = useState<NotificationChannel | null>(null);
  const [channelType, setChannelType] = useState<NotificationChannelType>('dingtalk');
  const [channelName, setChannelName] = useState('');
  const [channelConfig, setChannelConfig] = useState<Record<string, unknown>>({});
  const [savingChannel, setSavingChannel] = useState(false);
  const [bindingAccount, setBindingAccount] = useState('');
  const [bindingChannel, setBindingChannel] = useState('');
  const [savingBinding, setSavingBinding] = useState(false);
  const [riskLogs, setRiskLogs] = useState<RiskControlLog[]>([]);
  const [riskTotal, setRiskTotal] = useState(0);
  const [riskAccount, setRiskAccount] = useState('');
  const [riskStatus, setRiskStatus] = useState('');
  const [riskPage, setRiskPage] = useState(0);
  const [riskLoading, setRiskLoading] = useState(false);
  const [systemLogs, setSystemLogs] = useState<SystemLog[]>([]);
  const [systemLevel, setSystemLevel] = useState('');
  const [systemSource, setSystemSource] = useState('');
  const [systemLoading, setSystemLoading] = useState(false);

  const loadBaseData = async () => {
    setLoadingBase(true);
    try {
      const [accountData, channelData, bindingData] = await Promise.all([
        getAccountDetails(),
        getNotificationChannels(),
        getMessageNotifications(),
      ]);
      setAccounts(accountData);
      setChannels(channelData.data);
      setBindings(bindingData.data);
      if (!bindingAccount && accountData.length > 0) setBindingAccount(accountData[0].id);
    } catch (error) {
      notify(`加载通知配置失败：${(error as Error).message}`);
    } finally {
      setLoadingBase(false);
    }
  };

  useEffect(() => {
    void loadBaseData();
  }, []);

  const openCreateEditor = () => {
    const type: NotificationChannelType = 'dingtalk';
    setEditingChannel(null);
    setChannelType(type);
    setChannelName('');
    setChannelConfig({ ...CHANNEL_DEFINITIONS[type].defaults });
    setEditorOpen(true);
  };

  const openEditEditor = (channel: NotificationChannel) => {
    setEditingChannel(channel);
    setChannelType(channel.type);
    setChannelName(channel.name);
    setChannelConfig({ ...CHANNEL_DEFINITIONS[channel.type].defaults, ...channel.config });
    setEditorOpen(true);
  };

  const changeChannelType = (type: NotificationChannelType) => {
    setChannelType(type);
    setChannelConfig({ ...CHANNEL_DEFINITIONS[type].defaults });
  };

  const saveChannel = async () => {
    setSavingChannel(true);
    try {
      if (editingChannel) {
        await updateNotificationChannel(editingChannel.id, {
          name: channelName,
          config: channelConfig,
          enabled: editingChannel.enabled,
        });
      } else {
        await createNotificationChannel({
          name: channelName,
          type: channelType,
          config: channelConfig,
        });
      }
      setEditorOpen(false);
      await loadBaseData();
    } catch (error) {
      notify(`保存通知渠道失败：${(error as Error).message}`);
    } finally {
      setSavingChannel(false);
    }
  };

  const toggleChannel = async (channel: NotificationChannel) => {
    try {
      await updateNotificationChannel(channel.id, { enabled: !channel.enabled });
      setChannels((current) => current.map((item) => (
        item.id === channel.id ? { ...item, enabled: !item.enabled } : item
      )));
      if (channel.enabled) {
        setBindings((current) => current.filter((item) => item.channel_id !== Number(channel.id)));
      } else {
        await loadBaseData();
      }
    } catch (error) {
      notify(`更新渠道状态失败：${(error as Error).message}`);
    }
  };

  const removeChannel = async (channel: NotificationChannel) => {
    if (!await confirmAction(`确认删除通知渠道“${channel.name}”？相关账号绑定也会被删除。`)) return;
    try {
      await deleteNotificationChannel(channel.id);
      await loadBaseData();
    } catch (error) {
      notify(`删除通知渠道失败：${(error as Error).message}`);
    }
  };

  const addBinding = async () => {
    if (!bindingAccount || !bindingChannel) {
      notify('请选择账号和通知渠道');
      return;
    }
    setSavingBinding(true);
    try {
      await setMessageNotification(bindingAccount, Number(bindingChannel), true);
      setBindingChannel('');
      await loadBaseData();
    } catch (error) {
      notify(`绑定失败：${(error as Error).message}`);
    } finally {
      setSavingBinding(false);
    }
  };

  const toggleBinding = async (binding: MessageNotification) => {
    try {
      await setMessageNotification(binding.cookie_id, binding.channel_id, !binding.enabled);
      await loadBaseData();
    } catch (error) {
      notify(`更新绑定失败：${(error as Error).message}`);
    }
  };

  const removeBinding = async (binding: MessageNotification) => {
    if (!await confirmAction(`确认解除账号与“${binding.channel_name}”的通知绑定？`)) return;
    try {
      await deleteMessageNotification(binding.id);
      setBindings((current) => current.filter((item) => item.id !== binding.id));
    } catch (error) {
      notify(`解除绑定失败：${(error as Error).message}`);
    }
  };

  const loadRiskLogs = async (page = riskPage) => {
    setRiskLoading(true);
    try {
      const result = await getRiskControlLogs({
        cookie_id: riskAccount || undefined,
        processing_status: riskStatus || undefined,
        limit: PAGE_SIZE,
        offset: page * PAGE_SIZE,
      });
      setRiskLogs(result.data || []);
      setRiskTotal(result.total || 0);
    } catch (error) {
      notify(`加载风控日志失败：${(error as Error).message}`);
    } finally {
      setRiskLoading(false);
    }
  };

  useEffect(() => {
    if (activeTab === 'risk') void loadRiskLogs();
  }, [activeTab, riskAccount, riskStatus, riskPage]);

  const removeRiskLog = async (log: RiskControlLog) => {
    if (!await confirmAction('确认删除这条风控日志？')) return;
    try {
      const result = await deleteRiskControlLog(log.id);
      if (result.success === false) throw new Error(result.message || '删除失败');
      await loadRiskLogs();
    } catch (error) {
      notify(`删除风控日志失败：${(error as Error).message}`);
    }
  };

  const loadSystemLogs = async () => {
    if (!isAdmin) return;
    setSystemLoading(true);
    try {
      const result = await getSystemLogs({
        lines: 300,
        level: systemLevel || undefined,
        source: systemSource.trim() || undefined,
      });
      if (!result.success) throw new Error(result.message || '加载失败');
      setSystemLogs(result.logs || []);
    } catch (error) {
      notify(`加载系统日志失败：${(error as Error).message}`);
    } finally {
      setSystemLoading(false);
    }
  };

  useEffect(() => {
    if (activeTab === 'system' && isAdmin) void loadSystemLogs();
  }, [activeTab]);

  const riskPageCount = Math.max(1, Math.ceil(riskTotal / PAGE_SIZE));

  const tabs: Array<{ id: PageTab; label: string; icon: typeof BellRing }> = [
    { id: 'channels', label: '通知渠道', icon: BellRing },
    { id: 'bindings', label: '账号通知', icon: Link2 },
    { id: 'risk', label: '风控日志', icon: ShieldAlert },
    ...(isAdmin ? [{ id: 'system' as PageTab, label: '系统日志', icon: Activity }] : []),
  ];

  return (
    <div className="page-stack animate-fade-in">
      <PageHeader
        title="通知与日志"
        description="统一管理外部通知渠道、账号绑定、风控事件和系统运行日志。"
        icon={BellRing}
        actions={(
          <button
            type="button"
            onClick={() => void loadBaseData()}
            disabled={loadingBase}
            className="ios-btn-secondary flex items-center justify-center gap-2 rounded-md px-4 py-2.5 text-sm disabled:opacity-50"
          >
            <RefreshCw className={`h-4 w-4 ${loadingBase ? 'animate-spin' : ''}`} />
            刷新配置
          </button>
        )}
      />

      <PageTabs
        value={activeTab}
        onChange={setActiveTab}
        items={tabs}
        ariaLabel="通知与日志功能"
      />

      {activeTab === 'channels' && (
        <section className="section-panel">
          <SectionHeader
            title="通知渠道"
            description="密钥仅用于服务端发送通知，请避免在日志或截图中公开。"
            icon={BellRing}
            actions={(
              <button
                type="button"
                onClick={openCreateEditor}
                className="ios-btn-primary flex items-center gap-2 rounded-md px-4 py-2.5 text-sm"
              >
                <Plus className="h-4 w-4" />
                新建渠道
              </button>
            )}
          />
          <div className="divide-y divide-gray-100 px-4">
            {channels.map((channel) => (
              <div key={channel.id} className="flex flex-col gap-3 py-4 sm:flex-row sm:items-center">
                <button
                  type="button"
                  role="switch"
                  aria-checked={channel.enabled}
                  onClick={() => void toggleChannel(channel)}
                  className={`relative h-6 w-11 shrink-0 rounded-full transition-colors ${channel.enabled ? 'bg-[#ffe100]' : 'bg-gray-300'}`}
                  title={channel.enabled ? '停用渠道' : '启用渠道'}
                >
                  <span className={`absolute left-1 top-1 h-4 w-4 rounded-full bg-white transition-transform ${channel.enabled ? 'translate-x-5' : ''}`} />
                </button>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-bold text-gray-900">{channel.name}</span>
                    <span className="rounded bg-gray-100 px-2 py-0.5 text-xs font-bold text-gray-600">
                      {CHANNEL_DEFINITIONS[channel.type]?.label || channel.type}
                    </span>
                  </div>
                  <p className="mt-1 text-xs text-gray-500">
                    {channel.enabled ? '可用于账号通知' : '已停用'}
                    {channel.updated_at ? ` · 更新于 ${formatTime(channel.updated_at)}` : ''}
                  </p>
                </div>
                <div className="flex gap-2">
                  <button
                    type="button"
                    onClick={() => openEditEditor(channel)}
                    title="编辑渠道"
                    className="flex h-9 w-9 items-center justify-center rounded-md bg-gray-100 text-gray-700 hover:bg-gray-200"
                  >
                    <Edit3 className="h-4 w-4" />
                  </button>
                  <button
                    type="button"
                    onClick={() => void removeChannel(channel)}
                    title="删除渠道"
                    className="flex h-9 w-9 items-center justify-center rounded-md bg-red-50 text-red-600 hover:bg-red-100"
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                </div>
              </div>
            ))}
            {!loadingBase && channels.length === 0 && (
              <EmptyState compact title="暂无通知渠道" description="新建渠道后可绑定到指定闲鱼账号。" icon={BellRing} />
            )}
          </div>
        </section>
      )}

      {activeTab === 'bindings' && (
        <section className="section-panel">
          <SectionHeader
            title="账号通知绑定"
            description="将闲鱼账号的订单、风控和运行事件发送到指定通知渠道。"
            icon={Link2}
          />
          <div className="grid gap-3 border-b border-gray-200 bg-gray-50/60 p-4 md:grid-cols-[1fr_1fr_auto]">
            <select
              value={bindingAccount}
              onChange={(event) => setBindingAccount(event.target.value)}
              className="ios-input rounded-md px-3 py-2.5 text-sm"
            >
              <option value="">选择账号</option>
              {accounts.map((account) => (
                <option key={account.id} value={account.id}>{accountLabel(account)}</option>
              ))}
            </select>
            <select
              value={bindingChannel}
              onChange={(event) => setBindingChannel(event.target.value)}
              className="ios-input rounded-md px-3 py-2.5 text-sm"
            >
              <option value="">选择已启用渠道</option>
              {channels.filter((channel) => channel.enabled).map((channel) => (
                <option key={channel.id} value={channel.id}>{channel.name}</option>
              ))}
            </select>
            <button
              type="button"
              onClick={() => void addBinding()}
              disabled={savingBinding}
              className="ios-btn-primary flex items-center justify-center gap-2 rounded-md px-4 py-2.5 text-sm disabled:opacity-50"
            >
              {savingBinding ? <Loader2 className="h-4 w-4 animate-spin" /> : <Link2 className="h-4 w-4" />}
              添加绑定
            </button>
          </div>
          <div className="divide-y divide-gray-100 px-4">
            {bindings.map((binding) => {
              const account = accounts.find((item) => item.id === binding.cookie_id);
              return (
                <div key={binding.id} className="flex flex-col gap-3 py-4 sm:flex-row sm:items-center">
                  <button
                    type="button"
                    role="switch"
                    aria-checked={binding.enabled}
                    onClick={() => void toggleBinding(binding)}
                    className={`relative h-6 w-11 shrink-0 rounded-full transition-colors ${binding.enabled ? 'bg-[#ffe100]' : 'bg-gray-300'}`}
                  >
                    <span className={`absolute left-1 top-1 h-4 w-4 rounded-full bg-white transition-transform ${binding.enabled ? 'translate-x-5' : ''}`} />
                  </button>
                  <div className="min-w-0 flex-1">
                    <p className="font-bold text-gray-900">{account ? accountLabel(account) : binding.cookie_id}</p>
                    <p className="mt-1 text-xs text-gray-500">
                      {binding.channel_name} · {binding.enabled ? '接收通知' : '暂停通知'}
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={() => void removeBinding(binding)}
                    title="解除绑定"
                    className="flex h-9 w-9 items-center justify-center rounded-md bg-red-50 text-red-600 hover:bg-red-100"
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                </div>
              );
            })}
            {!loadingBase && bindings.length === 0 && (
              <EmptyState compact title="暂无账号通知绑定" description="先创建并启用通知渠道，再将账号绑定到渠道。" icon={Link2} />
            )}
          </div>
        </section>
      )}

      {activeTab === 'risk' && (
        <section className="section-panel">
          <SectionHeader
            title="发货风控日志"
            description="查看发货前拦截、关单、补偿和异常处理结果。"
            icon={ShieldAlert}
          />
          <div className="toolbar rounded-none border-x-0 border-t-0 shadow-none">
            <div className="toolbar__group">
            <select
              value={riskAccount}
              onChange={(event) => {
                setRiskAccount(event.target.value);
                setRiskPage(0);
              }}
              className="ios-input rounded-md px-3 py-2.5 text-sm sm:min-w-56"
            >
              <option value="">全部账号</option>
              {accounts.map((account) => (
                <option key={account.id} value={account.id}>{accountLabel(account)}</option>
              ))}
            </select>
            <select
              value={riskStatus}
              onChange={(event) => {
                setRiskStatus(event.target.value);
                setRiskPage(0);
              }}
              className="ios-input rounded-md px-3 py-2.5 text-sm sm:min-w-40"
            >
              <option value="">全部状态</option>
              <option value="processing">处理中</option>
              <option value="success">成功</option>
              <option value="failed">失败</option>
            </select>
            <button
              type="button"
              onClick={() => void loadRiskLogs()}
              disabled={riskLoading}
              className="ios-btn-secondary flex items-center justify-center gap-2 rounded-md px-4 py-2.5 text-sm"
            >
              <RefreshCw className={`h-4 w-4 ${riskLoading ? 'animate-spin' : ''}`} />
              刷新
            </button>
            </div>
          </div>
          <div className="divide-y divide-gray-100 px-4">
            {riskLogs.map((log) => (
              <div key={log.id} className="grid gap-3 py-4 lg:grid-cols-[180px_120px_minmax(0,1fr)_44px] lg:items-start">
                <div>
                  <p className="break-all text-sm font-bold text-gray-900">{log.cookie_id}</p>
                  <p className="mt-1 text-xs text-gray-500">{formatTime(log.created_at)}</p>
                </div>
                <div>
                  <span className={`inline-flex rounded px-2 py-1 text-xs font-bold ${
                    log.processing_status === 'success'
                      ? 'bg-emerald-50 text-emerald-700'
                      : log.processing_status === 'failed'
                        ? 'bg-red-50 text-red-700'
                        : 'bg-amber-50 text-amber-700'
                  }`}>
                    {log.processing_status === 'success' ? '成功' : log.processing_status === 'failed' ? '失败' : '处理中'}
                  </span>
                  <p className="mt-2 text-xs text-gray-500">{log.event_type}</p>
                </div>
                <div className="min-w-0 text-sm leading-6 text-gray-700">
                  <p>{log.event_description || log.processing_result || '无详细描述'}</p>
                  {log.processing_result && log.event_description && (
                    <p className="mt-1 text-xs text-gray-500">{log.processing_result}</p>
                  )}
                  {log.error_message && (
                    <p className="mt-1 break-words text-xs text-red-600">{log.error_message}</p>
                  )}
                </div>
                <button
                  type="button"
                  onClick={() => void removeRiskLog(log)}
                  title="删除日志"
                  className="flex h-9 w-9 items-center justify-center rounded-md bg-red-50 text-red-600 hover:bg-red-100"
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              </div>
            ))}
            {!riskLoading && riskLogs.length === 0 && (
              <EmptyState compact title="没有符合条件的风控日志" description="调整账号或状态筛选条件后重新查询。" icon={ShieldAlert} />
            )}
          </div>
          <div className="flex items-center justify-between border-t border-gray-200 px-4 py-3">
            <p className="text-xs text-gray-500">共 {riskTotal} 条</p>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => setRiskPage((page) => Math.max(0, page - 1))}
                disabled={riskPage === 0}
                title="上一页"
                className="flex h-9 w-9 items-center justify-center rounded-md bg-gray-100 disabled:opacity-40"
              >
                <ChevronLeft className="h-4 w-4" />
              </button>
              <span className="min-w-20 text-center text-sm font-bold">{riskPage + 1} / {riskPageCount}</span>
              <button
                type="button"
                onClick={() => setRiskPage((page) => Math.min(riskPageCount - 1, page + 1))}
                disabled={riskPage + 1 >= riskPageCount}
                title="下一页"
                className="flex h-9 w-9 items-center justify-center rounded-md bg-gray-100 disabled:opacity-40"
              >
                <ChevronRight className="h-4 w-4" />
              </button>
            </div>
          </div>
        </section>
      )}

      {activeTab === 'system' && isAdmin && (
        <section className="section-panel">
          <SectionHeader
            title="系统运行日志"
            description="最多读取最近 300 行，可按级别和来源快速定位运行异常。"
            icon={Activity}
          />
          <div className="grid gap-3 border-b border-gray-200 bg-gray-50/60 p-4 sm:grid-cols-[160px_1fr_auto]">
            <select
              value={systemLevel}
              onChange={(event) => setSystemLevel(event.target.value)}
              className="ios-input rounded-md px-3 py-2.5 text-sm"
            >
              <option value="">全部级别</option>
              <option value="DEBUG">DEBUG</option>
              <option value="INFO">INFO</option>
              <option value="WARNING">WARNING</option>
              <option value="ERROR">ERROR</option>
            </select>
            <input
              value={systemSource}
              onChange={(event) => setSystemSource(event.target.value)}
              placeholder="按日志来源筛选"
              className="ios-input rounded-md px-3 py-2.5 text-sm"
            />
            <button
              type="button"
              onClick={() => void loadSystemLogs()}
              disabled={systemLoading}
              className="ios-btn-secondary flex items-center justify-center gap-2 rounded-md px-4 py-2.5 text-sm"
            >
              <RefreshCw className={`h-4 w-4 ${systemLoading ? 'animate-spin' : ''}`} />
              查询
            </button>
          </div>
          <div className="max-h-[620px] divide-y divide-gray-100 overflow-y-auto px-4 font-mono text-xs">
            {[...systemLogs].reverse().map((log, index) => (
              <div key={`${log.timestamp}-${index}`} className="grid gap-2 py-3 lg:grid-cols-[165px_80px_180px_minmax(0,1fr)]">
                <span className="text-gray-500">{formatTime(log.timestamp)}</span>
                <span className={`font-bold ${
                  log.level === 'ERROR' ? 'text-red-600' : log.level === 'WARNING' ? 'text-amber-700' : 'text-gray-700'
                }`}>{log.level}</span>
                <span className="truncate text-gray-500" title={log.source}>{log.source}</span>
                <span className="break-words text-gray-800">{log.message}</span>
              </div>
            ))}
            {!systemLoading && systemLogs.length === 0 && (
              <EmptyState compact title="暂无系统日志" description="当前筛选条件没有返回运行记录。" icon={Activity} />
            )}
          </div>
        </section>
      )}

      {editorOpen && (
        <div className="modal-overlay">
          <div className="modal-container max-w-xl">
            <div className="modal-header flex items-start justify-between gap-4">
              <div>
                <h3 className="text-lg font-bold text-gray-900">{editingChannel ? '编辑通知渠道' : '新建通知渠道'}</h3>
                <p className="mt-1 text-sm text-gray-500">配置服务端发送通知所需的连接信息。</p>
              </div>
              <button
                type="button"
                onClick={() => setEditorOpen(false)}
                title="关闭"
                className="flex h-9 w-9 items-center justify-center rounded-md hover:bg-gray-100"
              >
                <X className="h-5 w-5" />
              </button>
            </div>
            <div className="modal-body space-y-4">
              <label className="block text-sm font-bold text-gray-700">
                渠道名称
                <input
                  value={channelName}
                  onChange={(event) => setChannelName(event.target.value)}
                  placeholder="例如：订单告警群"
                  className="ios-input mt-2 w-full rounded-md px-3 py-2.5 font-normal"
                />
              </label>
              <label className="block text-sm font-bold text-gray-700">
                渠道类型
                <select
                  value={channelType}
                  disabled={Boolean(editingChannel)}
                  onChange={(event) => changeChannelType(event.target.value as NotificationChannelType)}
                  className="ios-input mt-2 w-full rounded-md px-3 py-2.5 font-normal disabled:bg-gray-100"
                >
                  {Object.entries(CHANNEL_DEFINITIONS).map(([type, definition]) => (
                    <option key={type} value={type}>{definition.label}</option>
                  ))}
                </select>
              </label>
              {CHANNEL_DEFINITIONS[channelType].fields.map((field) => (
                <label key={field.key} className="block text-sm font-bold text-gray-700">
                  {field.label}{field.optional ? '（可选）' : ''}
                  {field.type === 'textarea' ? (
                    <textarea
                      value={String(channelConfig[field.key] ?? '')}
                      onChange={(event) => setChannelConfig({ ...channelConfig, [field.key]: event.target.value })}
                      placeholder={field.placeholder}
                      rows={4}
                      className="ios-input mt-2 w-full resize-y rounded-md px-3 py-2.5 font-mono text-sm font-normal"
                    />
                  ) : field.type === 'select' ? (
                    <select
                      value={String(channelConfig[field.key] ?? '')}
                      onChange={(event) => setChannelConfig({ ...channelConfig, [field.key]: event.target.value })}
                      className="ios-input mt-2 w-full rounded-md px-3 py-2.5 font-normal"
                    >
                      {field.options?.map((option) => <option key={option}>{option}</option>)}
                    </select>
                  ) : (
                    <input
                      type={field.type || 'text'}
                      value={String(channelConfig[field.key] ?? '')}
                      onChange={(event) => setChannelConfig({
                        ...channelConfig,
                        [field.key]: field.type === 'number' ? Number(event.target.value) : event.target.value,
                      })}
                      placeholder={field.placeholder}
                      className="ios-input mt-2 w-full rounded-md px-3 py-2.5 font-normal"
                    />
                  )}
                </label>
              ))}
            </div>
            <div className="modal-footer flex justify-end gap-3">
              <button
                type="button"
                onClick={() => setEditorOpen(false)}
                className="ios-btn-secondary rounded-md px-4 py-2.5 text-sm"
              >
                取消
              </button>
              <button
                type="button"
                onClick={() => void saveChannel()}
                disabled={savingChannel}
                className="ios-btn-primary flex items-center gap-2 rounded-md px-4 py-2.5 text-sm disabled:opacity-50"
              >
                {savingChannel ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                保存
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default NotificationsAndLogs;
