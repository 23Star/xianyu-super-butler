import React, { useEffect, useMemo, useState } from 'react';
import { createPortal } from 'react-dom';
import {
  Box,
  Edit,
  Loader2,
  PackageCheck,
  Plus,
  RefreshCw,
  Save,
  Settings2,
  ShoppingBag,
  Trash2,
  X,
} from 'lucide-react';
import { AccountDetail, Card, Item, ShippingRule } from '../types';
import {
  createManualItem,
  deleteItem,
  deleteShippingRule,
  getAccountDetails,
  getCards,
  getItems,
  getShippingRules,
  syncItemsFromAccount,
  updateItemDetail,
  updateItemMultiQuantity,
  updateItemMultiSpec,
  updateShippingRule,
} from '../services/api';
import { confirmAction } from '../services/feedback';

type Notice = { type: 'success' | 'error'; message: string } | null;

interface DeliveryForm {
  cardId: string;
  deliveryCount: number;
  description: string;
  enabled: boolean;
}

interface ManualItemForm {
  cookieId: string;
  itemId: string;
  title: string;
  price: string;
  imageUrl: string;
  description: string;
  detail: string;
}

const emptyManualItem: ManualItemForm = {
  cookieId: '',
  itemId: '',
  title: '',
  price: '',
  imageUrl: '',
  description: '',
  detail: '',
};

const itemKey = (item: Pick<Item, 'cookie_id' | 'item_id'>) =>
  `${item.cookie_id}:${item.item_id}`;

const formatPrice = (price?: string) => {
  const value = price?.trim().replace(/^[¥￥]\s*/, '');
  return value ? `¥${value}` : '价格未知';
};

const normalizeImageUrl = (url?: string) => {
  const value = url?.trim();
  if (!value) return '';
  return value.startsWith('//') ? `https:${value}` : value;
};

const ItemImage: React.FC<{ item: Item }> = ({ item }) => {
  const src = normalizeImageUrl(item.item_image);
  const [failed, setFailed] = useState(false);

  useEffect(() => setFailed(false), [src]);

  if (!src || failed) {
    return (
      <div className="flex h-full w-full items-center justify-center text-gray-300">
        <Box className="h-8 w-8" />
      </div>
    );
  }

  return (
    <img
      src={src}
      alt={item.item_title || '商品图片'}
      className="h-full w-full object-cover"
      loading="lazy"
      referrerPolicy="no-referrer"
      onError={() => setFailed(true)}
    />
  );
};

const Toggle: React.FC<{
  checked: boolean;
  disabled?: boolean;
  label: string;
  onChange: () => void;
}> = ({ checked, disabled, label, onChange }) => (
  <button
    type="button"
    role="switch"
    aria-checked={checked}
    aria-label={label}
    disabled={disabled}
    onClick={onChange}
    className={`relative inline-flex h-6 w-11 flex-none items-center rounded-full transition-colors ${
      checked ? 'bg-green-500' : 'bg-gray-300'
    } disabled:cursor-not-allowed disabled:opacity-50`}
  >
    <span
      className={`h-4 w-4 rounded-full bg-white shadow-sm transition-transform ${
        checked ? 'translate-x-6' : 'translate-x-1'
      }`}
    />
  </button>
);

const ItemList: React.FC = () => {
  const [items, setItems] = useState<Item[]>([]);
  const [accounts, setAccounts] = useState<AccountDetail[]>([]);
  const [cards, setCards] = useState<Card[]>([]);
  const [productRules, setProductRules] = useState<ShippingRule[]>([]);
  const [selectedAccount, setSelectedAccount] = useState('');
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [savingKey, setSavingKey] = useState('');
  const [notice, setNotice] = useState<Notice>(null);

  const [detailItem, setDetailItem] = useState<Item | null>(null);
  const [itemDetail, setItemDetail] = useState('');
  const [deliveryItem, setDeliveryItem] = useState<Item | null>(null);
  const [deliveryForm, setDeliveryForm] = useState<DeliveryForm>({
    cardId: '',
    deliveryCount: 1,
    description: '',
    enabled: true,
  });
  const [showManualModal, setShowManualModal] = useState(false);
  const [manualForm, setManualForm] = useState<ManualItemForm>(emptyManualItem);

  const accountNames = useMemo(
    () => new Map(accounts.map(account => [
      account.id,
      account.nickname || account.remark || `账号 ${account.id.substring(0, 6)}`,
    ])),
    [accounts],
  );

  const ruleMap = useMemo(() => {
    const map = new Map<string, ShippingRule>();
    productRules.forEach(rule => {
      if (rule.cookie_id && rule.item_id) {
        map.set(`${rule.cookie_id}:${rule.item_id}`, rule);
      }
    });
    return map;
  }, [productRules]);

  const loadData = async () => {
    setLoading(true);
    try {
      const [accountData, itemData, cardData, ruleData] = await Promise.all([
        getAccountDetails(),
        getItems(),
        getCards(),
        getShippingRules(),
      ]);
      setAccounts(accountData);
      setItems(itemData);
      setCards(cardData);
      setProductRules(ruleData.filter(rule => Boolean(rule.item_id)));
      setSelectedAccount(current => current || accountData[0]?.id || '');
    } catch (error) {
      setNotice({
        type: 'error',
        message: error instanceof Error ? error.message : '商品数据加载失败',
      });
    } finally {
      setLoading(false);
    }
  };

  const reloadRules = async () => {
    const rules = await getShippingRules();
    setProductRules(rules.filter(rule => Boolean(rule.item_id)));
  };

  useEffect(() => {
    void loadData();
  }, []);

  const handleSync = async () => {
    if (!selectedAccount) {
      setNotice({ type: 'error', message: '请先选择需要同步的账号' });
      return;
    }

    setSyncing(true);
    setNotice(null);
    try {
      const result = await syncItemsFromAccount(selectedAccount);
      if (result?.success === false) throw new Error(result.message || '同步失败');
      setItems(await getItems());
      setNotice({ type: 'success', message: result?.message || '商品同步完成' });
    } catch (error) {
      setNotice({ type: 'error', message: error instanceof Error ? error.message : '同步失败' });
    } finally {
      setSyncing(false);
    }
  };

  const openManualModal = () => {
    setManualForm({ ...emptyManualItem, cookieId: selectedAccount || accounts[0]?.id || '' });
    setShowManualModal(true);
  };

  const handleCreateManualItem = async () => {
    if (!manualForm.cookieId || !manualForm.itemId.trim() || !manualForm.title.trim()) {
      setNotice({ type: 'error', message: '账号、商品 ID 和商品标题为必填项' });
      return;
    }

    setSavingKey('manual-item');
    try {
      await createManualItem({
        cookie_id: manualForm.cookieId,
        item_id: manualForm.itemId.trim(),
        title: manualForm.title.trim(),
        price: manualForm.price.trim(),
        image_url: manualForm.imageUrl.trim(),
        description: manualForm.description.trim(),
        detail: manualForm.detail.trim(),
      });
      setItems(await getItems());
      setShowManualModal(false);
      setNotice({ type: 'success', message: '商品已添加，可继续配置自动发货' });
    } catch (error) {
      setNotice({ type: 'error', message: error instanceof Error ? error.message : '商品添加失败' });
    } finally {
      setSavingKey('');
    }
  };

  const openDetail = (item: Item) => {
    setDetailItem(item);
    setItemDetail(item.item_detail || '');
  };

  const handleSaveDetail = async () => {
    if (!detailItem) return;
    const key = itemKey(detailItem);
    setSavingKey(key);
    try {
      await updateItemDetail(detailItem.cookie_id, detailItem.item_id, itemDetail);
      setItems(current => current.map(item =>
        itemKey(item) === key ? { ...item, item_detail: itemDetail } : item,
      ));
      setDetailItem(null);
      setNotice({ type: 'success', message: '商品详情已保存' });
    } catch (error) {
      setNotice({ type: 'error', message: error instanceof Error ? error.message : '保存失败' });
    } finally {
      setSavingKey('');
    }
  };

  const openDelivery = (item: Item) => {
    const rule = ruleMap.get(itemKey(item));
    setDeliveryItem(item);
    setDeliveryForm({
      cardId: rule?.card_group_id ? String(rule.card_group_id) : '',
      deliveryCount: Math.max(1, rule?.priority || 1),
      description: rule?.name || '',
      enabled: rule?.enabled ?? true,
    });
  };

  const handleSaveDelivery = async () => {
    if (!deliveryItem) return;
    if (!deliveryForm.cardId) {
      setNotice({ type: 'error', message: '请选择自动发货使用的卡密或内容' });
      return;
    }

    const key = itemKey(deliveryItem);
    const existing = ruleMap.get(key);
    setSavingKey(key);
    try {
      await updateShippingRule({
        id: existing?.id,
        item_keyword: '',
        cookie_id: deliveryItem.cookie_id,
        item_id: deliveryItem.item_id,
        card_group_id: Number(deliveryForm.cardId),
        priority: Math.max(1, Math.floor(deliveryForm.deliveryCount || 1)),
        name: deliveryForm.description.trim() || `${deliveryItem.item_title || deliveryItem.item_id} 自动发货`,
        enabled: deliveryForm.enabled,
      });
      await reloadRules();
      setDeliveryItem(null);
      setNotice({ type: 'success', message: '商品自动发货配置已保存' });
    } catch (error) {
      setNotice({ type: 'error', message: error instanceof Error ? error.message : '发货配置保存失败' });
    } finally {
      setSavingKey('');
    }
  };

  const handleToggleDelivery = async (item: Item) => {
    const key = itemKey(item);
    const rule = ruleMap.get(key);
    if (!rule) {
      openDelivery(item);
      return;
    }

    setSavingKey(key);
    try {
      await updateShippingRule({ ...rule, enabled: !rule.enabled });
      setProductRules(current => current.map(currentRule =>
        currentRule.id === rule.id ? { ...currentRule, enabled: !rule.enabled } : currentRule,
      ));
    } catch (error) {
      setNotice({ type: 'error', message: error instanceof Error ? error.message : '状态更新失败' });
    } finally {
      setSavingKey('');
    }
  };

  const handleDelete = async (item: Item) => {
    if (!await confirmAction(`确认删除商品“${item.item_title || item.item_id}”的本地记录吗？`)) return;
    const key = itemKey(item);
    const rule = ruleMap.get(key);
    setSavingKey(key);
    try {
      if (rule) await deleteShippingRule(rule.id);
      await deleteItem(item.cookie_id, item.item_id);
      setItems(current => current.filter(currentItem => itemKey(currentItem) !== key));
      setProductRules(current => current.filter(currentRule => currentRule.id !== rule?.id));
      setNotice({ type: 'success', message: '商品及其专属发货配置已删除' });
    } catch (error) {
      setNotice({ type: 'error', message: error instanceof Error ? error.message : '删除失败' });
    } finally {
      setSavingKey('');
    }
  };

  const toggleSetting = async (
    item: Item,
    field: 'is_multi_spec' | 'multi_quantity_delivery',
  ) => {
    const key = itemKey(item);
    const enabled = !Boolean(item[field]);
    setSavingKey(key);
    try {
      if (field === 'is_multi_spec') {
        await updateItemMultiSpec(item.cookie_id, item.item_id, enabled);
      } else {
        await updateItemMultiQuantity(item.cookie_id, item.item_id, enabled);
      }
      setItems(current => current.map(currentItem =>
        itemKey(currentItem) === key ? { ...currentItem, [field]: enabled } : currentItem,
      ));
    } catch (error) {
      setNotice({ type: 'error', message: error instanceof Error ? error.message : '状态更新失败' });
    } finally {
      setSavingKey('');
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
      <div className="flex flex-col justify-between gap-4 xl:flex-row xl:items-end">
        <div>
          <h2 className="text-2xl font-bold text-gray-900">商品管理</h2>
          <p className="mt-1 text-sm text-gray-500">
            同步或手动添加商品，并为每件商品单独配置自动发货。
          </p>
        </div>
        <div className="flex flex-col gap-2 sm:flex-row">
          <select
            className="ios-input min-w-56 rounded-md px-3 py-2.5 text-sm"
            value={selectedAccount}
            onChange={event => setSelectedAccount(event.target.value)}
            aria-label="选择同步账号"
          >
            <option value="">选择需要同步的账号</option>
            {accounts.map(account => (
              <option key={account.id} value={account.id}>{accountNames.get(account.id)}</option>
            ))}
          </select>
          <button
            type="button"
            onClick={openManualModal}
            className="ios-btn-secondary flex items-center justify-center gap-2 rounded-md px-4 py-2.5 font-bold"
          >
            <Plus className="h-4 w-4" />
            手动添加
          </button>
          <button
            type="button"
            onClick={handleSync}
            disabled={syncing || !selectedAccount}
            className="ios-btn-primary flex items-center justify-center gap-2 rounded-md px-5 py-2.5 font-bold disabled:opacity-50"
          >
            <RefreshCw className={`h-4 w-4 ${syncing ? 'animate-spin' : ''}`} />
            {syncing ? '同步中' : '同步商品'}
          </button>
        </div>
      </div>

      {notice && (
        <div
          role="status"
          className={`flex items-center justify-between gap-4 rounded-md border px-4 py-3 text-sm ${
            notice.type === 'success'
              ? 'border-green-200 bg-green-50 text-green-800'
              : 'border-red-200 bg-red-50 text-red-700'
          }`}
        >
          <span>{notice.message}</span>
          <button type="button" onClick={() => setNotice(null)} aria-label="关闭提示">
            <X className="h-4 w-4" />
          </button>
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
        {items.map(item => {
          const key = itemKey(item);
          const busy = savingKey === key;
          const rule = ruleMap.get(key);
          return (
            <article key={key} className="ios-card rounded-lg border border-gray-200 p-4">
              <div className="flex gap-4">
                <div className="h-24 w-24 flex-none overflow-hidden rounded-md bg-gray-100">
                  <ItemImage item={item} />
                </div>
                <div className="min-w-0 flex-1">
                  <h3 className="min-h-10 line-clamp-2 text-sm font-bold text-gray-900">
                    {item.item_title || '未命名商品'}
                  </h3>
                  <div className="mt-2 flex items-center justify-between gap-2">
                    <span className="font-bold text-red-600">{formatPrice(item.item_price)}</span>
                    <span className="truncate text-xs text-gray-400">ID {item.item_id}</span>
                  </div>
                  <div className="mt-2 text-xs leading-5 text-gray-500">
                    <p className="break-words font-medium text-gray-600">
                      {accountNames.get(item.cookie_id) || '未命名账号'}
                    </p>
                    <p className="break-all font-mono text-gray-400">账号 {item.cookie_id}</p>
                  </div>
                </div>
              </div>

              <div className="mt-4 rounded-md border border-gray-200 bg-gray-50 p-3">
                <div className="flex items-center justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <PackageCheck className={`h-4 w-4 ${rule?.enabled ? 'text-green-600' : 'text-gray-400'}`} />
                      <span className="text-sm font-bold text-gray-800">自动发货</span>
                    </div>
                    <p className="mt-1 truncate text-xs text-gray-500">
                      {rule
                        ? `${rule.card_group_name || `卡密 ${rule.card_group_id}`} · 每单 ${rule.priority} 份`
                        : '未配置发货内容'}
                    </p>
                  </div>
                  <Toggle
                    checked={Boolean(rule?.enabled)}
                    disabled={busy}
                    label={`${item.item_title || item.item_id} 自动发货`}
                    onChange={() => handleToggleDelivery(item)}
                  />
                </div>
                <button
                  type="button"
                  onClick={() => openDelivery(item)}
                  disabled={busy}
                  className="mt-3 flex w-full items-center justify-center gap-2 rounded-md border border-gray-200 bg-white px-3 py-2 text-xs font-bold text-gray-700 hover:bg-gray-50"
                >
                  <Settings2 className="h-4 w-4" />
                  {rule ? '配置发货策略' : '设置自动发货'}
                </button>
              </div>

              <div className="mt-3 grid grid-cols-2 gap-2">
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => toggleSetting(item, 'is_multi_spec')}
                  className={`rounded-md border px-3 py-2 text-xs font-semibold ${
                    item.is_multi_spec
                      ? 'border-blue-200 bg-blue-50 text-blue-700'
                      : 'border-gray-200 bg-white text-gray-600 hover:bg-gray-50'
                  }`}
                >
                  多规格 {item.is_multi_spec ? '已开启' : '已关闭'}
                </button>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => toggleSetting(item, 'multi_quantity_delivery')}
                  className={`rounded-md border px-3 py-2 text-xs font-semibold ${
                    item.multi_quantity_delivery
                      ? 'border-green-200 bg-green-50 text-green-700'
                      : 'border-gray-200 bg-white text-gray-600 hover:bg-gray-50'
                  }`}
                >
                  多数量 {item.multi_quantity_delivery ? '已开启' : '已关闭'}
                </button>
              </div>

              <div className="mt-3 flex justify-end gap-1 border-t border-gray-100 pt-3">
                <button
                  type="button"
                  onClick={() => openDetail(item)}
                  disabled={busy}
                  className="rounded-md p-2 text-gray-600 hover:bg-gray-100"
                  title="编辑本地详情"
                  aria-label="编辑本地详情"
                >
                  <Edit className="h-4 w-4" />
                </button>
                <button
                  type="button"
                  onClick={() => handleDelete(item)}
                  disabled={busy}
                  className="rounded-md p-2 text-red-500 hover:bg-red-50"
                  title="删除本地记录"
                  aria-label="删除本地记录"
                >
                  {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Trash2 className="h-4 w-4" />}
                </button>
              </div>
            </article>
          );
        })}

        {items.length === 0 && (
          <div className="col-span-full rounded-lg border border-dashed border-gray-300 bg-white py-20 text-center text-gray-400">
            <ShoppingBag className="mx-auto mb-3 h-10 w-10 opacity-40" />
            <p className="font-medium">暂无商品数据</p>
            <p className="mt-1 text-sm">同步闲鱼商品，或手动添加一件商品。</p>
          </div>
        )}
      </div>

      {deliveryItem && createPortal(
        <div className="modal-overlay">
          <div className="modal-container">
            <div className="modal-header flex items-start justify-between gap-4">
              <div>
                <h3 className="text-xl font-bold text-gray-900">商品自动发货</h3>
                <p className="mt-1 line-clamp-1 text-sm text-gray-500">
                  {deliveryItem.item_title || deliveryItem.item_id}
                </p>
              </div>
              <button type="button" onClick={() => setDeliveryItem(null)} className="rounded-md p-2 hover:bg-gray-100" aria-label="关闭">
                <X className="h-5 w-5" />
              </button>
            </div>
            <div className="modal-body space-y-5">
              <div>
                <label className="mb-2 block text-sm font-bold text-gray-700" htmlFor="delivery-card">
                  发货卡密或内容
                </label>
                <select
                  id="delivery-card"
                  value={deliveryForm.cardId}
                  onChange={event => setDeliveryForm(current => ({ ...current, cardId: event.target.value }))}
                  className="ios-input w-full rounded-md px-3 py-2.5"
                >
                  <option value="">请选择卡密</option>
                  {cards.map(card => (
                    <option key={card.id} value={card.id} disabled={!card.enabled}>
                      {card.name || `卡密 ${card.id}`}{card.enabled ? '' : '（已停用）'}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="mb-2 block text-sm font-bold text-gray-700" htmlFor="delivery-count">
                  每单发货数量
                </label>
                <input
                  id="delivery-count"
                  type="number"
                  min={1}
                  step={1}
                  value={deliveryForm.deliveryCount}
                  onChange={event => setDeliveryForm(current => ({
                    ...current,
                    deliveryCount: Math.max(1, Number(event.target.value) || 1),
                  }))}
                  className="ios-input w-full rounded-md px-3 py-2.5"
                />
              </div>
              <div>
                <label className="mb-2 block text-sm font-bold text-gray-700" htmlFor="delivery-description">
                  策略备注
                </label>
                <input
                  id="delivery-description"
                  value={deliveryForm.description}
                  onChange={event => setDeliveryForm(current => ({ ...current, description: event.target.value }))}
                  className="ios-input w-full rounded-md px-3 py-2.5"
                  placeholder="例如：Kimi 周卡自动发货"
                />
              </div>
              <div className="flex items-center justify-between rounded-md border border-gray-200 bg-gray-50 p-4">
                <div>
                  <p className="text-sm font-bold text-gray-800">启用自动发货</p>
                  <p className="mt-1 text-xs text-gray-500">关闭后保留策略，但不会触发发货。</p>
                </div>
                <Toggle
                  checked={deliveryForm.enabled}
                  label="启用商品自动发货"
                  onChange={() => setDeliveryForm(current => ({ ...current, enabled: !current.enabled }))}
                />
              </div>
            </div>
            <div className="modal-footer flex justify-end gap-2">
              <button type="button" onClick={() => setDeliveryItem(null)} className="ios-btn-secondary rounded-md px-4 py-2.5">
                取消
              </button>
              <button
                type="button"
                onClick={handleSaveDelivery}
                disabled={Boolean(savingKey)}
                className="ios-btn-primary flex items-center gap-2 rounded-md px-4 py-2.5"
              >
                {savingKey ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                保存策略
              </button>
            </div>
          </div>
        </div>,
        document.body,
      )}

      {detailItem && createPortal(
        <div className="modal-overlay">
          <div className="modal-container">
            <div className="modal-header flex items-start justify-between gap-4">
              <div>
                <h3 className="text-xl font-bold text-gray-900">编辑商品详情</h3>
                <p className="mt-1 line-clamp-1 text-sm text-gray-500">{detailItem.item_title || detailItem.item_id}</p>
              </div>
              <button type="button" onClick={() => setDetailItem(null)} className="rounded-md p-2 hover:bg-gray-100" aria-label="关闭">
                <X className="h-5 w-5" />
              </button>
            </div>
            <div className="modal-body">
              <label className="mb-2 block text-sm font-bold text-gray-700" htmlFor="item-detail">本地商品详情</label>
              <textarea
                id="item-detail"
                value={itemDetail}
                onChange={event => setItemDetail(event.target.value)}
                className="ios-input min-h-64 w-full resize-y rounded-md p-3 font-mono text-sm"
                placeholder="补充商品说明，供自动回复和发货逻辑读取。"
              />
            </div>
            <div className="modal-footer flex justify-end gap-2">
              <button type="button" onClick={() => setDetailItem(null)} className="ios-btn-secondary rounded-md px-4 py-2.5">取消</button>
              <button
                type="button"
                onClick={handleSaveDetail}
                disabled={Boolean(savingKey)}
                className="ios-btn-primary flex items-center gap-2 rounded-md px-4 py-2.5"
              >
                {savingKey ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                保存
              </button>
            </div>
          </div>
        </div>,
        document.body,
      )}

      {showManualModal && createPortal(
        <div className="modal-overlay">
          <div className="modal-container">
            <div className="modal-header flex items-start justify-between gap-4">
              <div>
                <h3 className="text-xl font-bold text-gray-900">手动添加商品</h3>
                <p className="mt-1 text-sm text-gray-500">适用于暂未同步到列表、但需要配置自动发货的商品。</p>
              </div>
              <button type="button" onClick={() => setShowManualModal(false)} className="rounded-md p-2 hover:bg-gray-100" aria-label="关闭">
                <X className="h-5 w-5" />
              </button>
            </div>
            <div className="modal-body grid grid-cols-1 gap-4 sm:grid-cols-2">
              <div className="sm:col-span-2">
                <label className="mb-2 block text-sm font-bold text-gray-700" htmlFor="manual-account">所属账号</label>
                <select
                  id="manual-account"
                  value={manualForm.cookieId}
                  onChange={event => setManualForm(current => ({ ...current, cookieId: event.target.value }))}
                  className="ios-input w-full rounded-md px-3 py-2.5"
                >
                  <option value="">请选择账号</option>
                  {accounts.map(account => (
                    <option key={account.id} value={account.id}>{accountNames.get(account.id)}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="mb-2 block text-sm font-bold text-gray-700" htmlFor="manual-item-id">商品 ID</label>
                <input
                  id="manual-item-id"
                  value={manualForm.itemId}
                  onChange={event => setManualForm(current => ({ ...current, itemId: event.target.value }))}
                  className="ios-input w-full rounded-md px-3 py-2.5"
                  placeholder="例如 1070863591807"
                />
              </div>
              <div>
                <label className="mb-2 block text-sm font-bold text-gray-700" htmlFor="manual-price">价格</label>
                <input
                  id="manual-price"
                  value={manualForm.price}
                  onChange={event => setManualForm(current => ({ ...current, price: event.target.value }))}
                  className="ios-input w-full rounded-md px-3 py-2.5"
                  placeholder="例如 80"
                />
              </div>
              <div className="sm:col-span-2">
                <label className="mb-2 block text-sm font-bold text-gray-700" htmlFor="manual-title">商品标题</label>
                <input
                  id="manual-title"
                  value={manualForm.title}
                  onChange={event => setManualForm(current => ({ ...current, title: event.target.value }))}
                  className="ios-input w-full rounded-md px-3 py-2.5"
                />
              </div>
              <div className="sm:col-span-2">
                <label className="mb-2 block text-sm font-bold text-gray-700" htmlFor="manual-image">图片 URL</label>
                <input
                  id="manual-image"
                  value={manualForm.imageUrl}
                  onChange={event => setManualForm(current => ({ ...current, imageUrl: event.target.value }))}
                  className="ios-input w-full rounded-md px-3 py-2.5"
                  placeholder="https://..."
                />
              </div>
              <div className="sm:col-span-2">
                <label className="mb-2 block text-sm font-bold text-gray-700" htmlFor="manual-description">商品简介</label>
                <input
                  id="manual-description"
                  value={manualForm.description}
                  onChange={event => setManualForm(current => ({ ...current, description: event.target.value }))}
                  className="ios-input w-full rounded-md px-3 py-2.5"
                />
              </div>
              <div className="sm:col-span-2">
                <label className="mb-2 block text-sm font-bold text-gray-700" htmlFor="manual-detail">本地详情</label>
                <textarea
                  id="manual-detail"
                  value={manualForm.detail}
                  onChange={event => setManualForm(current => ({ ...current, detail: event.target.value }))}
                  className="ios-input min-h-28 w-full resize-y rounded-md p-3"
                />
              </div>
            </div>
            <div className="modal-footer flex justify-end gap-2">
              <button type="button" onClick={() => setShowManualModal(false)} className="ios-btn-secondary rounded-md px-4 py-2.5">
                取消
              </button>
              <button
                type="button"
                onClick={handleCreateManualItem}
                disabled={savingKey === 'manual-item'}
                className="ios-btn-primary flex items-center gap-2 rounded-md px-4 py-2.5"
              >
                {savingKey === 'manual-item' ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
                添加商品
              </button>
            </div>
          </div>
        </div>,
        document.body,
      )}
    </div>
  );
};

export default ItemList;
