import React, { useEffect, useMemo, useState } from 'react';
import { Loader2, Save, ScanLine, ShieldAlert } from 'lucide-react';
import { EmptyState, NoticeBanner, PageHeader } from './ui';
import TagPicker, { type TagPickerOption } from './TagPicker';
import {
  getAccountDetails,
  getItems,
  getDeliverySkuOptions,
  buyerTestDeliverySkuOptions,
  saveDeliverySkuRules,
  DeliverySkuDiscovery,
  DeliverySkuOption,
} from '../services/api';
import { confirmAction } from '../services/feedback';
import type { AccountDetail, Item } from '../types';

type Rule = { max_deliveries: number; block_message: string };

const accountLabel = (account: AccountDetail) =>
  account.nickname || account.remark || `账号 ${account.id.substring(0, 6)}`;

export default function SkuAntiAbusePage() {
  const [accounts, setAccounts] = useState<AccountDetail[]>([]);
  const [items, setItems] = useState<Item[]>([]);
  const [loading, setLoading] = useState(true);
  const [cookieId, setCookieId] = useState('');
  const [itemId, setItemId] = useState('');
  const [rows, setRows] = useState<DeliverySkuOption[]>([]);
  const [rules, setRules] = useState<Record<string, Rule>>({});
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');
  const [detectionStatus, setDetectionStatus] = useState('');
  const [retryAfterSeconds, setRetryAfterSeconds] = useState(0);
  const [warning, setWarning] = useState('');

  useEffect(() => {
    Promise.all([getAccountDetails(), getItems()])
      .then(([a, i]) => { setAccounts(a || []); setItems(i || []); })
      .catch(() => setError('账号或商品加载失败'))
      .finally(() => setLoading(false));
  }, []);

  const accountOptions = useMemo<TagPickerOption[]>(
    () => accounts.map(account => ({
      value: account.id,
      label: accountLabel(account),
      description: `账号 ${account.id}`,
      imageUrl: account.avatar_url,
    })),
    [accounts],
  );

  const itemOptions = useMemo<TagPickerOption[]>(
    () => items
      .filter(item => item.cookie_id === cookieId)
      .map(item => {
        const title = (item.item_title || '').trim();
        const price = (item.item_price || '').trim().replace(/^[¥￥]\s*/, '');
        return {
          value: item.item_id,
          label: title || `商品 ${item.item_id}`,
          description: [item.item_id, price ? `¥${price}` : ''].filter(Boolean).join(' · '),
          imageUrl: item.item_image,
        };
      }),
    [items, cookieId],
  );

  const applyDiscovery = (data: DeliverySkuDiscovery) => {
    setRows(data.options);
    setRules(current => Object.fromEntries(
      data.options.map(row => [row.key, current[row.key] || { max_deliveries: 1, block_message: '' }]),
    ));
    setDetectionStatus(data.detection_status);
    setRetryAfterSeconds(data.retry_after_seconds || 0);
    setWarning(data.warning || '');
    if (data.detection_status === 'unauthorized') {
      setNotice('');
    } else if (data.detection_status === 'risk_control') {
      setNotice('');
    } else {
      setNotice(data.options.length
        ? `已识别 ${data.options.length} 个 SKU，可设置防薅规则`
        : '暂无可识别 SKU，请先在商品发货配置中维护规格或完成一笔订单');
    }
  };

  const resetDetection = () => {
    setRows([]);
    setRules({});
    setDetectionStatus('');
    setRetryAfterSeconds(0);
    setWarning('');
    setNotice('');
    setError('');
  };

  const selectAccount = (next: string[]) => {
    setCookieId(next[0] || '');
    setItemId('');
    resetDetection();
  };

  const selectItem = (next: string[]) => {
    setItemId(next[0] || '');
    resetDetection();
  };

  const discover = async () => {
    if (!cookieId || !itemId) return setError('请先选择账号和商品');
    setBusy(true); setError(''); setWarning('');
    try {
      applyDiscovery(await getDeliverySkuOptions(cookieId, itemId));
    } catch (e) {
      setDetectionStatus(''); setError(e instanceof Error ? e.message : '识别失败');
    } finally {
      setBusy(false);
    }
  };

  const probeBuyer = async () => {
    if (!cookieId || !itemId) return;
    const confirmed = await confirmAction(
      '卖家接口没有该商品的 SKU 读取权限。买家接口会以买家身份读取商品详情，风控风险更高，只调用一次且失败不会自动重试。确认继续吗？',
      { title: '尝试买家接口', confirmLabel: '仍然调用一次', danger: true },
    );
    if (!confirmed) return;
    setBusy(true); setError(''); setWarning('');
    try {
      applyDiscovery(await buyerTestDeliverySkuOptions(cookieId, itemId));
    } catch (e) {
      setError(e instanceof Error ? e.message : '买家接口识别失败');
    } finally {
      setBusy(false);
    }
  };

  const save = async () => {
    setBusy(true); setError('');
    try {
      await saveDeliverySkuRules(cookieId, itemId, rows.map(row => ({
        key: row.key,
        name: row.name,
        enabled: true,
        max_deliveries: Math.max(1, Math.min(100, rules[row.key]?.max_deliveries || 1)),
        block_message: rules[row.key]?.block_message || '',
      })));
      setNotice('防薅规则已保存');
    } catch (e) {
      setError(e instanceof Error ? e.message : '保存失败');
    } finally {
      setBusy(false);
    }
  };

  const cooldownMinutes = Math.max(1, Math.ceil(retryAfterSeconds / 60));

  return (
    <div className="page-stack animate-fade-in">
      <PageHeader title="SKU 防薅" description="按账号、商品和 SKU 设置同一买家的自动发货上限。" />
      <div className="overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--surface)] shadow-[var(--shadow-sm)]">
        <div className="border-b border-[var(--border)] bg-gradient-to-r from-amber-50 to-white px-6 py-6 dark:from-amber-950/20 dark:to-[var(--surface)]">
          <div className="flex items-start gap-4">
            <span className="grid h-12 w-12 shrink-0 place-items-center rounded-2xl bg-[var(--brand)] text-[#2a2416] shadow-[var(--shadow-brand)]">
              <ShieldAlert size={23} />
            </span>
            <div>
              <h2 className="text-lg font-bold text-[var(--text)]">先识别，再设置限制</h2>
              <p className="mt-1 text-sm leading-6 text-[var(--text-muted)]">识别只读取已有 SKU 数据；限制规则只在本页面生效。</p>
            </div>
          </div>
        </div>
        <div className="grid gap-4 px-6 py-5 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto_auto] md:items-end">
          <div>
            <span className="field-label">账号</span>
            <TagPicker
              options={accountOptions}
              selected={cookieId ? [cookieId] : []}
              onChange={selectAccount}
              multiple={false}
              searchable={false}
              placeholder="选择账号"
              emptyText="暂无可选账号"
              loading={loading}
              loadingText="正在加载账号"
              ariaLabel="选择账号"
            />
          </div>
          <div>
            <span className="field-label">商品</span>
            <TagPicker
              options={itemOptions}
              selected={itemId ? [itemId] : []}
              onChange={selectItem}
              multiple={false}
              searchable
              disabled={!cookieId}
              placeholder={cookieId ? '选择商品' : '请先选择账号'}
              searchPlaceholder="搜索商品标题"
              emptyText="该账号暂无商品"
              loading={loading}
              loadingText="正在加载商品"
              ariaLabel="选择商品"
            />
          </div>
          <button className="ios-btn-secondary inline-flex h-11 items-center justify-center gap-2 rounded-xl px-5 text-sm font-semibold" disabled={busy} onClick={discover}>
            {busy ? <Loader2 className="animate-spin" size={16} /> : <ScanLine size={16} />}识别 SKU
          </button>
          <button className="ios-btn-primary inline-flex h-11 items-center justify-center gap-2 rounded-xl px-5 text-sm font-semibold disabled:opacity-40" disabled={busy || !rows.length} onClick={save}>
            <Save size={16} />保存规则
          </button>
        </div>
        {error && (
          <div className="mx-6 mb-4">
            <NoticeBanner type="error" message={error} />
          </div>
        )}
        {detectionStatus === 'unauthorized' && (
          <div className="mx-6 mb-4 space-y-3">
            <NoticeBanner type="warning">
              <span className="block">
                <span className="block font-semibold">该账号没有卖家 SKU 接口权限</span>
                <span className="mt-1 block text-xs font-normal leading-5 opacity-80">下单后系统会自动记录订单里的 SKU；也可以点下方按钮用买家接口尝试一次（风控风险更高，失败不会自动重试）。</span>
                {warning && <span className="mt-1 block break-all text-xs font-normal opacity-70">{warning}</span>}
              </span>
            </NoticeBanner>
            <button type="button" onClick={probeBuyer} disabled={busy} className="ios-btn-secondary inline-flex h-9 items-center justify-center gap-2 rounded-lg px-4 text-xs font-semibold disabled:opacity-50">
              {busy ? <Loader2 className="animate-spin" size={14} /> : <ScanLine size={14} />}尝试买家 SKU 接口
            </button>
          </div>
        )}
        {detectionStatus === 'risk_control' && (
          <div className="mx-6 mb-4">
            <NoticeBanner
              type="warning"
              message={`触发平台风控，已暂停识别请求，请约 ${cooldownMinutes} 分钟后再试。${warning ? `（${warning}）` : ''}`}
            />
          </div>
        )}
        {detectionStatus && detectionStatus !== 'unauthorized' && detectionStatus !== 'risk_control' && warning && (
          <div className="mx-6 mb-4">
            <NoticeBanner type="info" message={`商家接口暂时不可用，已返回本地 SKU：${warning}`} />
          </div>
        )}
        {notice && (
          <div className="mx-6 mb-4">
            <NoticeBanner type="success" message={notice} />
          </div>
        )}
        <div className="border-t border-[var(--border)] px-6 py-5">
          <div className="mb-4 flex items-center justify-between">
            <div>
              <h3 className="font-bold text-[var(--text)]">已识别规格</h3>
              <p className="mt-1 text-xs text-[var(--text-soft)]">限制按买家累计自动发货次数计算，范围 1–100 次。</p>
            </div>
            <span className="rounded-full bg-amber-100 px-3 py-1 text-xs font-bold text-amber-800">{rows.length} 个 SKU</span>
          </div>
          {rows.length ? (
            <div className="space-y-3">
              {rows.map(row => (
                <div key={row.key} className="grid gap-4 rounded-xl border border-[var(--border)] bg-[var(--surface-hover)] p-4 md:grid-cols-[minmax(0,1fr)_150px_minmax(0,1.4fr)] md:items-center">
                  <div className="min-w-0">
                    <p className="truncate font-semibold text-[var(--text)]">{row.name}</p>
                    <p className="mt-1 truncate font-mono text-xs text-[var(--text-soft)]">{row.key}</p>
                  </div>
                  <label className="field-label">
                    最多自动发货
                    <input
                      className="ios-input mt-2 h-10 w-full rounded-lg"
                      type="number"
                      min={1}
                      max={100}
                      value={rules[row.key]?.max_deliveries || 1}
                      onChange={e => setRules(x => ({ ...x, [row.key]: { ...x[row.key], max_deliveries: Number(e.target.value) || 1 } }))}
                    />
                  </label>
                  <label className="field-label">
                    超限回复话术
                    <input
                      className="ios-input mt-2 h-10 w-full rounded-lg"
                      value={rules[row.key]?.block_message || ''}
                      onChange={e => setRules(x => ({ ...x, [row.key]: { ...x[row.key], block_message: e.target.value } }))}
                      placeholder="留空使用系统默认提示"
                    />
                  </label>
                </div>
              ))}
            </div>
          ) : (
            <EmptyState
              compact
              icon={ScanLine}
              title="选择账号和商品后开始识别"
              description="识别结果来自卖家/买家接口和订单观测。"
            />
          )}
        </div>
      </div>
    </div>
  );
}
