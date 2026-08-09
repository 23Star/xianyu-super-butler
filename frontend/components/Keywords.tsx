import React, { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import { AccountDetail, ShippingRule, ReplyRule, DefaultReply } from '../types';
import { getAccountDetails, getReplyRules, updateReplyRule, deleteReplyRule, getShippingRules, updateShippingRule, deleteShippingRule, getCards, getDefaultReplies, getDefaultReply, updateDefaultReply, deleteDefaultReply, clearDefaultReplyRecords } from '../services/api';
import { Plus, Trash2, MessageSquare, X, Save, Key, Truck, Power, PowerOff, Edit2, RefreshCw, Sparkles, Bot } from 'lucide-react';
import { confirmAction, notify } from '../services/feedback';
import { EmptyState, PageHeader, PageLoading, PageTabs, SectionHeader } from './ui';

type ReplyTabType = 'reply' | 'default';
type KeywordsMode = 'reply' | 'delivery';

interface KeywordsProps {
  mode: KeywordsMode;
}

interface Keyword {
  id: string;
  keyword: string;
  reply_content: string;
  match_type: 'exact' | 'fuzzy';
  enabled: boolean;
}

interface DeliveryRuleForm {
  keyword: string;
  cookie_id: string;
  card_id: string;
  description: string;
  enabled: boolean;
}

interface DefaultReplyForm {
  cookie_id: string;
  enabled: boolean;
  reply_content: string;
  reply_once: boolean;
  reply_image_url: string;
}

const Keywords: React.FC<KeywordsProps> = ({ mode }) => {
  const [accounts, setAccounts] = useState<AccountDetail[]>([]);
  const [selectedAccount, setSelectedAccount] = useState<string>('');
  const [activeTab, setActiveTab] = useState<ReplyTabType>('reply');

  // 关键词回复相关状态
  const [keywords, setKeywords] = useState<Keyword[]>([]);
  const [showReplyModal, setShowReplyModal] = useState(false);
  const [editingKeyword, setEditingKeyword] = useState<Keyword | null>(null);
  const [replyForm, setReplyForm] = useState({
    keyword: '',
    reply_content: ''
  });

  // 关键词发货相关状态
  const [shippingRules, setShippingRules] = useState<ShippingRule[]>([]);
  const [cards, setCards] = useState<any[]>([]);
  const [showDeliveryModal, setShowDeliveryModal] = useState(false);
  const [editingDeliveryRule, setEditingDeliveryRule] = useState<ShippingRule | null>(null);
  const [deliveryForm, setDeliveryForm] = useState<DeliveryRuleForm>({
    keyword: '',
    cookie_id: '',
    card_id: '',
    description: '',
    enabled: true
  });

  // 账号默认回复相关状态
  const [defaultReplies, setDefaultReplies] = useState<Record<string, DefaultReply>>({});
  const [showDefaultModal, setShowDefaultModal] = useState(false);
  const [editingDefaultReply, setEditingDefaultReply] = useState<DefaultReply | null>(null);
  const [defaultForm, setDefaultForm] = useState<DefaultReplyForm>({
    cookie_id: '',
    enabled: false,
    reply_content: '',
    reply_once: false,
    reply_image_url: ''
  });

  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (mode === 'delivery') {
      loadShippingRules();
      loadCards();
      getAccountDetails().then(setAccounts);
      return;
    }

    getAccountDetails().then((data) => {
      setAccounts(data);
      // 默认选择第一个账号
      if (data && data.length > 0) {
        setSelectedAccount((current) => current || data[0].id);
      }
    });
  }, [mode]);

  useEffect(() => {
    if (mode === 'reply' && selectedAccount) {
      loadKeywords();
      loadDefaultReplies();
    }
  }, [mode, selectedAccount]);

  const loadDefaultReplies = async () => {
    try {
      const data = await getDefaultReplies();
      setDefaultReplies(data);
    } catch (e) {
      console.error('加载默认回复失败', e);
    }
  };

  const loadShippingRules = async () => {
    try {
      const data = await getShippingRules();
      setShippingRules(data.filter(rule => !rule.item_id));
    } catch (e) {
      console.error('加载发货规则失败', e);
    }
  };

  const loadCards = async () => {
    try {
      const data = await getCards();
      setCards(data);
    } catch (e) {
      console.error('加载卡券失败', e);
    }
  };

  const loadKeywords = async () => {
    if (!selectedAccount) return;
    setLoading(true);
    try {
      const data = await getReplyRules(selectedAccount);
      setKeywords(data as Keyword[]);
    } catch (e) {
      console.error('加载关键词失败', e);
    } finally {
      setLoading(false);
    }
  };

  const handleAdd = () => {
    if (mode === 'delivery') {
      setEditingDeliveryRule(null);
      setDeliveryForm({ keyword: '', cookie_id: '', card_id: '', description: '', enabled: true });
      setShowDeliveryModal(true);
    } else if (activeTab === 'reply') {
      setEditingKeyword(null);
      setReplyForm({ keyword: '', reply_content: '' });
      setShowReplyModal(true);
    } else {
      // default tab - 编辑选中账号的默认回复
      if (!selectedAccount) return;
      loadDefaultReplyForEdit(selectedAccount);
    }
  };

  const loadDefaultReplyForEdit = async (cookieId: string) => {
    try {
      const data = await getDefaultReply(cookieId);
      setEditingDefaultReply(data);
      setDefaultForm({
        cookie_id: cookieId,
        enabled: data.enabled,
        reply_content: data.reply_content,
        reply_once: data.reply_once,
        reply_image_url: data.reply_image_url || ''
      });
      setShowDefaultModal(true);
    } catch (e) {
      console.error('加载默认回复失败', e);
      // 如果没有设置，创建新的
      setEditingDefaultReply(null);
      setDefaultForm({
        cookie_id: cookieId,
        enabled: false,
        reply_content: '',
        reply_once: false,
        reply_image_url: ''
      });
      setShowDefaultModal(true);
    }
  };

  const handleEdit = (keyword: Keyword) => {
    if (activeTab === 'reply') {
      setEditingKeyword(keyword);
      setReplyForm({
        keyword: keyword.keyword,
        reply_content: keyword.reply_content
      });
      setShowReplyModal(true);
    }
  };

  const handleEditDelivery = (rule: ShippingRule) => {
    setEditingDeliveryRule(rule);
    setDeliveryForm({
      keyword: rule.item_keyword,
      cookie_id: rule.cookie_id || '',
      card_id: String(rule.card_group_id),
      description: rule.name,
      enabled: rule.enabled
    });
    setShowDeliveryModal(true);
  };

  const handleSave = async () => {
    if (!selectedAccount) {
      notify('请先选择账号');
      return;
    }
    if (!replyForm.keyword.trim() || !replyForm.reply_content.trim()) {
      notify('请填写关键词和回复内容');
      return;
    }

    try {
      await updateReplyRule(
        {
          id: editingKeyword?.id,
          keyword: replyForm.keyword,
          reply_content: replyForm.reply_content,
          match_type: 'exact',
          enabled: true
        },
        selectedAccount
      );
      setShowReplyModal(false);
      loadKeywords();
      notify('保存成功！');
    } catch (e) {
      notify('保存失败：' + (e as Error).message);
    }
  };

  const handleSaveDelivery = async () => {
    if (!deliveryForm.keyword.trim()) {
      notify('请填写触发关键词');
      return;
    }
    if (!deliveryForm.card_id) {
      notify('请选择卡券');
      return;
    }

    try {
      await updateShippingRule({
        id: editingDeliveryRule?.id,
        item_keyword: deliveryForm.keyword,
        cookie_id: deliveryForm.cookie_id || undefined,
        item_id: undefined,
        card_group_id: parseInt(deliveryForm.card_id),
        name: deliveryForm.description,
        priority: 1,
        enabled: deliveryForm.enabled
      });
      setShowDeliveryModal(false);
      loadShippingRules();
      notify('保存成功！');
    } catch (e) {
      notify('保存失败：' + (e as Error).message);
    }
  };

  const handleDelete = async (id: string) => {
    if (!selectedAccount || !await confirmAction('确认删除该关键词吗？')) return;
    try {
      await deleteReplyRule(id, selectedAccount);
      loadKeywords();
      notify('删除成功！');
    } catch (e) {
      notify('删除失败：' + (e as Error).message);
    }
  };

  const handleDeleteDelivery = async (id: string) => {
    if (!await confirmAction('确认删除该发货规则吗？')) return;
    try {
      await deleteShippingRule(id);
      loadShippingRules();
      notify('删除成功！');
    } catch (e) {
      notify('删除失败：' + (e as Error).message);
    }
  };

  const handleToggleDelivery = async (rule: ShippingRule) => {
    try {
      await updateShippingRule({
        id: rule.id,
        item_keyword: rule.item_keyword,
        cookie_id: rule.cookie_id,
        item_id: rule.item_id,
        card_group_id: rule.card_group_id,
        name: rule.name,
        priority: rule.priority,
        enabled: !rule.enabled
      });
      loadShippingRules();
    } catch (e) {
      notify('操作失败：' + (e as Error).message);
    }
  };

  const handleSaveDefault = async () => {
    if (!defaultForm.cookie_id) {
      notify('请先选择账号');
      return;
    }

    try {
      await updateDefaultReply(defaultForm.cookie_id, {
        enabled: defaultForm.enabled,
        reply_content: defaultForm.reply_content,
        reply_once: defaultForm.reply_once,
        reply_image_url: defaultForm.reply_image_url
      });
      setShowDefaultModal(false);
      loadDefaultReplies();
      notify('保存成功！');
    } catch (e) {
      notify('保存失败：' + (e as Error).message);
    }
  };

  const handleDeleteDefault = async (cookieId: string) => {
    if (!await confirmAction('确认删除该默认回复吗？')) return;
    try {
      await deleteDefaultReply(cookieId);
      loadDefaultReplies();
      notify('删除成功！');
    } catch (e) {
      notify('删除失败：' + (e as Error).message);
    }
  };

  const handleClearRecords = async (cookieId: string) => {
    if (!await confirmAction('确认清空该账号的回复记录吗？清空后可以重新对所有对话使用默认回复。')) return;
    try {
      await clearDefaultReplyRecords(cookieId);
      notify('清空成功！');
    } catch (e) {
      notify('清空失败：' + (e as Error).message);
    }
  };

  const enabledDefaultCount = (Object.values(defaultReplies) as DefaultReply[])
    .filter(reply => reply.enabled).length;

  const refreshCurrent = () => {
    if (mode === 'delivery') {
      void Promise.all([loadShippingRules(), loadCards()]);
    } else if (activeTab === 'reply') {
      void loadKeywords();
    } else {
      void loadDefaultReplies();
    }
  };

  const renderStatusSwitch = (enabled: boolean, onClick: () => void, label: string) => (
    <button
      type="button"
      role="switch"
      aria-checked={enabled}
      aria-label={label}
      onClick={onClick}
      className={`relative h-6 w-11 shrink-0 rounded-full transition-colors ${
        enabled ? 'bg-[#ffe100]' : 'bg-gray-300'
      }`}
    >
      <span className={`absolute left-1 top-1 h-4 w-4 rounded-full bg-white transition-transform ${
        enabled ? 'translate-x-5' : ''
      }`} />
    </button>
  );

  return (
    <div className="page-stack animate-fade-in">
      <PageHeader
        title={mode === 'reply' ? '自动回复' : '通用自动发货'}
        description={mode === 'reply'
          ? '管理账号关键词回复和未命中规则时的默认回复。'
          : '管理按账号或全部账号生效的关键词兜底发货规则。'}
        icon={mode === 'reply' ? MessageSquare : Truck}
      />

      {mode === 'reply' && (
        <PageTabs
          value={activeTab}
          onChange={setActiveTab}
          ariaLabel="自动回复功能"
          items={[
            { id: 'reply', label: '关键词回复', icon: Key, count: keywords.length },
            { id: 'default', label: '账号默认回复', icon: Bot, count: enabledDefaultCount },
          ]}
        />
      )}

      <div className="toolbar">
        <div className="toolbar__group">
          {mode === 'reply' ? (
            <>
              <label htmlFor="reply-account" className="text-xs font-bold text-gray-600">应用账号</label>
              <select
                id="reply-account"
                className="ios-input rounded-md px-3 py-2.5 text-sm sm:min-w-64"
                value={selectedAccount}
                onChange={(event) => setSelectedAccount(event.target.value)}
              >
                <option value="">请选择账号</option>
                {accounts.map((account) => (
                  <option key={account.id} value={account.id}>
                    {account.nickname || account.remark || account.id}
                  </option>
                ))}
              </select>
            </>
          ) : (
            <p className="text-sm text-gray-600">
              商品专属规则在“商品与发货”配置，此处仅处理关键词兜底。
            </p>
          )}
        </div>
        <div className="toolbar__group">
          <button
            type="button"
            onClick={refreshCurrent}
            className="ios-btn-secondary flex items-center justify-center gap-2 rounded-md px-4 py-2.5 text-sm"
          >
            <RefreshCw className="h-4 w-4" />
            刷新
          </button>
          <button
            type="button"
            onClick={handleAdd}
            disabled={mode === 'reply' && !selectedAccount}
            className="ios-btn-primary flex items-center justify-center gap-2 rounded-md px-4 py-2.5 text-sm"
          >
            <Plus className="h-4 w-4" />
            {mode === 'delivery' ? '添加通用规则' : activeTab === 'reply' ? '添加关键词' : '编辑默认回复'}
          </button>
        </div>
      </div>

      {mode === 'reply' && !selectedAccount ? (
        <EmptyState
          title="请选择闲鱼账号"
          description="选择账号后可查看和编辑该账号的自动回复配置。"
          icon={MessageSquare}
        />
      ) : mode === 'reply' && activeTab === 'reply' ? (
        loading ? (
          <PageLoading label="正在加载关键词回复" />
        ) : (
          <section className="section-panel">
            <SectionHeader
              title="关键词回复规则"
              description={`当前账号共 ${keywords.length} 条规则`}
              icon={Key}
            />
            <div className="divide-y divide-gray-100">
              {keywords.map((keyword) => (
                <article key={keyword.id} className="grid gap-3 px-4 py-4 sm:grid-cols-[minmax(160px,0.7fr)_minmax(0,1.5fr)_auto] sm:items-center">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <h3 className="break-words text-sm font-bold text-gray-900">{keyword.keyword}</h3>
                      <span className="status-badge status-badge-success">精确匹配</span>
                    </div>
                  </div>
                  <p className="min-w-0 whitespace-pre-wrap break-words text-sm leading-6 text-gray-600">
                    {keyword.reply_content || '未填写回复内容'}
                  </p>
                  <div className="flex justify-end gap-2">
                    <button
                      type="button"
                      onClick={() => handleEdit(keyword)}
                      className="flex h-9 w-9 items-center justify-center rounded-md bg-gray-100 text-gray-700 hover:bg-gray-200"
                      title="编辑关键词"
                    >
                      <Edit2 className="h-4 w-4" />
                    </button>
                    <button
                      type="button"
                      onClick={() => void handleDelete(keyword.id)}
                      className="flex h-9 w-9 items-center justify-center rounded-md bg-red-50 text-red-600 hover:bg-red-100"
                      title="删除关键词"
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </div>
                </article>
              ))}
              {keywords.length === 0 && (
                <EmptyState compact title="暂无关键词回复" description="添加规则后，命中关键词的买家消息将使用指定内容回复。" icon={MessageSquare} />
              )}
            </div>
          </section>
        )
      ) : mode === 'delivery' ? (
        <section className="section-panel">
          <SectionHeader
            title="关键词兜底发货"
            description={`共 ${shippingRules.length} 条通用规则`}
            icon={Truck}
          />
          <div className="divide-y divide-gray-100">
            {shippingRules.map((rule) => (
              <article key={rule.id} className="grid gap-3 px-4 py-4 lg:grid-cols-[minmax(180px,0.7fr)_minmax(0,1.4fr)_auto] lg:items-center">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <h3 className="break-words text-sm font-bold text-gray-900">{rule.item_keyword}</h3>
                    <span className={`status-badge ${rule.enabled ? 'status-badge-success' : 'bg-gray-100 text-gray-600'}`}>
                      {rule.enabled ? '已启用' : '已停用'}
                    </span>
                  </div>
                  <p className="mt-1 text-xs text-gray-500">{rule.cookie_id ? '指定账号' : '全部账号'}</p>
                </div>
                <div className="min-w-0 text-sm text-gray-600">
                  <p className="truncate">发货内容：{rule.card_group_name || `卡密 ${rule.card_group_id}`}</p>
                  {rule.cookie_id && (
                    <p className="mt-1 truncate text-xs text-gray-500">
                      账号：{accounts.find(account => account.id === rule.cookie_id)?.nickname || rule.cookie_id}
                    </p>
                  )}
                  {rule.name && <p className="mt-1 break-words text-xs text-gray-500">{rule.name}</p>}
                </div>
                <div className="flex justify-end gap-2">
                  <button
                    type="button"
                    onClick={() => void handleToggleDelivery(rule)}
                    className="flex h-9 w-9 items-center justify-center rounded-md bg-gray-100 text-gray-700 hover:bg-gray-200"
                    title={rule.enabled ? '停用规则' : '启用规则'}
                  >
                    {rule.enabled ? <PowerOff className="h-4 w-4" /> : <Power className="h-4 w-4" />}
                  </button>
                  <button
                    type="button"
                    onClick={() => handleEditDelivery(rule)}
                    className="flex h-9 w-9 items-center justify-center rounded-md bg-gray-100 text-gray-700 hover:bg-gray-200"
                    title="编辑规则"
                  >
                    <Edit2 className="h-4 w-4" />
                  </button>
                  <button
                    type="button"
                    onClick={() => void handleDeleteDelivery(rule.id)}
                    className="flex h-9 w-9 items-center justify-center rounded-md bg-red-50 text-red-600 hover:bg-red-100"
                    title="删除规则"
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                </div>
              </article>
            ))}
            {shippingRules.length === 0 && (
              <EmptyState compact title="暂无通用发货规则" description="商品专属发货请在“商品与发货”中配置。" icon={Truck} />
            )}
          </div>
        </section>
      ) : (
        <section className="section-panel">
          <SectionHeader
            title="账号默认回复"
            description="关键词规则未命中时使用对应账号的默认内容。"
            icon={Bot}
          />
          <div className="divide-y divide-gray-100">
            {accounts.map((account) => {
              const defaultReply = defaultReplies[account.id];
              const enabled = Boolean(defaultReply?.enabled);
              return (
                <article key={account.id} className="grid gap-3 px-4 py-4 sm:grid-cols-[minmax(180px,0.7fr)_minmax(0,1.4fr)_auto] sm:items-center">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <h3 className="truncate text-sm font-bold text-gray-900">
                        {account.nickname || account.remark || account.id}
                      </h3>
                      <span className={`status-badge ${enabled ? 'status-badge-success' : 'bg-gray-100 text-gray-600'}`}>
                        {enabled ? '已启用' : '未启用'}
                      </span>
                      {defaultReply?.reply_once && <span className="status-badge status-badge-info">单会话一次</span>}
                    </div>
                    <p className="mt-1 break-all text-xs text-gray-500">{account.id}</p>
                  </div>
                  <p className="min-w-0 whitespace-pre-wrap break-words text-sm leading-6 text-gray-600">
                    {defaultReply?.reply_content || '未设置默认回复内容'}
                  </p>
                  <div className="flex justify-end gap-2">
                    <button
                      type="button"
                      onClick={() => void loadDefaultReplyForEdit(account.id)}
                      className="flex h-9 w-9 items-center justify-center rounded-md bg-gray-100 text-gray-700 hover:bg-gray-200"
                      title="编辑默认回复"
                    >
                      <Edit2 className="h-4 w-4" />
                    </button>
                    {enabled && (
                      <>
                        <button
                          type="button"
                          onClick={() => void handleClearRecords(account.id)}
                          className="flex h-9 w-9 items-center justify-center rounded-md bg-blue-50 text-blue-700 hover:bg-blue-100"
                          title="清空回复记录"
                        >
                          <RefreshCw className="h-4 w-4" />
                        </button>
                        <button
                          type="button"
                          onClick={() => void handleDeleteDefault(account.id)}
                          className="flex h-9 w-9 items-center justify-center rounded-md bg-red-50 text-red-600 hover:bg-red-100"
                          title="删除默认回复"
                        >
                          <Trash2 className="h-4 w-4" />
                        </button>
                      </>
                    )}
                  </div>
                </article>
              );
            })}
            {accounts.length === 0 && (
              <EmptyState compact title="暂无闲鱼账号" description="添加账号后可配置账号默认回复。" icon={Bot} />
            )}
          </div>
        </section>
      )}

      {mode === 'reply' && showReplyModal && createPortal(
        <div className="modal-overlay">
          <div className="modal-container">
            <div className="modal-header flex items-start justify-between gap-4">
              <div>
                <h3 className="text-lg font-bold text-gray-900">{editingKeyword ? '编辑关键词回复' : '添加关键词回复'}</h3>
                <p className="mt-1 text-sm text-gray-500">当前规则使用精确匹配。</p>
              </div>
              <button type="button" onClick={() => setShowReplyModal(false)} className="rounded-md p-2 hover:bg-gray-100" aria-label="关闭">
                <X className="h-5 w-5" />
              </button>
            </div>
            <div className="modal-body space-y-4">
              <label className="block">
                <span className="field-label">触发关键词</span>
                <input
                  value={replyForm.keyword}
                  onChange={(event) => setReplyForm({ ...replyForm, keyword: event.target.value })}
                  placeholder="例如：价格、包邮"
                  className="ios-input w-full rounded-md px-3 py-2.5"
                />
              </label>
              <label className="block">
                <span className="field-label">回复内容</span>
                <textarea
                  value={replyForm.reply_content}
                  onChange={(event) => setReplyForm({ ...replyForm, reply_content: event.target.value })}
                  placeholder="输入自动回复内容"
                  rows={7}
                  className="ios-input w-full resize-y rounded-md px-3 py-2.5"
                />
              </label>
            </div>
            <div className="modal-footer flex justify-end gap-2">
              <button type="button" onClick={() => setShowReplyModal(false)} className="ios-btn-secondary rounded-md px-4 py-2.5">取消</button>
              <button type="button" onClick={() => void handleSave()} className="ios-btn-primary flex items-center gap-2 rounded-md px-4 py-2.5">
                <Save className="h-4 w-4" />
                保存
              </button>
            </div>
          </div>
        </div>,
        document.body
      )}

      {mode === 'delivery' && showDeliveryModal && createPortal(
        <div className="modal-overlay">
          <div className="modal-container">
            <div className="modal-header flex items-start justify-between gap-4">
              <div>
                <h3 className="text-lg font-bold text-gray-900">{editingDeliveryRule ? '编辑通用发货规则' : '添加通用发货规则'}</h3>
                <p className="mt-1 text-sm text-gray-500">未指定账号时对全部闲鱼账号生效。</p>
              </div>
              <button type="button" onClick={() => setShowDeliveryModal(false)} className="rounded-md p-2 hover:bg-gray-100" aria-label="关闭">
                <X className="h-5 w-5" />
              </button>
            </div>
            <div className="modal-body grid gap-4 sm:grid-cols-2">
              <label className="block sm:col-span-2">
                <span className="field-label">适用账号</span>
                <select
                  value={deliveryForm.cookie_id}
                  onChange={(event) => setDeliveryForm({ ...deliveryForm, cookie_id: event.target.value })}
                  className="ios-input w-full rounded-md px-3 py-2.5"
                >
                  <option value="">全部账号</option>
                  {accounts.map(account => (
                    <option key={account.id} value={account.id}>{account.nickname || account.remark || account.id}</option>
                  ))}
                </select>
              </label>
              <label className="block sm:col-span-2">
                <span className="field-label">商品关键词</span>
                <input
                  value={deliveryForm.keyword}
                  onChange={(event) => setDeliveryForm({ ...deliveryForm, keyword: event.target.value })}
                  placeholder="例如：会员、周卡"
                  className="ios-input w-full rounded-md px-3 py-2.5"
                />
              </label>
              <label className="block">
                <span className="field-label">发货卡密或内容</span>
                <select
                  value={deliveryForm.card_id}
                  onChange={(event) => setDeliveryForm({ ...deliveryForm, card_id: event.target.value })}
                  className="ios-input w-full rounded-md px-3 py-2.5"
                >
                  <option value="">请选择</option>
                  {cards.map(card => (
                    <option key={card.id} value={card.id}>
                      {card.name || card.text_content?.substring(0, 30) || `卡券 ${card.id}`}
                    </option>
                  ))}
                </select>
              </label>
              <label className="block">
                <span className="field-label">规则备注</span>
                <input
                  value={deliveryForm.description}
                  onChange={(event) => setDeliveryForm({ ...deliveryForm, description: event.target.value })}
                  placeholder="便于识别此规则"
                  className="ios-input w-full rounded-md px-3 py-2.5"
                />
              </label>
              <div className="flex items-center justify-between rounded-md border border-gray-200 bg-gray-50 p-4 sm:col-span-2">
                <div>
                  <p className="text-sm font-bold text-gray-800">启用规则</p>
                  <p className="mt-1 text-xs text-gray-500">停用后保留配置但不参与匹配。</p>
                </div>
                {renderStatusSwitch(
                  deliveryForm.enabled,
                  () => setDeliveryForm({ ...deliveryForm, enabled: !deliveryForm.enabled }),
                  '启用通用发货规则'
                )}
              </div>
            </div>
            <div className="modal-footer flex justify-end gap-2">
              <button type="button" onClick={() => setShowDeliveryModal(false)} className="ios-btn-secondary rounded-md px-4 py-2.5">取消</button>
              <button type="button" onClick={() => void handleSaveDelivery()} className="ios-btn-primary flex items-center gap-2 rounded-md px-4 py-2.5">
                <Save className="h-4 w-4" />
                保存
              </button>
            </div>
          </div>
        </div>,
        document.body
      )}

      {mode === 'reply' && showDefaultModal && createPortal(
        <div className="modal-overlay">
          <div className="modal-container">
            <div className="modal-header flex items-start justify-between gap-4">
              <div>
                <h3 className="text-lg font-bold text-gray-900">账号默认回复</h3>
                <p className="mt-1 text-sm text-gray-500">关键词规则未命中时使用此内容。</p>
              </div>
              <button type="button" onClick={() => setShowDefaultModal(false)} className="rounded-md p-2 hover:bg-gray-100" aria-label="关闭">
                <X className="h-5 w-5" />
              </button>
            </div>
            <div className="modal-body space-y-4">
              <label className="block">
                <span className="field-label">应用账号</span>
                <select
                  value={defaultForm.cookie_id}
                  onChange={(event) => setDefaultForm({ ...defaultForm, cookie_id: event.target.value })}
                  className="ios-input w-full rounded-md px-3 py-2.5"
                >
                  <option value="">请选择账号</option>
                  {accounts.map(account => (
                    <option key={account.id} value={account.id}>{account.nickname || account.remark || account.id}</option>
                  ))}
                </select>
              </label>
              <div className="grid gap-3 sm:grid-cols-2">
                <div className="flex items-center justify-between rounded-md border border-gray-200 bg-gray-50 p-4">
                  <div>
                    <p className="text-sm font-bold text-gray-800">启用默认回复</p>
                    <p className="mt-1 text-xs text-gray-500">参与当前账号自动回复。</p>
                  </div>
                  {renderStatusSwitch(
                    defaultForm.enabled,
                    () => setDefaultForm({ ...defaultForm, enabled: !defaultForm.enabled }),
                    '启用默认回复'
                  )}
                </div>
                <div className="flex items-center justify-between rounded-md border border-gray-200 bg-gray-50 p-4">
                  <div>
                    <p className="text-sm font-bold text-gray-800">单会话一次</p>
                    <p className="mt-1 text-xs text-gray-500">每个对话仅触发一次。</p>
                  </div>
                  {renderStatusSwitch(
                    defaultForm.reply_once,
                    () => setDefaultForm({ ...defaultForm, reply_once: !defaultForm.reply_once }),
                    '每个会话只回复一次'
                  )}
                </div>
              </div>
              <label className="block">
                <span className="field-label">回复内容</span>
                <textarea
                  value={defaultForm.reply_content}
                  onChange={(event) => setDefaultForm({ ...defaultForm, reply_content: event.target.value })}
                  placeholder="输入默认回复内容"
                  rows={7}
                  className="ios-input w-full resize-y rounded-md px-3 py-2.5"
                />
              </label>
              <label className="block">
                <span className="field-label">回复图片 URL（可选）</span>
                <div className="relative">
                  <Sparkles className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
                  <input
                    value={defaultForm.reply_image_url}
                    onChange={(event) => setDefaultForm({ ...defaultForm, reply_image_url: event.target.value })}
                    placeholder="https://example.com/image.jpg"
                    className="ios-input w-full rounded-md py-2.5 pl-9 pr-3"
                  />
                </div>
              </label>
            </div>
            <div className="modal-footer flex justify-end gap-2">
              <button type="button" onClick={() => setShowDefaultModal(false)} className="ios-btn-secondary rounded-md px-4 py-2.5">取消</button>
              <button type="button" onClick={() => void handleSaveDefault()} className="ios-btn-primary flex items-center gap-2 rounded-md px-4 py-2.5">
                <Save className="h-4 w-4" />
                保存
              </button>
            </div>
          </div>
        </div>,
        document.body
      )}
    </div>
  );
};

export default Keywords;
