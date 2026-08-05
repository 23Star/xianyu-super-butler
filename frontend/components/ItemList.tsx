import React, { useEffect, useMemo, useState } from 'react';
import { createPortal } from 'react-dom';
import { Item, AccountDetail } from '../types';
import {
  deleteItem,
  getAccountDetails,
  getItems,
  syncItemsFromAccount,
  updateItemDetail,
  updateItemMultiQuantity,
  updateItemMultiSpec,
} from '../services/api';
import { confirmAction } from '../services/feedback';
import { Box, RefreshCw, ShoppingBag, Edit, Trash2, Save, X, Loader2 } from 'lucide-react';

type Notice = { type: 'success' | 'error'; message: string } | null;

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

  useEffect(() => {
    setFailed(false);
  }, [src]);

  if (!src || failed) {
    return <div className="w-full h-full flex items-center justify-center text-gray-300"><Box className="w-8 h-8" /></div>;
  }

  return (
    <img
      src={src}
      alt={item.item_title || '商品图片'}
      className="w-full h-full object-cover"
      loading="lazy"
      referrerPolicy="no-referrer"
      onError={() => setFailed(true)}
    />
  );
};

const ItemList: React.FC = () => {
  const [items, setItems] = useState<Item[]>([]);
  const [accounts, setAccounts] = useState<AccountDetail[]>([]);
  const [selectedAccount, setSelectedAccount] = useState('');
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [savingKey, setSavingKey] = useState('');
  const [selectedItem, setSelectedItem] = useState<Item | null>(null);
  const [itemDetail, setItemDetail] = useState('');
  const [notice, setNotice] = useState<Notice>(null);

  const accountNames = useMemo(
    () => new Map(accounts.map(account => [account.id, account.nickname || account.remark || account.id])),
    [accounts],
  );

  const loadData = async () => {
    setLoading(true);
    try {
      const [accountData, itemData] = await Promise.all([getAccountDetails(), getItems()]);
      setAccounts(accountData);
      setItems(itemData);
    } catch (error) {
      setNotice({ type: 'error', message: error instanceof Error ? error.message : '商品数据加载失败' });
    } finally {
      setLoading(false);
    }
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

  const openEdit = (item: Item) => {
    setSelectedItem(item);
    setItemDetail(item.item_detail || '');
  };

  const handleSaveDetail = async () => {
    if (!selectedItem) return;
    const key = `${selectedItem.cookie_id}-${selectedItem.item_id}`;
    setSavingKey(key);
    try {
      await updateItemDetail(selectedItem.cookie_id, selectedItem.item_id, itemDetail);
      setItems(current => current.map(item =>
        item.cookie_id === selectedItem.cookie_id && item.item_id === selectedItem.item_id
          ? { ...item, item_detail: itemDetail }
          : item,
      ));
      setSelectedItem(null);
      setNotice({ type: 'success', message: '商品详情已保存' });
    } catch (error) {
      setNotice({ type: 'error', message: error instanceof Error ? error.message : '保存失败' });
    } finally {
      setSavingKey('');
    }
  };

  const handleDelete = async (item: Item) => {
    if (!await confirmAction(`确认删除商品“${item.item_title || item.item_id}”的本地记录吗？`)) return;
    const key = `${item.cookie_id}-${item.item_id}`;
    setSavingKey(key);
    try {
      await deleteItem(item.cookie_id, item.item_id);
      setItems(current => current.filter(currentItem =>
        currentItem.cookie_id !== item.cookie_id || currentItem.item_id !== item.item_id,
      ));
      setNotice({ type: 'success', message: '商品记录已删除，可通过同步重新获取' });
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
    const key = `${item.cookie_id}-${item.item_id}`;
    const enabled = !Boolean(item[field]);
    setSavingKey(key);
    try {
      if (field === 'is_multi_spec') {
        await updateItemMultiSpec(item.cookie_id, item.item_id, enabled);
      } else {
        await updateItemMultiQuantity(item.cookie_id, item.item_id, enabled);
      }
      setItems(current => current.map(currentItem =>
        currentItem.cookie_id === item.cookie_id && currentItem.item_id === item.item_id
          ? { ...currentItem, [field]: enabled }
          : currentItem,
      ));
    } catch (error) {
      setNotice({ type: 'error', message: error instanceof Error ? error.message : '状态更新失败' });
    } finally {
      setSavingKey('');
    }
  };

  if (loading) {
    return <div className="py-24 flex justify-center"><Loader2 className="w-8 h-8 text-yellow-500 animate-spin" /></div>;
  }

  return (
    <div className="space-y-5 animate-fade-in">
      <div className="flex flex-col xl:flex-row xl:items-end justify-between gap-4">
        <div>
          <h2 className="text-2xl font-bold text-gray-900">商品管理</h2>
          <p className="text-gray-500 mt-1 text-sm">商品来自闲鱼账号同步；这里管理本地详情和发货策略。</p>
        </div>
        <div className="flex flex-col sm:flex-row gap-2">
          <select
            className="ios-input px-3 py-2.5 rounded-md text-sm min-w-56"
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
            onClick={handleSync}
            disabled={syncing || !selectedAccount}
            className="ios-btn-primary flex items-center justify-center gap-2 px-5 py-2.5 rounded-md font-bold disabled:opacity-50"
          >
            <RefreshCw className={`w-4 h-4 ${syncing ? 'animate-spin' : ''}`} />
            {syncing ? '同步中' : '同步商品'}
          </button>
        </div>
      </div>

      {notice && (
        <div
          role="status"
          className={`flex items-center justify-between gap-4 px-4 py-3 rounded-md border text-sm ${
            notice.type === 'success'
              ? 'bg-green-50 border-green-200 text-green-800'
              : 'bg-red-50 border-red-200 text-red-700'
          }`}
        >
          <span>{notice.message}</span>
          <button type="button" onClick={() => setNotice(null)} aria-label="关闭提示"><X className="w-4 h-4" /></button>
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
        {items.map(item => {
          const key = `${item.cookie_id}-${item.item_id}`;
          const busy = savingKey === key;
          const accountName = accountNames.get(item.cookie_id);
          return (
            <article key={key} className="ios-card p-4 rounded-lg border border-gray-200">
              <div className="flex gap-4">
                <div className="w-24 h-24 flex-none bg-gray-100 rounded-md overflow-hidden">
                  <ItemImage item={item} />
                </div>
                <div className="min-w-0 flex-1">
                  <h3 className="font-bold text-gray-900 line-clamp-2 text-sm min-h-10">{item.item_title || '未命名商品'}</h3>
                  <div className="mt-2 flex items-center justify-between gap-2">
                    <span className="font-bold text-red-600">{formatPrice(item.item_price)}</span>
                    <span className="text-xs text-gray-400 truncate">ID {item.item_id}</span>
                  </div>
                  <div
                    className="mt-2 text-xs text-gray-500 leading-5"
                    title={`${accountName || '未命名账号'} (${item.cookie_id})`}
                  >
                    <p className="font-medium text-gray-600 break-words">{accountName || '未命名账号'}</p>
                    <p className="font-mono text-gray-400 break-all">账号 {item.cookie_id}</p>
                  </div>
                </div>
              </div>

              <div className="mt-4 grid grid-cols-2 gap-2">
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => toggleSetting(item, 'is_multi_spec')}
                  className={`text-xs font-semibold px-3 py-2 rounded-md border transition-colors ${
                    item.is_multi_spec
                      ? 'bg-blue-50 border-blue-200 text-blue-700'
                      : 'bg-white border-gray-200 text-gray-600 hover:bg-gray-50'
                  }`}
                >
                  多规格 {item.is_multi_spec ? '已开启' : '已关闭'}
                </button>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => toggleSetting(item, 'multi_quantity_delivery')}
                  className={`text-xs font-semibold px-3 py-2 rounded-md border transition-colors ${
                    item.multi_quantity_delivery
                      ? 'bg-green-50 border-green-200 text-green-700'
                      : 'bg-white border-gray-200 text-gray-600 hover:bg-gray-50'
                  }`}
                >
                  多数量 {item.multi_quantity_delivery ? '已开启' : '已关闭'}
                </button>
              </div>

              <div className="mt-3 flex justify-end gap-1 border-t border-gray-100 pt-3">
                <button
                  type="button"
                  onClick={() => openEdit(item)}
                  disabled={busy}
                  className="p-2 rounded-md text-gray-600 hover:bg-gray-100"
                  title="编辑本地详情"
                  aria-label="编辑本地详情"
                >
                  <Edit className="w-4 h-4" />
                </button>
                <button
                  type="button"
                  onClick={() => handleDelete(item)}
                  disabled={busy}
                  className="p-2 rounded-md text-red-500 hover:bg-red-50"
                  title="删除本地记录"
                  aria-label="删除本地记录"
                >
                  {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Trash2 className="w-4 h-4" />}
                </button>
              </div>
            </article>
          );
        })}

        {items.length === 0 && (
          <div className="col-span-full py-20 text-center text-gray-400 border border-dashed border-gray-300 rounded-lg bg-white">
            <ShoppingBag className="w-10 h-10 mx-auto mb-3 opacity-40" />
            <p className="font-medium">暂无商品数据</p>
            <p className="text-sm mt-1">选择账号后同步闲鱼商品。</p>
          </div>
        )}
      </div>

      {selectedItem && createPortal(
        <div className="modal-overlay">
          <div className="modal-container">
            <div className="modal-header flex items-start justify-between gap-4">
              <div>
                <h3 className="text-xl font-bold text-gray-900">编辑商品详情</h3>
                <p className="text-sm text-gray-500 mt-1 line-clamp-1">{selectedItem.item_title || selectedItem.item_id}</p>
              </div>
              <button type="button" onClick={() => setSelectedItem(null)} className="p-2 rounded-md hover:bg-gray-100" aria-label="关闭">
                <X className="w-5 h-5" />
              </button>
            </div>
            <div className="modal-body">
              <label className="block text-sm font-bold text-gray-700 mb-2" htmlFor="item-detail">本地商品详情</label>
              <textarea
                id="item-detail"
                value={itemDetail}
                onChange={event => setItemDetail(event.target.value)}
                className="ios-input w-full min-h-64 rounded-md p-3 resize-y font-mono text-sm"
                placeholder="可保存商品 JSON 或补充说明，供自动回复逻辑读取。"
              />
            </div>
            <div className="modal-footer flex justify-end gap-2">
              <button type="button" onClick={() => setSelectedItem(null)} className="ios-btn-secondary px-4 py-2.5 rounded-md">取消</button>
              <button
                type="button"
                onClick={handleSaveDetail}
                disabled={Boolean(savingKey)}
                className="ios-btn-primary px-4 py-2.5 rounded-md flex items-center gap-2"
              >
                {savingKey ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
                保存
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
