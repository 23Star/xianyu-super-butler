import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  ArrowLeft,
  Image,
  Inbox,
  Loader2,
  Package,
  Plus,
  RefreshCw,
  Search,
  Send,
  Settings2,
  Smile,
  Trash2,
  UserRound,
} from 'lucide-react';

import {
  AccountDetail,
  ChatAccount,
  ChatConversation,
  ChatMessage,
  Item,
  MessageFilter,
  MessageFilterType,
} from '../types';
import {
  batchCreateMessageFilters,
  batchDeleteMessageFilters,
  deleteMessageFilter,
  getAccountDetails,
  getChatAccounts,
  getChatConversations,
  getChatMessages,
  getItems,
  getMessageFilters,
  sendChatMessage,
  toggleMessageFilter,
} from '../services/api';
import { confirmAction, notify } from '../services/feedback';

type View = 'messages' | 'filters';

interface MessageManagementProps {
  isActive?: boolean;
}

const normalizeImageUrl = (value?: string) => {
  if (!value) return '';
  return value.startsWith('//') ? `https:${value}` : value;
};

const formatTimestamp = (value?: number) => {
  if (!value) return '';
  const timestamp = value < 1_000_000_000_000 ? value * 1000 : value;
  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) return '';
  const now = new Date();
  if (date.toDateString() === now.toDateString()) {
    return date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
  }
  return date.toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' });
};

const formatDateTime = (value?: string) => {
  if (!value) return '-';
  const date = new Date(value.includes('T') ? value : value.replace(' ', 'T'));
  return Number.isNaN(date.getTime())
    ? value
    : date.toLocaleString('zh-CN', {
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
      });
};

const accountName = (account?: ChatAccount) =>
  account?.displayName || account?.accountId || '未选择账号';

const filterTypeLabel: Record<MessageFilterType, string> = {
  skip_reply: '跳过自动回复',
  skip_notify: '跳过外部通知',
};

const MessageManagement: React.FC<MessageManagementProps> = ({ isActive = true }) => {
  const [view, setView] = useState<View>('messages');
  const [accounts, setAccounts] = useState<ChatAccount[]>([]);
  const [accountDetails, setAccountDetails] = useState<AccountDetail[]>([]);
  const [items, setItems] = useState<Item[]>([]);
  const [activeAccountId, setActiveAccountId] = useState('');
  const [conversations, setConversations] = useState<ChatConversation[]>([]);
  const [activeCid, setActiveCid] = useState('');
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [query, setQuery] = useState('');
  const [accountsLoading, setAccountsLoading] = useState(true);
  const [conversationsLoading, setConversationsLoading] = useState(false);
  const [messagesLoading, setMessagesLoading] = useState(false);
  const [draft, setDraft] = useState('');
  const [sending, setSending] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const [filters, setFilters] = useState<MessageFilter[]>([]);
  const [filtersLoading, setFiltersLoading] = useState(true);
  const [filterAccount, setFilterAccount] = useState('');
  const [filterType, setFilterType] = useState<MessageFilterType | ''>('');
  const [newAccount, setNewAccount] = useState('');
  const [newType, setNewType] = useState<MessageFilterType>('skip_reply');
  const [newKeywords, setNewKeywords] = useState('');
  const [selectedFilterIds, setSelectedFilterIds] = useState<number[]>([]);
  const [savingFilters, setSavingFilters] = useState(false);

  const activeAccount = accounts.find((account) => account.accountId === activeAccountId);
  const activeConversation = conversations.find((conversation) => conversation.cid === activeCid);

  const itemMap = useMemo(
    () => new Map(items.map((item) => [`${item.cookie_id}:${item.item_id}`, item])),
    [items]
  );

  const activeItem = activeConversation?.itemId
    ? itemMap.get(`${activeAccountId}:${activeConversation.itemId}`)
    : undefined;

  const visibleConversations = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase();
    if (!normalized) return conversations;
    return conversations.filter((conversation) =>
      [
        conversation.otherUserName,
        conversation.otherUserId,
        conversation.itemTitle,
        conversation.itemId,
        conversation.lastMessageSummary,
      ].some((value) => String(value || '').toLocaleLowerCase().includes(normalized))
    );
  }, [conversations, query]);

  const selectedAllFilters = filters.length > 0
    && filters.every((filter) => selectedFilterIds.includes(filter.id));

  const loadAccounts = async () => {
    setAccountsLoading(true);
    try {
      const data = await getChatAccounts();
      setAccounts(data);
      setActiveAccountId((current) => {
        if (current && data.some((account) => account.accountId === current)) return current;
        return data.find((account) => account.connected)?.accountId || data[0]?.accountId || '';
      });
    } catch (error) {
      notify(`加载消息账号失败：${(error as Error).message}`, 'error');
    } finally {
      setAccountsLoading(false);
    }
  };

  const loadConversations = async (silent = false) => {
    if (!activeAccountId) {
      setConversations([]);
      return;
    }
    if (!silent) setConversationsLoading(true);
    try {
      const result = await getChatConversations(activeAccountId);
      setConversations(result.conversations || []);
      setActiveCid((current) => {
        if (current && result.conversations.some((conversation) => conversation.cid === current)) {
          return current;
        }
        return result.conversations[0]?.cid || '';
      });
    } catch (error) {
      if (!silent) notify(`加载会话失败：${(error as Error).message}`, 'error');
    } finally {
      if (!silent) setConversationsLoading(false);
    }
  };

  const loadMessages = async (silent = false) => {
    if (!activeAccountId || !activeCid) {
      setMessages([]);
      return;
    }
    if (!silent) setMessagesLoading(true);
    try {
      const result = await getChatMessages(activeAccountId, activeCid);
      setMessages(result.messages || []);
    } catch (error) {
      if (!silent) notify(`加载聊天记录失败：${(error as Error).message}`, 'error');
    } finally {
      if (!silent) setMessagesLoading(false);
    }
  };

  const loadFilters = async () => {
    setFiltersLoading(true);
    try {
      const data = await getMessageFilters({
        cookie_id: filterAccount || undefined,
        filter_type: filterType || undefined,
      });
      setFilters(data);
      setSelectedFilterIds((current) =>
        current.filter((id) => data.some((filter) => filter.id === id))
      );
    } catch (error) {
      notify(`加载过滤规则失败：${(error as Error).message}`, 'error');
    } finally {
      setFiltersLoading(false);
    }
  };

  useEffect(() => {
    const initialize = async () => {
      const detailsRequest = getAccountDetails()
        .then((data) => {
          setAccountDetails(data);
          setNewAccount(data[0]?.id || '');
        })
        .catch((error) => notify(`加载账号资料失败：${(error as Error).message}`, 'error'));
      const itemsRequest = getItems()
        .then(setItems)
        .catch((error) => notify(`加载商品资料失败：${(error as Error).message}`, 'error'));
      await Promise.all([loadAccounts(), detailsRequest, itemsRequest, loadFilters()]);
    };
    void initialize();
  }, []);

  useEffect(() => {
    setActiveCid('');
    setMessages([]);
    if (isActive) void loadConversations();
  }, [isActive, activeAccountId]);

  useEffect(() => {
    if (isActive) void loadMessages();
  }, [isActive, activeAccountId, activeCid]);

  useEffect(() => {
    if (!isActive || view !== 'messages' || !activeAccountId) return undefined;
    void loadConversations(true);
    const timer = window.setInterval(() => void loadConversations(true), 3000);
    return () => window.clearInterval(timer);
  }, [isActive, view, activeAccountId]);

  useEffect(() => {
    if (!isActive || view !== 'messages' || !activeAccountId || !activeCid) return undefined;
    void loadMessages(true);
    const timer = window.setInterval(() => void loadMessages(true), 3000);
    return () => window.clearInterval(timer);
  }, [isActive, view, activeAccountId, activeCid]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const sendMessage = async () => {
    const text = draft.trim();
    if (!text || !activeConversation || !activeAccountId || sending) return;
    setSending(true);
    try {
      await sendChatMessage(activeAccountId, {
        cid: activeConversation.cid,
        to_user_id: activeConversation.otherUserId,
        text,
      });
      setDraft('');
      await Promise.all([loadMessages(true), loadConversations(true)]);
      notify('消息已发送', 'success');
    } catch (error) {
      notify(`发送失败：${(error as Error).message}`, 'error');
    } finally {
      setSending(false);
    }
  };

  const createFilters = async () => {
    const keywords = newKeywords.split(/\r?\n/).map((value) => value.trim()).filter(Boolean);
    if (!newAccount || keywords.length === 0) {
      notify('请选择账号并填写至少一个关键词', 'warning');
      return;
    }
    setSavingFilters(true);
    try {
      const result = await batchCreateMessageFilters({
        cookie_id: newAccount,
        filter_type: newType,
        keywords,
      });
      setNewKeywords('');
      await loadFilters();
      notify(`新增 ${result.created} 条，跳过重复 ${result.skipped} 条`, 'success');
    } catch (error) {
      notify(`新增规则失败：${(error as Error).message}`, 'error');
    } finally {
      setSavingFilters(false);
    }
  };

  const removeFilter = async (filter: MessageFilter) => {
    if (!await confirmAction(`删除过滤关键词“${filter.keyword}”？`)) return;
    try {
      await deleteMessageFilter(filter.id);
      await loadFilters();
      notify('规则已删除', 'success');
    } catch (error) {
      notify(`删除失败：${(error as Error).message}`, 'error');
    }
  };

  const removeSelectedFilters = async () => {
    if (
      selectedFilterIds.length === 0
      || !await confirmAction(`删除选中的 ${selectedFilterIds.length} 条规则？`)
    ) return;
    try {
      await batchDeleteMessageFilters(selectedFilterIds);
      setSelectedFilterIds([]);
      await loadFilters();
      notify('所选规则已删除', 'success');
    } catch (error) {
      notify(`批量删除失败：${(error as Error).message}`, 'error');
    }
  };

  const renderAvatar = (url: string | undefined, label: string, className: string) => {
    const normalized = normalizeImageUrl(url);
    return normalized ? (
      <img src={normalized} alt="" className={`${className} object-cover`} />
    ) : (
      <div className={`${className} flex items-center justify-center bg-[#252525] text-sm font-bold text-white`}>
        {label.trim().slice(0, 1) || <UserRound className="h-4 w-4" />}
      </div>
    );
  };

  const renderMessages = () => (
    <div className="grid h-full min-h-0 overflow-hidden bg-white lg:grid-cols-[356px_minmax(0,1fr)]">
      <aside className="flex min-h-0 flex-col border-b border-[#e9e9e9] lg:border-b-0 lg:border-r">
        <div className="flex h-[68px] shrink-0 items-center gap-3 border-b border-[#eeeeee] px-4">
          <select
            value={activeAccountId}
            onChange={(event) => setActiveAccountId(event.target.value)}
            aria-label="消息账号"
            className="h-10 min-w-0 flex-1 rounded-md border border-[#dedede] bg-white px-3 text-sm font-bold outline-none focus:border-[#e6c600]"
          >
            {accounts.length === 0 && <option value="">暂无账号</option>}
            {accounts.map((account) => (
              <option key={account.accountId} value={account.accountId}>
                {account.connected ? '在线' : '离线'} · {accountName(account)}
              </option>
            ))}
          </select>
          <button
            type="button"
            onClick={() => void Promise.all([loadAccounts(), loadConversations()])}
            title="刷新账号和会话"
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full hover:bg-[#f3f3f3]"
          >
            <RefreshCw className={`h-4 w-4 ${
              accountsLoading || conversationsLoading ? 'animate-spin' : ''
            }`} />
          </button>
          <button
            type="button"
            onClick={() => setView('filters')}
            title="消息过滤规则"
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full hover:bg-[#f3f3f3]"
          >
            <Settings2 className="h-4 w-4" />
          </button>
        </div>

        <div className="border-b border-[#eeeeee] p-3">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[#aaa]" />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="搜索联系人、商品或消息"
              className="h-9 w-full rounded-md bg-[#f4f4f4] pl-9 pr-3 text-sm outline-none focus:ring-2 focus:ring-[#ffe100]"
            />
          </div>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto">
          {conversationsLoading && conversations.length === 0 && (
            <div className="flex justify-center py-16">
              <Loader2 className="h-6 w-6 animate-spin text-[#d6b600]" />
            </div>
          )}
          {visibleConversations.map((conversation) => {
            const selected = conversation.cid === activeCid;
            const title = conversation.otherUserName || `闲鱼用户 ${conversation.otherUserId}`;
            return (
              <button
                key={conversation.cid}
                type="button"
                onClick={() => setActiveCid(conversation.cid)}
                className={`grid w-full grid-cols-[48px_minmax(0,1fr)_auto] gap-3 px-4 py-3 text-left ${
                  selected ? 'bg-[#f0f0f0]' : 'hover:bg-[#f7f7f7]'
                }`}
              >
                {renderAvatar(conversation.otherUserAvatar, title, 'h-12 w-12 rounded-full')}
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <p className="truncate text-sm font-bold text-[#222]">{title}</p>
                    {conversation.unreadCount > 0 && (
                      <span className="min-w-5 rounded-full bg-[#ff4d4f] px-1.5 text-center text-[10px] leading-5 text-white">
                        {conversation.unreadCount > 99 ? '99+' : conversation.unreadCount}
                      </span>
                    )}
                  </div>
                  <p className="mt-1 truncate text-xs text-[#777]">
                    {conversation.lastMessageSummary || '暂无消息'}
                  </p>
                  <p className="mt-1 truncate text-[10px] text-[#aaa]">
                    {conversation.itemTitle || (conversation.itemId ? `商品 ${conversation.itemId}` : '普通会话')}
                  </p>
                </div>
                <span className="pt-0.5 text-[10px] text-[#aaa]">
                  {formatTimestamp(conversation.lastMessageTime)}
                </span>
              </button>
            );
          })}
          {!conversationsLoading && visibleConversations.length === 0 && (
            <div className="px-6 py-20 text-center">
              <Inbox className="mx-auto h-9 w-9 text-[#d0d0d0]" />
              <p className="mt-3 text-sm text-[#777]">
                {activeAccount?.connected ? '暂无会话' : '账号离线，无法读取会话'}
              </p>
            </div>
          )}
        </div>
      </aside>

      <section className="flex min-h-0 min-w-0 flex-col">
        {activeConversation ? (
          <>
            <header className="flex h-[68px] shrink-0 items-center justify-between border-b border-[#eeeeee] px-5">
              <div className="min-w-0">
                <h3 className="truncate text-base font-bold text-[#222]">
                  {activeConversation.otherUserName || `闲鱼用户 ${activeConversation.otherUserId}`}
                </h3>
                <p className="mt-0.5 truncate text-xs text-[#999]">
                  {activeConversation.otherUserId}
                </p>
              </div>
              <span className={`inline-flex items-center gap-1.5 text-xs font-bold ${
                activeAccount?.connected ? 'text-emerald-600' : 'text-[#999]'
              }`}>
                <span className={`h-2 w-2 rounded-full ${
                  activeAccount?.connected ? 'bg-emerald-500' : 'bg-[#bbb]'
                }`} />
                {activeAccount?.connected ? '账号在线' : '账号离线'}
              </span>
            </header>

            <div className="flex min-h-[92px] shrink-0 items-center gap-4 border-b border-[#eeeeee] px-5 py-3">
              {normalizeImageUrl(activeConversation.itemImage || activeItem?.item_image) ? (
                <img
                  src={normalizeImageUrl(activeConversation.itemImage || activeItem?.item_image)}
                  alt=""
                  className="h-16 w-16 shrink-0 rounded-md object-cover"
                />
              ) : (
                <div className="flex h-16 w-16 shrink-0 items-center justify-center rounded-md bg-[#f2f2f2] text-[#aaa]">
                  <Package className="h-5 w-5" />
                </div>
              )}
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-bold text-[#222]">
                  {activeConversation.itemTitle || activeItem?.item_title || '未关联商品'}
                </p>
                {activeItem?.item_price && (
                  <p className="mt-1 text-base font-extrabold text-[#ff3b30]">
                    <span className="text-xs">¥</span>
                    {String(activeItem.item_price).replace(/^[¥￥]\s*/, '')}
                  </p>
                )}
                <p className="mt-1 truncate text-xs text-[#999]">
                  {activeConversation.itemId ? `商品 ID ${activeConversation.itemId}` : '普通会话'}
                </p>
              </div>
              <span className="hidden rounded-md bg-[#ffe100] px-4 py-2 text-xs font-bold text-[#222] sm:inline-flex">
                {accountName(activeAccount)}
              </span>
            </div>

            <div className="min-h-0 flex-1 overflow-y-auto bg-[#f7f7f7] px-4 py-6 sm:px-8">
              {messagesLoading && messages.length === 0 ? (
                <div className="flex h-full items-center justify-center">
                  <Loader2 className="h-6 w-6 animate-spin text-[#d6b600]" />
                </div>
              ) : (
                <div className="mx-auto max-w-4xl space-y-4">
                  {messages.map((message, index) => {
                    const previous = messages[index - 1];
                    const showTime = !previous || Math.abs(message.time - previous.time) > 300_000;
                    const senderLabel = message.isSelf
                      ? accountName(activeAccount)
                      : activeConversation.otherUserName || activeConversation.otherUserId;
                    return (
                      <div key={message.messageId || `${message.time}-${index}`}>
                        {showTime && (
                          <p className="mb-3 text-center text-[11px] text-[#aaa]">
                            {formatTimestamp(message.time)}
                          </p>
                        )}
                        <div className={`flex items-start gap-2.5 ${message.isSelf ? 'justify-end' : ''}`}>
                          {!message.isSelf && renderAvatar(
                            activeConversation.otherUserAvatar,
                            senderLabel,
                            'h-9 w-9 shrink-0 rounded-full'
                          )}
                          <div className={`max-w-[76%] rounded-md px-3.5 py-2.5 text-sm leading-6 ${
                            message.isSelf ? 'bg-[#ffe100] text-[#222]' : 'bg-white text-[#333]'
                          }`}>
                            {message.images.map((url) => (
                              <img
                                key={url}
                                src={normalizeImageUrl(url)}
                                alt="聊天图片"
                                className="mb-2 max-h-80 max-w-full rounded object-contain last:mb-0"
                              />
                            ))}
                            {message.text && (
                              <p className="whitespace-pre-wrap break-words">{message.text}</p>
                            )}
                          </div>
                          {message.isSelf && renderAvatar(
                            activeAccount?.avatarUrl,
                            senderLabel,
                            'h-9 w-9 shrink-0 rounded-full'
                          )}
                        </div>
                      </div>
                    );
                  })}
                  {messages.length === 0 && !messagesLoading && (
                    <p className="py-16 text-center text-sm text-[#999]">暂无聊天记录</p>
                  )}
                  <div ref={messagesEndRef} />
                </div>
              )}
            </div>

            <footer className="shrink-0 border-t border-[#eeeeee] bg-white px-5 py-3">
              <div className="mb-2 flex items-center gap-4 text-[#555]">
                <button type="button" title="表情（暂未开放）" className="hover:text-[#111]">
                  <Smile className="h-5 w-5" />
                </button>
                <button type="button" title="图片（暂未开放）" className="hover:text-[#111]">
                  <Image className="h-5 w-5" />
                </button>
              </div>
              <div className="flex items-end gap-3">
                <textarea
                  value={draft}
                  onChange={(event) => setDraft(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter' && !event.shiftKey) {
                      event.preventDefault();
                      void sendMessage();
                    }
                  }}
                  rows={3}
                  placeholder={activeAccount?.connected ? '输入消息' : '账号离线，暂时无法发送'}
                  disabled={!activeAccount?.connected}
                  className="min-h-[72px] min-w-0 flex-1 resize-none border-0 px-0 py-1 text-sm leading-6 outline-none placeholder:text-[#aaa] disabled:bg-white"
                />
                <button
                  type="button"
                  onClick={() => void sendMessage()}
                  disabled={!draft.trim() || sending || !activeAccount?.connected}
                  className="flex h-9 items-center gap-2 rounded-md bg-[#ffe100] px-5 text-sm font-bold text-[#222] hover:bg-[#f4d900] disabled:cursor-not-allowed disabled:bg-[#f2f2f2] disabled:text-[#aaa]"
                >
                  {sending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
                  发送
                </button>
              </div>
            </footer>
          </>
        ) : (
          <div className="flex flex-1 flex-col items-center justify-center px-6 text-center">
            <Inbox className="h-12 w-12 text-[#d0d0d0]" />
            <p className="mt-4 text-sm font-bold text-[#666]">选择一条会话查看消息</p>
            <p className="mt-1 text-xs text-[#aaa]">会话和聊天记录直接来自当前闲鱼账号</p>
          </div>
        )}
      </section>
    </div>
  );

  const renderFilters = () => (
    <div className="h-full overflow-y-auto bg-[#f4f5f7] p-4 sm:p-6 lg:p-8">
      <section className="mx-auto max-w-[1400px] overflow-hidden border border-[#e5e5e5] bg-white">
        <header className="flex min-h-14 items-center justify-between gap-3 bg-[#ffe100] px-5 py-3">
          <div>
            <h3 className="text-base font-extrabold text-[#222]">消息过滤规则</h3>
            <p className="mt-0.5 text-xs text-[#665b00]">命中关键词后跳过自动回复或外部通知</p>
          </div>
          <button
            type="button"
            onClick={() => setView('messages')}
            className="flex items-center gap-2 rounded-md bg-white/80 px-4 py-2 text-xs font-bold text-[#222] hover:bg-white"
          >
            <ArrowLeft className="h-4 w-4" />
            返回消息
          </button>
        </header>

        <div className="p-4 sm:p-5">
          <div className="grid gap-3 border-b border-[#eeeeee] pb-5 lg:grid-cols-[220px_180px_minmax(240px,1fr)_auto]">
            <select
              value={newAccount}
              onChange={(event) => setNewAccount(event.target.value)}
              className="rounded-md border border-[#dedede] bg-white px-3 py-2.5 text-sm"
            >
              <option value="">选择账号</option>
              {accountDetails.map((account) => (
                <option key={account.id} value={account.id}>
                  {account.nickname || account.remark || account.id}
                </option>
              ))}
            </select>
            <select
              value={newType}
              onChange={(event) => setNewType(event.target.value as MessageFilterType)}
              className="rounded-md border border-[#dedede] bg-white px-3 py-2.5 text-sm"
            >
              <option value="skip_reply">跳过自动回复</option>
              <option value="skip_notify">跳过外部通知</option>
            </select>
            <textarea
              value={newKeywords}
              onChange={(event) => setNewKeywords(event.target.value)}
              rows={2}
              placeholder={'每行一个关键词，例如：\n系统通知'}
              className="min-h-20 resize-y rounded-md border border-[#dedede] px-3 py-2.5 text-sm"
            />
            <button
              type="button"
              onClick={() => void createFilters()}
              disabled={savingFilters}
              className="flex min-h-11 items-center justify-center gap-2 rounded-md bg-[#222] px-4 py-2.5 text-sm font-bold text-white disabled:opacity-50"
            >
              {savingFilters ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
              批量添加
            </button>
          </div>

          <div className="flex flex-col gap-3 py-4 sm:flex-row sm:items-center">
            <select
              value={filterAccount}
              onChange={(event) => setFilterAccount(event.target.value)}
              className="rounded-md border border-[#dedede] bg-white px-3 py-2.5 text-sm sm:min-w-52"
            >
              <option value="">全部账号</option>
              {accountDetails.map((account) => (
                <option key={account.id} value={account.id}>
                  {account.nickname || account.remark || account.id}
                </option>
              ))}
            </select>
            <select
              value={filterType}
              onChange={(event) => setFilterType(event.target.value as MessageFilterType | '')}
              className="rounded-md border border-[#dedede] bg-white px-3 py-2.5 text-sm sm:min-w-44"
            >
              <option value="">全部用途</option>
              <option value="skip_reply">跳过自动回复</option>
              <option value="skip_notify">跳过外部通知</option>
            </select>
            <button
              type="button"
              onClick={() => void loadFilters()}
              className="flex items-center justify-center gap-2 rounded-md bg-[#f1f1f1] px-4 py-2.5 text-sm font-bold text-[#444]"
            >
              <RefreshCw className={`h-4 w-4 ${filtersLoading ? 'animate-spin' : ''}`} />
              查询
            </button>
            {selectedFilterIds.length > 0 && (
              <button
                type="button"
                onClick={() => void removeSelectedFilters()}
                className="flex items-center justify-center gap-2 rounded-md bg-red-50 px-4 py-2.5 text-sm font-bold text-red-600"
              >
                <Trash2 className="h-4 w-4" />
                删除所选
              </button>
            )}
          </div>

          <div className="divide-y divide-[#eeeeee] border-y border-[#eeeeee]">
            {filters.length > 0 && (
              <label className="flex items-center gap-3 py-3 text-xs font-bold text-[#777]">
                <input
                  type="checkbox"
                  checked={selectedAllFilters}
                  onChange={(event) =>
                    setSelectedFilterIds(event.target.checked ? filters.map((filter) => filter.id) : [])
                  }
                  className="h-4 w-4 accent-[#f5c400]"
                />
                全选当前列表
              </label>
            )}
            {filters.map((filter) => (
              <div
                key={filter.id}
                className="grid gap-3 py-4 sm:grid-cols-[24px_52px_180px_minmax(0,1fr)_44px] sm:items-center"
              >
                <input
                  type="checkbox"
                  checked={selectedFilterIds.includes(filter.id)}
                  onChange={(event) =>
                    setSelectedFilterIds((current) =>
                      event.target.checked
                        ? [...current, filter.id]
                        : current.filter((id) => id !== filter.id)
                    )
                  }
                  className="h-4 w-4 accent-[#f5c400]"
                />
                <button
                  type="button"
                  role="switch"
                  aria-checked={filter.enabled}
                  onClick={() => void toggleMessageFilter(filter.id).then(loadFilters)}
                  title={filter.enabled ? '停用规则' : '启用规则'}
                  className={`relative h-6 w-11 rounded-full transition-colors ${
                    filter.enabled ? 'bg-[#f5c400]' : 'bg-gray-300'
                  }`}
                >
                  <span className={`absolute left-1 top-1 h-4 w-4 rounded-full bg-white transition-transform ${
                    filter.enabled ? 'translate-x-5' : ''
                  }`} />
                </button>
                <div>
                  <p className="break-all text-sm font-bold text-[#222]">{filter.cookie_id}</p>
                  <p className="mt-1 text-xs text-[#888]">{filterTypeLabel[filter.filter_type]}</p>
                </div>
                <div className="min-w-0">
                  <p className="break-words text-sm font-medium text-[#333]">{filter.keyword}</p>
                  <p className="mt-1 text-xs text-[#aaa]">
                    {formatDateTime(filter.updated_at || filter.created_at)}
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => void removeFilter(filter)}
                  title="删除规则"
                  className="flex h-9 w-9 items-center justify-center rounded-md bg-red-50 text-red-600 hover:bg-red-100"
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              </div>
            ))}
            {!filtersLoading && filters.length === 0 && (
              <p className="py-12 text-center text-sm text-[#888]">暂无消息过滤规则</p>
            )}
          </div>
        </div>
      </section>
    </div>
  );

  return view === 'messages' ? renderMessages() : renderFilters();
};

export default MessageManagement;
