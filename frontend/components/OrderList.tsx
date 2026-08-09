import React, { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import { Order, OrderStatus, Item } from '../types';
import { getOrders, syncOrders, syncSingleOrder, manualShipOrder, updateOrder, deleteOrder, importOrders, getItems } from '../services/api';
import { confirmAction, notify } from '../services/feedback';
import { Search, Truck, RefreshCw, ChevronLeft, ChevronRight, PackageCheck, Edit, Eye, Plus, Save, X, ExternalLink, Trash2, ClipboardList } from 'lucide-react';
import { EmptyState, PageHeader, PageTabs } from './ui';

const StatusBadge: React.FC<{ status: OrderStatus }> = ({ status }) => {
  const styles = {
    processing: 'bg-yellow-100 text-yellow-800',
    pending_ship: 'bg-[#FFE815] text-black',
    shipped: 'bg-blue-100 text-blue-700',
    completed: 'bg-green-100 text-green-700',
    cancelled: 'bg-gray-100 text-gray-500',
    refunding: 'bg-red-100 text-red-600',
  };

  const labels = {
    processing: '处理中',
    pending_ship: '待发货',
    shipped: '已发货',
    completed: '已完成',
    cancelled: '已取消',
    refunding: '退款中',
  };

  return (
    <span className={`inline-flex rounded px-2 py-1 text-xs font-bold ${styles[status] || styles.cancelled}`}>
      {labels[status] || status}
    </span>
  );
};

const OrderList: React.FC = () => {
  const [orders, setOrders] = useState<Order[]>([]);
  const [allOrders, setAllOrders] = useState<Order[]>([]); // 保存所有订单用于搜索
  const [items, setItems] = useState<Item[]>([]);
  const [itemNames, setItemNames] = useState<Record<string, string>>({});
  const [filter, setFilter] = useState('all');
  const [searchText, setSearchText] = useState(''); // 搜索文本
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [loading, setLoading] = useState(false);
  const [showDetailModal, setShowDetailModal] = useState(false);
  const [showEditModal, setShowEditModal] = useState(false);
  const [showImportModal, setShowImportModal] = useState(false);
  const [selectedOrder, setSelectedOrder] = useState<Order | null>(null);
  const [editingOrder, setEditingOrder] = useState<Partial<Order> | null>(null);
  const [importText, setImportText] = useState('');
  const [showShipModal, setShowShipModal] = useState(false);
  const [shipOrderId, setShipOrderId] = useState<string>('');
  const [shipLoading, setShipLoading] = useState(false);
  const [shipResult, setShipResult] = useState<{success: boolean; message: string} | null>(null);
  const [syncingOrderId, setSyncingOrderId] = useState<string | null>(null);
  const [deletingOrderId, setDeletingOrderId] = useState<string | null>(null);

  // 搜索过滤订单
  const filterOrders = (ordersToFilter: Order[]): Order[] => {
    if (!searchText.trim()) {
      return ordersToFilter;
    }

    const searchLower = searchText.toLowerCase().trim();
    return ordersToFilter.filter(order =>
      order.order_id?.toLowerCase().includes(searchLower) ||
      order.item_id?.toLowerCase().includes(searchLower) ||
      order.buyer_id?.toLowerCase().includes(searchLower) ||
      order.item_title?.toLowerCase().includes(searchLower) ||
      order.receiver_name?.toLowerCase().includes(searchLower) ||
      order.receiver_phone?.toLowerCase().includes(searchLower)
    );
  };

  const loadOrders = async () => {
      setLoading(true);

      try {
          // 如果有搜索文本，加载所有页的数据；否则只加载当前页
          if (searchText.trim()) {
              // 搜索模式：循环加载所有页
              let allOrdersData: Order[] = [];
              let currentPage = 1;
              let hasMore = true;

              while (hasMore) {
                  const res = await getOrders(undefined, filter, currentPage, 100);
                  allOrdersData = [...allOrdersData, ...res.data];
                  hasMore = currentPage < res.total_pages;
                  currentPage++;
              }

              setAllOrders(allOrdersData);
              setOrders(filterOrders(allOrdersData));
              setTotalPages(1); // 搜索时不分页
          } else {
              // 普通模式：只加载当前页
              const res = await getOrders(undefined, filter, page, 20);
              setAllOrders(res.data);
              setOrders(filterOrders(res.data));
              setTotalPages(res.total_pages);
          }
      } catch (e) {
          console.error('加载订单失败:', e);
      } finally {
          setLoading(false);
      }
  };

  // 当订单数据改变时，重新过滤订单
  useEffect(() => {
    setOrders(filterOrders(allOrders));
  }, [allOrders, searchText]);

  // 从订单的 item_id 查找对应的商品名称（通过标题匹配）
  const getItemNameById = (orderId: string, orderItemTitle?: string): string => {
      // 如果订单有 item_title，优先使用
      if (orderItemTitle && orderItemTitle.trim()) {
          return orderItemTitle;
      }

      // 尝试通过 item_id 直接匹配
      if (itemNames[orderId]) {
          return itemNames[orderId];
      }

      // 尝试在商品列表中查找相似标题的商品
      const matchingItem = items.find(item => {
          // 如果订单有标题，尝试匹配商品标题
          if (orderItemTitle && item.item_title) {
              // 检查是否包含关键词
              const orderTitleLower = orderItemTitle.toLowerCase();
              const itemTitleLower = item.item_title.toLowerCase();
              return itemTitleLower.includes(orderTitleLower) || orderTitleLower.includes(itemTitleLower);
          }
          return false;
      });

      if (matchingItem?.item_title) {
          return matchingItem.item_title;
      }

      return '未知商品';
  };

  // 从商品列表构建商品ID到商品名的映射
  const buildItemNamesMap = (sourceItems: Item[]) => {
      const namesMap: Record<string, string> = {};
      sourceItems.forEach(item => {
          // 使用 item_id 作为键，商品标题作为值
          if (item.item_id) {
              namesMap[item.item_id] = item.item_title || item.item_id;
          }
      });
      setItemNames(namesMap);
  };

  useEffect(() => {
    loadOrders();
    // 加载商品列表
    getItems().then((itemsList) => {
      setItems(itemsList);
      buildItemNamesMap(itemsList);
    }).catch((e) => {
      console.error('加载商品列表失败:', e);
    });
  }, [filter, page, searchText]);

  const handleSync = async () => {
      setLoading(true);
      await syncOrders();
      loadOrders();
  };

  const handleShip = (id: string) => {
      setShipOrderId(id);
      setShipResult(null);
      setShowShipModal(true);
  };

  const executeShip = async (mode: 'status_only' | 'full_delivery') => {
      setShipLoading(true);
      setShipResult(null);
      try {
          const res = await manualShipOrder([shipOrderId], mode);
          const result = res?.results?.[0];
          if (result?.success) {
              setShipResult({ success: true, message: result.message });
              loadOrders();
          } else {
              setShipResult({ success: false, message: result?.message || '发货失败' });
          }
      } catch (e: any) {
          setShipResult({ success: false, message: e?.message || '请求失败' });
      } finally {
          setShipLoading(false);
      }
  };

  const handleViewDetail = (order: Order) => {
    setSelectedOrder(order);
    setShowDetailModal(true);
  };

  const handleEdit = (order: Order) => {
    setEditingOrder({ ...order });
    setShowEditModal(true);
  };

  const handleSaveEdit = async () => {
    if (!editingOrder || !editingOrder.order_id) return;
    try {
      // 映射前端字段到后端期望的字段名
      const updateData: Record<string, any> = {};

      if (editingOrder.status !== undefined) {
        updateData.order_status = editingOrder.status;
      }
      if (editingOrder.buyer_id !== undefined) {
        updateData.buyer_id = editingOrder.buyer_id;
      }
      if (editingOrder.amount !== undefined) {
        updateData.amount = editingOrder.amount;
      }
      if (editingOrder.receiver_name !== undefined) {
        updateData.receiver_name = editingOrder.receiver_name;
      }
      if (editingOrder.receiver_phone !== undefined) {
        updateData.receiver_phone = editingOrder.receiver_phone;
      }
      if (editingOrder.receiver_address !== undefined) {
        updateData.receiver_address = editingOrder.receiver_address;
      }
      if (editingOrder.item_id !== undefined) {
        updateData.item_id = editingOrder.item_id;
      }
      if (editingOrder.quantity !== undefined) {
        updateData.quantity = editingOrder.quantity;
      }

      await updateOrder(editingOrder.order_id, updateData);
      setShowEditModal(false);
      setEditingOrder(null);
      loadOrders();
    } catch (error) {
      console.error('更新订单失败:', error);
      notify('更新失败，请重试');
    }
  };

  const handleImportOrders = async () => {
    try {
      const orders = JSON.parse(importText);
      await importOrders(Array.isArray(orders) ? orders : [orders]);
      setShowImportModal(false);
      setImportText('');
      loadOrders();
      notify('订单导入成功');
    } catch (error) {
      notify('导入失败，请检查JSON格式');
    }
  };

  const handleSyncSingle = async (orderId: string) => {
    setSyncingOrderId(orderId);
    try {
      const result = await syncSingleOrder(orderId);
      if (result.success) {
        await loadOrders();
      } else {
        notify(result.message || '同步失败');
      }
    } catch (error: any) {
      console.error('同步订单失败:', error);
      notify(error?.message || '同步失败，请重试');
    } finally {
      setSyncingOrderId(null);
    }
  };

  const handleDelete = async (orderId: string) => {
    if (!await confirmAction('确认删除该订单吗？删除后无法恢复。')) return;
    setDeletingOrderId(orderId);
    try {
      await deleteOrder(orderId);
      setAllOrders(prev => prev.filter(o => o.order_id !== orderId));
    } catch (error: any) {
      console.error('删除订单失败:', error);
      notify(error?.message || '删除失败，请重试');
      await loadOrders();
    } finally {
      setDeletingOrderId(null);
    }
  };

  const pendingCount = allOrders.filter(order => order.status === 'pending_ship').length;
  const shippedCount = allOrders.filter(order => order.status === 'shipped').length;
  const exceptionCount = allOrders.filter(order => ['cancelled', 'refunding'].includes(order.status)).length;

  return (
    <div className="page-stack animate-fade-in">
      <PageHeader
        title="订单管理"
        description="同步闲鱼交易状态，核对买家与商品信息，并处理人工或完整自动发货。"
        icon={ClipboardList}
        actions={(
          <>
            <button
              onClick={loadOrders}
              className="ios-btn-secondary flex items-center justify-center rounded-md p-2.5 text-gray-600"
              title="刷新订单"
              aria-label="刷新订单"
            >
                <RefreshCw className={`w-5 h-5 ${loading ? 'animate-spin' : ''}`} />
            </button>
            <button
              onClick={() => setShowImportModal(true)}
              className="ios-btn-secondary flex items-center justify-center gap-2 rounded-md px-4 py-2.5 text-sm"
            >
              <Plus className="w-4 h-4" />
              插入订单
            </button>
            <button onClick={handleSync} className="ios-btn-primary flex items-center justify-center gap-2 rounded-md px-4 py-2.5 text-sm">
                <Truck className="h-4 w-4" />
                同步订单
            </button>
          </>
        )}
      />

      <div className="metric-grid">
        <div className="metric-card">
          <p className="metric-card__label">当前结果</p>
          <p className="metric-card__value">{allOrders.length}</p>
          <p className="metric-card__meta">第 {page} 页加载的数据</p>
        </div>
        <div className="metric-card">
          <p className="metric-card__label">待发货</p>
          <p className="metric-card__value">{pendingCount}</p>
          <p className="metric-card__meta">需要优先处理</p>
        </div>
        <div className="metric-card">
          <p className="metric-card__label">已发货</p>
          <p className="metric-card__value">{shippedCount}</p>
          <p className="metric-card__meta">等待确认或完成</p>
        </div>
        <div className="metric-card">
          <p className="metric-card__label">异常订单</p>
          <p className="metric-card__value">{exceptionCount}</p>
          <p className="metric-card__meta">取消或退款中</p>
        </div>
      </div>

      <section className="section-panel">
        {/* Toolbar */}
        <div className="toolbar rounded-none border-0 border-b shadow-none">
          <PageTabs
            value={filter}
            onChange={(value) => { setFilter(value); setPage(1); setSearchText(''); }}
            ariaLabel="订单状态筛选"
            items={[
              { id: 'all', label: '全部' },
              { id: 'pending_ship', label: '待发货', count: pendingCount },
              { id: 'shipped', label: '已发货', count: shippedCount },
              { id: 'cancelled', label: '已取消' },
              { id: 'refunding', label: '退款中' },
            ]}
          />
          <div className="group relative w-full md:w-auto">
             <Search className="w-4 h-4 absolute left-4 top-1/2 -translate-y-1/2 text-gray-400 group-focus-within:text-[#FFE815] transition-colors" />
             <input
                 type="text"
                 placeholder="搜索订单号/商品/买家..."
                 value={searchText}
                 onChange={(e) => { setSearchText(e.target.value); setPage(1); }}
                 className="ios-input w-full rounded-md bg-white py-2.5 pl-10 pr-4 md:w-72"
             />
          </div>
        </div>

        {/* Table */}
        <div className="min-h-0 overflow-x-auto md:min-h-[360px]">
          <table className="data-table responsive-data-table min-w-[1040px] table-fixed">
            <thead>
              <tr>
                <th style={{width: '28%'}}>订单信息</th>
                <th style={{width: '25%'}}>买家信息</th>
                <th style={{width: '10%'}}>实付金额</th>
                <th style={{width: '11%'}}>当前状态</th>
                <th className="text-right" style={{width: '26%'}}>操作</th>
              </tr>
            </thead>
            <tbody>
              {orders.map((order) => (
                <tr key={order.id} className="group">
                  <td data-label="订单信息">
                    <div className="flex items-center gap-3">
                      <div className="h-12 w-12 flex-shrink-0 overflow-hidden rounded-md border border-gray-200 bg-gray-100">
                        {order.item_image ? (
                            <img src={order.item_image} alt="" className="w-full h-full object-cover" />
                        ) : (
                            <div className="w-full h-full flex items-center justify-center text-gray-300"><PackageCheck /></div>
                        )}
                      </div>
                      <div className="min-w-0">
                        <div className="font-bold text-gray-900 line-clamp-1 text-sm">
                          {getItemNameById(order.item_id, order.item_title)}
                        </div>
                        <div className="text-xs text-gray-500 mt-1 font-medium">订单ID: {order.order_id}</div>
                        <div className="text-xs text-gray-400 mt-0.5">数量: {order.quantity} • {order.created_at}</div>
                      </div>
                    </div>
                  </td>
                  <td data-label="买家信息">
                      <div className="flex flex-col gap-0.5">
                          <div className="text-sm font-bold text-gray-800">{order.buyer_id || '未知买家'}</div>
                          {order.receiver_name && (
                              <div className="text-xs text-gray-600">收货人：{order.receiver_name}</div>
                          )}
                          {order.receiver_phone && (
                              <div className="font-mono text-xs text-gray-600">{order.receiver_phone}</div>
                          )}
                          {order.receiver_address && (
                              <div className="line-clamp-1 text-xs text-gray-500">{order.receiver_address}</div>
                          )}
                      </div>
                  </td>
                  <td data-label="实付金额" className="font-feature-settings-tnum text-sm font-extrabold text-gray-900">¥{order.amount}</td>
                  <td data-label="当前状态">
                    <StatusBadge status={order.status} />
                  </td>
                  <td data-label="操作" className="text-right">
                    <div className="flex items-center justify-end gap-1">
                    {order.status === 'pending_ship' && (
                        <button
                            onClick={() => handleShip(order.order_id)}
                            className="ios-btn-primary mr-1 rounded-md px-3 py-2 text-xs"
                        >
                            立即发货
                        </button>
                    )}
                    <a
                      href={`https://www.goofish.com/order-detail?orderId=${order.order_id}&role=seller`}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex rounded-md p-2 text-gray-500 transition-colors hover:bg-amber-50 hover:text-amber-700"
                      title="查看闲鱼详情"
                    >
                      <ExternalLink className="w-4 h-4" />
                    </a>
                    <button
                      onClick={() => handleViewDetail(order)}
                      className="rounded-md p-2 text-gray-500 transition-colors hover:bg-blue-50 hover:text-blue-600"
                      title="查看详情"
                    >
                      <Eye className="w-4 h-4" />
                    </button>
                    <button
                      onClick={() => handleEdit(order)}
                      className="rounded-md p-2 text-gray-500 transition-colors hover:bg-gray-100 hover:text-black"
                      title="编辑订单"
                    >
                      <Edit className="w-4 h-4" />
                    </button>
                    <button
                      onClick={() => handleSyncSingle(order.order_id)}
                      disabled={syncingOrderId === order.order_id}
                      className="rounded-md p-2 text-gray-500 transition-colors hover:bg-green-50 hover:text-green-700 disabled:opacity-50"
                      title="同步订单"
                    >
                      <RefreshCw className={`w-4 h-4 ${syncingOrderId === order.order_id ? 'animate-spin' : ''}`} />
                    </button>
                    <button
                      onClick={() => handleDelete(order.order_id)}
                      disabled={deletingOrderId === order.order_id}
                      className="rounded-md p-2 text-gray-500 transition-colors hover:bg-red-50 hover:text-red-600 disabled:opacity-50"
                      title="删除订单"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {!loading && orders.length === 0 && (
            <div className="p-4">
              <EmptyState
                compact
                icon={PackageCheck}
                title="没有匹配的订单"
                description={searchText ? '请调整搜索条件，或清空搜索后查看全部订单。' : '可先同步闲鱼订单，或手动插入用于补录的订单数据。'}
              />
            </div>
          )}
        </div>

        {/* Pagination */}
        <div className="p-4 border-t border-gray-50 flex items-center justify-between bg-white">
            <div className="text-sm text-gray-500 font-medium pl-2">
                第 {page} 页 / 共 {totalPages} 页
            </div>
            <div className="flex gap-2">
                <button
                    disabled={page <= 1}
                    onClick={() => setPage(p => p - 1)}
                    className="rounded-md bg-gray-50 p-2.5 text-gray-600 transition-colors hover:bg-gray-100 disabled:cursor-not-allowed disabled:opacity-50"
                >
                    <ChevronLeft className="w-5 h-5" />
                </button>
                <button
                    disabled={page >= totalPages}
                    onClick={() => setPage(p => p + 1)}
                    className="rounded-md bg-gray-50 p-2.5 text-gray-600 transition-colors hover:bg-gray-100 disabled:cursor-not-allowed disabled:opacity-50"
                >
                    <ChevronRight className="w-5 h-5" />
                </button>
            </div>
        </div>
      </section>

      {/* 订单详情弹窗 - 使用 Portal */}
      {showDetailModal && selectedOrder && createPortal(
        <div className="modal-overlay">
          <div className="modal-container">
            <div className="modal-header">
              <div className="flex w-full items-start justify-between gap-4">
                <div>
                  <h3 className="text-lg font-bold text-gray-900">订单详情</h3>
                  <p className="mt-1 break-all text-xs text-gray-500">{selectedOrder.order_id}</p>
                </div>
                <button
                  type="button"
                  onClick={() => setShowDetailModal(false)}
                  className="rounded-md p-2 hover:bg-gray-100"
                  aria-label="关闭订单详情"
                >
                  <X className="w-5 h-5 text-gray-600" />
                </button>
              </div>
            </div>

            <div className="modal-body space-y-6">
              {/* Order Info */}
              <div className="space-y-4">
                <h4 className="text-lg font-bold text-gray-800">订单信息</h4>
                <div className="grid gap-4 rounded-md border border-gray-200 bg-gray-50 p-4 sm:grid-cols-2">
                  <div>
                    <div className="text-xs text-gray-500 mb-1">订单号</div>
                    <div className="font-mono text-sm font-bold text-gray-900">{selectedOrder.order_id}</div>
                  </div>
                  <div>
                    <div className="text-xs text-gray-500 mb-1">状态</div>
                    <StatusBadge status={selectedOrder.status} />
                  </div>
                  <div>
                    <div className="text-xs text-gray-500 mb-1">实付金额</div>
                    <div className="text-lg font-extrabold text-gray-900">¥{selectedOrder.amount}</div>
                  </div>
                  <div>
                    <div className="text-xs text-gray-500 mb-1">数量</div>
                    <div className="font-bold text-gray-900">{selectedOrder.quantity}</div>
                  </div>
                  <div className="col-span-2">
                    <div className="text-xs text-gray-500 mb-1">创建时间</div>
                    <div className="text-sm font-medium text-gray-700">{selectedOrder.created_at}</div>
                  </div>
                </div>
              </div>

              {/* Item Info */}
              <div className="space-y-4">
                <h4 className="text-lg font-bold text-gray-800">商品信息</h4>
                <div className="flex items-center gap-4 rounded-md border border-gray-200 bg-gray-50 p-4">
                  {selectedOrder.item_image && (
                    <img src={selectedOrder.item_image} alt="" className="h-20 w-20 rounded-md border border-gray-200 object-cover" />
                  )}
                  <div className="flex-1">
                    <div className="font-bold text-gray-900 mb-1">
                      {getItemNameById(selectedOrder.item_id, selectedOrder.item_title)}
                    </div>
                    <div className="text-sm text-gray-500">商品ID: {selectedOrder.item_id}</div>
                    {selectedOrder.item_price && (
                      <div className="text-sm text-gray-500 mt-1">标价: ¥{selectedOrder.item_price}</div>
                    )}
                  </div>
                </div>
              </div>

              {/* Buyer Info */}
              <div className="space-y-4">
                <h4 className="text-lg font-bold text-gray-800">买家信息</h4>
                <div className="space-y-3 rounded-md border border-gray-200 bg-gray-50 p-4">
                  <div>
                    <div className="text-xs text-gray-500 mb-1">买家ID</div>
                    <div className="font-bold text-gray-900">{selectedOrder.buyer_id}</div>
                  </div>
                  {selectedOrder.receiver_name && (
                    <div>
                      <div className="text-xs text-gray-500 mb-1">收货人</div>
                      <div className="font-medium text-gray-700">{selectedOrder.receiver_name}</div>
                    </div>
                  )}
                  {selectedOrder.receiver_phone && (
                    <div>
                      <div className="text-xs text-gray-500 mb-1">联系电话</div>
                      <div className="font-mono text-sm text-gray-700">{selectedOrder.receiver_phone}</div>
                    </div>
                  )}
                  {selectedOrder.receiver_address && (
                    <div>
                      <div className="text-xs text-gray-500 mb-1">收货地址</div>
                      <div className="text-sm text-gray-700">{selectedOrder.receiver_address}</div>
                    </div>
                  )}
                </div>
              </div>
            </div>

            <div className="modal-footer">
              <div className="flex w-full gap-2">
                <button
                  type="button"
                  onClick={() => setShowDetailModal(false)}
                  className="ios-btn-secondary flex-1 rounded-md px-4 py-2.5 text-sm"
                >
                  关闭
                </button>
                {selectedOrder.status === 'pending_ship' && (
                  <button
                    type="button"
                    onClick={() => {
                      setShowDetailModal(false);
                      handleShip(selectedOrder.order_id);
                    }}
                    className="ios-btn-primary flex-1 rounded-md px-4 py-2.5 text-sm"
                  >
                    立即发货
                  </button>
                )}
              </div>
            </div>
          </div>
        </div>,
        document.body
      )}

      {/* Import Modal - 使用 Portal */}
      {showImportModal && createPortal(
        <div className="modal-overlay">
          <div className="modal-container">
            <div className="modal-header">
              <div className="flex items-center justify-between w-full">
                <div>
                  <h3 className="text-lg font-bold text-gray-900">插入订单</h3>
                  <p className="mt-1 text-xs text-gray-500">粘贴单条订单对象或订单数组，用于补录和测试。</p>
                </div>
                <button
                  onClick={() => setShowImportModal(false)}
                  className="rounded-md p-2 hover:bg-gray-100"
                  aria-label="关闭插入订单"
                >
                  <X className="w-5 h-5 text-gray-600" />
                </button>
              </div>
            </div>

            <div className="modal-body space-y-5">
              <div>
                <label className="field-label">订单 JSON</label>
                <textarea
                  value={importText}
                  onChange={(event) => setImportText(event.target.value)}
                  className="ios-input min-h-64 w-full resize-y rounded-md px-4 py-3 font-mono text-sm"
                  placeholder={'[\n  {\n    "order_id": "订单号",\n    "item_id": "商品ID",\n    "buyer_id": "买家ID",\n    "status": "pending_ship",\n    "quantity": 1,\n    "amount": 0.01\n  }\n]'}
                />
                <p className="mt-2 text-xs text-gray-500">状态可使用 processing、pending_ship、shipped、completed、cancelled 或 refunding。</p>
              </div>
            </div>

            <div className="modal-footer">
              <div className="flex w-full gap-2">
                <button
                  type="button"
                  onClick={() => setShowImportModal(false)}
                  className="ios-btn-secondary flex-1 rounded-md px-4 py-2.5 text-sm"
                >
                  取消
                </button>
                <button
                  onClick={handleImportOrders}
                  disabled={!importText.trim()}
                  className="ios-btn-primary flex-1 rounded-md px-6 py-2.5 text-sm disabled:opacity-50"
                >
                  导入订单
                </button>
              </div>
            </div>
          </div>
        </div>,
        document.body
      )}

      {/* Ship Modal - 发货方式选择 */}
      {showShipModal && createPortal(
        <div className="modal-overlay">
          <div className="modal-container" style={{ maxWidth: '480px' }}>
            <div className="modal-header">
              <div className="flex w-full items-start justify-between gap-4">
                <div>
                  <h3 className="text-lg font-bold text-gray-900">立即发货</h3>
                  <p className="mt-1 text-xs text-gray-500">选择只更新平台状态，或执行完整卡密发货。</p>
                </div>
                <button
                  type="button"
                  onClick={() => { setShowShipModal(false); setShipResult(null); }}
                  className="rounded-md p-2 hover:bg-gray-100"
                  aria-label="关闭发货操作"
                >
                  <X className="w-5 h-5 text-gray-600" />
                </button>
              </div>
            </div>

            <div className="modal-body space-y-4">
              <p className="text-sm text-gray-600">请选择发货方式：</p>

              {/* 选项A: 仅修改发货状态 */}
              <button
                type="button"
                onClick={() => executeShip('status_only')}
                disabled={shipLoading}
                className="w-full rounded-md border border-gray-200 p-4 text-left transition-colors hover:border-gray-400 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
              >
                <div className="flex items-start gap-3">
                  <div className="mt-0.5 flex h-10 w-10 shrink-0 items-center justify-center rounded-md bg-blue-100">
                    <Truck className="w-5 h-5 text-blue-600" />
                  </div>
                  <div>
                    <div className="font-bold text-gray-900 text-sm">仅修改闲鱼发货状态</div>
                    <div className="text-xs text-gray-500 mt-1 leading-relaxed">
                      不实际扣除或发送卡券，仅在闲鱼平台将订单标记为"已发货"。
                      适用于已经给客户发过货、只是忘记在闲鱼修改状态的情况。
                    </div>
                  </div>
                </div>
              </button>

              {/* 选项B: 完整发货流程 */}
              <button
                type="button"
                onClick={() => executeShip('full_delivery')}
                disabled={shipLoading}
                className="w-full rounded-md border border-gray-200 p-4 text-left transition-colors hover:border-amber-400 hover:bg-yellow-50 disabled:cursor-not-allowed disabled:opacity-50"
              >
                <div className="flex items-start gap-3">
                  <div className="mt-0.5 flex h-10 w-10 shrink-0 items-center justify-center rounded-md bg-yellow-100">
                    <PackageCheck className="w-5 h-5 text-yellow-700" />
                  </div>
                  <div>
                    <div className="font-bold text-gray-900 text-sm">完整发货（匹配卡券并发送）</div>
                    <div className="text-xs text-gray-500 mt-1 leading-relaxed">
                      自动匹配发货规则、获取卡券、发送卡券信息给买家，并修改发货状态。
                      适用于订单既没有发送卡券给买家、也没有修改发货状态的情况。
                    </div>
                  </div>
                </div>
              </button>

              {/* 加载状态 */}
              {shipLoading && (
                <div className="flex items-center justify-center gap-2 py-3">
                  <RefreshCw className="w-4 h-4 animate-spin text-gray-500" />
                  <span className="text-sm text-gray-500">正在处理中...</span>
                </div>
              )}

              {/* 结果显示 */}
              {shipResult && (
                <div className={`rounded-md border p-3 text-sm ${shipResult.success ? 'border-green-200 bg-green-50 text-green-800' : 'border-red-200 bg-red-50 text-red-800'}`}>
                  {shipResult.message}
                </div>
              )}
            </div>

            <div className="modal-footer">
              <button
                type="button"
                onClick={() => { setShowShipModal(false); setShipResult(null); }}
                className="ios-btn-secondary w-full rounded-md px-4 py-2.5 text-sm"
              >
                {shipResult?.success ? '完成' : '取消'}
              </button>
            </div>
          </div>
        </div>,
        document.body
      )}

      {/* Edit Modal - 使用 Portal */}
      {showEditModal && editingOrder && createPortal(
        <div className="modal-overlay">
          <div className="modal-container">
            <div className="modal-header">
              <div className="flex w-full items-start justify-between gap-4">
                <div>
                  <h3 className="text-lg font-bold text-gray-900">编辑订单</h3>
                  <p className="mt-1 break-all text-xs text-gray-500">{editingOrder.order_id}</p>
                </div>
                <button
                  type="button"
                  onClick={() => setShowEditModal(false)}
                  className="rounded-md p-2 hover:bg-gray-100"
                  aria-label="关闭编辑订单"
                >
                  <X className="w-5 h-5 text-gray-600" />
                </button>
              </div>
            </div>

            <div className="modal-body space-y-5">
              <div className="grid gap-4 sm:grid-cols-2">
                <div>
                  <label className="block text-sm font-bold text-gray-700 mb-2">订单号</label>
                  <input
                    type="text"
                    value={editingOrder.order_id}
                    disabled
                    className="ios-input w-full rounded-md bg-gray-50 px-3 py-2.5 text-gray-500"
                  />
                </div>
                <div>
                  <label className="block text-sm font-bold text-gray-700 mb-2">订单状态</label>
                  <select
                    value={editingOrder.status}
                    onChange={(e) => setEditingOrder({ ...editingOrder, status: e.target.value as OrderStatus })}
                    className="ios-input w-full rounded-md px-3 py-2.5"
                  >
                    <option value="processing">处理中</option>
                    <option value="pending_ship">待发货</option>
                    <option value="shipped">已发货</option>
                    <option value="completed">已完成</option>
                    <option value="cancelled">已取消</option>
                    <option value="refunding">退款中</option>
                  </select>
                </div>
              </div>

              <div className="grid gap-4 sm:grid-cols-2">
                <div>
                  <label className="block text-sm font-bold text-gray-700 mb-2">买家ID</label>
                  <input
                    type="text"
                    value={editingOrder.buyer_id}
                    onChange={(e) => setEditingOrder({ ...editingOrder, buyer_id: e.target.value })}
                    className="ios-input w-full rounded-md px-3 py-2.5"
                  />
                </div>
                <div>
                  <label className="block text-sm font-bold text-gray-700 mb-2">实付金额</label>
                  <input
                    type="number"
                    value={editingOrder.amount}
                    onChange={(e) => setEditingOrder({ ...editingOrder, amount: parseFloat(e.target.value) })}
                    className="ios-input w-full rounded-md px-3 py-2.5"
                  />
                </div>
              </div>

              <div className="grid gap-4 sm:grid-cols-2">
                <div>
                  <label className="block text-sm font-bold text-gray-700 mb-2">收货人</label>
                  <input
                    type="text"
                    value={editingOrder.receiver_name || ''}
                    onChange={(e) => setEditingOrder({ ...editingOrder, receiver_name: e.target.value })}
                    className="ios-input w-full rounded-md px-3 py-2.5"
                  />
                </div>
                <div>
                  <label className="block text-sm font-bold text-gray-700 mb-2">联系电话</label>
                  <input
                    type="text"
                    value={editingOrder.receiver_phone || ''}
                    onChange={(e) => setEditingOrder({ ...editingOrder, receiver_phone: e.target.value })}
                    className="ios-input w-full rounded-md px-3 py-2.5"
                  />
                </div>
              </div>

              <div>
                <label className="block text-sm font-bold text-gray-700 mb-2">收货地址</label>
                <textarea
                  value={editingOrder.receiver_address || ''}
                  onChange={(e) => setEditingOrder({ ...editingOrder, receiver_address: e.target.value })}
                  rows={2}
                  className="ios-input w-full resize-y rounded-md px-3 py-2.5"
                />
              </div>

              <div>
                <label className="block text-sm font-bold text-gray-700 mb-2">商品标题</label>
                <input
                  type="text"
                  value={editingOrder.item_title || ''}
                  onChange={(e) => setEditingOrder({ ...editingOrder, item_title: e.target.value })}
                  className="ios-input w-full rounded-md px-3 py-2.5"
                />
              </div>
            </div>

            <div className="modal-footer">
              <div className="flex w-full gap-2">
                <button
                  type="button"
                  onClick={() => setShowEditModal(false)}
                  className="ios-btn-secondary flex-1 rounded-md px-4 py-2.5 text-sm"
                >
                  取消
                </button>
                <button
                  type="button"
                  onClick={handleSaveEdit}
                  className="ios-btn-primary flex flex-1 items-center justify-center gap-2 rounded-md px-4 py-2.5 text-sm"
                >
                  <Save className="w-4 h-4" />
                  保存更改
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

export default OrderList;
