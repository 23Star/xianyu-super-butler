import React, { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import { Card } from '../types';
import { getCards, createCard, updateCard, deleteCard } from '../services/api';
import { confirmAction, notify } from '../services/feedback';
import { Plus, CreditCard, FileText, Image as ImageIcon, Code, Edit, Trash2, Save, X, Package, Boxes } from 'lucide-react';
import { EmptyState, PageHeader, SectionHeader } from './ui';

const CardList: React.FC = () => {
  const [cards, setCards] = useState<Card[]>([]);
  const [showEditModal, setShowEditModal] = useState(false);
  const [showAddModal, setShowAddModal] = useState(false);
  const [selectedCard, setSelectedCard] = useState<Card | null>(null);
  const [editForm, setEditForm] = useState<Partial<Card>>({});
  const [addForm, setAddForm] = useState({
    name: '',
    type: 'text' as Card['type'],
    content: '',
    description: '',
    enabled: true,
    delay_seconds: 0
  });

  useEffect(() => {
    getCards().then(setCards);
  }, []);

  const CardIcon = ({ type }: { type: string }) => {
      switch(type) {
          case 'text': return <FileText className="w-5 h-5 text-blue-500" />;
          case 'image': return <ImageIcon className="w-5 h-5 text-purple-500" />;
          case 'api': return <Code className="w-5 h-5 text-orange-500" />;
          default: return <CreditCard className="w-5 h-5 text-gray-500" />;
      }
  };

  const handleEdit = (card: Card) => {
    setSelectedCard(card);
    setEditForm({
      id: card.id,
      name: card.name || '',
      type: card.type || 'text',
      // API 配置
      api_url: card.api_config?.url || '',
      api_method: card.api_config?.method || 'GET',
      api_timeout: card.api_config?.timeout || 10,
      api_headers: card.api_config?.headers || '',
      api_params: card.api_config?.params || '',
      // 文本配置
      text_content: card.text_content || '',
      // 批量数据配置
      data_content: card.data_content || '',
      // 图片配置
      image_url: card.image_url || '',
      // 通用配置
      delay_seconds: card.delay_seconds || 0,
      description: card.description || '',
      enabled: card.enabled
    });
    setShowEditModal(true);
  };

  const handleSaveEdit = async () => {
    if (!selectedCard) return;

    // 验证必填字段
    if (!editForm.name?.trim()) {
      notify('请输入卡密名称');
      return;
    }
    if (!editForm.type) {
      notify('请选择卡密类型');
      return;
    }

    try {
      const updateData: Partial<Card> = {
        name: editForm.name.trim(),
        type: editForm.type as any,
        description: editForm.description?.trim(),
        delay_seconds: editForm.delay_seconds || 0,
        enabled: editForm.enabled ?? true
      };

      // 根据类型设置内容
      if (editForm.type === 'api') {
        updateData.api_config = {
          url: editForm.api_url?.trim(),
          method: editForm.api_method as 'GET' | 'POST',
          timeout: editForm.api_timeout || 10,
          headers: editForm.api_headers?.trim() || undefined,
          params: editForm.api_params?.trim() || undefined
        };
      } else if (editForm.type === 'text') {
        updateData.text_content = editForm.text_content?.trim() || '';
      } else if (editForm.type === 'data') {
        updateData.data_content = editForm.data_content?.trim() || '';
      } else if (editForm.type === 'image') {
        updateData.image_url = editForm.image_url?.trim() || '';
      }

      await updateCard(selectedCard.id, updateData);
      setShowEditModal(false);
      getCards().then(setCards);
    } catch (error) {
      console.error('更新卡密失败:', error);
      notify('更新失败，请重试');
    }
  };

  const handleDelete = async (id: string) => {
    if (await confirmAction('确认删除该卡密吗？')) {
      try {
        await deleteCard(id);
        getCards().then(setCards);
      } catch (error) {
        console.error('删除卡密失败:', error);
        notify('删除失败，请重试');
      }
    }
  };

  const handleAddCard = async () => {
    const name = addForm.name.trim();
    const content = addForm.content.trim();
    if (!name) {
      notify('请输入卡密名称');
      return;
    }
    if (!content) {
      notify(addForm.type === 'api' ? '请输入 API 地址' : '请输入卡密内容');
      return;
    }

    try {
      const createData: Partial<Card> = {
        name,
        type: addForm.type,
        description: addForm.description.trim(),
        enabled: addForm.enabled,
        delay_seconds: addForm.delay_seconds
      };

      if (addForm.type === 'text') {
        createData.text_content = content;
      } else if (addForm.type === 'data') {
        createData.data_content = content;
      } else if (addForm.type === 'image') {
        createData.image_url = content;
      } else {
        createData.api_config = {
          url: content,
          method: 'GET',
          timeout: 10
        };
      }

      await createCard(createData);
      setShowAddModal(false);
      setAddForm({
        name: '',
        type: 'text',
        content: '',
        description: '',
        enabled: true,
        delay_seconds: 0
      });
      getCards().then(setCards);
    } catch (error) {
      console.error('添加卡密失败:', error);
      notify('添加失败，请重试');
    }
  };

  const toggleCardStatus = async (card: Card) => {
    try {
      await updateCard(card.id, { ...card, enabled: !card.enabled });
      getCards().then(setCards);
    } catch (error) {
      console.error('切换状态失败:', error);
    }
  };

  const enabledCount = cards.filter(card => card.enabled).length;
  const batchInventory = cards.reduce((total, card) => {
    if (card.type !== 'data' || !card.data_content) return total;
    return total + card.data_content.split('\n').filter(line => line.trim()).length;
  }, 0);

  return (
    <div className="page-stack animate-fade-in">
      <PageHeader
        title="卡密库存"
        description="集中维护自动发货所需的固定文本、批量卡密、图片和 API 数据源。"
        icon={CreditCard}
        actions={(
          <button
            onClick={() => setShowAddModal(true)}
            className="ios-btn-primary flex items-center justify-center gap-2 rounded-md px-4 py-2 text-sm"
          >
            <Plus className="h-4 w-4" />
            添加卡密
          </button>
        )}
      />

      <div className="metric-grid">
        <div className="metric-card">
          <p className="metric-card__label">卡密组</p>
          <p className="metric-card__value">{cards.length}</p>
          <p className="metric-card__meta">所有已配置的数据源</p>
        </div>
        <div className="metric-card">
          <p className="metric-card__label">启用中</p>
          <p className="metric-card__value">{enabledCount}</p>
          <p className="metric-card__meta">{cards.length - enabledCount} 组已停用</p>
        </div>
        <div className="metric-card">
          <p className="metric-card__label">批量库存</p>
          <p className="metric-card__value">{batchInventory}</p>
          <p className="metric-card__meta">按有效非空行统计</p>
        </div>
      </div>

      <section className="section-panel">
        <SectionHeader
          title="库存数据源"
          description="停用后不会被自动发货规则调用，已有内容仍会保留。"
          icon={Boxes}
        />
        <div className="overflow-x-auto">
          <table className="data-table responsive-data-table min-w-[860px]">
            <thead>
              <tr>
                <th className="w-[22%]">卡密名称</th>
                <th className="w-[11%]">类型</th>
                <th className="w-[25%]">内容 / 库存</th>
                <th className="w-[22%]">说明</th>
                <th className="w-[10%]">状态</th>
                <th className="w-[10%] text-right">操作</th>
              </tr>
            </thead>
            <tbody>
              {cards.map((card) => {
                // 计算库存或内容预览
                let stockInfo = '';
                if (card.type === 'data' && card.data_content) {
                  const lines = card.data_content.split('\n').filter(line => line.trim());
                  stockInfo = `库存: ${lines.length} 条`;
                } else if (card.type === 'text' && card.text_content) {
                  stockInfo = card.text_content.substring(0, 20) + (card.text_content.length > 20 ? '...' : '');
                } else if (card.type === 'api' && card.api_config) {
                  stockInfo = card.api_config.url;
                } else if (card.type === 'image' && card.image_url) {
                  stockInfo = '图片链接';
                }

                return (
                  <tr key={card.id} className="group">
                    <td data-label="卡密名称">
                      <div className="flex items-center gap-3">
                        <div className="rounded-md border border-gray-200 bg-gray-50 p-2">
                          <CardIcon type={card.type} />
                        </div>
                        <span className="text-sm font-bold text-gray-900">{card.name}</span>
                      </div>
                    </td>
                    <td data-label="类型">
                      <span className={`inline-flex rounded px-2 py-1 text-xs font-bold ${
                        card.type === 'text' ? 'bg-blue-50 text-blue-600' :
                        card.type === 'data' ? 'bg-purple-50 text-purple-600' :
                        card.type === 'api' ? 'bg-orange-50 text-orange-600' :
                        'bg-pink-50 text-pink-600'
                      }`}>
                        {card.type === 'text' ? '文本' :
                         card.type === 'data' ? '批量' :
                         card.type === 'api' ? 'API' : '图片'}
                      </span>
                    </td>
                    <td data-label="内容 / 库存">
                      <span className="block max-w-[260px] truncate font-mono text-xs text-gray-600" title={stockInfo}>
                        {stockInfo}
                      </span>
                    </td>
                    <td data-label="说明">
                      <span
                        className="block max-w-[220px] truncate text-sm text-gray-500"
                        title={card.description || '-'}
                      >
                        {card.description || '-'}
                      </span>
                    </td>
                    <td data-label="状态">
                      <button
                        onClick={() => toggleCardStatus(card)}
                        className={`relative h-6 w-10 rounded-full transition-colors ${
                          card.enabled ? 'bg-[#ffe100]' : 'bg-gray-300'
                        }`}
                        title={card.enabled ? '停用' : '启用'}
                        aria-label={`${card.enabled ? '停用' : '启用'}卡密 ${card.name}`}
                      >
                        <span className={`absolute top-1 h-4 w-4 rounded-full bg-white shadow-sm transition-transform ${
                          card.enabled ? 'left-5' : 'left-1'
                        }`} />
                      </button>
                    </td>
                    <td data-label="操作">
                      <div className="flex items-center justify-end gap-1">
                        <button
                          onClick={() => handleEdit(card)}
                          className="rounded-md p-2 text-gray-500 transition-colors hover:bg-gray-100 hover:text-black"
                          title="编辑"
                          aria-label={`编辑卡密 ${card.name}`}
                        >
                          <Edit className="w-4 h-4" />
                        </button>
                        <button
                          onClick={() => handleDelete(card.id)}
                          className="rounded-md p-2 text-gray-500 transition-colors hover:bg-red-50 hover:text-red-600"
                          title="删除"
                          aria-label={`删除卡密 ${card.name}`}
                        >
                          <Trash2 className="h-4 w-4" />
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        {cards.length === 0 && (
          <div className="p-4">
            <EmptyState
              compact
              icon={Package}
              title="暂无卡密配置"
              description="添加固定文本、批量卡密、图片或 API 数据源后，可在商品发货策略中直接选择。"
            />
          </div>
        )}
      </section>

      {/* 编辑卡密弹窗 - 使用 Portal */}
      {showEditModal && selectedCard && createPortal(
        <div className="modal-overlay">
          <div className="modal-container">
            <div className="modal-header">
              <div className="flex items-center justify-between gap-4">
                <div>
                  <h3 className="text-lg font-bold text-gray-900">编辑卡密</h3>
                  <p className="mt-1 text-xs text-gray-500">修改数据源内容及发货调用方式。</p>
                </div>
                <button
                  onClick={() => setShowEditModal(false)}
                  className="rounded-md p-2 hover:bg-gray-100"
                  aria-label="关闭编辑卡密"
                >
                  <X className="w-5 h-5 text-gray-500" />
                </button>
              </div>
            </div>

            <div className="modal-body">
              <div className="space-y-5">
                {/* 基本信息 */}
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div>
                    <label className="block text-sm font-bold text-gray-700 mb-2">卡密名称 <span className="text-red-500">*</span></label>
                    <input
                      type="text"
                      value={editForm.name || ''}
                      onChange={(e) => setEditForm({ ...editForm, name: e.target.value })}
                      className="ios-input w-full rounded-md px-3 py-2.5"
                      placeholder="例如：游戏点卡、会员卡等"
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-bold text-gray-700 mb-2">卡券类型</label>
                    <select
                      value={editForm.type || 'text'}
                      onChange={(e) => setEditForm({ ...editForm, type: e.target.value as any })}
                      className="ios-input w-full rounded-md px-3 py-2.5"
                    >
                      <option value="">请选择类型</option>
                      <option value="text">固定文字</option>
                      <option value="data">批量数据</option>
                      <option value="api">API接口</option>
                      <option value="image">图片</option>
                    </select>
                  </div>
                </div>

                {/* API 配置 */}
                {editForm.type === 'api' && (
                  <div className="space-y-4 rounded-md border border-gray-200 bg-gray-50 p-4">
                    <h3 className="font-bold text-gray-900">API 配置</h3>
                    <div>
                      <label className="block text-sm font-bold text-gray-700 mb-2">API 地址</label>
                      <input
                        type="url"
                        value={editForm.api_url || ''}
                        onChange={(e) => setEditForm({ ...editForm, api_url: e.target.value })}
                        className="ios-input w-full rounded-md px-3 py-2.5 font-mono text-sm"
                        placeholder="https://api.example.com/get-card"
                      />
                    </div>
                    <div className="grid gap-4 sm:grid-cols-2">
                      <div>
                        <label className="block text-sm font-bold text-gray-700 mb-2">请求方法</label>
                        <select
                          value={editForm.api_method || 'GET'}
                          onChange={(e) => setEditForm({ ...editForm, api_method: e.target.value as 'GET' | 'POST' })}
                          className="ios-input w-full rounded-md px-3 py-2.5"
                        >
                          <option value="GET">GET</option>
                          <option value="POST">POST</option>
                        </select>
                      </div>
                      <div>
                        <label className="block text-sm font-bold text-gray-700 mb-2">超时时间（秒）</label>
                        <input
                          type="number"
                          value={editForm.api_timeout || 10}
                          onChange={(e) => setEditForm({ ...editForm, api_timeout: parseInt(e.target.value) || 10 })}
                          className="ios-input w-full rounded-md px-3 py-2.5"
                          min="1"
                          max="60"
                        />
                      </div>
                    </div>
                    <div>
                      <label className="block text-sm font-bold text-gray-700 mb-2">请求头（JSON 格式）</label>
                      <textarea
                        value={editForm.api_headers || ''}
                        onChange={(e) => setEditForm({ ...editForm, api_headers: e.target.value })}
                        className="ios-input h-20 w-full resize-y rounded-md px-3 py-2.5 font-mono text-sm"
                        placeholder='{"Authorization": "Bearer token"}'
                      />
                    </div>
                    <div>
                      <label className="block text-sm font-bold text-gray-700 mb-2">请求参数（JSON 格式）</label>
                      <textarea
                        value={editForm.api_params || ''}
                        onChange={(e) => setEditForm({ ...editForm, api_params: e.target.value })}
                        className="ios-input h-20 w-full resize-y rounded-md px-3 py-2.5 font-mono text-sm"
                        placeholder='{"type": "card", "count": 1}'
                      />
                    </div>
                  </div>
                )}

                {/* 固定文字配置 */}
                {editForm.type === 'text' && (
                  <div className="rounded-md border border-gray-200 bg-gray-50 p-4">
                    <h3 className="font-bold text-gray-900 mb-3">固定文字配置</h3>
                    <div>
                      <label className="block text-sm font-bold text-gray-700 mb-2">文字内容</label>
                      <textarea
                        value={editForm.text_content || ''}
                        onChange={(e) => setEditForm({ ...editForm, text_content: e.target.value })}
                        className="ios-input h-32 w-full resize-y rounded-md px-3 py-2.5"
                        placeholder="请输入要发送的固定文字内容..."
                      />
                    </div>
                  </div>
                )}

                {/* 批量数据配置 */}
                {editForm.type === 'data' && (
                  <div className="rounded-md border border-gray-200 bg-gray-50 p-4">
                    <h3 className="font-bold text-gray-900 mb-3">批量数据配置</h3>
                    <div>
                      <label className="block text-sm font-bold text-gray-700 mb-2">数据内容（一行一个）</label>
                      <textarea
                        value={editForm.data_content || ''}
                        onChange={(e) => setEditForm({ ...editForm, data_content: e.target.value })}
                        className="ios-input h-72 w-full resize-y rounded-md px-3 py-2.5 font-mono text-sm"
                        placeholder="请输入数据，每行一个：&#10;卡号1:密码1&#10;卡号2:密码2&#10;或者&#10;兑换码1&#10;兑换码2"
                      />
                      <p className="text-xs text-gray-500 mt-2">支持格式：卡号:密码 或 单独的兑换码</p>
                      <p className="text-xs text-gray-500">当前库存：<span className="font-bold text-amber-600">
                        {editForm.data_content ? editForm.data_content.split('\n').filter(line => line.trim()).length : 0}
                      </span> 条</p>
                    </div>
                  </div>
                )}

                {/* 图片配置 */}
                {editForm.type === 'image' && (
                  <div className="rounded-md border border-gray-200 bg-gray-50 p-4">
                    <h3 className="font-bold text-gray-900 mb-3">图片配置</h3>
                    <div>
                      <label className="block text-sm font-bold text-gray-700 mb-2">图片 URL</label>
                      <input
                        type="url"
                        value={editForm.image_url || ''}
                        onChange={(e) => setEditForm({ ...editForm, image_url: e.target.value })}
                        className="ios-input w-full rounded-md px-3 py-2.5 font-mono text-sm"
                        placeholder="https://example.com/image.png"
                      />
                      <p className="text-xs text-gray-500 mt-2">输入图片卡密的 URL 地址</p>
                    </div>
                    {editForm.image_url && (
                      <div className="mt-3">
                        <label className="block text-sm font-bold text-gray-700 mb-2">图片预览</label>
                        <img
                          src={editForm.image_url}
                          alt="预览"
                          className="max-h-48 max-w-full rounded-md border border-gray-200"
                          onError={(e) => { e.currentTarget.src = 'https://via.placeholder.com/400x200?text=图片加载失败'; }}
                        />
                      </div>
                    )}
                  </div>
                )}

                {/* 延时发货时间 */}
                <div>
                  <label className="block text-sm font-bold text-gray-700 mb-2">延时发货时间（秒）</label>
                  <div className="flex items-center gap-2">
                    <input
                      type="number"
                      value={editForm.delay_seconds || 0}
                      onChange={(e) => setEditForm({ ...editForm, delay_seconds: parseInt(e.target.value) || 0 })}
                      className="ios-input flex-1 rounded-md px-3 py-2.5"
                      min="0"
                      max="3600"
                      placeholder="0"
                    />
                    <span className="text-sm text-gray-500 whitespace-nowrap">秒</span>
                  </div>
                  <p className="text-xs text-gray-500 mt-1">0表示立即发货，最大3600秒（1小时）</p>
                </div>

                {/* 备注信息 */}
                <div>
                  <label className="block text-sm font-bold text-gray-700 mb-2">备注信息</label>
                  <textarea
                    value={editForm.description || ''}
                    onChange={(e) => setEditForm({ ...editForm, description: e.target.value })}
                    className="ios-input h-32 w-full resize-y rounded-md px-3 py-2.5"
                    placeholder="可选的备注信息"
                  />
                </div>

                {/* 启用状态 */}
                <div className="flex items-center justify-between gap-4 rounded-md border border-gray-200 bg-gray-50 p-4">
                  <span className="font-bold text-gray-900">启用状态</span>
                  <button
                    type="button"
                    onClick={() => setEditForm({ ...editForm, enabled: !editForm.enabled })}
                    className={`relative h-6 w-11 shrink-0 rounded-full transition-colors ${
                      editForm.enabled ? 'bg-[#FFE815]' : 'bg-gray-300'
                    }`}
                  >
                    <span
                      className={`absolute left-1 top-1 block h-4 w-4 rounded-full bg-white shadow-sm transition-transform ${
                        editForm.enabled ? 'translate-x-5' : ''
                      }`}
                    />
                  </button>
                </div>
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

      {/* 添加新卡密弹窗 - 使用 Portal */}
      {showAddModal && createPortal(
        <div className="modal-overlay">
          <div className="modal-container">
            <div className="modal-header">
              <div className="flex items-center justify-between gap-4">
                <div>
                  <h3 className="text-lg font-bold text-gray-900">添加卡密</h3>
                  <p className="mt-1 text-xs text-gray-500">创建可复用的自动发货内容或库存来源。</p>
                </div>
                <button
                  onClick={() => setShowAddModal(false)}
                  className="rounded-md p-2 hover:bg-gray-100"
                  aria-label="关闭添加卡密"
                >
                  <X className="w-5 h-5 text-gray-500" />
                </button>
              </div>
            </div>

            <div className="modal-body">
              <div className="space-y-4">
                <div>
                  <label className="block text-sm font-bold text-gray-700 mb-2">卡密名称</label>
                  <input
                    type="text"
                    value={addForm.name}
                    onChange={(e) => setAddForm({ ...addForm, name: e.target.value })}
                    placeholder="例如：VIP会员卡密"
                    className="ios-input w-full rounded-md px-3 py-2.5"
                  />
                </div>

                <div>
                  <label className="block text-sm font-bold text-gray-700 mb-2">类型</label>
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                    <button
                      type="button"
                      onClick={() => setAddForm({ ...addForm, type: 'text' })}
                      className={`rounded-md border p-3 text-sm font-bold transition-colors ${addForm.type === 'text' ? 'border-amber-400 bg-[#FFE815] text-black' : 'border-gray-200 bg-gray-50 text-gray-600 hover:bg-gray-100'}`}
                    >
                      <FileText className="w-5 h-5 mx-auto mb-1" />
                      文本
                    </button>
                    <button
                      type="button"
                      onClick={() => setAddForm({ ...addForm, type: 'data' })}
                      className={`rounded-md border p-3 text-sm font-bold transition-colors ${addForm.type === 'data' ? 'border-amber-400 bg-[#FFE815] text-black' : 'border-gray-200 bg-gray-50 text-gray-600 hover:bg-gray-100'}`}
                    >
                      <Package className="w-5 h-5 mx-auto mb-1" />
                      批量
                    </button>
                    <button
                      type="button"
                      onClick={() => setAddForm({ ...addForm, type: 'image' })}
                      className={`rounded-md border p-3 text-sm font-bold transition-colors ${addForm.type === 'image' ? 'border-amber-400 bg-[#FFE815] text-black' : 'border-gray-200 bg-gray-50 text-gray-600 hover:bg-gray-100'}`}
                    >
                      <ImageIcon className="w-5 h-5 mx-auto mb-1" />
                      图片
                    </button>
                    <button
                      type="button"
                      onClick={() => setAddForm({ ...addForm, type: 'api' })}
                      className={`rounded-md border p-3 text-sm font-bold transition-colors ${addForm.type === 'api' ? 'border-amber-400 bg-[#FFE815] text-black' : 'border-gray-200 bg-gray-50 text-gray-600 hover:bg-gray-100'}`}
                    >
                      <Code className="w-5 h-5 mx-auto mb-1" />
                      API
                    </button>
                  </div>
                </div>

                <div>
                  <label className="block text-sm font-bold text-gray-700 mb-2">
                    {addForm.type === 'text'
                      ? '固定文字'
                      : addForm.type === 'data'
                        ? '批量数据（一行一个）'
                        : addForm.type === 'image'
                          ? '图片 URL'
                          : 'API 地址'}
                  </label>
                  {addForm.type === 'api' ? (
                    <input
                      type="text"
                      value={addForm.content}
                      onChange={(e) => setAddForm({ ...addForm, content: e.target.value })}
                      placeholder="https://api.example.com/get-code"
                      className="ios-input w-full rounded-md px-3 py-2.5"
                    />
                  ) : (
                    <textarea
                      value={addForm.content}
                      onChange={(e) => setAddForm({ ...addForm, content: e.target.value })}
                      className="ios-input h-36 w-full resize-y rounded-md px-3 py-2.5 font-mono text-sm"
                      placeholder={
                        addForm.type === 'text'
                          ? '请输入自动发送的固定文字'
                          : addForm.type === 'data'
                            ? 'CODE-123456\nCODE-789012\n...'
                            : 'https://example.com/image.jpg'
                      }
                    />
                  )}
                  {addForm.type === 'data' && (
                    <p className="text-xs text-gray-500 mt-2">
                      当前库存：{addForm.content.split('\n').filter(line => line.trim()).length} 条
                    </p>
                  )}
                </div>

                <div>
                  <label className="block text-sm font-bold text-gray-700 mb-2">描述</label>
                  <textarea
                    value={addForm.description}
                    onChange={(e) => setAddForm({ ...addForm, description: e.target.value })}
                    placeholder="卡密用途描述"
                    className="ios-input h-20 w-full resize-y rounded-md px-3 py-2.5"
                  />
                </div>

                <div>
                  <label className="block text-sm font-bold text-gray-700 mb-2">延时发货（秒）</label>
                  <input
                    type="number"
                    value={addForm.delay_seconds}
                    onChange={(e) => setAddForm({ ...addForm, delay_seconds: parseInt(e.target.value) || 0 })}
                    className="ios-input w-full rounded-md px-3 py-2.5"
                    min="0"
                    placeholder="0"
                  />
                </div>
              </div>
            </div>

            <div className="modal-footer">
              <div className="flex w-full gap-2">
                <button
                  type="button"
                  onClick={() => setShowAddModal(false)}
                  className="ios-btn-secondary flex-1 rounded-md px-4 py-2.5 text-sm"
                >
                  取消
                </button>
                <button
                  type="button"
                  onClick={handleAddCard}
                  className="ios-btn-primary flex flex-1 items-center justify-center gap-2 rounded-md px-4 py-2.5 text-sm"
                >
                  <Plus className="w-4 h-4" />
                  添加卡密
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

export default CardList;
