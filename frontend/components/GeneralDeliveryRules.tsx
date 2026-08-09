import React, { useState } from 'react';
import { createPortal } from 'react-dom';
import {
  Edit2,
  KeyRound,
  Loader2,
  PackageCheck,
  Plus,
  Power,
  PowerOff,
  RefreshCw,
  Save,
  Trash2,
  X,
} from 'lucide-react';

import { AccountDetail, Card, ShippingRule } from '../types';
import {
  deleteShippingRule,
  updateShippingRule,
} from '../services/api';
import { confirmAction, notify } from '../services/feedback';
import { EmptyState, SectionHeader } from './ui';

interface GeneralDeliveryRulesProps {
  accounts: AccountDetail[];
  cards: Card[];
  rules: ShippingRule[];
  onReload: () => Promise<void>;
}

interface RuleForm {
  keyword: string;
  cookieId: string;
  cardId: string;
  deliveryCount: number;
  description: string;
  enabled: boolean;
}

const emptyRuleForm: RuleForm = {
  keyword: '',
  cookieId: '',
  cardId: '',
  deliveryCount: 1,
  description: '',
  enabled: true,
};

const GeneralDeliveryRules: React.FC<GeneralDeliveryRulesProps> = ({
  accounts,
  cards,
  rules,
  onReload,
}) => {
  const [editingRule, setEditingRule] = useState<ShippingRule | null>(null);
  const [showModal, setShowModal] = useState(false);
  const [saving, setSaving] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [busyRuleId, setBusyRuleId] = useState('');
  const [form, setForm] = useState<RuleForm>(emptyRuleForm);

  const openCreate = () => {
    setEditingRule(null);
    setForm(emptyRuleForm);
    setShowModal(true);
  };

  const openEdit = (rule: ShippingRule) => {
    setEditingRule(rule);
    setForm({
      keyword: rule.item_keyword,
      cookieId: rule.cookie_id || '',
      cardId: String(rule.card_group_id),
      deliveryCount: Math.max(1, rule.priority || 1),
      description: rule.name || '',
      enabled: rule.enabled,
    });
    setShowModal(true);
  };

  const handleReload = async () => {
    setRefreshing(true);
    try {
      await onReload();
    } catch (error) {
      notify(`刷新失败：${(error as Error).message}`);
    } finally {
      setRefreshing(false);
    }
  };

  const handleSave = async () => {
    if (!form.keyword.trim()) {
      notify('请填写触发关键词');
      return;
    }
    if (!form.cardId) {
      notify('请选择发货卡密或内容');
      return;
    }

    setSaving(true);
    try {
      await updateShippingRule({
        id: editingRule?.id,
        item_keyword: form.keyword.trim(),
        cookie_id: form.cookieId || undefined,
        item_id: undefined,
        card_group_id: Number(form.cardId),
        priority: Math.max(1, Math.floor(form.deliveryCount || 1)),
        name: form.description.trim(),
        enabled: form.enabled,
      });
      await onReload();
      setShowModal(false);
      notify('通用发货规则已保存');
    } catch (error) {
      notify(`保存失败：${(error as Error).message}`);
    } finally {
      setSaving(false);
    }
  };

  const toggleRule = async (rule: ShippingRule) => {
    setBusyRuleId(rule.id);
    try {
      await updateShippingRule({ ...rule, enabled: !rule.enabled });
      await onReload();
    } catch (error) {
      notify(`更新失败：${(error as Error).message}`);
    } finally {
      setBusyRuleId('');
    }
  };

  const removeRule = async (rule: ShippingRule) => {
    if (!await confirmAction(`确认删除通用发货规则“${rule.item_keyword}”吗？`)) return;
    setBusyRuleId(rule.id);
    try {
      await deleteShippingRule(rule.id);
      await onReload();
      notify('通用发货规则已删除');
    } catch (error) {
      notify(`删除失败：${(error as Error).message}`);
    } finally {
      setBusyRuleId('');
    }
  };

  return (
    <div className="space-y-4">
      <section className="section-panel">
        <SectionHeader
          title="账号与全局兜底规则"
          description="按商品标题或本地详情关键词匹配，商品专属规则优先。"
          icon={KeyRound}
          actions={(
            <>
          <button
            type="button"
            onClick={() => void handleReload()}
            disabled={refreshing}
                className="ios-btn-secondary flex items-center justify-center gap-2 rounded-md px-4 py-2 text-sm disabled:opacity-50"
          >
            <RefreshCw className={`h-4 w-4 ${refreshing ? 'animate-spin' : ''}`} />
            刷新
          </button>
          <button
            type="button"
            onClick={openCreate}
                className="ios-btn-primary flex items-center justify-center gap-2 rounded-md px-4 py-2 text-sm"
          >
            <Plus className="h-4 w-4" />
            添加规则
          </button>
            </>
          )}
        />
        <div className="divide-y divide-gray-100">
        {rules.map((rule) => {
          const busy = busyRuleId === rule.id;
          const account = accounts.find(item => item.id === rule.cookie_id);
          return (
            <article
              key={rule.id}
                className={`p-4 ${rule.enabled ? '' : 'opacity-70'}`}
            >
              <div className="flex flex-col gap-4 lg:flex-row lg:items-center">
                <div className={`flex h-11 w-11 flex-none items-center justify-center rounded-md ${
                  rule.enabled ? 'bg-blue-50 text-blue-700' : 'bg-gray-100 text-gray-400'
                }`}>
                  <KeyRound className="h-5 w-5" />
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <h4 className="font-bold text-gray-900">{rule.item_keyword}</h4>
                    <span className={`rounded px-2 py-1 text-xs font-bold ${
                      rule.enabled ? 'bg-green-50 text-green-700' : 'bg-gray-100 text-gray-500'
                    }`}>
                      {rule.enabled ? '已启用' : '已停用'}
                    </span>
                    <span className="rounded bg-blue-50 px-2 py-1 text-xs font-bold text-blue-700">
                      {rule.cookie_id ? '指定账号' : '全部账号'}
                    </span>
                  </div>
                  <div className="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-sm text-gray-600">
                    <span>发货：{rule.card_group_name || `卡密 ${rule.card_group_id}`}</span>
                    <span>每单：{Math.max(1, rule.priority || 1)} 份</span>
                    {rule.cookie_id && (
                      <span>账号：{account?.nickname || account?.remark || rule.cookie_id}</span>
                    )}
                  </div>
                  {rule.name && <p className="mt-2 text-sm text-gray-500">{rule.name}</p>}
                </div>
                <div className="flex flex-none justify-end gap-2">
                  <button
                    type="button"
                    onClick={() => void toggleRule(rule)}
                    disabled={busy}
                    className={`rounded-md p-2.5 ${
                      rule.enabled
                        ? 'bg-amber-50 text-amber-700 hover:bg-amber-100'
                        : 'bg-green-50 text-green-700 hover:bg-green-100'
                    }`}
                    title={rule.enabled ? '停用规则' : '启用规则'}
                    aria-label={rule.enabled ? '停用规则' : '启用规则'}
                  >
                    {busy
                      ? <Loader2 className="h-4 w-4 animate-spin" />
                      : rule.enabled
                        ? <PowerOff className="h-4 w-4" />
                        : <Power className="h-4 w-4" />}
                  </button>
                  <button
                    type="button"
                    onClick={() => openEdit(rule)}
                    disabled={busy}
                    className="rounded-md bg-gray-100 p-2.5 text-gray-700 hover:bg-gray-200"
                    title="编辑规则"
                    aria-label="编辑规则"
                  >
                    <Edit2 className="h-4 w-4" />
                  </button>
                  <button
                    type="button"
                    onClick={() => void removeRule(rule)}
                    disabled={busy}
                    className="rounded-md bg-red-50 p-2.5 text-red-600 hover:bg-red-100"
                    title="删除规则"
                    aria-label="删除规则"
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                </div>
              </div>
            </article>
          );
        })}

        {rules.length === 0 && (
            <EmptyState
              compact
              title="暂无通用发货规则"
              description="可添加指定账号或全部账号适用的关键词兜底规则。"
              icon={PackageCheck}
            />
        )}
        </div>
      </section>

      {showModal && createPortal(
        <div className="modal-overlay">
          <div className="modal-container">
            <div className="modal-header flex items-start justify-between gap-4">
              <div>
                <h3 className="text-xl font-bold text-gray-900">
                  {editingRule ? '编辑通用发货规则' : '添加通用发货规则'}
                </h3>
                <p className="mt-1 text-sm text-gray-500">未指定账号时对当前用户的全部闲鱼账号生效。</p>
              </div>
              <button
                type="button"
                onClick={() => setShowModal(false)}
                className="rounded-md p-2 hover:bg-gray-100"
                aria-label="关闭"
              >
                <X className="h-5 w-5" />
              </button>
            </div>
            <div className="modal-body grid grid-cols-1 gap-4 sm:grid-cols-2">
              <div className="sm:col-span-2">
                <label className="mb-2 block text-sm font-bold text-gray-700" htmlFor="generic-rule-account">
                  适用账号
                </label>
                <select
                  id="generic-rule-account"
                  value={form.cookieId}
                  onChange={event => setForm(current => ({ ...current, cookieId: event.target.value }))}
                  className="ios-input w-full rounded-md px-3 py-2.5"
                >
                  <option value="">全部账号</option>
                  {accounts.map(account => (
                    <option key={account.id} value={account.id}>
                      {account.nickname || account.remark || account.id}
                    </option>
                  ))}
                </select>
              </div>
              <div className="sm:col-span-2">
                <label className="mb-2 block text-sm font-bold text-gray-700" htmlFor="generic-rule-keyword">
                  商品关键词
                </label>
                <input
                  id="generic-rule-keyword"
                  value={form.keyword}
                  onChange={event => setForm(current => ({ ...current, keyword: event.target.value }))}
                  className="ios-input w-full rounded-md px-3 py-2.5"
                  placeholder="例如：Kimi、会员、周卡"
                />
              </div>
              <div>
                <label className="mb-2 block text-sm font-bold text-gray-700" htmlFor="generic-rule-card">
                  发货卡密或内容
                </label>
                <select
                  id="generic-rule-card"
                  value={form.cardId}
                  onChange={event => setForm(current => ({ ...current, cardId: event.target.value }))}
                  className="ios-input w-full rounded-md px-3 py-2.5"
                >
                  <option value="">请选择</option>
                  {cards.map(card => (
                    <option key={card.id} value={card.id} disabled={!card.enabled}>
                      {card.name || `卡密 ${card.id}`}{card.enabled ? '' : '（已停用）'}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="mb-2 block text-sm font-bold text-gray-700" htmlFor="generic-rule-count">
                  每单发货数量
                </label>
                <input
                  id="generic-rule-count"
                  type="number"
                  min={1}
                  step={1}
                  value={form.deliveryCount}
                  onChange={event => setForm(current => ({
                    ...current,
                    deliveryCount: Math.max(1, Number(event.target.value) || 1),
                  }))}
                  className="ios-input w-full rounded-md px-3 py-2.5"
                />
              </div>
              <div className="sm:col-span-2">
                <label className="mb-2 block text-sm font-bold text-gray-700" htmlFor="generic-rule-description">
                  规则备注
                </label>
                <input
                  id="generic-rule-description"
                  value={form.description}
                  onChange={event => setForm(current => ({ ...current, description: event.target.value }))}
                  className="ios-input w-full rounded-md px-3 py-2.5"
                  placeholder="便于识别此规则"
                />
              </div>
              <div className="sm:col-span-2 flex items-center justify-between rounded-md border border-gray-200 bg-gray-50 p-4">
                <div>
                  <p className="text-sm font-bold text-gray-800">启用规则</p>
                  <p className="mt-1 text-xs text-gray-500">关闭后保留配置，但不会参与匹配。</p>
                </div>
                <button
                  type="button"
                  role="switch"
                  aria-checked={form.enabled}
                  onClick={() => setForm(current => ({ ...current, enabled: !current.enabled }))}
                  className={`relative inline-flex h-6 w-11 items-center rounded-full ${
                    form.enabled ? 'bg-green-500' : 'bg-gray-300'
                  }`}
                  aria-label="启用通用发货规则"
                >
                  <span className={`h-4 w-4 rounded-full bg-white transition-transform ${
                    form.enabled ? 'translate-x-6' : 'translate-x-1'
                  }`} />
                </button>
              </div>
            </div>
            <div className="modal-footer flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setShowModal(false)}
                className="ios-btn-secondary rounded-md px-4 py-2.5"
              >
                取消
              </button>
              <button
                type="button"
                onClick={() => void handleSave()}
                disabled={saving}
                className="ios-btn-primary flex items-center gap-2 rounded-md px-4 py-2.5 disabled:opacity-50"
              >
                {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                保存规则
              </button>
            </div>
          </div>
        </div>,
        document.body,
      )}
    </div>
  );
};

export default GeneralDeliveryRules;
