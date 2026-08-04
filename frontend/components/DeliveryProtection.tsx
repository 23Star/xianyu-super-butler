import React, { useEffect, useState } from 'react';
import { RefreshCw, Save, ShieldAlert, Trash2, UserRoundX } from 'lucide-react';

import { AccountDetail, DeliveryBlockRule, PersonalBlacklistEntry } from '../types';
import {
  createPersonalBlacklist,
  deletePersonalBlacklist,
  getAccountDetails,
  getDeliveryBlockRules,
  getPersonalBlacklist,
  updateDeliveryBlockRule,
  updatePersonalBlacklist,
} from '../services/api';

const DeliveryProtection: React.FC = () => {
  const [accounts, setAccounts] = useState<AccountDetail[]>([]);
  const [selectedAccount, setSelectedAccount] = useState('');
  const [rules, setRules] = useState<DeliveryBlockRule[]>([]);
  const [blacklist, setBlacklist] = useState<PersonalBlacklistEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [savingRule, setSavingRule] = useState('');
  const [form, setForm] = useState({ buyer_id: '', buyer_nick: '', item_id: '', reason: '' });

  useEffect(() => {
    getAccountDetails()
      .then((data) => {
        setAccounts(data);
        if (data.length > 0) setSelectedAccount(data[0].id);
      })
      .catch((error) => console.error('加载账号失败', error));
  }, []);

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
      alert(`加载发货保护配置失败：${(error as Error).message}`);
    } finally {
      setLoading(false);
    }
  };

  const patchRule = (ruleCode: string, changes: Partial<DeliveryBlockRule>) => {
    setRules((current) => current.map((rule) => (
      rule.rule_code === ruleCode ? { ...rule, ...changes } : rule
    )));
  };

  const saveRule = async (rule: DeliveryBlockRule) => {
    setSavingRule(rule.rule_code);
    try {
      const saved = await updateDeliveryBlockRule(selectedAccount, rule.rule_code, {
        enabled: rule.enabled,
        priority: rule.priority,
        block_reason: rule.block_reason,
        excluded_item_ids: rule.excluded_item_ids,
        config: rule.config,
      });
      patchRule(rule.rule_code, saved);
    } catch (error) {
      alert(`保存失败：${(error as Error).message}`);
    } finally {
      setSavingRule('');
    }
  };

  const addBlacklist = async () => {
    if (!form.buyer_id.trim()) {
      alert('请输入买家 ID');
      return;
    }
    try {
      await createPersonalBlacklist({
        account_id: selectedAccount,
        buyer_id: form.buyer_id.trim(),
        buyer_nick: form.buyer_nick.trim(),
        item_id: form.item_id.trim() || undefined,
        reason: form.reason.trim(),
        is_enabled: true,
      });
      setForm({ buyer_id: '', buyer_nick: '', item_id: '', reason: '' });
      setBlacklist(await getPersonalBlacklist(selectedAccount));
    } catch (error) {
      alert(`添加失败：${(error as Error).message}`);
    }
  };

  const toggleBlacklist = async (entry: PersonalBlacklistEntry) => {
    try {
      const saved = await updatePersonalBlacklist(entry.id, { is_enabled: !entry.is_enabled });
      setBlacklist((current) => current.map((item) => item.id === entry.id ? saved : item));
    } catch (error) {
      alert(`更新失败：${(error as Error).message}`);
    }
  };

  const removeBlacklist = async (entry: PersonalBlacklistEntry) => {
    if (!confirm(`确认移除买家 ${entry.buyer_nick || entry.buyer_id}？`)) return;
    try {
      await deletePersonalBlacklist(entry.id);
      setBlacklist((current) => current.filter((item) => item.id !== entry.id));
    } catch (error) {
      alert(`删除失败：${(error as Error).message}`);
    }
  };

  return (
    <div className="space-y-5">
      <div className="flex flex-col gap-3 border-b border-gray-200 pb-5 sm:flex-row sm:items-end sm:justify-between">
        <div className="w-full sm:max-w-sm">
          <label className="mb-2 block text-sm font-bold text-gray-700">应用账号</label>
          <select
            value={selectedAccount}
            onChange={(event) => setSelectedAccount(event.target.value)}
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
                <div key={rule.rule_code} className="grid gap-3 py-4 lg:grid-cols-[minmax(220px,1fr)_90px_minmax(240px,1.3fr)_44px] lg:items-center">
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
                  <button
                    type="button"
                    onClick={() => void saveRule(rule)}
                    disabled={savingRule === rule.rule_code}
                    title="保存规则"
                    className="flex h-10 w-10 items-center justify-center rounded-lg bg-gray-900 text-white hover:bg-gray-700 disabled:opacity-50"
                  >
                    <Save className="h-4 w-4" />
                  </button>
                </div>
              ))}
            </div>
          </section>

          <section className="pt-2">
            <div className="mb-3 flex items-center gap-2">
              <UserRoundX className="h-5 w-5 text-red-600" />
              <h3 className="text-base font-bold text-gray-900">当前账号黑名单</h3>
            </div>
            <div className="grid gap-2 border-y border-gray-200 py-4 md:grid-cols-2 xl:grid-cols-5">
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
              <input
                value={form.item_id}
                onChange={(event) => setForm({ ...form, item_id: event.target.value })}
                placeholder="商品 ID（留空为账号级）"
                className="rounded-md border border-gray-200 px-3 py-2 text-sm"
              />
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
                      {entry.item_id ? ` · 商品 ${entry.item_id}` : ' · 当前账号全部商品'}
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
                <p className="py-8 text-center text-sm text-gray-500">当前账号暂无黑名单记录</p>
              )}
            </div>
          </section>
        </>
      )}
    </div>
  );
};

export default DeliveryProtection;
