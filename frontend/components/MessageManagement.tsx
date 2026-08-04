import React, { useEffect, useMemo, useState } from 'react';
import {
  ChevronLeft,
  ChevronRight,
  Filter,
  Loader2,
  MessageSquareText,
  Plus,
  RefreshCw,
  Search,
  Trash2,
} from 'lucide-react';

import {
  AccountDetail,
  AutoReplyLog,
  MessageFilter,
  MessageFilterType,
} from '../types';
import {
  batchCreateMessageFilters,
  batchDeleteMessageFilters,
  deleteMessageFilter,
  getAccountDetails,
  getAutoReplyLogs,
  getMessageFilters,
  toggleMessageFilter,
} from '../services/api';

type PageTab = 'filters' | 'logs';

const PAGE_SIZE = 20;

const formatTime = (value?: string) => {
  if (!value) return '-';
  const date = new Date(value.includes('T') ? value : value.replace(' ', 'T'));
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN');
};

const accountLabel = (account: AccountDetail) =>
  account.nickname || account.remark || account.id;

const filterTypeLabel: Record<MessageFilterType, string> = {
  skip_reply: '跳过自动回复',
  skip_notify: '跳过外部通知',
};

const strategyLabel: Record<string, string> = {
  keyword: '关键词',
  ai: 'AI',
  default: '默认回复',
  api: '接口回复',
  none: '未回复',
};

const reasonLabel: Record<string, string> = {
  reply_selected: '已选择回复',
  reply_sent: '回复已发送',
  skip_reply_filter: '命中过滤规则',
  auto_reply_disabled: '自动回复已关闭',
  chat_paused: '会话已暂停',
  empty_reply: '回复内容为空',
  no_rule_matched: '未匹配规则',
  send_failed: '发送失败',
  failed: '处理失败',
};

const MessageManagement: React.FC = () => {
  const [activeTab, setActiveTab] = useState<PageTab>('filters');
  const [accounts, setAccounts] = useState<AccountDetail[]>([]);
  const [filters, setFilters] = useState<MessageFilter[]>([]);
  const [filtersLoading, setFiltersLoading] = useState(true);
  const [filterAccount, setFilterAccount] = useState('');
  const [filterType, setFilterType] = useState<MessageFilterType | ''>('');
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [newAccount, setNewAccount] = useState('');
  const [newType, setNewType] = useState<MessageFilterType>('skip_reply');
  const [newKeywords, setNewKeywords] = useState('');
  const [saving, setSaving] = useState(false);

  const [logs, setLogs] = useState<AutoReplyLog[]>([]);
  const [logsLoading, setLogsLoading] = useState(false);
  const [logAccount, setLogAccount] = useState('');
  const [logStatus, setLogStatus] = useState('');
  const [logStrategy, setLogStrategy] = useState('');
  const [logKeyword, setLogKeyword] = useState('');
  const [logPage, setLogPage] = useState(1);
  const [logTotal, setLogTotal] = useState(0);
  const [logPages, setLogPages] = useState(1);

  const selectedAll = useMemo(
    () => filters.length > 0 && filters.every((item) => selectedIds.includes(item.id)),
    [filters, selectedIds]
  );

  const loadFilters = async () => {
    setFiltersLoading(true);
    try {
      const data = await getMessageFilters({
        cookie_id: filterAccount || undefined,
        filter_type: filterType || undefined,
      });
      setFilters(data);
      setSelectedIds((ids) => ids.filter((id) => data.some((item) => item.id === id)));
    } catch (error) {
      alert(`加载过滤规则失败：${(error as Error).message}`);
    } finally {
      setFiltersLoading(false);
    }
  };

  const loadLogs = async (page = logPage) => {
    setLogsLoading(true);
    try {
      const result = await getAutoReplyLogs({
        cookie_id: logAccount || undefined,
        process_status: logStatus || undefined,
        reply_strategy: logStrategy || undefined,
        keyword: logKeyword.trim() || undefined,
        page,
        page_size: PAGE_SIZE,
      });
      setLogs(result.data || []);
      setLogPage(result.page);
      setLogTotal(result.total);
      setLogPages(result.total_pages || 1);
    } catch (error) {
      alert(`加载回复日志失败：${(error as Error).message}`);
    } finally {
      setLogsLoading(false);
    }
  };

  useEffect(() => {
    const initialize = async () => {
      try {
        const accountData = await getAccountDetails();
        setAccounts(accountData);
        if (accountData.length > 0) setNewAccount(accountData[0].id);
      } catch (error) {
        alert(`加载账号失败：${(error as Error).message}`);
      }
      await loadFilters();
    };
    void initialize();
  }, []);

  useEffect(() => {
    if (activeTab === 'logs' && logs.length === 0) void loadLogs(1);
  }, [activeTab]);

  const createFilters = async () => {
    const keywords = newKeywords
      .split(/\r?\n/)
      .map((item) => item.trim())
      .filter(Boolean);
    if (!newAccount || keywords.length === 0) {
      alert('请选择账号并填写至少一个关键词');
      return;
    }
    setSaving(true);
    try {
      const result = await batchCreateMessageFilters({
        cookie_id: newAccount,
        keywords,
        filter_type: newType,
      });
      setNewKeywords('');
      await loadFilters();
      alert(`已新增 ${result.created} 条，跳过重复 ${result.skipped} 条`);
    } catch (error) {
      alert(`新增过滤规则失败：${(error as Error).message}`);
    } finally {
      setSaving(false);
    }
  };

  const removeFilter = async (filter: MessageFilter) => {
    if (!confirm(`删除过滤关键词“${filter.keyword}”？`)) return;
    try {
      await deleteMessageFilter(filter.id);
      await loadFilters();
    } catch (error) {
      alert(`删除失败：${(error as Error).message}`);
    }
  };

  const removeSelected = async () => {
    if (selectedIds.length === 0 || !confirm(`删除选中的 ${selectedIds.length} 条规则？`)) return;
    try {
      await batchDeleteMessageFilters(selectedIds);
      setSelectedIds([]);
      await loadFilters();
    } catch (error) {
      alert(`批量删除失败：${(error as Error).message}`);
    }
  };

  const toggleFilter = async (filter: MessageFilter) => {
    try {
      const updated = await toggleMessageFilter(filter.id);
      setFilters((items) => items.map((item) => item.id === updated.id ? updated : item));
    } catch (error) {
      alert(`更新规则失败：${(error as Error).message}`);
    }
  };

  return (
    <div className="animate-fade-in">
      <div className="mb-6">
        <h2 className="text-2xl font-extrabold text-gray-900">消息管理</h2>
        <p className="mt-1 text-sm text-gray-500">过滤无需处理的消息，并追踪每次自动回复的决策和发送结果。</p>
      </div>

      <div className="mb-5 flex gap-1 overflow-x-auto border-b border-gray-200">
        {[
          { id: 'filters' as const, label: '消息过滤', icon: Filter },
          { id: 'logs' as const, label: '回复日志', icon: MessageSquareText },
        ].map((tab) => {
          const Icon = tab.icon;
          return (
            <button
              key={tab.id}
              type="button"
              onClick={() => setActiveTab(tab.id)}
              className={`flex shrink-0 items-center gap-2 border-b-2 px-4 py-3 text-sm font-bold ${
                activeTab === tab.id
                  ? 'border-yellow-400 text-gray-950'
                  : 'border-transparent text-gray-500 hover:text-gray-800'
              }`}
            >
              <Icon className="h-4 w-4" />
              {tab.label}
            </button>
          );
        })}
      </div>

      {activeTab === 'filters' && (
        <section>
          <div className="mb-5 grid gap-3 border-y border-gray-200 py-4 lg:grid-cols-[220px_180px_minmax(240px,1fr)_auto]">
            <select
              value={newAccount}
              onChange={(event) => setNewAccount(event.target.value)}
              className="rounded-lg border border-gray-200 bg-white px-3 py-2.5 text-sm font-medium"
            >
              <option value="">选择账号</option>
              {accounts.map((account) => (
                <option key={account.id} value={account.id}>{accountLabel(account)}</option>
              ))}
            </select>
            <select
              value={newType}
              onChange={(event) => setNewType(event.target.value as MessageFilterType)}
              className="rounded-lg border border-gray-200 bg-white px-3 py-2.5 text-sm font-medium"
            >
              <option value="skip_reply">跳过自动回复</option>
              <option value="skip_notify">跳过外部通知</option>
            </select>
            <textarea
              value={newKeywords}
              onChange={(event) => setNewKeywords(event.target.value)}
              rows={2}
              placeholder={'每行一个关键词，例如：\n系统通知'}
              className="min-h-20 resize-y rounded-lg border border-gray-200 px-3 py-2.5 text-sm"
            />
            <button
              type="button"
              onClick={() => void createFilters()}
              disabled={saving}
              className="flex min-h-11 items-center justify-center gap-2 rounded-lg bg-gray-900 px-4 py-2.5 text-sm font-bold text-white disabled:opacity-50"
            >
              {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
              批量添加
            </button>
          </div>

          <div className="flex flex-col gap-3 pb-3 sm:flex-row sm:items-center">
            <select
              value={filterAccount}
              onChange={(event) => setFilterAccount(event.target.value)}
              className="rounded-lg border border-gray-200 bg-white px-3 py-2.5 text-sm font-medium sm:min-w-52"
            >
              <option value="">全部账号</option>
              {accounts.map((account) => (
                <option key={account.id} value={account.id}>{accountLabel(account)}</option>
              ))}
            </select>
            <select
              value={filterType}
              onChange={(event) => setFilterType(event.target.value as MessageFilterType | '')}
              className="rounded-lg border border-gray-200 bg-white px-3 py-2.5 text-sm font-medium sm:min-w-44"
            >
              <option value="">全部用途</option>
              <option value="skip_reply">跳过自动回复</option>
              <option value="skip_notify">跳过外部通知</option>
            </select>
            <button
              type="button"
              onClick={() => void loadFilters()}
              className="flex items-center justify-center gap-2 rounded-lg bg-gray-100 px-4 py-2.5 text-sm font-bold text-gray-700"
            >
              <RefreshCw className={`h-4 w-4 ${filtersLoading ? 'animate-spin' : ''}`} />
              查询
            </button>
            {selectedIds.length > 0 && (
              <button
                type="button"
                onClick={() => void removeSelected()}
                className="flex items-center justify-center gap-2 rounded-lg bg-red-50 px-4 py-2.5 text-sm font-bold text-red-600"
              >
                <Trash2 className="h-4 w-4" />
                删除所选
              </button>
            )}
          </div>

          <div className="divide-y divide-gray-100 border-y border-gray-200">
            {filters.length > 0 && (
              <label className="flex items-center gap-3 py-3 text-xs font-bold text-gray-500">
                <input
                  type="checkbox"
                  checked={selectedAll}
                  onChange={(event) => setSelectedIds(event.target.checked ? filters.map((item) => item.id) : [])}
                  className="h-4 w-4 accent-amber-500"
                />
                全选当前列表
              </label>
            )}
            {filters.map((filter) => (
              <div key={filter.id} className="grid gap-3 py-4 sm:grid-cols-[24px_52px_180px_minmax(0,1fr)_44px] sm:items-center">
                <input
                  type="checkbox"
                  checked={selectedIds.includes(filter.id)}
                  onChange={(event) => setSelectedIds((ids) =>
                    event.target.checked ? [...ids, filter.id] : ids.filter((id) => id !== filter.id)
                  )}
                  className="h-4 w-4 accent-amber-500"
                />
                <button
                  type="button"
                  role="switch"
                  aria-checked={filter.enabled}
                  onClick={() => void toggleFilter(filter)}
                  title={filter.enabled ? '停用规则' : '启用规则'}
                  className={`relative h-6 w-11 rounded-full transition-colors ${filter.enabled ? 'bg-amber-500' : 'bg-gray-300'}`}
                >
                  <span className={`absolute left-1 top-1 h-4 w-4 rounded-full bg-white transition-transform ${filter.enabled ? 'translate-x-5' : ''}`} />
                </button>
                <div>
                  <p className="break-all text-sm font-bold text-gray-900">{filter.cookie_id}</p>
                  <p className="mt-1 text-xs text-gray-500">{filterTypeLabel[filter.filter_type]}</p>
                </div>
                <div className="min-w-0">
                  <p className="break-words text-sm font-medium text-gray-800">{filter.keyword}</p>
                  <p className="mt-1 text-xs text-gray-400">{formatTime(filter.updated_at || filter.created_at)}</p>
                </div>
                <button
                  type="button"
                  onClick={() => void removeFilter(filter)}
                  title="删除规则"
                  className="flex h-9 w-9 items-center justify-center rounded-lg bg-red-50 text-red-600 hover:bg-red-100"
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              </div>
            ))}
            {!filtersLoading && filters.length === 0 && (
              <p className="py-12 text-center text-sm text-gray-500">暂无消息过滤规则</p>
            )}
          </div>
        </section>
      )}

      {activeTab === 'logs' && (
        <section>
          <div className="grid gap-3 border-y border-gray-200 py-4 md:grid-cols-2 xl:grid-cols-[200px_150px_150px_minmax(180px,1fr)_auto]">
            <select
              value={logAccount}
              onChange={(event) => setLogAccount(event.target.value)}
              className="rounded-lg border border-gray-200 bg-white px-3 py-2.5 text-sm font-medium"
            >
              <option value="">全部账号</option>
              {accounts.map((account) => (
                <option key={account.id} value={account.id}>{accountLabel(account)}</option>
              ))}
            </select>
            <select
              value={logStatus}
              onChange={(event) => setLogStatus(event.target.value)}
              className="rounded-lg border border-gray-200 bg-white px-3 py-2.5 text-sm font-medium"
            >
              <option value="">全部处理状态</option>
              <option value="success">已处理</option>
              <option value="skipped">已跳过</option>
              <option value="failed">失败</option>
            </select>
            <select
              value={logStrategy}
              onChange={(event) => setLogStrategy(event.target.value)}
              className="rounded-lg border border-gray-200 bg-white px-3 py-2.5 text-sm font-medium"
            >
              <option value="">全部回复策略</option>
              <option value="keyword">关键词</option>
              <option value="ai">AI</option>
              <option value="default">默认回复</option>
              <option value="api">接口回复</option>
              <option value="none">未回复</option>
            </select>
            <input
              value={logKeyword}
              onChange={(event) => setLogKeyword(event.target.value)}
              placeholder="搜索收到或发出的内容"
              className="rounded-lg border border-gray-200 px-3 py-2.5 text-sm"
            />
            <button
              type="button"
              onClick={() => void loadLogs(1)}
              className="flex items-center justify-center gap-2 rounded-lg bg-gray-900 px-4 py-2.5 text-sm font-bold text-white"
            >
              <Search className="h-4 w-4" />
              查询
            </button>
          </div>

          <div className="divide-y divide-gray-100">
            {logsLoading && logs.length === 0 && (
              <div className="flex justify-center py-14"><Loader2 className="h-6 w-6 animate-spin text-amber-500" /></div>
            )}
            {logs.map((log) => (
              <article key={log.id} className="grid gap-3 py-4 lg:grid-cols-[180px_130px_minmax(0,1fr)_minmax(0,1fr)]">
                <div>
                  <p className="break-all text-sm font-bold text-gray-900">{log.cookie_id}</p>
                  <p className="mt-1 text-xs text-gray-500">{formatTime(log.created_at)}</p>
                  <p className="mt-1 break-all text-xs text-gray-400">{log.sender_user_name || log.sender_user_id || '-'}</p>
                </div>
                <div>
                  <span className={`inline-flex rounded px-2 py-1 text-xs font-bold ${
                    log.process_status === 'success'
                      ? 'bg-emerald-50 text-emerald-700'
                      : log.process_status === 'failed'
                        ? 'bg-red-50 text-red-700'
                        : 'bg-amber-50 text-amber-700'
                  }`}>
                    {log.process_status === 'success' ? '已处理' : log.process_status === 'failed' ? '失败' : '已跳过'}
                  </span>
                  <p className="mt-2 text-xs font-bold text-gray-700">{strategyLabel[log.reply_strategy] || log.reply_strategy}</p>
                  <p className="mt-1 text-xs text-gray-500">{reasonLabel[log.decision_reason || ''] || log.decision_reason || '-'}</p>
                </div>
                <div className="min-w-0">
                  <p className="text-xs font-bold text-gray-500">收到消息</p>
                  <p className="mt-1 whitespace-pre-wrap break-words text-sm leading-6 text-gray-800">{log.source_message || '-'}</p>
                  {log.matched_keyword && <p className="mt-1 text-xs text-amber-700">命中：{log.matched_keyword}</p>}
                </div>
                <div className="min-w-0">
                  <div className="flex items-center justify-between gap-2">
                    <p className="text-xs font-bold text-gray-500">回复内容</p>
                    <span className={`text-xs font-bold ${
                      log.send_status === 'success' ? 'text-emerald-600' : log.send_status === 'failed' ? 'text-red-600' : 'text-gray-400'
                    }`}>
                      {log.send_status === 'success' ? '发送成功' : log.send_status === 'failed' ? '发送失败' : '未发送'}
                    </span>
                  </div>
                  <p className="mt-1 whitespace-pre-wrap break-words text-sm leading-6 text-gray-800">{log.reply_text || '-'}</p>
                  {log.error_message && <p className="mt-1 break-words text-xs text-red-600">{log.error_message}</p>}
                </div>
              </article>
            ))}
            {!logsLoading && logs.length === 0 && (
              <p className="py-12 text-center text-sm text-gray-500">暂无自动回复决策日志</p>
            )}
          </div>

          <div className="flex items-center justify-between border-t border-gray-200 pt-4">
            <p className="text-xs text-gray-500">共 {logTotal} 条</p>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => void loadLogs(Math.max(1, logPage - 1))}
                disabled={logPage <= 1 || logsLoading}
                title="上一页"
                className="flex h-9 w-9 items-center justify-center rounded-lg bg-gray-100 disabled:opacity-40"
              >
                <ChevronLeft className="h-4 w-4" />
              </button>
              <span className="min-w-20 text-center text-sm font-bold">{logPage} / {logPages}</span>
              <button
                type="button"
                onClick={() => void loadLogs(Math.min(logPages, logPage + 1))}
                disabled={logPage >= logPages || logsLoading}
                title="下一页"
                className="flex h-9 w-9 items-center justify-center rounded-lg bg-gray-100 disabled:opacity-40"
              >
                <ChevronRight className="h-4 w-4" />
              </button>
            </div>
          </div>
        </section>
      )}
    </div>
  );
};

export default MessageManagement;
