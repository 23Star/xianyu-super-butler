import React, { useEffect, useMemo, useState } from 'react';
import {
  Archive,
  CheckCircle2,
  ExternalLink,
  FileSearch,
  Link2,
  Loader2,
  PackageCheck,
  Pencil,
  Play,
  RefreshCw,
  Save,
  Search,
  ShieldCheck,
  Trash2,
  X,
} from 'lucide-react';

import {
  AccountDetail,
  AutomationTaskRun,
  ProductDeletePreview,
  ProductDeleteRule,
  ProductFilterRule,
  ProductMaterial,
} from '../types';
import {
  compensateProductCards,
  deleteProductDeleteRule,
  deleteProductFilterRule,
  deleteProductMaterial,
  getAccountDetails,
  getProductAutomationRuns,
  getProductDeleteRules,
  getProductFilterRules,
  getProductMaterials,
  previewProductDeleteRule,
  repairProductShortLinks,
  repairPublishedProductIds,
  runProductFilterRule,
  saveProductDeleteRule,
  saveProductFilterRule,
  updateProductMaterial,
} from '../services/api';
import { confirmAction, notify } from '../services/feedback';

type TabKey = 'materials' | 'filters' | 'delete' | 'repairs';

const tabs: Array<{ id: TabKey; label: string; icon: React.ElementType }> = [
  { id: 'materials', label: '素材库', icon: Archive },
  { id: 'filters', label: '筛选规则', icon: Search },
  { id: 'delete', label: '删除计划', icon: Trash2 },
  { id: 'repairs', label: '补偿任务', icon: ShieldCheck },
];

const emptyFilterForm = {
  id: undefined as number | undefined,
  cookie_id: '',
  name: '',
  include_keywords: '',
  exclude_keywords: '',
  min_price: '',
  max_price: '',
  category: '',
  daily_limit: '50',
  enabled: true,
};

const emptyDeleteForm = {
  id: undefined as number | undefined,
  cookie_id: '',
  name: '',
  min_publish_days: '30',
  daily_limit: '10',
  skip_reply_activity: true,
  skip_order_activity: true,
  enabled: false,
};

const splitKeywords = (value: string) => (
  value
    .split(/[,，\n]/)
    .map((item) => item.trim())
    .filter(Boolean)
);

const formatDate = (value?: string) => {
  if (!value) return '-';
  const date = new Date(value.includes('T') ? value : `${value.replace(' ', 'T')}Z`);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { hour12: false });
};

const normalizeImage = (value?: string) => {
  if (!value) return '';
  return value.startsWith('//') ? `https:${value}` : value;
};

const taskNames: Record<string, string> = {
  material_filter: '素材筛选',
  delete_preview: '删除预演',
  published_id_repair: '商品 ID 回写',
  short_link_repair: '链接修复',
  card_compensation: '卡券补偿',
};

const ProductAutomation: React.FC = () => {
  const [activeTab, setActiveTab] = useState<TabKey>('materials');
  const [accounts, setAccounts] = useState<AccountDetail[]>([]);
  const [materials, setMaterials] = useState<ProductMaterial[]>([]);
  const [filterRules, setFilterRules] = useState<ProductFilterRule[]>([]);
  const [deleteRules, setDeleteRules] = useState<ProductDeleteRule[]>([]);
  const [runs, setRuns] = useState<AutomationTaskRun[]>([]);
  const [loading, setLoading] = useState(true);
  const [busyKey, setBusyKey] = useState('');
  const [accountFilter, setAccountFilter] = useState('');
  const [materialQuery, setMaterialQuery] = useState('');
  const [editingMaterial, setEditingMaterial] = useState<ProductMaterial | null>(null);
  const [filterForm, setFilterForm] = useState(emptyFilterForm);
  const [deleteForm, setDeleteForm] = useState(emptyDeleteForm);
  const [preview, setPreview] = useState<ProductDeletePreview | null>(null);

  const accountNames = useMemo(
    () => new Map(accounts.map((account) => [
      account.id,
      account.nickname || account.remark || `账号 ${account.id.slice(0, 6)}`,
    ])),
    [accounts],
  );

  const visibleMaterials = useMemo(() => {
    const query = materialQuery.trim().toLowerCase();
    return materials.filter((material) => {
      if (accountFilter && material.cookie_id !== accountFilter) return false;
      if (!query) return true;
      return [
        material.title,
        material.source_item_id,
        material.published_item_id,
        material.category,
      ].some((value) => String(value || '').toLowerCase().includes(query));
    });
  }, [materials, accountFilter, materialQuery]);

  const loadAll = async (showLoader = true) => {
    if (showLoader) setLoading(true);
    try {
      const [accountData, materialData, filterData, deleteData, runData] = await Promise.all([
        getAccountDetails(),
        getProductMaterials(),
        getProductFilterRules(),
        getProductDeleteRules(),
        getProductAutomationRuns(),
      ]);
      setAccounts(accountData);
      setMaterials(materialData);
      setFilterRules(filterData);
      setDeleteRules(deleteData);
      setRuns(runData);
      if (!filterForm.cookie_id && accountData[0]) {
        setFilterForm((current) => ({ ...current, cookie_id: accountData[0].id }));
      }
      if (!deleteForm.cookie_id && accountData[0]) {
        setDeleteForm((current) => ({ ...current, cookie_id: accountData[0].id }));
      }
    } catch (error) {
      notify(`商品自动化数据加载失败：${(error as Error).message}`, 'error');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadAll();
  }, []);

  const saveMaterial = async () => {
    if (!editingMaterial) return;
    setBusyKey(`material-${editingMaterial.id}`);
    try {
      const saved = await updateProductMaterial(editingMaterial.id, {
        title: editingMaterial.title,
        description: editingMaterial.description,
        category: editingMaterial.category,
        price: editingMaterial.price,
        images: editingMaterial.images,
        source_url: editingMaterial.source_url,
        short_url: editingMaterial.short_url,
        delivery_content: editingMaterial.delivery_content,
        publish_status: editingMaterial.publish_status,
        published_item_id: editingMaterial.published_item_id,
        publish_trace_code: editingMaterial.publish_trace_code,
      });
      setMaterials((current) => current.map((item) => item.id === saved.id ? saved : item));
      setEditingMaterial(null);
      notify('素材已保存', 'success');
    } catch (error) {
      notify(`素材保存失败：${(error as Error).message}`, 'error');
    } finally {
      setBusyKey('');
    }
  };

  const removeMaterial = async (material: ProductMaterial) => {
    const confirmed = await confirmAction(`删除本地素材“${material.title}”？`, {
      title: '删除素材',
      confirmLabel: '删除',
    });
    if (!confirmed) return;
    setBusyKey(`material-${material.id}`);
    try {
      await deleteProductMaterial(material.id);
      setMaterials((current) => current.filter((item) => item.id !== material.id));
      notify('素材已删除', 'success');
    } catch (error) {
      notify(`删除失败：${(error as Error).message}`, 'error');
    } finally {
      setBusyKey('');
    }
  };

  const editFilterRule = (rule: ProductFilterRule) => {
    setFilterForm({
      id: rule.id,
      cookie_id: rule.cookie_id,
      name: rule.name,
      include_keywords: rule.include_keywords.join('，'),
      exclude_keywords: rule.exclude_keywords.join('，'),
      min_price: rule.min_price == null ? '' : String(rule.min_price),
      max_price: rule.max_price == null ? '' : String(rule.max_price),
      category: rule.category || '',
      daily_limit: String(rule.daily_limit),
      enabled: rule.enabled,
    });
  };

  const saveFilterRule = async () => {
    if (!filterForm.cookie_id || !filterForm.name.trim()) {
      notify('请选择账号并填写规则名称', 'warning');
      return;
    }
    setBusyKey('filter-save');
    try {
      const saved = await saveProductFilterRule({
        id: filterForm.id,
        cookie_id: filterForm.cookie_id,
        name: filterForm.name.trim(),
        include_keywords: splitKeywords(filterForm.include_keywords),
        exclude_keywords: splitKeywords(filterForm.exclude_keywords),
        min_price: filterForm.min_price === '' ? undefined : Number(filterForm.min_price),
        max_price: filterForm.max_price === '' ? undefined : Number(filterForm.max_price),
        category: filterForm.category.trim(),
        daily_limit: Number(filterForm.daily_limit) || 50,
        enabled: filterForm.enabled,
      });
      setFilterRules((current) => {
        const exists = current.some((item) => item.id === saved.id);
        return exists ? current.map((item) => item.id === saved.id ? saved : item) : [saved, ...current];
      });
      setFilterForm({ ...emptyFilterForm, cookie_id: filterForm.cookie_id });
      notify('筛选规则已保存', 'success');
    } catch (error) {
      notify(`规则保存失败：${(error as Error).message}`, 'error');
    } finally {
      setBusyKey('');
    }
  };

  const runFilter = async (rule: ProductFilterRule) => {
    setBusyKey(`filter-run-${rule.id}`);
    try {
      const result = await runProductFilterRule(rule.id);
      notify(result.summary, 'success');
      await loadAll(false);
    } catch (error) {
      notify(`筛选执行失败：${(error as Error).message}`, 'error');
    } finally {
      setBusyKey('');
    }
  };

  const removeFilterRule = async (rule: ProductFilterRule) => {
    if (!await confirmAction(`删除筛选规则“${rule.name}”？`, { title: '删除规则', confirmLabel: '删除' })) return;
    try {
      await deleteProductFilterRule(rule.id);
      setFilterRules((current) => current.filter((item) => item.id !== rule.id));
      notify('筛选规则已删除', 'success');
    } catch (error) {
      notify(`删除失败：${(error as Error).message}`, 'error');
    }
  };

  const editDeleteRule = (rule: ProductDeleteRule) => {
    setDeleteForm({
      id: rule.id,
      cookie_id: rule.cookie_id,
      name: rule.name,
      min_publish_days: String(rule.min_publish_days),
      daily_limit: String(rule.daily_limit),
      skip_reply_activity: rule.skip_reply_activity,
      skip_order_activity: rule.skip_order_activity,
      enabled: rule.enabled,
    });
  };

  const saveDeletePlan = async () => {
    if (!deleteForm.cookie_id || !deleteForm.name.trim()) {
      notify('请选择账号并填写计划名称', 'warning');
      return;
    }
    setBusyKey('delete-save');
    try {
      const saved = await saveProductDeleteRule({
        id: deleteForm.id,
        cookie_id: deleteForm.cookie_id,
        name: deleteForm.name.trim(),
        min_publish_days: Number(deleteForm.min_publish_days) || 30,
        daily_limit: Number(deleteForm.daily_limit) || 10,
        skip_reply_activity: deleteForm.skip_reply_activity,
        skip_order_activity: deleteForm.skip_order_activity,
        enabled: deleteForm.enabled,
        execution_mode: 'dry_run',
      });
      setDeleteRules((current) => {
        const withoutSameAccount = current.filter((item) => item.cookie_id !== saved.cookie_id);
        return [saved, ...withoutSameAccount];
      });
      setDeleteForm({ ...emptyDeleteForm, cookie_id: deleteForm.cookie_id });
      notify('删除预演计划已保存', 'success');
    } catch (error) {
      notify(`计划保存失败：${(error as Error).message}`, 'error');
    } finally {
      setBusyKey('');
    }
  };

  const runDeletePreview = async (rule: ProductDeleteRule) => {
    setBusyKey(`delete-preview-${rule.id}`);
    try {
      const result = await previewProductDeleteRule(rule.id);
      setPreview(result);
      setRuns(await getProductAutomationRuns());
      notify(result.summary, 'info');
    } catch (error) {
      notify(`删除预演失败：${(error as Error).message}`, 'error');
    } finally {
      setBusyKey('');
    }
  };

  const removeDeleteRule = async (rule: ProductDeleteRule) => {
    if (!await confirmAction(`删除计划“${rule.name}”？`, { title: '删除计划', confirmLabel: '删除' })) return;
    try {
      await deleteProductDeleteRule(rule.id);
      setDeleteRules((current) => current.filter((item) => item.id !== rule.id));
      notify('删除计划已删除', 'success');
    } catch (error) {
      notify(`删除失败：${(error as Error).message}`, 'error');
    }
  };

  const runRepair = async (
    key: string,
    action: () => Promise<{ summary: string }>,
  ) => {
    setBusyKey(key);
    try {
      const result = await action();
      notify(result.summary, 'success');
      await loadAll(false);
    } catch (error) {
      notify(`任务执行失败：${(error as Error).message}`, 'error');
    } finally {
      setBusyKey('');
    }
  };

  if (loading) {
    return (
      <div className="flex justify-center py-24">
        <Loader2 className="h-8 w-8 animate-spin text-yellow-500" />
      </div>
    );
  }

  return (
    <div className="space-y-5 animate-fade-in">
      <div className="flex flex-col gap-4 border-b border-gray-200 pb-5 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <h2 className="text-2xl font-bold text-gray-900">商品自动化</h2>
          <div className="mt-4 flex flex-wrap gap-1 rounded-md bg-gray-100 p-1">
            {tabs.map((tab) => {
              const Icon = tab.icon;
              return (
                <button
                  key={tab.id}
                  type="button"
                  onClick={() => setActiveTab(tab.id)}
                  className={`flex items-center gap-2 rounded px-3 py-2 text-sm font-bold transition-colors ${
                    activeTab === tab.id ? 'bg-white text-gray-950 shadow-sm' : 'text-gray-500 hover:text-gray-900'
                  }`}
                >
                  <Icon className="h-4 w-4" />
                  {tab.label}
                </button>
              );
            })}
          </div>
        </div>
        <button
          type="button"
          onClick={() => void loadAll(false)}
          className="ios-btn-secondary flex items-center justify-center gap-2 rounded-md px-4 py-2.5 text-sm"
        >
          <RefreshCw className="h-4 w-4" />
          刷新
        </button>
      </div>

      {activeTab === 'materials' && (
        <section className="space-y-4">
          <div className="flex flex-col gap-3 sm:flex-row">
            <select
              value={accountFilter}
              onChange={(event) => setAccountFilter(event.target.value)}
              className="ios-input rounded-md px-3 py-2.5 text-sm sm:w-64"
            >
              <option value="">全部账号</option>
              {accounts.map((account) => (
                <option key={account.id} value={account.id}>{accountNames.get(account.id)}</option>
              ))}
            </select>
            <label className="relative flex-1">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
              <input
                value={materialQuery}
                onChange={(event) => setMaterialQuery(event.target.value)}
                placeholder="搜索标题、商品 ID 或分类"
                className="ios-input w-full rounded-md py-2.5 pl-10 pr-3 text-sm"
              />
            </label>
            <span className="self-center text-sm font-medium text-gray-500">{visibleMaterials.length} 条素材</span>
          </div>

          <div className="overflow-hidden rounded-lg border border-gray-200 bg-white">
            <div className="overflow-x-auto">
              <table className="min-w-[980px] w-full text-left text-sm">
                <thead className="bg-gray-50 text-xs font-bold text-gray-500">
                  <tr>
                    <th className="px-4 py-3">素材</th>
                    <th className="px-4 py-3">账号</th>
                    <th className="px-4 py-3">来源 / 发布 ID</th>
                    <th className="px-4 py-3">状态</th>
                    <th className="px-4 py-3">发货绑定</th>
                    <th className="px-4 py-3 text-right">操作</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {visibleMaterials.map((material) => (
                    <tr key={material.id} className="hover:bg-gray-50">
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-3">
                          <div className="h-12 w-12 flex-none overflow-hidden rounded bg-gray-100">
                            {material.images[0] ? (
                              <img
                                src={normalizeImage(material.images[0])}
                                alt=""
                                className="h-full w-full object-cover"
                                referrerPolicy="no-referrer"
                              />
                            ) : <Archive className="m-3 h-6 w-6 text-gray-300" />}
                          </div>
                          <div className="min-w-0">
                            <div className="max-w-72 truncate font-bold text-gray-900">{material.title}</div>
                            <div className="mt-1 text-xs text-gray-500">
                              {material.price == null ? '价格未设置' : `¥${material.price}`}
                              {material.category ? ` · ${material.category}` : ''}
                            </div>
                          </div>
                        </div>
                      </td>
                      <td className="px-4 py-3 text-gray-600">{accountNames.get(material.cookie_id) || material.cookie_id}</td>
                      <td className="px-4 py-3">
                        <div className="font-mono text-xs text-gray-700">{material.source_item_id}</div>
                        <div className="mt-1 font-mono text-xs text-gray-400">
                          {material.published_item_id || '尚未回写'}
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        <span className={`rounded px-2 py-1 text-xs font-bold ${
                          material.publish_status === 'published'
                            ? 'bg-green-50 text-green-700'
                            : 'bg-gray-100 text-gray-600'
                        }`}>
                          {material.publish_status === 'published' ? '已发布' : '草稿'}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-xs text-gray-600">
                        {material.auto_card_id ? `卡券 #${material.auto_card_id}` : '未绑定'}
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex justify-end gap-1">
                          {material.source_url && (
                            <a
                              href={material.source_url}
                              target="_blank"
                              rel="noreferrer"
                              title="打开来源商品"
                              className="rounded p-2 text-gray-500 hover:bg-gray-100 hover:text-gray-900"
                            >
                              <ExternalLink className="h-4 w-4" />
                            </a>
                          )}
                          <button
                            type="button"
                            title="编辑素材"
                            onClick={() => setEditingMaterial({ ...material, images: [...material.images] })}
                            className="rounded p-2 text-gray-500 hover:bg-gray-100 hover:text-gray-900"
                          >
                            <Pencil className="h-4 w-4" />
                          </button>
                          <button
                            type="button"
                            title="删除素材"
                            disabled={busyKey === `material-${material.id}`}
                            onClick={() => void removeMaterial(material)}
                            className="rounded p-2 text-red-500 hover:bg-red-50 disabled:opacity-50"
                          >
                            <Trash2 className="h-4 w-4" />
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {visibleMaterials.length === 0 && (
              <div className="py-16 text-center text-sm text-gray-500">暂无素材</div>
            )}
          </div>
        </section>
      )}

      {activeTab === 'filters' && (
        <section className="space-y-5">
          <div className="rounded-lg border border-gray-200 bg-white p-4">
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
              <label className="text-xs font-bold text-gray-600">
                账号
                <select
                  value={filterForm.cookie_id}
                  onChange={(event) => setFilterForm({ ...filterForm, cookie_id: event.target.value })}
                  className="ios-input mt-1.5 w-full rounded-md px-3 py-2.5 text-sm"
                >
                  <option value="">选择账号</option>
                  {accounts.map((account) => (
                    <option key={account.id} value={account.id}>{accountNames.get(account.id)}</option>
                  ))}
                </select>
              </label>
              <label className="text-xs font-bold text-gray-600">
                规则名称
                <input
                  value={filterForm.name}
                  onChange={(event) => setFilterForm({ ...filterForm, name: event.target.value })}
                  className="ios-input mt-1.5 w-full rounded-md px-3 py-2.5 text-sm"
                />
              </label>
              <label className="text-xs font-bold text-gray-600">
                包含关键词
                <input
                  value={filterForm.include_keywords}
                  onChange={(event) => setFilterForm({ ...filterForm, include_keywords: event.target.value })}
                  placeholder="逗号分隔"
                  className="ios-input mt-1.5 w-full rounded-md px-3 py-2.5 text-sm"
                />
              </label>
              <label className="text-xs font-bold text-gray-600">
                排除关键词
                <input
                  value={filterForm.exclude_keywords}
                  onChange={(event) => setFilterForm({ ...filterForm, exclude_keywords: event.target.value })}
                  placeholder="逗号分隔"
                  className="ios-input mt-1.5 w-full rounded-md px-3 py-2.5 text-sm"
                />
              </label>
              <label className="text-xs font-bold text-gray-600">
                最低价格
                <input
                  type="number"
                  min="0"
                  value={filterForm.min_price}
                  onChange={(event) => setFilterForm({ ...filterForm, min_price: event.target.value })}
                  className="ios-input mt-1.5 w-full rounded-md px-3 py-2.5 text-sm"
                />
              </label>
              <label className="text-xs font-bold text-gray-600">
                最高价格
                <input
                  type="number"
                  min="0"
                  value={filterForm.max_price}
                  onChange={(event) => setFilterForm({ ...filterForm, max_price: event.target.value })}
                  className="ios-input mt-1.5 w-full rounded-md px-3 py-2.5 text-sm"
                />
              </label>
              <label className="text-xs font-bold text-gray-600">
                分类
                <input
                  value={filterForm.category}
                  onChange={(event) => setFilterForm({ ...filterForm, category: event.target.value })}
                  className="ios-input mt-1.5 w-full rounded-md px-3 py-2.5 text-sm"
                />
              </label>
              <label className="text-xs font-bold text-gray-600">
                每日上限
                <input
                  type="number"
                  min="1"
                  max="1000"
                  value={filterForm.daily_limit}
                  onChange={(event) => setFilterForm({ ...filterForm, daily_limit: event.target.value })}
                  className="ios-input mt-1.5 w-full rounded-md px-3 py-2.5 text-sm"
                />
              </label>
            </div>
            <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-gray-100 pt-4">
              <button
                type="button"
                role="switch"
                aria-checked={filterForm.enabled}
                onClick={() => setFilterForm({ ...filterForm, enabled: !filterForm.enabled })}
                className="flex items-center gap-2 text-sm font-bold text-gray-700"
              >
                <span className={`relative h-6 w-11 rounded-full ${filterForm.enabled ? 'bg-yellow-400' : 'bg-gray-300'}`}>
                  <span className={`absolute left-1 top-1 h-4 w-4 rounded-full bg-white transition-transform ${filterForm.enabled ? 'translate-x-5' : ''}`} />
                </span>
                启用规则
              </button>
              <div className="flex gap-2">
                {filterForm.id && (
                  <button
                    type="button"
                    onClick={() => setFilterForm({ ...emptyFilterForm, cookie_id: filterForm.cookie_id })}
                    className="ios-btn-secondary rounded-md px-4 py-2.5 text-sm"
                  >
                    取消编辑
                  </button>
                )}
                <button
                  type="button"
                  onClick={() => void saveFilterRule()}
                  disabled={busyKey === 'filter-save'}
                  className="ios-btn-primary flex items-center gap-2 rounded-md px-4 py-2.5 text-sm disabled:opacity-50"
                >
                  {busyKey === 'filter-save' ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                  保存规则
                </button>
              </div>
            </div>
          </div>

          <div className="divide-y divide-gray-100 overflow-hidden rounded-lg border border-gray-200 bg-white">
            {filterRules.map((rule) => (
              <div key={rule.id} className="grid gap-4 p-4 lg:grid-cols-[minmax(220px,1.2fr)_minmax(260px,1.5fr)_180px_auto] lg:items-center">
                <div>
                  <div className="flex items-center gap-2">
                    <span className={`h-2.5 w-2.5 rounded-full ${rule.enabled ? 'bg-green-500' : 'bg-gray-300'}`} />
                    <span className="font-bold text-gray-900">{rule.name}</span>
                  </div>
                  <div className="mt-1 text-xs text-gray-500">{accountNames.get(rule.cookie_id) || rule.cookie_id}</div>
                </div>
                <div className="text-xs leading-5 text-gray-600">
                  <div>包含：{rule.include_keywords.join('、') || '不限'}</div>
                  <div>排除：{rule.exclude_keywords.join('、') || '无'}</div>
                </div>
                <div className="text-xs text-gray-500">
                  <div>今日 {rule.today_count}/{rule.daily_limit}</div>
                  <div className="mt-1">累计 {rule.total_count} · {formatDate(rule.last_run_at)}</div>
                </div>
                <div className="flex justify-end gap-1">
                  <button
                    type="button"
                    title="执行筛选"
                    disabled={!rule.enabled || busyKey === `filter-run-${rule.id}`}
                    onClick={() => void runFilter(rule)}
                    className="rounded p-2 text-green-700 hover:bg-green-50 disabled:opacity-40"
                  >
                    {busyKey === `filter-run-${rule.id}` ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
                  </button>
                  <button type="button" title="编辑规则" onClick={() => editFilterRule(rule)} className="rounded p-2 text-gray-500 hover:bg-gray-100">
                    <Pencil className="h-4 w-4" />
                  </button>
                  <button type="button" title="删除规则" onClick={() => void removeFilterRule(rule)} className="rounded p-2 text-red-500 hover:bg-red-50">
                    <Trash2 className="h-4 w-4" />
                  </button>
                </div>
              </div>
            ))}
            {filterRules.length === 0 && <div className="py-16 text-center text-sm text-gray-500">暂无筛选规则</div>}
          </div>
        </section>
      )}

      {activeTab === 'delete' && (
        <section className="space-y-5">
          <div className="flex items-center gap-3 rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
            <ShieldCheck className="h-5 w-5 flex-none" />
            当前执行模式固定为 dry-run，只生成候选记录，不会删除闲鱼商品或本地商品。
          </div>

          <div className="rounded-lg border border-gray-200 bg-white p-4">
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
              <label className="text-xs font-bold text-gray-600">
                账号
                <select
                  value={deleteForm.cookie_id}
                  onChange={(event) => setDeleteForm({ ...deleteForm, cookie_id: event.target.value })}
                  className="ios-input mt-1.5 w-full rounded-md px-3 py-2.5 text-sm"
                >
                  <option value="">选择账号</option>
                  {accounts.map((account) => (
                    <option key={account.id} value={account.id}>{accountNames.get(account.id)}</option>
                  ))}
                </select>
              </label>
              <label className="text-xs font-bold text-gray-600">
                计划名称
                <input
                  value={deleteForm.name}
                  onChange={(event) => setDeleteForm({ ...deleteForm, name: event.target.value })}
                  className="ios-input mt-1.5 w-full rounded-md px-3 py-2.5 text-sm"
                />
              </label>
              <label className="text-xs font-bold text-gray-600">
                最少上架天数
                <input
                  type="number"
                  min="1"
                  value={deleteForm.min_publish_days}
                  onChange={(event) => setDeleteForm({ ...deleteForm, min_publish_days: event.target.value })}
                  className="ios-input mt-1.5 w-full rounded-md px-3 py-2.5 text-sm"
                />
              </label>
              <label className="text-xs font-bold text-gray-600">
                每日候选上限
                <input
                  type="number"
                  min="1"
                  max="200"
                  value={deleteForm.daily_limit}
                  onChange={(event) => setDeleteForm({ ...deleteForm, daily_limit: event.target.value })}
                  className="ios-input mt-1.5 w-full rounded-md px-3 py-2.5 text-sm"
                />
              </label>
            </div>
            <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-gray-100 pt-4">
              <div className="flex flex-wrap gap-4">
                <label className="flex items-center gap-2 text-sm font-medium text-gray-700">
                  <input
                    type="checkbox"
                    checked={deleteForm.skip_reply_activity}
                    onChange={(event) => setDeleteForm({ ...deleteForm, skip_reply_activity: event.target.checked })}
                    className="h-4 w-4 accent-yellow-400"
                  />
                  排除有自动回复活动的商品
                </label>
                <label className="flex items-center gap-2 text-sm font-medium text-gray-700">
                  <input
                    type="checkbox"
                    checked={deleteForm.skip_order_activity}
                    onChange={(event) => setDeleteForm({ ...deleteForm, skip_order_activity: event.target.checked })}
                    className="h-4 w-4 accent-yellow-400"
                  />
                  排除有订单记录的商品
                </label>
              </div>
              <div className="flex gap-2">
                {deleteForm.id && (
                  <button
                    type="button"
                    onClick={() => setDeleteForm({ ...emptyDeleteForm, cookie_id: deleteForm.cookie_id })}
                    className="ios-btn-secondary rounded-md px-4 py-2.5 text-sm"
                  >
                    取消编辑
                  </button>
                )}
                <button
                  type="button"
                  onClick={() => void saveDeletePlan()}
                  disabled={busyKey === 'delete-save'}
                  className="ios-btn-primary flex items-center gap-2 rounded-md px-4 py-2.5 text-sm disabled:opacity-50"
                >
                  {busyKey === 'delete-save' ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                  保存计划
                </button>
              </div>
            </div>
          </div>

          <div className="divide-y divide-gray-100 overflow-hidden rounded-lg border border-gray-200 bg-white">
            {deleteRules.map((rule) => (
              <div key={rule.id} className="grid gap-4 p-4 lg:grid-cols-[minmax(220px,1fr)_1fr_180px_auto] lg:items-center">
                <div>
                  <div className="font-bold text-gray-900">{rule.name}</div>
                  <div className="mt-1 text-xs text-gray-500">{accountNames.get(rule.cookie_id) || rule.cookie_id}</div>
                </div>
                <div className="text-xs leading-5 text-gray-600">
                  上架 ≥ {rule.min_publish_days} 天 · 最多 {rule.daily_limit} 件
                  <br />
                  {rule.skip_reply_activity ? '排除自动回复活动' : '不检查自动回复'} · {rule.skip_order_activity ? '排除订单' : '不检查订单'}
                </div>
                <div>
                  <span className="rounded bg-amber-50 px-2 py-1 text-xs font-bold text-amber-700">DRY-RUN</span>
                  <div className="mt-2 text-xs text-gray-500">{formatDate(rule.last_run_at)}</div>
                </div>
                <div className="flex justify-end gap-1">
                  <button
                    type="button"
                    title="执行预演"
                    disabled={busyKey === `delete-preview-${rule.id}`}
                    onClick={() => void runDeletePreview(rule)}
                    className="rounded p-2 text-amber-700 hover:bg-amber-50 disabled:opacity-50"
                  >
                    {busyKey === `delete-preview-${rule.id}` ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileSearch className="h-4 w-4" />}
                  </button>
                  <button type="button" title="编辑计划" onClick={() => editDeleteRule(rule)} className="rounded p-2 text-gray-500 hover:bg-gray-100">
                    <Pencil className="h-4 w-4" />
                  </button>
                  <button type="button" title="删除计划" onClick={() => void removeDeleteRule(rule)} className="rounded p-2 text-red-500 hover:bg-red-50">
                    <Trash2 className="h-4 w-4" />
                  </button>
                </div>
              </div>
            ))}
            {deleteRules.length === 0 && <div className="py-16 text-center text-sm text-gray-500">暂无删除计划</div>}
          </div>
        </section>
      )}

      {activeTab === 'repairs' && (
        <section className="space-y-5">
          <div className="grid gap-3 lg:grid-cols-3">
            {[
              {
                key: 'repair-ids',
                title: '商品 ID 回写',
                label: '开始回写',
                icon: PackageCheck,
                action: repairPublishedProductIds,
              },
              {
                key: 'repair-links',
                title: '链接修复',
                label: '修复链接',
                icon: Link2,
                action: repairProductShortLinks,
              },
              {
                key: 'repair-cards',
                title: '卡券补偿',
                label: '补偿绑定',
                icon: CheckCircle2,
                action: compensateProductCards,
              },
            ].map((task) => {
              const Icon = task.icon;
              return (
                <div key={task.key} className="rounded-lg border border-gray-200 bg-white p-4">
                  <div className="flex items-center gap-3">
                    <div className="rounded-md bg-yellow-50 p-2 text-amber-700"><Icon className="h-5 w-5" /></div>
                    <h3 className="font-bold text-gray-900">{task.title}</h3>
                  </div>
                  <button
                    type="button"
                    disabled={busyKey === task.key}
                    onClick={() => void runRepair(task.key, task.action)}
                    className="ios-btn-primary mt-5 flex w-full items-center justify-center gap-2 rounded-md px-4 py-2.5 text-sm disabled:opacity-50"
                  >
                    {busyKey === task.key ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
                    {task.label}
                  </button>
                </div>
              );
            })}
          </div>

          <div className="overflow-hidden rounded-lg border border-gray-200 bg-white">
            <div className="flex items-center justify-between border-b border-gray-100 px-4 py-3">
              <h3 className="font-bold text-gray-900">执行记录</h3>
              <span className="text-xs text-gray-500">最近 {runs.length} 条</span>
            </div>
            <div className="overflow-x-auto">
              <table className="min-w-[820px] w-full text-left text-sm">
                <thead className="bg-gray-50 text-xs font-bold text-gray-500">
                  <tr>
                    <th className="px-4 py-3">任务</th>
                    <th className="px-4 py-3">模式</th>
                    <th className="px-4 py-3">检查 / 命中 / 变更 / 失败</th>
                    <th className="px-4 py-3">结果</th>
                    <th className="px-4 py-3">时间</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {runs.map((run) => (
                    <tr key={run.id}>
                      <td className="px-4 py-3 font-bold text-gray-800">{taskNames[run.task_type] || run.task_type}</td>
                      <td className="px-4 py-3 text-xs font-mono text-gray-500">{run.execution_mode}</td>
                      <td className="px-4 py-3 text-gray-600">
                        {run.checked_count} / {run.matched_count} / {run.changed_count} / {run.failed_count}
                      </td>
                      <td className="max-w-md px-4 py-3 text-gray-600">{run.summary || run.error_message || '-'}</td>
                      <td className="whitespace-nowrap px-4 py-3 text-xs text-gray-500">{formatDate(run.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {runs.length === 0 && <div className="py-16 text-center text-sm text-gray-500">暂无执行记录</div>}
          </div>
        </section>
      )}

      {editingMaterial && (
        <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/40 p-0 sm:items-center sm:p-4">
          <div className="max-h-[92vh] w-full overflow-y-auto rounded-t-lg bg-white shadow-xl sm:max-w-3xl sm:rounded-lg">
            <div className="sticky top-0 z-10 flex items-center justify-between border-b border-gray-200 bg-white px-5 py-4">
              <h3 className="font-bold text-gray-900">编辑素材</h3>
              <button type="button" onClick={() => setEditingMaterial(null)} className="rounded p-2 text-gray-500 hover:bg-gray-100" aria-label="关闭">
                <X className="h-5 w-5" />
              </button>
            </div>
            <div className="grid gap-4 p-5 md:grid-cols-2">
              <label className="text-xs font-bold text-gray-600 md:col-span-2">
                标题
                <input
                  value={editingMaterial.title}
                  onChange={(event) => setEditingMaterial({ ...editingMaterial, title: event.target.value })}
                  className="ios-input mt-1.5 w-full rounded-md px-3 py-2.5 text-sm"
                />
              </label>
              <label className="text-xs font-bold text-gray-600">
                分类
                <input
                  value={editingMaterial.category}
                  onChange={(event) => setEditingMaterial({ ...editingMaterial, category: event.target.value })}
                  className="ios-input mt-1.5 w-full rounded-md px-3 py-2.5 text-sm"
                />
              </label>
              <label className="text-xs font-bold text-gray-600">
                价格
                <input
                  type="number"
                  min="0"
                  value={editingMaterial.price ?? ''}
                  onChange={(event) => setEditingMaterial({
                    ...editingMaterial,
                    price: event.target.value === '' ? undefined : Number(event.target.value),
                  })}
                  className="ios-input mt-1.5 w-full rounded-md px-3 py-2.5 text-sm"
                />
              </label>
              <label className="text-xs font-bold text-gray-600 md:col-span-2">
                描述
                <textarea
                  rows={5}
                  value={editingMaterial.description}
                  onChange={(event) => setEditingMaterial({ ...editingMaterial, description: event.target.value })}
                  className="ios-input mt-1.5 w-full resize-y rounded-md px-3 py-2.5 text-sm"
                />
              </label>
              <label className="text-xs font-bold text-gray-600 md:col-span-2">
                发货内容
                <textarea
                  rows={4}
                  value={editingMaterial.delivery_content}
                  onChange={(event) => setEditingMaterial({ ...editingMaterial, delivery_content: event.target.value })}
                  className="ios-input mt-1.5 w-full resize-y rounded-md px-3 py-2.5 text-sm"
                />
              </label>
              <label className="text-xs font-bold text-gray-600">
                已发布商品 ID
                <input
                  value={editingMaterial.published_item_id}
                  onChange={(event) => setEditingMaterial({ ...editingMaterial, published_item_id: event.target.value })}
                  className="ios-input mt-1.5 w-full rounded-md px-3 py-2.5 text-sm"
                />
              </label>
              <label className="text-xs font-bold text-gray-600">
                追踪码
                <input
                  value={editingMaterial.publish_trace_code}
                  onChange={(event) => setEditingMaterial({ ...editingMaterial, publish_trace_code: event.target.value })}
                  className="ios-input mt-1.5 w-full rounded-md px-3 py-2.5 text-sm"
                />
              </label>
              <label className="text-xs font-bold text-gray-600">
                来源链接
                <input
                  value={editingMaterial.source_url}
                  onChange={(event) => setEditingMaterial({ ...editingMaterial, source_url: event.target.value })}
                  className="ios-input mt-1.5 w-full rounded-md px-3 py-2.5 text-sm"
                />
              </label>
              <label className="text-xs font-bold text-gray-600">
                短链
                <input
                  value={editingMaterial.short_url}
                  onChange={(event) => setEditingMaterial({ ...editingMaterial, short_url: event.target.value })}
                  className="ios-input mt-1.5 w-full rounded-md px-3 py-2.5 text-sm"
                />
              </label>
            </div>
            <div className="sticky bottom-0 flex justify-end gap-2 border-t border-gray-200 bg-white px-5 py-4">
              <button type="button" onClick={() => setEditingMaterial(null)} className="ios-btn-secondary rounded-md px-4 py-2.5 text-sm">取消</button>
              <button
                type="button"
                onClick={() => void saveMaterial()}
                disabled={busyKey === `material-${editingMaterial.id}`}
                className="ios-btn-primary flex items-center gap-2 rounded-md px-4 py-2.5 text-sm disabled:opacity-50"
              >
                {busyKey === `material-${editingMaterial.id}` ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                保存
              </button>
            </div>
          </div>
        </div>
      )}

      {preview && (
        <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/40 p-0 sm:items-center sm:p-4">
          <div className="max-h-[90vh] w-full overflow-y-auto rounded-t-lg bg-white shadow-xl sm:max-w-4xl sm:rounded-lg">
            <div className="sticky top-0 z-10 flex items-center justify-between border-b border-gray-200 bg-white px-5 py-4">
              <div>
                <h3 className="font-bold text-gray-900">删除预演结果</h3>
                <p className="mt-1 text-xs text-gray-500">{preview.summary}</p>
              </div>
              <button type="button" onClick={() => setPreview(null)} className="rounded p-2 text-gray-500 hover:bg-gray-100" aria-label="关闭">
                <X className="h-5 w-5" />
              </button>
            </div>
            <div className="grid gap-6 p-5 lg:grid-cols-2">
              <div>
                <h4 className="mb-3 text-sm font-bold text-amber-800">候选 {preview.candidates.length}</h4>
                <div className="divide-y divide-gray-100 border-y border-gray-200">
                  {preview.candidates.map((item) => (
                    <div key={item.item_id} className="py-3">
                      <div className="font-medium text-gray-900">{item.item_title || item.item_id}</div>
                      <div className="mt-1 text-xs text-gray-500">ID {item.item_id} · {item.age_days || 0} 天 · {item.reason}</div>
                    </div>
                  ))}
                  {preview.candidates.length === 0 && <div className="py-8 text-center text-sm text-gray-500">无候选商品</div>}
                </div>
              </div>
              <div>
                <h4 className="mb-3 text-sm font-bold text-gray-700">已跳过 {preview.skipped.length}</h4>
                <div className="divide-y divide-gray-100 border-y border-gray-200">
                  {preview.skipped.map((item) => (
                    <div key={item.item_id} className="py-3">
                      <div className="font-medium text-gray-900">{item.item_title || item.item_id}</div>
                      <div className="mt-1 text-xs text-gray-500">ID {item.item_id} · {item.reason}</div>
                    </div>
                  ))}
                  {preview.skipped.length === 0 && <div className="py-8 text-center text-sm text-gray-500">无跳过记录</div>}
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default ProductAutomation;
