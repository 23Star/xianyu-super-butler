import React, { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import { Card } from '../types';
import { getCards, createCard, updateCard, deleteCard } from '../services/api';
import { Plus, CreditCard, Clock, FileText, Image as ImageIcon, Code, Edit, Trash2, Save, X, Eye, EyeOff, Package } from 'lucide-react';

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
      // 多规格配置
      is_multi_spec: card.is_multi_spec || false,
      spec_name: card.spec_name || '',
      spec_value: card.spec_value || '',
      enabled: card.enabled
    });
    setShowEditModal(true);
  };

  const handleSaveEdit = async () => {
    if (!selectedCard) return;

    // 验证必填字段
    if (!editForm.name?.trim()) {
      alert('请输入卡密名称');
      return;
    }
    if (!editForm.type) {
      alert('请选择卡密类型');
      return;
    }

    try {
      const updateData: Partial<Card> = {
        name: editForm.name.trim(),
        type: editForm.type as any,
        description: editForm.description?.trim(),
        delay_seconds: editForm.delay_seconds || 0,
        enabled: editForm.enabled ?? true,
        is_multi_spec: editForm.is_multi_spec,
        spec_name: editForm.spec_name,
        spec_value: editForm.spec_value
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
      alert('更新失败，请重试');
    }
  };

  const handleDelete = async (id: string) => {
    if (confirm('确认删除该卡密吗？')) {
      try {
        await deleteCard(id);
        getCards().then(setCards);
      } catch (error) {
        console.error('删除卡密失败:', error);
        alert('删除失败，请重试');
      }
    }
  };

  const handleAddCard = async () => {
    const name = addForm.name.trim();
    const content = addForm.content.trim();
    if (!name) {
      alert('请输入卡密名称');
      return;
    }
    if (!content) {
      alert(addForm.type === 'api' ? '请输入 API 地址' : '请输入卡密内容');
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
      alert('添加失败，请重试');
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

  return (
    <div className="space-y-5 animate-fade-in">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h2 className="text-2xl font-bold text-gray-900">卡密库存</h2>
          <p className="mt-1 text-sm text-gray-500">管理自动发货的卡密、链接或图片资源。</p>
        </div>
        <button
            onClick={() => setShowAddModal(true)}
            className="ios-btn-primary flex w-full items-center justify-center gap-2 rounded-lg px-4 py-2.5 font-bold sm:w-auto"
        >
          <Plus className="w-5 h-5" />
          添加新卡密
        </button>
      </div>

      <div className="ios-card overflow-hidden rounded-lg border border-gray-100 bg-white shadow-sm">
        <div className="overflow-x-auto">
          <table className="min-w-[900px] w-full text-left border-collapse">
            <thead>
              <tr className="bg-white text-gray-400 text-xs font-bold uppercase tracking-wider border-b border-gray-50">
                <th className="px-8 py-5 w-[15%]">卡密名称</th>
                <th className="px-6 py-5 w-[12%]">类型</th>
                <th className="px-6 py-5 w-[25%]">内容/库存</th>
                <th className="px-6 py-5 w-[20%]">描述</th>
                <th className="px-6 py-5 w-[10%]">状态</th>
                <th className="px-6 py-5 w-[10%] text-right">操作</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
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
                } else if (card.type === 'image' && card.text_content) {
                  stockInfo = '图片链接';
                }

                return (
                  <tr key={card.id} className="hover:bg-[#FFFDE7]/50 transition-colors group">
                    <td className="px-8 py-5">
                      <div className="flex items-center gap-3">
                        <div className="p-2 bg-gray-50 rounded-xl group-hover:bg-white transition-colors">
                          <CardIcon type={card.type} />
                        </div>
                        <span className="font-bold text-gray-900">{card.name}</span>
                      </div>
                    </td>
                    <td className="px-6 py-5">
                      <span className={`px-3 py-1.5 rounded-lg text-xs font-bold ${
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
                    <td className="px-6 py-5">
                      <span className="text-sm text-gray-600 font-mono block truncate" title={stockInfo}>
                        {stockInfo}
                      </span>
                    </td>
                    <td className="px-6 py-5">
                      <span
                        className="text-sm text-gray-500 block max-w-[200px] truncate"
                        title={card.description || '-'}
                      >
                        {card.description || '-'}
                      </span>
                    </td>
                    <td className="px-6 py-5">
                      <button
                        onClick={() => toggleCardStatus(card)}
                        className={`w-12 h-8 rounded-full relative transition-colors ${
                          card.enabled ? 'bg-green-500' : 'bg-gray-300'
                        }`}
                        title={card.enabled ? '停用' : '启用'}
                        aria-label={`${card.enabled ? '停用' : '启用'}卡密 ${card.name}`}
                      >
                        <div className={`absolute top-1 w-6 h-6 bg-white rounded-full shadow-sm transition-transform ${
                          card.enabled ? 'left-5' : 'left-1'
                        }`}></div>
                      </button>
                    </td>
                    <td className="px-6 py-5">
                      <div className="flex items-center justify-end gap-2">
                        <button
                          onClick={() => handleEdit(card)}
                          className="rounded-lg p-2 text-gray-400 transition-colors hover:bg-gray-100 hover:text-black"
                          title="编辑"
                          aria-label={`编辑卡密 ${card.name}`}
                        >
                          <Edit className="w-4 h-4" />
                        </button>
                        <button
                          onClick={() => handleDelete(card.id)}
                          className="rounded-lg p-2 text-gray-400 transition-colors hover:bg-red-50 hover:text-red-500"
                          title="删除"
                          aria-label={`删除卡密 ${card.name}`}
                        >
                          <Trash2 className="w-5 h-5" />
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
          <div className="py-20 text-center text-gray-400">
            <Package className="w-12 h-12 mx-auto mb-4 opacity-30" />
            <p>暂无卡密配置，请点击右上角添加。</p>
          </div>
        )}
      </div>

      {/* 编辑卡密弹窗 - 使用 Portal */}
      {showEditModal && selectedCard && createPortal(
        <div className="modal-overlay-centered">
          <div className="modal-container">
            <div className="modal-header">
              <h3 className="text-2xl font-extrabold text-gray-900">编辑卡密</h3>
              <button
                onClick={() => setShowEditModal(false)}
                className="p-2 rounded-xl hover:bg-gray-100 transition-colors"
              >
                <X className="w-5 h-5 text-gray-500" />
              </button>
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
                      className="w-full ios-input px-4 py-3 rounded-xl"
                      placeholder="例如：游戏点卡、会员卡等"
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-bold text-gray-700 mb-2">卡券类型</label>
                    <select
                      value={editForm.type || 'text'}
                      onChange={(e) => setEditForm({ ...editForm, type: e.target.value as any })}
                      className="w-full ios-input px-4 py-3 rounded-xl"
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
                  <div className="border border-gray-200 rounded-xl p-4 space-y-4 bg-gray-50">
                    <h3 className="font-bold text-gray-900">API 配置</h3>
                    <div>
                      <label className="block text-sm font-bold text-gray-700 mb-2">API 地址</label>
                      <input
                        type="url"
                        value={editForm.api_url || ''}
                        onChange={(e) => setEditForm({ ...editForm, api_url: e.target.value })}
                        className="w-full ios-input px-4 py-3 rounded-xl font-mono text-sm"
                        placeholder="https://api.example.com/get-card"
                      />
                    </div>
                    <div className="grid grid-cols-2 gap-4">
                      <div>
                        <label className="block text-sm font-bold text-gray-700 mb-2">请求方法</label>
                        <select
                          value={editForm.api_method || 'GET'}
                          onChange={(e) => setEditForm({ ...editForm, api_method: e.target.value as 'GET' | 'POST' })}
                          className="w-full ios-input px-4 py-3 rounded-xl"
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
                          className="w-full ios-input px-4 py-3 rounded-xl"
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
                        className="w-full ios-input px-4 py-3 rounded-xl h-20 resize-none font-mono text-sm"
                        placeholder='{"Authorization": "Bearer token"}'
                      />
                    </div>
                    <div>
                      <label className="block text-sm font-bold text-gray-700 mb-2">请求参数（JSON 格式）</label>
                      <textarea
                        value={editForm.api_params || ''}
                        onChange={(e) => setEditForm({ ...editForm, api_params: e.target.value })}
                        className="w-full ios-input px-4 py-3 rounded-xl h-20 resize-none font-mono text-sm"
                        placeholder='{"type": "card", "count": 1}'
                      />
                    </div>
                  </div>
                )}

                {/* 固定文字配置 */}
                {editForm.type === 'text' && (
                  <div className="border border-gray-200 rounded-xl p-4 bg-gray-50">
                    <h3 className="font-bold text-gray-900 mb-3">固定文字配置</h3>
                    <div>
                      <label className="block text-sm font-bold text-gray-700 mb-2">文字内容</label>
                      <textarea
                        value={editForm.text_content || ''}
                        onChange={(e) => setEditForm({ ...editForm, text_content: e.target.value })}
                        className="w-full ios-input px-4 py-3 rounded-xl h-32 resize-none"
                        placeholder="请输入要发送的固定文字内容..."
                      />
                    </div>
                  </div>
                )}

                {/* 批量数据配置 */}
                {editForm.type === 'data' && (
                  <div className="border border-gray-200 rounded-xl p-4 bg-gray-50">
                    <h3 className="font-bold text-gray-900 mb-3">批量数据配置</h3>
                    <div>
                      <label className="block text-sm font-bold text-gray-700 mb-2">数据内容（一行一个）</label>
                      <textarea
                        value={editForm.data_content || ''}
                        onChange={(e) => setEditForm({ ...editForm, data_content: e.target.value })}
                        className="w-full ios-input px-4 py-3 rounded-xl h-80 resize-none font-mono text-sm"
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
                  <div className="border border-gray-200 rounded-xl p-4 bg-gray-50">
                    <h3 className="font-bold text-gray-900 mb-3">图片配置</h3>
                    <div>
                      <label className="block text-sm font-bold text-gray-700 mb-2">图片 URL</label>
                      <input
                        type="url"
                        value={editForm.image_url || ''}
                        onChange={(e) => setEditForm({ ...editForm, image_url: e.target.value })}
                        className="w-full ios-input px-4 py-3 rounded-xl font-mono text-sm"
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
                          className="max-w-full max-h-48 rounded-xl border border-gray-200"
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
                      className="flex-1 ios-input px-4 py-3 rounded-xl"
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
                    className="w-full ios-input px-4 py-3 rounded-xl h-40 resize-none"
                    placeholder="可选的备注信息"
                  />
                </div>

                {/* 多规格设置 */}
                <div className="border border-gray-200 rounded-xl p-4">
                  <div className="flex items-center gap-3 mb-3">
                    <input
                      type="checkbox"
                      id="edit-isMultiSpec"
                      checked={editForm.is_multi_spec || false}
                      onChange={(e) => setEditForm({ ...editForm, is_multi_spec: e.target.checked })}
                      className="w-4 h-4 rounded"
                    />
                    <label htmlFor="edit-isMultiSpec" className="font-bold text-gray-900">
                      多规格卡券
                    </label>
                  </div>
                  <p className="text-xs text-gray-500 mb-3">开启后可以为同一商品的不同规格创建不同的卡券</p>

                  {editForm.is_multi_spec && (
                    <div className="grid grid-cols-2 gap-4">
                      <div>
                        <label className="block text-sm font-bold text-gray-700 mb-2">规格名称</label>
                        <input
                          type="text"
                          value={editForm.spec_name || ''}
                          onChange={(e) => setEditForm({ ...editForm, spec_name: e.target.value })}
                          className="w-full ios-input px-4 py-3 rounded-xl"
                          placeholder="例如：套餐类型、颜色、尺寸"
                        />
                      </div>
                      <div>
                        <label className="block text-sm font-bold text-gray-700 mb-2">规格值</label>
                        <input
                          type="text"
                          value={editForm.spec_value || ''}
                          onChange={(e) => setEditForm({ ...editForm, spec_value: e.target.value })}
                          className="w-full ios-input px-4 py-3 rounded-xl"
                          placeholder="例如：30天、红色、XL"
                        />
                      </div>
                    </div>
                  )}
                </div>

                {/* 启用状态 */}
                <div className="flex items-center justify-between p-4 bg-gray-50 rounded-xl">
                  <span className="font-bold text-gray-900">启用状态</span>
                  <button
                    type="button"
                    onClick={() => setEditForm({ ...editForm, enabled: !editForm.enabled })}
                    className={`w-14 h-8 rounded-full transition-colors duration-300 relative ${
                      editForm.enabled ? 'bg-[#FFE815]' : 'bg-gray-300'
                    }`}
                  >
                    <span
                      className={`absolute top-1 w-6 h-6 bg-white rounded-full shadow-md transition-transform duration-300 block ${
                        editForm.enabled ? 'translate-x-7' : 'translate-x-1'
                      }`}
                    />
                  </button>
                </div>
              </div>
            </div>

            <div className="modal-footer">
              <div className="flex gap-3 w-full">
                <button
                  onClick={() => setShowEditModal(false)}
                  className="flex-1 px-6 py-3 rounded-xl font-bold bg-gray-100 text-gray-700 hover:bg-gray-200 transition-colors"
                >
                  取消
                </button>
                <button
                  onClick={handleSaveEdit}
                  className="flex-1 ios-btn-primary px-6 py-3 rounded-xl font-bold flex items-center justify-center gap-2"
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
        <div className="modal-overlay-centered">
          <div className="modal-container">
            <div className="modal-header">
              <h3 className="text-2xl font-extrabold text-gray-900">添加新卡密</h3>
              <button
                onClick={() => setShowAddModal(false)}
                className="p-2 rounded-xl hover:bg-gray-100 transition-colors"
              >
                <X className="w-5 h-5 text-gray-500" />
              </button>
            </div>

            <div className="flex-1 overflow-y-auto -mr-2 pr-2">
              <div className="space-y-4">
                <div>
                  <label className="block text-sm font-bold text-gray-700 mb-2">卡密名称</label>
                  <input
                    type="text"
                    value={addForm.name}
                    onChange={(e) => setAddForm({ ...addForm, name: e.target.value })}
                    placeholder="例如：VIP会员卡密"
                    className="w-full ios-input px-4 py-3 rounded-xl"
                  />
                </div>

                <div>
                  <label className="block text-sm font-bold text-gray-700 mb-2">类型</label>
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                    <button
                      type="button"
                      onClick={() => setAddForm({ ...addForm, type: 'text' })}
                      className={`p-3 rounded-xl font-bold transition-all ${addForm.type === 'text' ? 'bg-[#FFE815] text-black' : 'bg-gray-100 text-gray-600'}`}
                    >
                      <FileText className="w-5 h-5 mx-auto mb-1" />
                      文本
                    </button>
                    <button
                      type="button"
                      onClick={() => setAddForm({ ...addForm, type: 'data' })}
                      className={`p-3 rounded-xl font-bold transition-all ${addForm.type === 'data' ? 'bg-[#FFE815] text-black' : 'bg-gray-100 text-gray-600'}`}
                    >
                      <Package className="w-5 h-5 mx-auto mb-1" />
                      批量
                    </button>
                    <button
                      type="button"
                      onClick={() => setAddForm({ ...addForm, type: 'image' })}
                      className={`p-3 rounded-xl font-bold transition-all ${addForm.type === 'image' ? 'bg-[#FFE815] text-black' : 'bg-gray-100 text-gray-600'}`}
                    >
                      <ImageIcon className="w-5 h-5 mx-auto mb-1" />
                      图片
                    </button>
                    <button
                      type="button"
                      onClick={() => setAddForm({ ...addForm, type: 'api' })}
                      className={`p-3 rounded-xl font-bold transition-all ${addForm.type === 'api' ? 'bg-[#FFE815] text-black' : 'bg-gray-100 text-gray-600'}`}
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
                      className="w-full ios-input px-4 py-3 rounded-xl"
                    />
                  ) : (
                    <textarea
                      value={addForm.content}
                      onChange={(e) => setAddForm({ ...addForm, content: e.target.value })}
                      className="w-full ios-input px-4 py-3 rounded-xl h-40 resize-none font-mono text-sm"
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
                    className="w-full ios-input px-4 py-3 rounded-xl h-20 resize-none"
                  />
                </div>

                <div>
                  <label className="block text-sm font-bold text-gray-700 mb-2">延时发货（秒）</label>
                  <input
                    type="number"
                    value={addForm.delay_seconds}
                    onChange={(e) => setAddForm({ ...addForm, delay_seconds: parseInt(e.target.value) || 0 })}
                    className="w-full ios-input px-4 py-3 rounded-xl"
                    min="0"
                    placeholder="0"
                  />
                </div>
              </div>
            </div>

            <div className="modal-footer">
              <div className="flex gap-3 w-full">
                <button
                  onClick={() => setShowAddModal(false)}
                  className="flex-1 px-6 py-3 rounded-xl font-bold bg-gray-100 text-gray-700 hover:bg-gray-200 transition-colors"
                >
                  取消
                </button>
                <button
                  onClick={handleAddCard}
                  className="flex-1 ios-btn-primary px-6 py-3 rounded-xl font-bold flex items-center justify-center gap-2"
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
