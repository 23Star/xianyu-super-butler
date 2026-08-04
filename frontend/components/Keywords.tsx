import React, { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import { AccountDetail, ShippingRule, ReplyRule, DefaultReply } from '../types';
import { getAccountDetails, getReplyRules, updateReplyRule, deleteReplyRule, getShippingRules, updateShippingRule, deleteShippingRule, getCards, getDefaultReplies, getDefaultReply, updateDefaultReply, deleteDefaultReply, clearDefaultReplyRecords } from '../services/api';
import { Plus, Trash2, MessageSquare, X, Save, Loader2, Key, Truck, Power, PowerOff, Edit2, RefreshCw, Sparkles, Bot } from 'lucide-react';
import DeliveryProtection from './DeliveryProtection';

type ReplyTabType = 'reply' | 'default';
type KeywordsMode = 'reply' | 'delivery';
type DeliveryTabType = 'keywords' | 'protection';

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
  const [deliveryTab, setDeliveryTab] = useState<DeliveryTabType>('keywords');

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
      setShippingRules(data);
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
      setDeliveryForm({ keyword: '', card_id: '', description: '', enabled: true });
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
      card_id: String(rule.card_group_id),
      description: rule.name,
      enabled: rule.enabled
    });
    setShowDeliveryModal(true);
  };

  const handleSave = async () => {
    if (!selectedAccount) {
      alert('请先选择账号');
      return;
    }
    if (!replyForm.keyword.trim() || !replyForm.reply_content.trim()) {
      alert('请填写关键词和回复内容');
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
      alert('保存成功！');
    } catch (e) {
      alert('保存失败：' + (e as Error).message);
    }
  };

  const handleSaveDelivery = async () => {
    if (!deliveryForm.keyword.trim()) {
      alert('请填写触发关键词');
      return;
    }
    if (!deliveryForm.card_id) {
      alert('请选择卡券');
      return;
    }

    try {
      await updateShippingRule({
        id: editingDeliveryRule?.id,
        item_keyword: deliveryForm.keyword,
        card_group_id: parseInt(deliveryForm.card_id),
        name: deliveryForm.description,
        priority: 1,
        enabled: deliveryForm.enabled
      });
      setShowDeliveryModal(false);
      loadShippingRules();
      alert('保存成功！');
    } catch (e) {
      alert('保存失败：' + (e as Error).message);
    }
  };

  const handleDelete = async (id: string) => {
    if (!selectedAccount || !confirm('确认删除该关键词吗？')) return;
    try {
      await deleteReplyRule(id, selectedAccount);
      loadKeywords();
      alert('删除成功！');
    } catch (e) {
      alert('删除失败：' + (e as Error).message);
    }
  };

  const handleDeleteDelivery = async (id: string) => {
    if (!confirm('确认删除该发货规则吗？')) return;
    try {
      await deleteShippingRule(id);
      loadShippingRules();
      alert('删除成功！');
    } catch (e) {
      alert('删除失败：' + (e as Error).message);
    }
  };

  const handleToggleDelivery = async (rule: ShippingRule) => {
    try {
      await updateShippingRule({
        id: rule.id,
        item_keyword: rule.item_keyword,
        card_group_id: rule.card_group_id,
        name: rule.name,
        priority: rule.priority,
        enabled: !rule.enabled
      });
      loadShippingRules();
    } catch (e) {
      alert('操作失败：' + (e as Error).message);
    }
  };

  const handleSaveDefault = async () => {
    if (!defaultForm.cookie_id) {
      alert('请先选择账号');
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
      alert('保存成功！');
    } catch (e) {
      alert('保存失败：' + (e as Error).message);
    }
  };

  const handleDeleteDefault = async (cookieId: string) => {
    if (!confirm('确认删除该默认回复吗？')) return;
    try {
      await deleteDefaultReply(cookieId);
      loadDefaultReplies();
      alert('删除成功！');
    } catch (e) {
      alert('删除失败：' + (e as Error).message);
    }
  };

  const handleClearRecords = async (cookieId: string) => {
    if (!confirm('确认清空该账号的回复记录吗？清空后可以重新对所有对话使用默认回复。')) return;
    try {
      await clearDefaultReplyRecords(cookieId);
      alert('清空成功！');
    } catch (e) {
      alert('清空失败：' + (e as Error).message);
    }
  };

  return (
    <div className="space-y-5 animate-fade-in">
      {/* Header */}
      <div className="flex items-end justify-between">
        <div>
          <h2 className="text-2xl font-bold text-gray-900">
            {mode === 'reply' ? '自动回复' : '自动发货'}
          </h2>
          <p className="mt-1 text-sm text-gray-500">
            {mode === 'reply'
              ? '配置关键词回复和账号默认回复'
              : '配置卡密发货规则和发货前风险拦截'}
          </p>
        </div>
      </div>

      {/* Tab 切换 */}
      {mode === 'reply' && <div className="overflow-x-auto">
        <div className="inline-flex min-w-max rounded-lg bg-gray-100 p-1">
          <button
            onClick={() => setActiveTab('reply')}
            className={`flex items-center gap-2 rounded-md px-3 py-2 text-sm font-bold transition-colors sm:px-4 ${
              activeTab === 'reply'
                ? 'bg-white text-gray-900 shadow-sm'
                : 'text-gray-500 hover:bg-white/60 hover:text-gray-700'
            }`}
          >
            <MessageSquare className="w-6 h-6" />
            关键词回复
            {activeTab === 'reply' && (
              <span className="ml-1 rounded bg-gray-100 px-2 py-0.5 text-xs">{keywords.length}</span>
            )}
          </button>
          <button
            onClick={() => setActiveTab('default')}
            className={`flex items-center gap-2 rounded-md px-3 py-2 text-sm font-bold transition-colors sm:px-4 ${
              activeTab === 'default'
                ? 'bg-white text-gray-900 shadow-sm'
                : 'text-gray-500 hover:bg-white/60 hover:text-gray-700'
            }`}
          >
            <Bot className="w-6 h-6" />
            账号默认回复
            {activeTab === 'default' && (
              <span className="ml-1 rounded bg-gray-100 px-2 py-0.5 text-xs">
                {(Object.values(defaultReplies) as DefaultReply[]).filter(reply => reply.enabled).length}
              </span>
            )}
          </button>
        </div>
      </div>}

      {mode === 'delivery' && (
        <div className="overflow-x-auto">
          <div className="inline-flex min-w-max rounded-lg bg-gray-100 p-1">
            <button
              type="button"
              onClick={() => setDeliveryTab('keywords')}
              className={`rounded-md px-4 py-2 text-sm font-bold ${
                deliveryTab === 'keywords' ? 'bg-white text-gray-900 shadow-sm' : 'text-gray-500'
              }`}
            >
              关键词发货
            </button>
            <button
              type="button"
              onClick={() => setDeliveryTab('protection')}
              className={`rounded-md px-4 py-2 text-sm font-bold ${
                deliveryTab === 'protection' ? 'bg-white text-gray-900 shadow-sm' : 'text-gray-500'
              }`}
            >
              发货保护
            </button>
          </div>
        </div>
      )}

      {/* 操作栏 */}
      {(mode === 'reply' || deliveryTab === 'keywords') && <div className="rounded-lg border border-gray-100 bg-white p-4 shadow-sm">
        <div className="flex flex-col sm:flex-row gap-4 items-center justify-between">
          {mode === 'reply' ? <div className="flex items-center gap-4 w-full sm:w-auto">
            <label className="text-sm font-bold text-gray-700 whitespace-nowrap">选择账号</label>
            <select
              className="ios-input flex-1 rounded-lg border border-gray-200 px-4 py-2.5 font-medium transition-colors focus:border-[#FFE815] sm:w-64"
              value={selectedAccount}
              onChange={(e) => setSelectedAccount(e.target.value)}
            >
              <option value="">请选择账号</option>
              {accounts.map((acc) => (
                <option key={acc.id} value={acc.id}>
                  {acc.nickname}
                </option>
              ))}
            </select>
          </div> : <p className="w-full text-sm text-gray-500 sm:w-auto">按买家消息关键词匹配卡密并自动发货</p>}
          <div className="flex items-center gap-3 w-full sm:w-auto">
            <button
              onClick={() => {
                if (mode === 'delivery') {
                  loadShippingRules();
                  loadCards();
                } else if (activeTab === 'reply') {
                  loadKeywords();
                } else {
                  loadDefaultReplies();
                }
              }}
              className="flex flex-1 items-center justify-center gap-2 rounded-lg bg-gray-100 px-4 py-2.5 font-bold transition-colors hover:bg-gray-200 sm:flex-none"
            >
              <RefreshCw className="w-5 h-5" />
              刷新
            </button>
            <button
              onClick={handleAdd}
              disabled={mode === 'reply' && !selectedAccount}
              className="ios-btn-primary flex flex-1 items-center justify-center gap-2 rounded-lg px-4 py-2.5 font-bold disabled:cursor-not-allowed disabled:opacity-50 sm:flex-none"
            >
              <Plus className="w-5 h-5" />
              {mode === 'delivery' ? '添加发货规则' : activeTab === 'reply' ? '添加关键词' : '编辑默认回复'}
            </button>
          </div>
        </div>
      </div>}

      {/* 内容区域 */}
      {mode === 'reply' && !selectedAccount ? (
        <div className="rounded-lg border-2 border-dashed border-gray-200 bg-white py-16 text-center">
          <div className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-full bg-yellow-50">
            <MessageSquare className="h-8 w-8 text-yellow-500" />
          </div>
          <h3 className="mb-1 text-lg font-bold text-gray-900">请选择账号</h3>
          <p className="text-sm text-gray-500">选择一个账号以管理其关键词规则</p>
        </div>
      ) : mode === 'reply' && activeTab === 'reply' ? (
        // 关键词回复列表
        loading ? (
          <div className="py-24 flex justify-center">
            <div className="flex flex-col items-center gap-4">
              <Loader2 className="w-16 h-16 text-[#FFE815] animate-spin" />
              <p className="text-gray-500 font-medium">加载中...</p>
            </div>
          </div>
        ) : (
          <div className="space-y-4">
            {keywords.map((keyword) => (
              <div
                key={keyword.id}
                className="rounded-lg border border-gray-100 bg-white p-4 shadow-sm transition-colors hover:border-yellow-300"
              >
                <div className="flex flex-col gap-4 sm:flex-row sm:items-center">
                  {/* 图标 */}
                  <div className="flex-shrink-0">
                    <div className="flex h-12 w-12 items-center justify-center rounded-lg bg-yellow-50">
                      <Key className="h-6 w-6 text-yellow-700" />
                    </div>
                  </div>

                  {/* 内容 */}
                  <div className="flex-1 min-w-0">
                    <div className="mb-2 flex flex-wrap items-center gap-2">
                      <h3 className="font-bold text-gray-900">{keyword.keyword}</h3>
                      <span className="rounded bg-green-50 px-2 py-1 text-xs font-bold text-green-700">
                        精确匹配
                      </span>
                    </div>
                    <p className="line-clamp-2 rounded-md bg-gray-50 px-3 py-2 text-sm text-gray-600">
                      {keyword.reply_content || '无回复内容'}
                    </p>
                  </div>

                  {/* 操作按钮 */}
                  <div className="flex flex-shrink-0 justify-end gap-2">
                    <button
                      onClick={() => handleEdit(keyword)}
                      className="rounded-lg bg-amber-50 p-2.5 text-amber-700 transition-colors hover:bg-amber-100"
                      title="编辑"
                      aria-label={`编辑关键词 ${keyword.keyword}`}
                    >
                      <Edit2 className="w-5 h-5" />
                    </button>
                    <button
                      onClick={() => handleDelete(keyword.id)}
                      className="rounded-lg bg-red-50 p-2.5 text-red-600 transition-colors hover:bg-red-100"
                      title="删除"
                      aria-label={`删除关键词 ${keyword.keyword}`}
                    >
                      <Trash2 className="w-5 h-5" />
                    </button>
                  </div>
                </div>
              </div>
            ))}

            {keywords.length === 0 && (
              <div className="rounded-lg border-2 border-dashed border-gray-200 bg-white py-16 text-center">
                <div className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-full bg-yellow-50">
                  <MessageSquare className="h-8 w-8 text-yellow-500" />
                </div>
                <h3 className="mb-1 text-lg font-bold text-gray-900">暂无关键词</h3>
                <p className="text-sm text-gray-500">使用上方按钮添加新的关键词规则</p>
              </div>
            )}
          </div>
        )
      ) : mode === 'delivery' && deliveryTab === 'protection' ? (
        <DeliveryProtection />
      ) : mode === 'delivery' ? (
        // 关键词发货列表
        <div className="space-y-4">
          {shippingRules.map((rule) => (
            <div
              key={rule.id}
              className={`rounded-lg border p-4 shadow-sm transition-colors ${
                rule.enabled ? 'border-gray-100 bg-white hover:border-blue-300' : 'border-gray-200 bg-gray-50'
              }`}
            >
              <div className="flex flex-col gap-4 sm:flex-row sm:items-center">
                {/* 图标 */}
                <div className="flex-shrink-0">
                  <div className={`flex h-12 w-12 items-center justify-center rounded-lg ${
                    rule.enabled
                      ? 'bg-blue-500'
                      : 'bg-gray-300'
                  }`}>
                    <Truck className="h-6 w-6 text-white" />
                  </div>
                </div>

                {/* 内容 */}
                <div className="flex-1 min-w-0">
                  <div className="mb-2 flex flex-wrap items-center gap-2">
                    <h3 className="font-bold text-gray-900">{rule.item_keyword}</h3>
                    <span className={`rounded px-2 py-1 text-xs font-bold ${
                      rule.enabled
                        ? 'bg-green-50 text-green-700'
                        : 'bg-gray-200 text-gray-600'
                    }`}>
                      {rule.enabled ? '已启用' : '已禁用'}
                    </span>
                  </div>
                  <p className="rounded-md bg-gray-50 px-3 py-2 text-sm text-gray-600">
                    卡券：{rule.card_group_name || `ID: ${rule.card_group_id}`}
                    {rule.name && (
                      <>
                        <span className="mx-2 text-gray-300">|</span>
                        {rule.name}
                      </>
                    )}
                  </p>
                </div>

                {/* 操作按钮 */}
                <div className="flex flex-shrink-0 justify-end gap-2">
                  <button
                    onClick={() => handleToggleDelivery(rule)}
                    className={`rounded-lg p-2.5 transition-colors ${
                      rule.enabled
                        ? 'bg-amber-50 text-amber-700 hover:bg-amber-100'
                        : 'bg-green-50 text-green-700 hover:bg-green-100'
                    }`}
                    title={rule.enabled ? '禁用' : '启用'}
                  >
                    {rule.enabled ? <PowerOff className="w-5 h-5" /> : <Power className="w-5 h-5" />}
                  </button>
                  <button
                    onClick={() => handleEditDelivery(rule)}
                    className="rounded-lg bg-amber-50 p-2.5 text-amber-700 transition-colors hover:bg-amber-100"
                    title="编辑"
                  >
                    <Edit2 className="w-5 h-5" />
                  </button>
                  <button
                    onClick={() => handleDeleteDelivery(rule.id)}
                    className="rounded-lg bg-red-50 p-2.5 text-red-600 transition-colors hover:bg-red-100"
                    title="删除"
                  >
                    <Trash2 className="w-5 h-5" />
                  </button>
                </div>
              </div>
            </div>
          ))}

          {shippingRules.length === 0 && (
            <div className="rounded-lg border-2 border-dashed border-gray-200 bg-white py-16 text-center">
              <div className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-full bg-blue-50">
                <Truck className="h-8 w-8 text-blue-500" />
              </div>
              <h3 className="mb-1 text-lg font-bold text-gray-900">暂无发货规则</h3>
              <p className="text-sm text-gray-500">使用上方按钮添加新的发货规则</p>
            </div>
          )}
        </div>
      ) : mode === 'reply' && activeTab === 'default' ? (
        // 账号默认回复列表
        <div className="space-y-4">
          {accounts.map((account) => {
            const defaultReply = defaultReplies[account.id];
            const hasDefaultReply = defaultReply && defaultReply.enabled;
            return (
              <div
                key={account.id}
                className={`rounded-lg border p-4 shadow-sm transition-colors ${
                  hasDefaultReply ? 'border-gray-100 bg-white hover:border-purple-300' : 'border-gray-200 bg-gray-50'
                }`}
              >
                <div className="flex flex-col gap-4 sm:flex-row sm:items-center">
                  {/* 图标 */}
                  <div className="flex-shrink-0">
                    <div className={`flex h-12 w-12 items-center justify-center rounded-lg ${
                      hasDefaultReply
                        ? 'bg-purple-500'
                        : 'bg-gray-300'
                    }`}>
                      <Bot className="h-6 w-6 text-white" />
                    </div>
                  </div>

                  {/* 内容 */}
                  <div className="flex-1 min-w-0">
                    <div className="mb-2 flex flex-wrap items-center gap-2">
                      <h3 className="font-bold text-gray-900">{account.nickname}</h3>
                      <span className={`rounded px-2 py-1 text-xs font-bold ${
                        hasDefaultReply
                          ? 'bg-green-50 text-green-700'
                          : 'bg-gray-200 text-gray-600'
                      }`}>
                        {hasDefaultReply ? '已启用' : '未设置'}
                      </span>
                      {defaultReply?.reply_once && (
                        <span className="rounded bg-purple-100 px-2 py-1 text-xs font-bold text-purple-700">
                          只回复一次
                        </span>
                      )}
                    </div>
                    {hasDefaultReply && (
                      <p className="line-clamp-2 rounded-md bg-gray-50 px-3 py-2 text-sm text-gray-600">
                        {defaultReply.reply_content || '无回复内容'}
                      </p>
                    )}
                  </div>

                  {/* 操作按钮 */}
                  <div className="flex flex-shrink-0 justify-end gap-2">
                    <button
                      onClick={() => loadDefaultReplyForEdit(account.id)}
                      className="rounded-lg bg-purple-50 p-2.5 text-purple-700 transition-colors hover:bg-purple-100"
                      title="编辑"
                    >
                      <Edit2 className="w-5 h-5" />
                    </button>
                    {hasDefaultReply && (
                      <>
                        <button
                          onClick={() => handleClearRecords(account.id)}
                          className="rounded-lg bg-blue-50 p-2.5 text-blue-700 transition-colors hover:bg-blue-100"
                          title="清空回复记录"
                        >
                          <RefreshCw className="w-5 h-5" />
                        </button>
                        <button
                          onClick={() => handleDeleteDefault(account.id)}
                          className="rounded-lg bg-red-50 p-2.5 text-red-600 transition-colors hover:bg-red-100"
                          title="删除"
                        >
                          <Trash2 className="w-5 h-5" />
                        </button>
                      </>
                    )}
                  </div>
                </div>
              </div>
            );
          })}

          {accounts.length === 0 && (
            <div className="rounded-lg border-2 border-dashed border-gray-200 bg-white py-16 text-center">
              <div className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-full bg-purple-50">
                <Bot className="h-8 w-8 text-purple-500" />
              </div>
              <h3 className="mb-1 text-lg font-bold text-gray-900">暂无账号</h3>
              <p className="text-sm text-gray-500">请先添加账号</p>
            </div>
          )}
        </div>
      ) : null}

      {/* 关键词回复弹窗 */}
      {mode === 'reply' && showReplyModal && createPortal(
        <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-4 animate-fade-in">
          <div className="bg-white rounded-[2.5rem] shadow-2xl max-w-2xl w-full max-h-[90vh] overflow-hidden animate-scale-in">
            {/* Header */}
            <div className="bg-gradient-to-r from-[#FFE815] to-[#FFD700] p-8">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-4">
                  <div className="w-14 h-14 bg-white/30 backdrop-blur-sm rounded-2xl flex items-center justify-center">
                    <MessageSquare className="w-7 h-7 text-gray-900" />
                  </div>
                  <h3 className="text-3xl font-black text-gray-900">
                    {editingKeyword ? '编辑关键词' : '添加关键词'}
                  </h3>
                </div>
                <button
                  onClick={() => setShowReplyModal(false)}
                  className="p-3 bg-white/30 backdrop-blur-sm rounded-2xl hover:bg-white/40 transition-colors"
                >
                  <X className="w-6 h-6 text-gray-900" />
                </button>
              </div>
            </div>

            {/* Body */}
            <div className="p-8 space-y-6 overflow-y-auto max-h-[60vh]">
              <div>
                <label className="flex items-center gap-2 text-sm font-black text-gray-900 mb-3">
                  <Key className="w-5 h-5 text-[#FFE815]" />
                  触发关键词
                </label>
                <input
                  type="text"
                  value={replyForm.keyword}
                  onChange={(e) => setReplyForm({ ...replyForm, keyword: e.target.value })}
                  placeholder="例如：价格、包邮、怎么样"
                  className="w-full px-6 py-4 rounded-2xl font-medium border-2 border-gray-200 focus:border-[#FFE815] focus:ring-4 focus:ring-[#FFE815]/20 transition-all bg-gray-50"
                />
                <p className="text-sm text-gray-500 mt-2 ml-1">💡 买家消息中包含此关键词时自动回复</p>
              </div>

              <div>
                <label className="flex items-center gap-2 text-sm font-black text-gray-900 mb-3">
                  <MessageSquare className="w-5 h-5 text-[#FFE815]" />
                  回复内容
                </label>
                <textarea
                  value={replyForm.reply_content}
                  onChange={(e) => setReplyForm({ ...replyForm, reply_content: e.target.value })}
                  placeholder="输入自动回复的内容..."
                  rows={6}
                  className="w-full px-6 py-4 rounded-2xl font-medium border-2 border-gray-200 focus:border-[#FFE815] focus:ring-4 focus:ring-[#FFE815]/20 transition-all bg-gray-50 resize-none"
                />
                <p className="text-sm text-gray-500 mt-2 ml-1">💬 支持换行，系统将自动发送此内容给买家</p>
              </div>
            </div>

            {/* Footer */}
            <div className="p-8 bg-gray-50 border-t border-gray-100">
              <div className="flex gap-4">
                <button
                  onClick={() => setShowReplyModal(false)}
                  className="flex-1 px-8 py-4 rounded-2xl font-bold bg-white border-2 border-gray-200 hover:bg-gray-50 hover:border-gray-300 text-gray-700 transition-all shadow-lg hover:shadow-xl"
                >
                  取消
                </button>
                <button
                  onClick={handleSave}
                  className="flex-1 px-8 py-4 rounded-2xl font-bold bg-gradient-to-r from-[#FFE815] to-[#FFD700] hover:from-[#FFD700] hover:to-[#FFC800] text-gray-900 shadow-xl hover:shadow-2xl hover:scale-105 transition-all flex items-center justify-center gap-2"
                >
                  <Save className="w-5 h-5" />
                  保存关键词
                </button>
              </div>
            </div>
          </div>
        </div>,
        document.body
      )}

      {/* 关键词发货弹窗 */}
      {mode === 'delivery' && showDeliveryModal && createPortal(
        <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-4 animate-fade-in">
          <div className="bg-white rounded-[2.5rem] shadow-2xl max-w-2xl w-full max-h-[90vh] overflow-hidden animate-scale-in">
            {/* Header */}
            <div className="bg-gradient-to-r from-blue-400 to-blue-500 p-8">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-4">
                  <div className="w-14 h-14 bg-white/30 backdrop-blur-sm rounded-2xl flex items-center justify-center">
                    <Truck className="w-7 h-7 text-white" />
                  </div>
                  <h3 className="text-3xl font-black text-white">
                    {editingDeliveryRule ? '编辑发货规则' : '添加发货规则'}
                  </h3>
                </div>
                <button
                  onClick={() => setShowDeliveryModal(false)}
                  className="p-3 bg-white/30 backdrop-blur-sm rounded-2xl hover:bg-white/40 transition-colors"
                >
                  <X className="w-6 h-6 text-white" />
                </button>
              </div>
            </div>

            {/* Body */}
            <div className="p-8 space-y-6 overflow-y-auto max-h-[60vh]">
              <div>
                <label className="flex items-center gap-2 text-sm font-black text-gray-900 mb-3">
                  <Key className="w-5 h-5 text-blue-500" />
                  触发关键词
                </label>
                <input
                  type="text"
                  value={deliveryForm.keyword}
                  onChange={(e) => setDeliveryForm({ ...deliveryForm, keyword: e.target.value })}
                  placeholder="例如：发货卡密、自动发货"
                  className="w-full px-6 py-4 rounded-2xl font-medium border-2 border-gray-200 focus:border-blue-400 focus:ring-4 focus:ring-blue-400/20 transition-all bg-gray-50"
                />
                <p className="text-sm text-gray-500 mt-2 ml-1">💡 买家消息中包含此关键词时自动发货</p>
              </div>

              <div>
                <label className="flex items-center gap-2 text-sm font-black text-gray-900 mb-3">
                  <Sparkles className="w-5 h-5 text-blue-500" />
                  关联卡券
                </label>
                <select
                  value={deliveryForm.card_id}
                  onChange={(e) => setDeliveryForm({ ...deliveryForm, card_id: e.target.value })}
                  className="w-full px-6 py-4 rounded-2xl font-medium border-2 border-gray-200 focus:border-blue-400 focus:ring-4 focus:ring-blue-400/20 transition-all bg-gray-50"
                >
                  <option value="">请选择卡券</option>
                  {cards.map((card) => (
                    <option key={card.id} value={card.id}>
                      {card.name || card.text_content?.substring(0, 30) || `卡券 ${card.id}`}
                      {card.is_multi_spec && ` [${card.spec_name}: ${card.spec_value}]`}
                    </option>
                  ))}
                </select>
                <p className="text-sm text-gray-500 mt-2 ml-1">🎁 选择触发关键词时发送的卡券</p>
              </div>

              <div>
                <label className="flex items-center gap-2 text-sm font-black text-gray-900 mb-3">
                  <MessageSquare className="w-5 h-5 text-blue-500" />
                  描述（可选）
                </label>
                <input
                  type="text"
                  value={deliveryForm.description}
                  onChange={(e) => setDeliveryForm({ ...deliveryForm, description: e.target.value })}
                  placeholder="规则描述，方便识别"
                  className="w-full px-6 py-4 rounded-2xl font-medium border-2 border-gray-200 focus:border-blue-400 focus:ring-4 focus:ring-blue-400/20 transition-all bg-gray-50"
                />
              </div>

              <div className="flex items-center justify-between p-5 bg-gradient-to-r from-blue-50 to-blue-100/50 rounded-2xl border-2 border-blue-200">
                <div className="flex items-center gap-3">
                  <Power className="w-6 h-6 text-blue-500" />
                  <span className="text-base font-black text-gray-900">启用此规则</span>
                </div>
                <button
                  type="button"
                  onClick={() => setDeliveryForm({ ...deliveryForm, enabled: !deliveryForm.enabled })}
                  className={`relative inline-flex h-7 w-14 items-center rounded-full transition-all duration-300 ${
                    deliveryForm.enabled ? 'bg-blue-500' : 'bg-gray-300'
                  }`}
                >
                  <span
                    className={`inline-block h-5 w-5 transform rounded-full bg-white shadow-lg transition-transform duration-300 ${
                      deliveryForm.enabled ? 'translate-x-8' : 'translate-x-1'
                    }`}
                  />
                </button>
              </div>
            </div>

            {/* Footer */}
            <div className="p-8 bg-gray-50 border-t border-gray-100">
              <div className="flex gap-4">
                <button
                  onClick={() => setShowDeliveryModal(false)}
                  className="flex-1 px-8 py-4 rounded-2xl font-bold bg-white border-2 border-gray-200 hover:bg-gray-50 hover:border-gray-300 text-gray-700 transition-all shadow-lg hover:shadow-xl"
                >
                  取消
                </button>
                <button
                  onClick={handleSaveDelivery}
                  className="flex-1 px-8 py-4 rounded-2xl font-bold bg-gradient-to-r from-blue-400 to-blue-500 hover:from-blue-500 hover:to-blue-600 text-white shadow-xl hover:shadow-2xl hover:scale-105 transition-all flex items-center justify-center gap-2"
                >
                  <Save className="w-5 h-5" />
                  保存发货规则
                </button>
              </div>
            </div>
          </div>
        </div>,
        document.body
      )}

      {/* 账号默认回复弹窗 */}
      {mode === 'reply' && showDefaultModal && createPortal(
        <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-4 animate-fade-in">
          <div className="bg-white rounded-[2.5rem] shadow-2xl max-w-2xl w-full max-h-[90vh] overflow-hidden animate-scale-in">
            {/* Header */}
            <div className="bg-gradient-to-r from-purple-400 to-purple-500 p-8">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-4">
                  <div className="w-14 h-14 bg-white/30 backdrop-blur-sm rounded-2xl flex items-center justify-center">
                    <Bot className="w-7 h-7 text-white" />
                  </div>
                  <h3 className="text-3xl font-black text-white">
                    账号默认回复
                  </h3>
                </div>
                <button
                  onClick={() => setShowDefaultModal(false)}
                  className="p-3 bg-white/30 backdrop-blur-sm rounded-2xl hover:bg-white/40 transition-colors"
                >
                  <X className="w-6 h-6 text-white" />
                </button>
              </div>
            </div>

            {/* Body */}
            <div className="p-8 space-y-6 overflow-y-auto max-h-[60vh]">
              <div>
                <label className="flex items-center gap-2 text-sm font-black text-gray-900 mb-3">
                  <Bot className="w-5 h-5 text-purple-500" />
                  账号
                </label>
                <select
                  value={defaultForm.cookie_id}
                  onChange={(e) => setDefaultForm({ ...defaultForm, cookie_id: e.target.value })}
                  className="w-full px-6 py-4 rounded-2xl font-medium border-2 border-gray-200 focus:border-purple-400 focus:ring-4 focus:ring-purple-400/20 transition-all bg-gray-50"
                >
                  <option value="">请选择账号</option>
                  {accounts.map((acc) => (
                    <option key={acc.id} value={acc.id}>
                      {acc.nickname}
                    </option>
                  ))}
                </select>
                <p className="text-sm text-gray-500 mt-2 ml-1">🤖 为此账号设置默认回复内容</p>
              </div>

              <div className="flex items-center justify-between p-5 bg-gradient-to-r from-purple-50 to-purple-100/50 rounded-2xl border-2 border-purple-200">
                <div className="flex items-center gap-3">
                  <Power className="w-6 h-6 text-purple-500" />
                  <span className="text-base font-black text-gray-900">启用默认回复</span>
                </div>
                <button
                  type="button"
                  onClick={() => setDefaultForm({ ...defaultForm, enabled: !defaultForm.enabled })}
                  className={`relative inline-flex h-7 w-14 items-center rounded-full transition-all duration-300 ${
                    defaultForm.enabled ? 'bg-purple-500' : 'bg-gray-300'
                  }`}
                >
                  <span
                    className={`inline-block h-5 w-5 transform rounded-full bg-white shadow-lg transition-transform duration-300 ${
                      defaultForm.enabled ? 'translate-x-8' : 'translate-x-1'
                    }`}
                  />
                </button>
              </div>

              <div>
                <label className="flex items-center gap-2 text-sm font-black text-gray-900 mb-3">
                  <MessageSquare className="w-5 h-5 text-purple-500" />
                  回复内容
                </label>
                <textarea
                  value={defaultForm.reply_content}
                  onChange={(e) => setDefaultForm({ ...defaultForm, reply_content: e.target.value })}
                  placeholder="输入默认回复的内容..."
                  rows={6}
                  className="w-full px-6 py-4 rounded-2xl font-medium border-2 border-gray-200 focus:border-purple-400 focus:ring-4 focus:ring-purple-400/20 transition-all bg-gray-50 resize-none"
                />
                <p className="text-sm text-gray-500 mt-2 ml-1">💬 当没有匹配的关键词时，系统将自动发送此内容</p>
              </div>

              <div className="flex items-center justify-between p-5 bg-gradient-to-r from-amber-50 to-amber-100/50 rounded-2xl border-2 border-amber-200">
                <div className="flex items-center gap-3">
                  <span className="text-base font-black text-gray-900">🔁 只回复一次</span>
                  <span className="text-xs text-gray-500">启用后，每个对话只使用一次默认回复</span>
                </div>
                <button
                  type="button"
                  onClick={() => setDefaultForm({ ...defaultForm, reply_once: !defaultForm.reply_once })}
                  className={`relative inline-flex h-7 w-14 items-center rounded-full transition-all duration-300 ${
                    defaultForm.reply_once ? 'bg-amber-500' : 'bg-gray-300'
                  }`}
                >
                  <span
                    className={`inline-block h-5 w-5 transform rounded-full bg-white shadow-lg transition-transform duration-300 ${
                      defaultForm.reply_once ? 'translate-x-8' : 'translate-x-1'
                    }`}
                  />
                </button>
              </div>

              <div>
                <label className="flex items-center gap-2 text-sm font-black text-gray-900 mb-3">
                  <Sparkles className="w-5 h-5 text-purple-500" />
                  回复图片URL（可选）
                </label>
                <input
                  type="text"
                  value={defaultForm.reply_image_url}
                  onChange={(e) => setDefaultForm({ ...defaultForm, reply_image_url: e.target.value })}
                  placeholder="https://example.com/image.jpg"
                  className="w-full px-6 py-4 rounded-2xl font-medium border-2 border-gray-200 focus:border-purple-400 focus:ring-4 focus:ring-purple-400/20 transition-all bg-gray-50"
                />
                <p className="text-sm text-gray-500 mt-2 ml-1">🖼️ 可选：添加图片URL一起发送</p>
              </div>
            </div>

            {/* Footer */}
            <div className="p-8 bg-gray-50 border-t border-gray-100">
              <div className="flex gap-4">
                <button
                  onClick={() => setShowDefaultModal(false)}
                  className="flex-1 px-8 py-4 rounded-2xl font-bold bg-white border-2 border-gray-200 hover:bg-gray-50 hover:border-gray-300 text-gray-700 transition-all shadow-lg hover:shadow-xl"
                >
                  取消
                </button>
                <button
                  onClick={handleSaveDefault}
                  className="flex-1 px-8 py-4 rounded-2xl font-bold bg-gradient-to-r from-purple-400 to-purple-500 hover:from-purple-500 hover:to-purple-600 text-white shadow-xl hover:shadow-2xl hover:scale-105 transition-all flex items-center justify-center gap-2"
                >
                  <Save className="w-5 h-5" />
                  保存默认回复
                </button>
              </div>
            </div>
          </div>
        </div>,
        document.body
      )}
    </div>
  );
};

export default Keywords;
