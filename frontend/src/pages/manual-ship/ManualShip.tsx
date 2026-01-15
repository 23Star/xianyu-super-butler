import { useState, useEffect } from 'react'
import { motion } from 'framer-motion'
import { Package, RefreshCw, Send, MessageSquare, CheckSquare, Square } from 'lucide-react'
import { getOrders } from '@/api/orders'
import { verifyAllOrders, manualShipOrders } from '@/api/manual-ship'
import { getAccounts } from '@/api/accounts'
import { useUIStore } from '@/store/uiStore'
import { useAuthStore } from '@/store/authStore'
import { PageLoading } from '@/components/common/Loading'
import { Select } from '@/components/common/Select'
import type { Order, Account } from '@/types'

const statusMap: Record<string, { label: string; class: string }> = {
  pending_ship: { label: '待发货', class: 'badge-warning' },
  processing: { label: '处理中', class: 'badge-info' },
  processed: { label: '已处理', class: 'badge-success' },
  shipped: { label: '已发货', class: 'badge-success' },
  completed: { label: '已完成', class: 'badge-success' },
  refunding: { label: '退款中', class: 'badge-error' },
  cancelled: { label: '已取消', class: 'badge-gray' },
  unknown: { label: '未知', class: 'badge-gray' },
}

export function ManualShip() {
  const { addToast } = useUIStore()
  const { isAuthenticated, token, _hasHydrated } = useAuthStore()
  const [loading, setLoading] = useState(true)
  const [orders, setOrders] = useState<Order[]>([])
  const [accounts, setAccounts] = useState<Account[]>([])
  const [selectedAccount, setSelectedAccount] = useState('')
  const [selectedOrders, setSelectedOrders] = useState<Set<string>>(new Set())
  const [verifying, setVerifying] = useState(false)
  const [shipping, setShipping] = useState(false)
  const [customContent, setCustomContent] = useState('')
  const [showCustomModal, setShowCustomModal] = useState(false)

  const loadPendingOrders = async () => {
    if (!_hasHydrated || !isAuthenticated || !token) return
    try {
      setLoading(true)
      // 只获取待发货状态的订单
      const result = await getOrders(selectedAccount || undefined, 'pending_ship', 1, 1000)
      if (result.success) {
        // 过滤出system_shipped=0的订单
        const pendingOrders = (result.data || []).filter(order => !order.system_shipped)
        setOrders(pendingOrders)
      }
    } catch {
      addToast({ type: 'error', message: '加载待发货订单列表失败' })
    } finally {
      setLoading(false)
    }
  }

  const loadAccounts = async () => {
    if (!_hasHydrated || !isAuthenticated || !token) return
    try {
      const accounts = await getAccounts()
      setAccounts(accounts || [])
    } catch {
      // 静默失败
    }
  }

  useEffect(() => {
    if (_hasHydrated && isAuthenticated && token) {
      loadAccounts()
    }
  }, [_hasHydrated, isAuthenticated, token])

  useEffect(() => {
    if (!_hasHydrated || !isAuthenticated || !token) return
    loadPendingOrders()
  }, [_hasHydrated, isAuthenticated, token, selectedAccount])

  const handleSelectAll = () => {
    if (selectedOrders.size === orders.length) {
      setSelectedOrders(new Set())
    } else {
      setSelectedOrders(new Set(orders.map(o => o.order_id)))
    }
  }

  const handleSelectOrder = (orderId: string) => {
    const newSelected = new Set(selectedOrders)
    if (newSelected.has(orderId)) {
      newSelected.delete(orderId)
    } else {
      newSelected.add(orderId)
    }
    setSelectedOrders(newSelected)
  }

  const handleVerifyAll = async () => {
    if (!confirm('确定要核对所有订单数据吗？这可能需要较长时间。')) return

    setVerifying(true)
    try {
      const result = await verifyAllOrders()
      if (result.success) {
        addToast({
          type: 'success',
          message: `核对完成：成功${result.success_count}个，失败${result.failed_count}个`
        })
        loadPendingOrders()
      } else {
        addToast({ type: 'error', message: result.message || '核对失败' })
      }
    } catch {
      addToast({ type: 'error', message: '核对订单数据失败' })
    } finally {
      setVerifying(false)
    }
  }

  const handleAutoShipSingle = async (orderId: string) => {
    if (!confirm('确定要自动发货此订单吗？')) return

    setShipping(true)
    try {
      const result = await manualShipOrders([orderId], 'auto_match')
      if (result.success) {
        addToast({ type: 'success', message: '发货请求已提交' })
        loadPendingOrders()
      } else {
        addToast({ type: 'error', message: result.message || '发货失败' })
      }
    } catch {
      addToast({ type: 'error', message: '发货失败' })
    } finally {
      setShipping(false)
    }
  }

  const handleCustomShipSingle = (orderId: string) => {
    setSelectedOrders(new Set([orderId]))
    setShowCustomModal(true)
  }

  const handleBatchAutoShip = async () => {
    if (selectedOrders.size === 0) {
      addToast({ type: 'warning', message: '请先选择订单' })
      return
    }
    if (!confirm(`确定要对选中的 ${selectedOrders.size} 个订单自动发货吗？`)) return

    setShipping(true)
    try {
      const result = await manualShipOrders(Array.from(selectedOrders), 'auto_match')
      if (result.success) {
        addToast({
          type: 'success',
          message: `发货完成：成功${result.success_count}个，失败${result.failed_count}个`
        })
        setSelectedOrders(new Set())
        loadPendingOrders()
      } else {
        addToast({ type: 'error', message: result.message || '批量发货失败' })
      }
    } catch {
      addToast({ type: 'error', message: '批量发货失败' })
    } finally {
      setShipping(false)
    }
  }

  const handleBatchCustomShip = () => {
    if (selectedOrders.size === 0) {
      addToast({ type: 'warning', message: '请先选择订单' })
      return
    }
    setShowCustomModal(true)
  }

  const handleSubmitCustomShip = async () => {
    if (!customContent.trim()) {
      addToast({ type: 'warning', message: '请输入发货内容' })
      return
    }

    const orderIds = Array.from(selectedOrders)
    if (!confirm(`确定要对选中的 ${orderIds.length} 个订单发送自定义内容吗？`)) return

    setShipping(true)
    try {
      const result = await manualShipOrders(orderIds, 'custom', customContent)
      if (result.success) {
        addToast({
          type: 'success',
          message: `发货完成：成功${result.success_count}个，失败${result.failed_count}个`
        })
        setShowCustomModal(false)
        setCustomContent('')
        setSelectedOrders(new Set())
        loadPendingOrders()
      } else {
        addToast({ type: 'error', message: result.message || '发货失败' })
      }
    } catch {
      addToast({ type: 'error', message: '发货失败' })
    } finally {
      setShipping(false)
    }
  }

  if (!_hasHydrated || loading) {
    return <PageLoading />
  }

  if (!isAuthenticated) {
    return (
      <div className="flex items-center justify-center h-full">
        <p className="text-gray-500">请先登录</p>
      </div>
    )
  }

  return (
    <div className="p-4 sm:p-6 space-y-4 sm:space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">补发货管理</h1>
          <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
            管理待发货订单，支持单独发货和批量发货
          </p>
        </div>
        <div className="flex flex-col sm:flex-row gap-2">
          <button
            onClick={loadPendingOrders}
            disabled={loading}
            className="btn-ios-secondary w-full sm:w-auto"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
            刷新列表
          </button>
          <button
            onClick={handleVerifyAll}
            disabled={verifying}
            className="btn-ios-primary w-full sm:w-auto"
          >
            <RefreshCw className={`w-4 h-4 ${verifying ? 'animate-spin' : ''}`} />
            {verifying ? '核对中...' : '全量核对订单数据'}
          </button>
        </div>
      </div>

      {/* Filter */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        className="vben-card"
      >
        <div className="vben-card-body">
          <div className="input-group">
            <label className="input-label">筛选账号</label>
            <Select
              value={selectedAccount}
              onChange={setSelectedAccount}
              options={[
                { value: '', label: '所有账号' },
                ...accounts.map((account) => ({
                  value: account.id,
                  label: account.id,
                })),
              ]}
              placeholder="所有账号"
            />
          </div>
        </div>
      </motion.div>

      {/* Batch Actions */}
      {selectedOrders.size > 0 && (
        <motion.div
          initial={{ opacity: 0, y: -10 }}
          animate={{ opacity: 1, y: 0 }}
          className="vben-card"
        >
          <div className="vben-card-body flex flex-wrap items-center gap-3">
            <span className="text-sm text-gray-600 dark:text-gray-400">
              已选择 <span className="font-bold text-amber-600">{selectedOrders.size}</span> 个订单
            </span>
            <div className="flex gap-2 ml-auto">
              <button
                onClick={handleBatchAutoShip}
                disabled={shipping}
                className="btn-ios-primary"
              >
                <Send className="w-4 h-4" />
                全部自动发货
              </button>
              <button
                onClick={handleBatchCustomShip}
                disabled={shipping}
                className="btn-ios-secondary"
              >
                <MessageSquare className="w-4 h-4" />
                全部自定义发货
              </button>
            </div>
          </div>
        </motion.div>
      )}

      {/* Orders List */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.1 }}
        className="vben-card"
      >
        <div className="vben-card-header flex items-center justify-between">
          <h2 className="vben-card-title">
            <Package className="w-4 h-4" />
            待发货订单列表
          </h2>
          <span className="badge-warning">共 {orders.length} 个订单</span>
        </div>
        <div className="overflow-x-auto">
          <table className="table-ios">
            <thead>
              <tr>
                <th className="w-12">
                  <button
                    onClick={handleSelectAll}
                    className="p-2 hover:bg-gray-100 dark:hover:bg-gray-700 rounded transition-colors"
                  >
                    {selectedOrders.size === orders.length && orders.length > 0 ? (
                      <CheckSquare className="w-4 h-4 text-amber-500" />
                    ) : (
                      <Square className="w-4 h-4 text-gray-400" />
                    )}
                  </button>
                </th>
                <th>订单ID</th>
                <th>商品ID</th>
                <th>买家ID</th>
                <th>数量</th>
                <th>金额</th>
                <th>状态</th>
                <th>账号ID</th>
                <th>创建时间</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {orders.length === 0 ? (
                <tr>
                  <td colSpan={10} className="text-center py-8 text-gray-500">
                    <div className="flex flex-col items-center gap-2">
                      <Package className="w-12 h-12 text-gray-300" />
                      <p>暂无待发货订单</p>
                    </div>
                  </td>
                </tr>
              ) : (
                orders.map((order) => {
                  const status = statusMap[order.status] || { label: order.status, class: 'badge-gray' }
                  const isSelected = selectedOrders.has(order.order_id)

                  return (
                    <tr key={order.id} className={isSelected ? 'bg-amber-50 dark:bg-amber-900/10' : ''}>
                      <td>
                        <button
                          onClick={() => handleSelectOrder(order.order_id)}
                          className="p-2 hover:bg-gray-100 dark:hover:bg-gray-700 rounded transition-colors"
                        >
                          {isSelected ? (
                            <CheckSquare className="w-4 h-4 text-amber-500" />
                          ) : (
                            <Square className="w-4 h-4 text-gray-400" />
                          )}
                        </button>
                      </td>
                      <td className="font-mono text-sm">{order.order_id}</td>
                      <td className="text-sm">{order.item_id}</td>
                      <td className="text-sm">{order.buyer_id}</td>
                      <td>{order.quantity}</td>
                      <td className="text-amber-600 font-medium">¥{order.amount}</td>
                      <td>
                        <span className={status.class}>{status.label}</span>
                      </td>
                      <td className="font-medium text-amber-600 dark:text-amber-400">{order.cookie_id}</td>
                      <td className="text-sm text-gray-500">
                        {order.created_at ? new Date(order.created_at).toLocaleString('zh-CN') : '-'}
                      </td>
                      <td>
                        <div className="flex items-center gap-1">
                          <button
                            onClick={() => handleAutoShipSingle(order.order_id)}
                            disabled={shipping}
                            className="p-2 rounded-lg hover:bg-green-50 dark:hover:bg-green-900/20 transition-colors"
                            title="自动发货"
                          >
                            <Send className="w-4 h-4 text-green-500" />
                          </button>
                          <button
                            onClick={() => handleCustomShipSingle(order.order_id)}
                            disabled={shipping}
                            className="p-2 rounded-lg hover:bg-blue-50 dark:hover:bg-blue-900/20 transition-colors"
                            title="自定义发货"
                          >
                            <MessageSquare className="w-4 h-4 text-blue-500" />
                          </button>
                        </div>
                      </td>
                    </tr>
                  )
                })
              )}
            </tbody>
          </table>
        </div>
      </motion.div>

      {/* Custom Content Modal */}
      {showCustomModal && (
        <div className="modal-overlay">
          <div className="modal-container">
            <div className="modal-header">
              <h3 className="modal-title">
                <MessageSquare className="w-5 h-5" />
                自定义发货内容
              </h3>
              <button
                onClick={() => {
                  setShowCustomModal(false)
                  setCustomContent('')
                }}
                className="modal-close"
              >
                ×
              </button>
            </div>
            <div className="modal-body">
              <div className="space-y-4">
                <div>
                  <p className="text-sm text-gray-600 dark:text-gray-400 mb-2">
                    将向选中的 <span className="font-bold text-amber-600">{selectedOrders.size}</span> 个订单发送以下内容：
                  </p>
                  <textarea
                    value={customContent}
                    onChange={(e) => setCustomContent(e.target.value)}
                    placeholder="请输入发货内容..."
                    className="input-ios min-h-[120px]"
                  />
                </div>
              </div>
            </div>
            <div className="modal-footer">
              <button
                onClick={() => {
                  setShowCustomModal(false)
                  setCustomContent('')
                }}
                className="btn-ios-secondary"
                disabled={shipping}
              >
                取消
              </button>
              <button
                onClick={handleSubmitCustomShip}
                className="btn-ios-primary"
                disabled={shipping || !customContent.trim()}
              >
                {shipping ? '发送中...' : '确认发送'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
