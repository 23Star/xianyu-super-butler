import React, { useEffect, useMemo, useState } from 'react';
import { Loader2, RefreshCw, Save, ShieldAlert, Trash2, UserRoundX, X } from 'lucide-react';

import { AccountDetail, DeliveryBlockRule, Item, PersonalBlacklistEntry } from '../types';
import {
  createPersonalBlacklist,
  deletePersonalBlacklist,
  getDeliveryBlockRules,
  getPersonalBlacklist,
  updateDeliveryBlockRule,
  updatePersonalBlacklist,
} from '../services/api';
import { confirmAction, notify } from '../services/feedback';

interface DeliveryProtectionProps {
  accounts?: AccountDetail[];
  items?: Item[];
  selectedAccount?: string;
  onSelectedAccountChange?: (accountId: string) => void;
}

type BlacklistScope = 'item' | 'account' | 'global';

const DeliveryProtection: React.FC<DeliveryProtectionProps> = ({
  accounts = [],
  items = [],
  selectedAccount = '',
  onSelectedAccountChange,
}) => {
  const [rules, setRules] = useState<DeliveryBlockRule[]>([]);
  const [blacklist, setBlacklist] = useState<PersonalBlacklistEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [savingRule, setSavingRule] = useState('');
  const [form, setForm] = useState({
    scope: 'account' as BlacklistScope,
    buyer_id: '',
    buyer_nick: '',
    item_id: '',
    reason: '',
  });

  const accountItems = useMemo(
    () => items.filter((item) => item.cookie_id === selectedAccount),
    [items, selectedAccount],
  );

  useEffect(() => {
    if (selectedAccount) void loadData();
  }, [selectedAccount]);

  const loadData = async () => {
    if (!selectedAccount) return;
    setLoading(true);
    try {
      const [ruleData, blacklistData] = await Promise.all([
        getDeliveryBlockRules(selectedAccount),
        getPersonalBlacklist(selectedAccount),
      ]);
      setRules(ruleData);
      setBlacklist(blacklistData);
    } catch (error) {
      notify(`加载发货保护配置失败：${(error as Error).message}`);
    } finally {
      setLoading(false);
    }
  };

  const patchRule = (ruleCode: string, changes: Partial<DeliveryBlockRule>) => {
    setRules((current) => current.map((rule) => (
      rule.rule_code === ruleCode
        ? {
            ...rule,
            ...changes,
            only_card_after_close:
              changes.auto_close_order === false
                ? false
                : changes.only_card_after_close ?? rule.only_card_after_close,
          }
        : rule
    )));
  };

  const saveRule = async (rule: DeliveryBlockRule) => {
    setSavingRule(rule.rule_code);
    try {
      const saved = await updateDeliveryBlockRule(selectedAccount, rule.rule_code, {
        enabled: rule.enabled,
        priority: rule.priority,
        block_reason: rule.block_reason,
        auto_close_order: rule.auto_close_order,
        only_card_after_close: rule.only_card_after_close,
        excluded_item_ids: rule.excluded_item_ids,
        config: rule.config,
      });
      patchRule(rule.rule_code, saved);
      notify(`“${rule.rule_name}”已保存`);
    } catch (error) {
      notify(`保存失败：${(error as Error).message}`);
    } finally {
      setSavingRule('');
    }
  };

  const addBlacklist = async () => {
    if (!form.buyer_id.trim()) {
      notify('请输入买家 ID');
      return;
    }
    if (form.scope === 'item' && !form.item_id) {
      notify('请选择黑名单生效的商品');
      return;
    }
    try {
      await createPersonalBlacklist({
        account_id: form.scope === 'global' ? undefined : selectedAccount,
        buyer_id: form.buyer_id.trim(),
        buyer_nick: form.buyer_nick.trim(),
        item_id: form.scope === 'item' ? form.item_id : undefined,
        reason: form.reason.trim(),
        is_enabled: true,
      });
      setForm({
        scope: form.scope,
        buyer_id: '',
        buyer_nick: '',
        item_id: '',
        reason: '',
      });
      setBlacklist(await getPersonalBlacklist(selectedAccount));
    } catch (error) {
      notify(`添加失败：${(error as Error).message}`);
    }
  };

  const toggleBlacklist = async (entry: PersonalBlacklistEntry) => {
    try {
      const saved = await updatePersonalBlacklist(entry.id, { is_enabled: !entry.is_enabled });
      setBlacklist((current) => current.map((item) => item.id === entry.id ? saved : item));
    } catch (error) {
      notify(`更新失败：${(error as Error).message}`);
    }
  };

  const removeBlacklist = async (entry: PersonalBlacklistEntry) => {
    if (!await confirmAction(`确认移除买家 ${entry.buyer_nick || entry.buyer_id}？`)) return;
    try {
      await deletePersonalBlacklist(entry.id);
      setBlacklist((current) => current.filter((item) => item.id !== entry.id));
    } catch (error) {
      notify(`删除失败：${(error as Error).message}`);
    }
  };

  return (
    <div className="space-y-5">
      <div className="flex flex-col gap-3 border-b border-gray-200 pb-5 sm:flex-row sm:items-end sm:justify-between">
        <div className="w-full sm:max-w-sm">
          <label className="mb-2 block text-sm font-bold text-gray-700">应用账号</label>
          <select
            value={selectedAccount}
            onChange={(event) => onSelectedAccountChange?.(event.target.value)}
            className="w-full rounded-lg border border-gray-200 bg-white px-3 py-2.5 text-sm font-medium focus:border-yellow-400 focus:outline-none"
          >
            <option value="">请选择账号</option>
            {accounts.map((account) => (
              <option key={account.id} value={account.id}>
                {account.nickname || account.remark || account.id}
              </option>
            ))}
          </select>
        </div>
        <button
          type="button"
          onClick={() => void loadData()}
          disabled={!selectedAccount || loading}
          className="flex items-center justify-center gap-2 rounded-lg bg-gray-100 px-4 py-2.5 text-sm font-bold text-gray-700 hover:bg-gray-200 disabled:opacity-50"
        >
          <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
          刷新
        </button>
      </div>

      {!selectedAccount ? (
        <div className="border-2 border-dashed border-gray-200 py-16 text-center text-sm text-gray-500">
          选择账号后配置发货保护
        </div>
      ) : (
        <>
          <section>
            <div className="mb-3 flex items-center gap-2">
              <ShieldAlert className="h-5 w-5 text-amber-600" />
              <h3 className="text-base font-bold text-gray-900">拦截规则</h3>
            </div>
            <div className="divide-y divide-gray-100 border-y border-gray-200">
              {rules.map((rule) => (
                <div key={rule.rule_code} className="grid gap-4 py-5 xl:grid-cols-[minmax(230px,1fr)_minmax(360px,1.5fr)_44px] xl:items-start">
                  <div>
                    <div className="flex items-center gap-2">
                      <button
                        type="button"
                        role="switch"
                        aria-checked={rule.enabled}
                        onClick={() => patchRule(rule.rule_code, { enabled: !rule.enabled })}
                        className={`relative h-6 w-11 rounded-full transition-colors ${rule.enabled ? 'bg-amber-500' : 'bg-gray-300'}`}
                      >
                        <span className={`absolute left-1 top-1 h-4 w-4 rounded-full bg-white transition-transform ${rule.enabled ? 'translate-x-5' : 'translate-x-0'}`} />
                      </button>
                      <span className="font-bold text-gray-900">{rule.rule_name}</span>
                    </div>
                    <p className="mt-1 text-xs leading-5 text-gray-500">{rule.rule_description}</p>
                  </div>
                  <div className="grid gap-3 sm:grid-cols-[100px_1fr]">
                    <label className="text-xs font-bold text-gray-600">
                      优先级
                      <input
                        type="number"
                        min={0}
                        max={999}
                        value={rule.priority}
                        onChange={(event) => patchRule(rule.rule_code, { priority: Number(event.target.value) })}
                        className="mt-1 w-full rounded-md border border-gray-200 px-2 py-2 text-sm"
                      />
                    </label>
                    <label className="text-xs font-bold text-gray-600">
                      命中后发送给买家的提示
                      <input
                        value={rule.block_reason}
                        onChange={(event) => patchRule(rule.rule_code, { block_reason: event.target.value })}
                        placeholder="留空则只停止发货"
                        className="mt-1 w-full rounded-md border border-gray-200 px-3 py-2 text-sm font-normal"
                      />
                    </label>
                    <div className="rounded-md border border-gray-200 bg-gray-50 p-3 sm:col-span-2">
                      <div className="grid gap-3 md:grid-cols-2">
                        <label className="text-xs font-bold text-gray-600">
                          命中后处理
                          <span className="mt-2 flex items-center gap-2 font-medium text-gray-700">
                            <input
                              type="checkbox"
                              checked={rule.auto_close_order}
                              onChange={(event) => patchRule(rule.rule_code, {
                                auto_close_order: event.target.checked,
                                only_card_after_close: event.target.checked
                                  ? rule.only_card_after_close
                                  : false,
                              })}
                              className="h-4 w-4 rounded border-gray-300 text-amber-600"
                            />
                            主动关闭闲鱼订单
                          </span>
                        </label>
                        <label className={`text-xs font-bold ${
                          rule.auto_close_order ? 'text-gray-600' : 'text-gray-400'
                        }`}>
                          关单后处理
                          <span className="mt-2 flex items-center gap-2 font-medium">
                            <input
                              type="checkbox"
                              disabled={!rule.auto_close_order}
                              checked={rule.auto_close_order && rule.only_card_after_close}
                              onChange={(event) => patchRule(rule.rule_code, {
                                only_card_after_close: event.target.checked,
                              })}
                              className="h-4 w-4 rounded border-gray-300 text-amber-600 disabled:opacity-50"
                            />
                            关闭成功后仍发送卡券
                          </span>
                        </label>
                      </div>
                      <p className="mt-2 text-xs leading-5 text-gray-500">
                        未开启“关闭后仍发送卡券”时，规则命中即停止发货；关单失败也会停止发货。
                      </p>
                    </div>
                    <div className="sm:col-span-2">
                      <label className="text-xs font-bold text-gray-600">排除商品</label>
                      <div className="mt-1 grid gap-2 md:grid-cols-2">
                        <select
                          defaultValue=""
                          onChange={(event) => {
                            const itemId = event.target.value;
                            if (itemId && !rule.excluded_item_ids.includes(itemId)) {
                              patchRule(rule.rule_code, {
                                excluded_item_ids: [...rule.excluded_item_ids, itemId],
                              });
                            }
                            event.currentTarget.value = '';
                          }}
                          className="rounded-md border border-gray-200 bg-white px-3 py-2 text-sm font-normal"
                        >
                          <option value="">从当前账号商品中选择</option>
                          {accountItems.map((item) => (
                            <option key={item.item_id} value={item.item_id}>
                              {item.item_title || item.item_id}
                            </option>
                          ))}
                        </select>
                        <input
                          value={rule.excluded_item_ids.join(', ')}
                          onChange={(event) => patchRule(rule.rule_code, {
                            excluded_item_ids: event.target.value
                              .split(/[\s,，]+/)
                              .map(item => item.trim())
                              .filter(Boolean),
                          })}
                          placeholder="也可直接输入商品 ID，逗号分隔"
                          className="rounded-md border border-gray-200 px-3 py-2 text-sm font-normal"
                        />
                      </div>
                      {rule.excluded_item_ids.length > 0 && (
                        <div className="mt-2 flex flex-wrap gap-2">
                          {rule.excluded_item_ids.map((itemId) => {
                            const item = accountItems.find((candidate) => candidate.item_id === itemId);
                            return (
                              <span
                                key={itemId}
                                className="inline-flex max-w-full items-center gap-1 rounded bg-gray-100 px-2 py-1 text-xs text-gray-600"
                              >
                                <span className="max-w-52 truncate">{item?.item_title || itemId}</span>
                                <button
                                  type="button"
                                  onClick={() => patchRule(rule.rule_code, {
                                    excluded_item_ids: rule.excluded_item_ids.filter((id) => id !== itemId),
                                  })}
                                  title={`移除排除商品 ${itemId}`}
                                  className="rounded p-0.5 hover:bg-gray-200"
                                >
                                  <X className="h-3 w-3" />
                                </button>
                              </span>
                            );
                          })}
                        </div>
                      )}
                    </div>
                    {rule.rule_code === 'buyer_credit_zero' ? (
                      <label className="text-xs font-bold text-gray-600">
                        评价数阈值
                        <input
                          type="number"
                          min={0}
                          max={99999}
                          value={Number(rule.config.threshold) || 0}
                          onChange={(event) => patchRule(rule.rule_code, {
                            config: {
                              ...rule.config,
                              threshold: Math.max(0, Number(event.target.value) || 0),
                            },
                          })}
                          className="mt-1 w-full rounded-md border border-gray-200 px-2 py-2 text-sm"
                        />
                      </label>
                    ) : null}
                    {rule.rule_code === 'buyer_has_order' || rule.rule_code === 'buyer_has_order_global' ? (
                      <label className="flex items-center gap-2 text-xs font-bold text-gray-600 sm:col-span-2">
                        <input
                          type="checkbox"
                          checked={Boolean(rule.config.same_item_only)}
                          onChange={(event) => patchRule(rule.rule_code, {
                            config: { ...rule.config, same_item_only: event.target.checked },
                          })}
                          className="h-4 w-4 rounded border-gray-300 text-amber-600"
                        />
                        仅在买家已有同一商品订单时拦截
                      </label>
                    ) : null}
                    {rule.rule_code === 'buyer_unconfirmed' ? (
                      <>
                        <label className="text-xs font-bold text-gray-600">
                          未确认订单阈值
                          <input
                            type="number"
                            min={1}
                            max={99}
                            value={Number(rule.config.min_count) || 1}
                            onChange={(event) => patchRule(rule.rule_code, {
                              config: { ...rule.config, min_count: Math.max(1, Number(event.target.value) || 1) },
                            })}
                            className="mt-1 w-full rounded-md border border-gray-200 px-2 py-2 text-sm"
                          />
                        </label>
                        <label className="flex items-center gap-2 self-end pb-2 text-xs font-bold text-gray-600">
                          <input
                            type="checkbox"
                            checked={Boolean(rule.config.same_item_only)}
                            onChange={(event) => patchRule(rule.rule_code, {
                              config: { ...rule.config, same_item_only: event.target.checked },
                            })}
                            className="h-4 w-4 rounded border-gray-300 text-amber-600"
                          />
                          仅统计同一商品
                        </label>
                      </>
                    ) : null}
                  </div>
                  <button
                    type="button"
                    onClick={() => void saveRule(rule)}
                    disabled={savingRule === rule.rule_code}
                    title="保存规则"
                    className="flex h-10 w-10 items-center justify-center rounded-lg bg-gray-900 text-white hover:bg-gray-700 disabled:opacity-50"
                  >
                    {savingRule === rule.rule_code
                      ? <Loader2 className="h-4 w-4 animate-spin" />
                      : <Save className="h-4 w-4" />}
                  </button>
                </div>
              ))}
            </div>
          </section>

          <section className="pt-2">
            <div className="mb-3 flex items-center gap-2">
              <UserRoundX className="h-5 w-5 text-red-600" />
              <h3 className="text-base font-bold text-gray-900">买家黑名单</h3>
            </div>
            <div className="grid gap-2 border-y border-gray-200 py-4 md:grid-cols-2 xl:grid-cols-6">
              <select
                value={form.scope}
                onChange={(event) => setForm({
                  ...form,
                  scope: event.target.value as BlacklistScope,
                  item_id: '',
                })}
                className="rounded-md border border-gray-200 bg-white px-3 py-2 text-sm"
              >
                <option value="item">当前商品</option>
                <option value="account">当前账号</option>
                <option value="global">全部账号</option>
              </select>
              <input
                value={form.buyer_id}
                onChange={(event) => setForm({ ...form, buyer_id: event.target.value })}
                placeholder="买家 ID *"
                className="rounded-md border border-gray-200 px-3 py-2 text-sm"
              />
              <input
                value={form.buyer_nick}
                onChange={(event) => setForm({ ...form, buyer_nick: event.target.value })}
                placeholder="买家昵称"
                className="rounded-md border border-gray-200 px-3 py-2 text-sm"
              />
              {form.scope === 'item' ? (
                <select
                  value={form.item_id}
                  onChange={(event) => setForm({ ...form, item_id: event.target.value })}
                  className="rounded-md border border-gray-200 bg-white px-3 py-2 text-sm"
                >
                  <option value="">选择商品 *</option>
                  {accountItems.map((item) => (
                    <option key={item.item_id} value={item.item_id}>
                      {item.item_title || item.item_id}
                    </option>
                  ))}
                </select>
              ) : (
                <div className="flex items-center rounded-md border border-gray-100 bg-gray-50 px-3 py-2 text-xs text-gray-500">
                  {form.scope === 'account' ? '对当前账号全部商品生效' : '对名下全部闲鱼账号生效'}
                </div>
              )}
              <input
                value={form.reason}
                onChange={(event) => setForm({ ...form, reason: event.target.value })}
                placeholder="拉黑原因"
                className="rounded-md border border-gray-200 px-3 py-2 text-sm"
              />
              <button
                type="button"
                onClick={() => void addBlacklist()}
                className="rounded-md bg-red-600 px-4 py-2 text-sm font-bold text-white hover:bg-red-700"
              >
                加入黑名单
              </button>
            </div>
            <div className="divide-y divide-gray-100">
              {blacklist.map((entry) => (
                <div key={entry.id} className="flex flex-col gap-3 py-3 sm:flex-row sm:items-center">
                  <button
                    type="button"
                    role="switch"
                    aria-checked={entry.is_enabled}
                    onClick={() => void toggleBlacklist(entry)}
                    className={`relative h-6 w-11 shrink-0 rounded-full transition-colors ${entry.is_enabled ? 'bg-red-500' : 'bg-gray-300'}`}
                  >
                    <span className={`absolute left-1 top-1 h-4 w-4 rounded-full bg-white transition-transform ${entry.is_enabled ? 'translate-x-5' : 'translate-x-0'}`} />
                  </button>
                  <div className="min-w-0 flex-1">
                    <p className="font-bold text-gray-900">{entry.buyer_nick || entry.buyer_id}</p>
                    <p className="break-all text-xs text-gray-500">
                      ID {entry.buyer_id}
                      {entry.item_id
                        ? ` · 商品级 · ${entry.item_id}`
                        : entry.account_id
                          ? ` · 账号级 · ${entry.account_id}`
                          : ' · 全部账号'}
                      {entry.reason ? ` · ${entry.reason}` : ''}
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={() => void removeBlacklist(entry)}
                    title="移除黑名单"
                    className="flex h-9 w-9 items-center justify-center rounded-lg bg-red-50 text-red-600 hover:bg-red-100"
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                </div>
              ))}
              {blacklist.length === 0 && (
                <p className="py-8 text-center text-sm text-gray-500">暂无适用于当前账号的黑名单记录</p>
              )}
            </div>
          </section>
        </>
      )}
    </div>
  );
};

export default DeliveryProtection;
