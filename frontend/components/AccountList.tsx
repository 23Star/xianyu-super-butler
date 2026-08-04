import React, { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { AccountDetail, AIReplySettings } from '../types';
import {
  getAccountDetails,
  updateAccountStatus,
  deleteAccount,
  generateQRLogin,
  checkQRLoginStatus,
  updateAccountRemark,
  updateAccountAutoConfirm,
  updateAccountPauseDuration,
  updateAccountCookie,
  updateAccountLoginInfo,
  updateAccountAISettings,
  getAllAISettings,
  getAccountAISettings,
  refreshAccountProfile
} from '../services/api';
import {
  Power, Edit2, Trash2, QrCode, X, Check, Loader2,
  MessageSquare, RefreshCw, Save, User, Clock, MessageCircle,
  Key, Eye, EyeOff, Bot, Settings, MapPin, Users
} from 'lucide-react';

type ModalType = 'edit' | 'ai-settings' | null;

const AccountList: React.FC = () => {
  const [accounts, setAccounts] = useState<AccountDetail[]>([]);
  const [loading, setLoading] = useState(true);
  const [showQRModal, setShowQRModal] = useState(false);
  const [qrCodeUrl, setQrCodeUrl] = useState<string>('');
  const [qrStatus, setQrStatus] = useState<string>('pending');
  const [qrMessage, setQrMessage] = useState<string>('');
  const qrPollTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const qrSessionRef = useRef<string>('');
  const [activeModal, setActiveModal] = useState<ModalType>(null);
  const [editingAccount, setEditingAccount] = useState<AccountDetail | null>(null);
  const [refreshingProfileId, setRefreshingProfileId] = useState<string | null>(null);
  const [failedAvatars, setFailedAvatars] = useState<Set<string>>(new Set());

  // 编辑表单状态
  const [editForm, setEditForm] = useState({
    remark: '',
    cookie: '',
    auto_confirm: false,
    pause_duration: 0,
    username: '',
    login_password: '',
    show_browser: false,
    showLoginPassword: false,
  });

  // AI设置表单状态
  const [aiSettings, setAiSettings] = useState<AIReplySettings>({
    ai_enabled: false,
    model_name: 'qwen-plus',
    api_key: '',
    base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
    max_discount_percent: 10,
    max_discount_amount: 100,
    max_bargain_rounds: 3,
    custom_prompts: '',
  });
  const [saving, setSaving] = useState(false);

  const loadAccounts = async () => {
    setLoading(true);
    try {
      const data = await getAccountDetails();

      // 获取所有账号的AI设置
      let allAISettings: Record<string, AIReplySettings> = {};
      try {
        allAISettings = await getAllAISettings();
      } catch (e) {
        console.error('Failed to load AI settings:', e);
      }

      // 合并AI设置到账号数据
      const accountsWithAI = data.map(account => ({
        ...account,
        ai_enabled: allAISettings[account.id]?.ai_enabled ?? false,
        max_discount_percent: allAISettings[account.id]?.max_discount_percent ?? 10,
        max_discount_amount: allAISettings[account.id]?.max_discount_amount ?? 100,
        max_bargain_rounds: allAISettings[account.id]?.max_bargain_rounds ?? 3,
        custom_prompts: allAISettings[account.id]?.custom_prompts ?? '',
      }));

      setAccounts(accountsWithAI);
    } catch (error) {
      console.error('Failed to load accounts:', error);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadAccounts();
    return () => {
      qrSessionRef.current = '';
      if (qrPollTimerRef.current) clearTimeout(qrPollTimerRef.current);
    };
  }, []);

  const handleToggle = async (id: string, currentStatus: boolean) => {
    await updateAccountStatus(id, !currentStatus);
    loadAccounts();
  };

  const handleRefreshProfile = async (id: string) => {
    setRefreshingProfileId(id);
    try {
      await refreshAccountProfile(id);
      setFailedAvatars(previous => {
        const next = new Set(previous);
        next.delete(id);
        return next;
      });
      await loadAccounts();
    } catch (error) {
      console.error('Failed to refresh account profile:', error);
      alert(error instanceof Error ? error.message : '账号资料刷新失败');
    } finally {
      setRefreshingProfileId(null);
    }
  };

  const handleDelete = async (id: string) => {
    if (confirm('确认删除该账号吗？')) {
      await deleteAccount(id);
      loadAccounts();
    }
  };

  const openEditModal = (account: AccountDetail) => {
    setEditingAccount(account);
    setEditForm({
      remark: account.remark || account.note || '',
      cookie: account.cookie || account.value || '',
      auto_confirm: account.auto_confirm || false,
      pause_duration: account.pause_duration || 0,
      username: account.username || '',
      login_password: account.login_password || '',
      show_browser: account.show_browser || false,
      showLoginPassword: false,
    });
    setActiveModal('edit');
  };

  const openAIModal = async (account: AccountDetail) => {
    setEditingAccount(account);
    setSaving(true);
    try {
      const settings = await getAccountAISettings(account.id);
      setAiSettings({
        ai_enabled: settings.ai_enabled ?? false,
        model_name: settings.model_name || 'qwen-plus',
        api_key: settings.api_key || '',
        base_url: settings.base_url || 'https://dashscope.aliyuncs.com/compatible-mode/v1',
        max_discount_percent: settings.max_discount_percent ?? 10,
        max_discount_amount: settings.max_discount_amount ?? 100,
        max_bargain_rounds: settings.max_bargain_rounds ?? 3,
        custom_prompts: settings.custom_prompts ?? '',
      });
    } catch (e) {
      console.error('Failed to load AI settings:', e);
    } finally {
      setSaving(false);
    }
    setActiveModal('ai-settings');
  };

  const handleSaveEdit = async () => {
    if (!editingAccount) return;
    setSaving(true);

    try {
      const promises: Promise<any>[] = [];

      // 更新备注
      if (editForm.remark !== (editingAccount.remark || editingAccount.note || '')) {
        promises.push(updateAccountRemark(editingAccount.id, editForm.remark));
      }

      // 更新Cookie
      if (editForm.cookie && editForm.cookie !== (editingAccount.cookie || editingAccount.value || '')) {
        promises.push(updateAccountCookie(editingAccount.id, editForm.cookie));
      }

      // 更新自动确认
      if (editForm.auto_confirm !== editingAccount.auto_confirm) {
        promises.push(updateAccountAutoConfirm(editingAccount.id, editForm.auto_confirm));
      }

      // 更新暂停时长
      if (editForm.pause_duration !== (editingAccount.pause_duration || 0)) {
        promises.push(updateAccountPauseDuration(editingAccount.id, editForm.pause_duration));
      }

      // 更新登录信息
      if (
        editForm.username !== (editingAccount.username || '') ||
        editForm.login_password !== (editingAccount.login_password || '') ||
        editForm.show_browser !== (editingAccount.show_browser || false)
      ) {
        promises.push(updateAccountLoginInfo(editingAccount.id, {
          username: editForm.username,
          login_password: editForm.login_password,
          show_browser: editForm.show_browser,
        }));
      }

      await Promise.all(promises);
      setActiveModal(null);
      loadAccounts();
    } catch (error) {
      console.error('更新账号失败:', error);
      alert('更新失败，请重试');
    } finally {
      setSaving(false);
    }
  };

  const handleSaveAISettings = async () => {
    if (!editingAccount) return;
    setSaving(true);

    try {
      await updateAccountAISettings(editingAccount.id, aiSettings);
      setActiveModal(null);
      loadAccounts();
    } catch (error) {
      console.error('更新AI设置失败:', error);
      alert('更新失败，请重试');
    } finally {
      setSaving(false);
    }
  };

  const startQRLogin = async () => {
    qrSessionRef.current = '';
    if (qrPollTimerRef.current) clearTimeout(qrPollTimerRef.current);
    setShowQRModal(true);
    setQrStatus('loading');
    setQrMessage('');
    try {
      const res = await generateQRLogin();
      if (res.success && res.qr_code_url && res.session_id) {
        setQrCodeUrl(res.qr_code_url);
        setQrStatus('waiting');
        setQrMessage('等待扫码');
        qrSessionRef.current = res.session_id;

        const pollStatus = async () => {
          if (qrSessionRef.current !== res.session_id) return;
          try {
            const statusRes = await checkQRLoginStatus(res.session_id!);
            if (qrSessionRef.current !== res.session_id) return;

            if (statusRes.status === 'success') {
              qrSessionRef.current = '';
              if (statusRes.account_ready) {
                setQrStatus('success');
                setQrMessage(statusRes.message || '账号 Cookie 已刷新并保存');
                setTimeout(() => {
                  setShowQRModal(false);
                  loadAccounts();
                }, 1000);
              } else {
                setQrStatus('error');
                setQrMessage(statusRes.message || '扫码已确认，但账号 Cookie 未准备完成');
                loadAccounts();
              }
              return;
            }

            if (statusRes.status === 'scanned') {
              setQrStatus('scanned');
              setQrMessage('已扫码，请在手机上确认登录');
            } else if (statusRes.status === 'processing') {
              setQrStatus('processing');
              setQrMessage(statusRes.message || '已确认，正在准备账号...');
            } else if (
              statusRes.status === 'expired' ||
              statusRes.status === 'error' ||
              statusRes.status === 'cancelled' ||
              statusRes.status === 'not_found'
            ) {
              qrSessionRef.current = '';
              setQrStatus('error');
              setQrMessage(statusRes.message || '二维码已失效，请重试');
              return;
            } else if (statusRes.status === 'verification_required') {
              qrSessionRef.current = '';
              setQrStatus('error');
              setQrMessage(statusRes.message || '账号需要在手机上完成安全验证');
              return;
            }

            qrPollTimerRef.current = setTimeout(pollStatus, 800);
          } catch (error) {
            qrSessionRef.current = '';
            setQrStatus('error');
            setQrMessage(error instanceof Error ? error.message : '扫码状态查询失败');
          }
        };

        qrPollTimerRef.current = setTimeout(pollStatus, 300);
      } else {
        setQrStatus('error');
        setQrMessage('二维码生成失败，请重试');
      }
    } catch (e) {
      setQrStatus('error');
      setQrMessage(e instanceof Error ? e.message : '扫码登录请求失败');
    }
  };

  const closeQRModal = () => {
    qrSessionRef.current = '';
    if (qrPollTimerRef.current) clearTimeout(qrPollTimerRef.current);
    setShowQRModal(false);
  };

  if (loading) return <div className="p-20 flex justify-center"><Loader2 className="w-8 h-8 text-[#FFE815] animate-spin"/></div>;

  return (
    <div className="space-y-6 animate-fade-in relative">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h2 className="text-2xl font-bold text-gray-900">账号管理</h2>
          <p className="text-gray-500 mt-2 font-medium">管理您的闲鱼授权账号及设置。</p>
        </div>
        <button
            onClick={startQRLogin}
            className="ios-btn-primary flex w-full items-center justify-center gap-2 rounded-lg px-5 py-3 font-bold sm:w-auto"
        >
          <QrCode className="w-5 h-5" />
          扫码添加新账号
        </button>
      </div>

      {/* Account Grid */}
      <div className="grid grid-cols-1 gap-4">
        {accounts.map((account) => (
          <div key={account.id} className="ios-card flex flex-col gap-5 p-5 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex min-w-0 items-start gap-4 sm:items-center">
              <div className="relative">
                {account.avatar_url && !failedAvatars.has(account.id) ? (
                  <img
                    src={account.avatar_url.startsWith('//') ? `https:${account.avatar_url}` : account.avatar_url}
                    alt=""
                    className="h-14 w-14 rounded-lg object-cover"
                    referrerPolicy="no-referrer"
                    onError={() => setFailedAvatars(previous => new Set(previous).add(account.id))}
                  />
                ) : (
                  <div className="flex h-14 w-14 items-center justify-center rounded-lg bg-yellow-100 text-lg font-bold text-yellow-800">
                    {account.nickname?.trim().charAt(0) || account.remark?.trim().charAt(0) || '闲'}
                  </div>
                )}
                <div className={`absolute -bottom-1 -right-1 w-6 h-6 rounded-full border-4 border-white flex items-center justify-center ${account.enabled ? 'bg-green-500' : 'bg-gray-300'}`}>
                    {account.enabled && <Check className="w-3 h-3 text-white" />}
                </div>
              </div>
              <div className="min-w-0">
                <div className="mb-1 flex flex-wrap items-center gap-2">
                    <h3 className="break-words text-lg font-bold text-gray-900">{account.nickname || account.remark || '未命名账号'}</h3>
                    {account.enabled ? (
                        <span className="px-2.5 py-0.5 rounded-lg bg-green-100 text-green-700 text-xs font-bold">在线</span>
                    ) : (
                        <span className="px-2.5 py-0.5 rounded-lg bg-gray-100 text-gray-500 text-xs font-bold">暂停</span>
                    )}
                    {account.ai_enabled && (
                        <span className="px-2.5 py-0.5 rounded-lg bg-purple-100 text-purple-700 text-xs font-bold flex items-center gap-1">
                          <Bot className="w-3 h-3" /> AI
                        </span>
                    )}
                </div>
                <p className="break-all font-mono text-xs text-gray-500">闲鱼 ID {account.id}</p>
                <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-gray-600">
                  {account.location && (
                    <span className="flex items-center gap-1.5">
                      <MapPin className="h-4 w-4 text-gray-400" />
                      {account.location}
                    </span>
                  )}
                  {(account.followers !== undefined || account.following !== undefined) && (
                    <span className="flex items-center gap-1.5">
                      <Users className="h-4 w-4 text-gray-400" />
                      {account.followers?.toLocaleString() ?? '--'} 粉丝
                      <span className="text-gray-300">/</span>
                      {account.following?.toLocaleString() ?? '--'} 关注
                    </span>
                  )}
                </div>
                {account.bio && (
                  <p className="mt-2 max-w-3xl break-words text-sm leading-6 text-gray-600">{account.bio}</p>
                )}
                {account.remark && (
                  <p className="mt-1 text-xs font-medium text-gray-400">备注：{account.remark}</p>
                )}
                <div className="flex flex-wrap gap-2">
                   {account.auto_confirm && <span className="text-xs bg-yellow-50 text-yellow-700 px-3 py-1.5 rounded-lg font-bold flex items-center gap-1.5"><MessageSquare className="w-3 h-3"/> 自动回复</span>}
                   {account.pause_duration > 0 && <span className="text-xs bg-blue-50 text-blue-700 px-3 py-1.5 rounded-lg font-bold flex items-center gap-1.5"><Clock className="w-3 h-3"/> 暂停{account.pause_duration}分钟</span>}
                </div>
              </div>
            </div>
            <div className="flex items-center justify-end gap-1 border-t border-gray-100 pt-3 sm:border-0 sm:pt-0">
                <button
                    onClick={() => handleRefreshProfile(account.id)}
                    disabled={refreshingProfileId === account.id}
                    className="p-3 rounded-xl hover:bg-amber-50 transition-colors text-amber-700 disabled:cursor-wait disabled:opacity-50"
                    title="刷新闲鱼资料"
                    aria-label="刷新闲鱼资料"
                >
                    <RefreshCw className={`w-5 h-5 ${refreshingProfileId === account.id ? 'animate-spin' : ''}`} />
                </button>
                <button
                    onClick={() => openEditModal(account)}
                    className="p-3 rounded-xl hover:bg-gray-100 transition-colors text-gray-600"
                    title="编辑账号"
                >
                    <Edit2 className="w-5 h-5" />
                </button>
                <button
                    onClick={() => openAIModal(account)}
                    className="p-3 rounded-xl hover:bg-purple-100 transition-colors text-purple-600"
                    title="AI设置"
                >
                    <Bot className="w-5 h-5" />
                </button>
                <button
                    onClick={() => handleToggle(account.id, account.enabled)}
                    className={`p-3 rounded-xl transition-colors ${account.enabled ? 'text-green-600 hover:bg-green-50' : 'text-gray-400 hover:bg-gray-100'}`}
                    title={account.enabled ? '暂停账号' : '启用账号'}
                    aria-label={account.enabled ? '暂停账号' : '启用账号'}
                >
                    <Power className="w-5 h-5" />
                </button>
                <button
                    onClick={() => handleDelete(account.id)}
                    className="p-3 rounded-xl hover:bg-red-100 transition-colors text-red-500"
                    title="删除账号"
                    aria-label="删除账号"
                >
                    <Trash2 className="w-5 h-5" />
                </button>
            </div>
          </div>
        ))}

        {accounts.length === 0 && (
            <div className="ios-card p-12 text-center">
                <div className="w-20 h-20 bg-gray-100 rounded-full flex items-center justify-center mx-auto mb-4">
                    <User className="w-10 h-10 text-gray-400" />
                </div>
                <h3 className="text-lg font-bold text-gray-900">暂无账号</h3>
                <p className="text-gray-500 mt-1">请点击右上角扫码添加您的闲鱼账号</p>
            </div>
        )}
      </div>

      {/* QR Code Modal */}
      {showQRModal && createPortal(
          <div className="modal-overlay-centered">
              <div className="modal-container" style={{maxWidth: '24rem'}}>
                  <button
                    onClick={closeQRModal}
                    className="self-end p-2 bg-gray-100 rounded-full hover:bg-gray-200 transition-colors mb-6"
                  >
                    <X className="w-5 h-5 text-gray-600" />
                  </button>

                  <div className="modal-body">
                      <div className="text-center">
                          <h3 className="text-2xl font-extrabold text-gray-900 mb-2">扫码登录</h3>
                          <p className="text-gray-500 mb-8 font-medium">请打开闲鱼APP扫描下方二维码</p>

                          <div className="w-64 h-64 bg-[#F7F8FA] rounded-[2rem] mx-auto flex items-center justify-center overflow-hidden border-4 border-white shadow-inner mb-8 relative">
                              {qrStatus === 'loading' && <Loader2 className="w-10 h-10 text-[#FFE815] animate-spin" />}
                              {(qrStatus === 'waiting' || qrStatus === 'scanned') && (
                                  <img src={qrCodeUrl} alt="QR Code" className="w-full h-full p-2" />
                              )}
                              {qrStatus === 'scanned' && (
                                  <div className="absolute inset-x-3 bottom-3 bg-white/95 border border-gray-200 px-3 py-2 text-sm font-semibold text-gray-800">
                                      已扫码，请在手机确认
                                  </div>
                              )}
                              {qrStatus === 'processing' && (
                                  <div className="absolute inset-0 bg-white/95 flex flex-col items-center justify-center text-gray-800">
                                      <Loader2 className="w-10 h-10 text-amber-500 animate-spin mb-4" />
                                      <span className="font-bold">正在准备账号</span>
                                      <span className="text-xs text-gray-500 mt-2">无需重复扫码</span>
                                  </div>
                              )}
                              {qrStatus === 'success' && (
                                  <div className="absolute inset-0 bg-white/95 flex flex-col items-center justify-center text-green-600 animate-fade-in">
                                      <div className="w-16 h-16 bg-green-100 rounded-full flex items-center justify-center mb-4">
                                         <Check className="w-8 h-8" />
                                      </div>
                                      <span className="font-bold text-lg">登录成功</span>
                                  </div>
                              )}
                              {qrStatus === 'error' && (
                                  <div className="flex flex-col items-center px-4 text-center">
                                      <span className="text-red-500 font-bold mb-2">账号未登录完成</span>
                                      {qrMessage && <span className="text-xs text-gray-500 mb-3">{qrMessage}</span>}
                                      <button onClick={startQRLogin} className="text-xs bg-gray-200 px-3 py-1 rounded-full flex items-center gap-1 hover:bg-gray-300"><RefreshCw className="w-3 h-3"/> 重试</button>
                                  </div>
                              )}
                          </div>

                          <p className="text-xs text-gray-400 font-medium bg-gray-50 py-2 rounded-xl">
                            {qrMessage || '二维码有效期为5分钟，请尽快扫码。'}
                          </p>
                      </div>
                  </div>
              </div>
          </div>,
          document.body
      )}

      {/* 编辑账号弹窗 */}
      {activeModal === 'edit' && editingAccount && createPortal(
        <div className="modal-overlay-centered">
          <div className="modal-container" style={{maxWidth: '600px'}}>
            <div className="modal-header">
              <div>
                <h3 className="text-2xl font-extrabold text-gray-900">编辑账号</h3>
                <p className="text-sm text-gray-500 mt-1">{editingAccount.nickname || editingAccount.remark || editingAccount.id}</p>
              </div>
              <button
                onClick={() => setActiveModal(null)}
                className="p-2 rounded-xl hover:bg-gray-100 transition-colors flex-shrink-0"
              >
                <X className="w-5 h-5 text-gray-500" />
              </button>
            </div>

            <div className="modal-body space-y-6">
              {/* 账号ID */}
              <div>
                <label className="block text-sm font-bold text-gray-700 mb-2">账号ID</label>
                <input
                  type="text"
                  value={editingAccount.id}
                  disabled
                  className="w-full ios-input px-4 py-3 rounded-xl bg-gray-50 text-gray-500"
                />
              </div>

              {/* 备注 */}
              <div>
                <label className="block text-sm font-bold text-gray-700 mb-2">备注</label>
                <input
                  type="text"
                  value={editForm.remark}
                  onChange={(e) => setEditForm({ ...editForm, remark: e.target.value })}
                  placeholder="为账号添加备注"
                  className="w-full ios-input px-4 py-3 rounded-xl"
                />
              </div>

              {/* Cookie */}
              <div>
                <label className="block text-sm font-bold text-gray-700 mb-2">Cookie</label>
                <textarea
                  value={editForm.cookie}
                  onChange={(e) => setEditForm({ ...editForm, cookie: e.target.value })}
                  placeholder="更新账号Cookie"
                  className="w-full ios-input px-4 py-3 rounded-xl h-32 resize-none font-mono text-xs"
                />
                <p className="text-xs text-gray-500 mt-1">当前Cookie长度: {editForm.cookie.length} 字符</p>
              </div>

              {/* 自动确认收货 */}
              <div className="flex items-center justify-between p-4 bg-gray-50 rounded-xl">
                <div>
                  <div className="font-bold text-gray-900 flex items-center gap-2">
                    <Check className="w-4 h-4 text-green-500" />
                    自动确认收货
                  </div>
                  <div className="text-xs text-gray-500">自动点击确认收货按钮</div>
                </div>
                <button
                  type="button"
                  onClick={() => setEditForm({ ...editForm, auto_confirm: !editForm.auto_confirm })}
                  className={`w-14 h-8 rounded-full transition-colors duration-300 relative ${
                    editForm.auto_confirm ? 'bg-[#FFE815]' : 'bg-gray-300'
                  }`}
                >
                  <span
                    className={`absolute top-1 w-6 h-6 bg-white rounded-full shadow-md transition-transform duration-300 ${
                      editForm.auto_confirm ? 'translate-x-7' : 'translate-x-1'
                    }`}
                  />
                </button>
              </div>

              {/* 暂停时长 */}
              <div>
                <label className="block text-sm font-bold text-gray-700 mb-2 flex items-center gap-2">
                  <Clock className="w-4 h-4 text-blue-500" />
                  暂停处理时长（分钟）
                </label>
                <input
                  type="number"
                  value={editForm.pause_duration}
                  onChange={(e) => setEditForm({ ...editForm, pause_duration: parseInt(e.target.value) || 0 })}
                  placeholder="0"
                  min="0"
                  max="1440"
                  className="w-full ios-input px-4 py-3 rounded-xl"
                />
                <p className="text-xs text-gray-500 mt-1">设置后会暂停处理该账号的订单，到时间后自动恢复</p>
              </div>

              {/* 登录信息 */}
              <div className="border-t border-gray-200 pt-6">
                <h3 className="text-lg font-bold text-gray-900 mb-4 flex items-center gap-2">
                  <Key className="w-5 h-5 text-amber-500" />
                  登录信息
                </h3>
                <div className="space-y-4">
                  <div>
                    <label className="block text-sm font-bold text-gray-700 mb-2">用户名</label>
                    <input
                      type="text"
                      value={editForm.username}
                      onChange={(e) => setEditForm({ ...editForm, username: e.target.value })}
                      placeholder="闲鱼账号/手机号"
                      className="w-full ios-input px-4 py-3 rounded-xl"
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-bold text-gray-700 mb-2">登录密码</label>
                    <div className="relative">
                      <input
                        type={editForm.showLoginPassword ? 'text' : 'password'}
                        value={editForm.login_password}
                        onChange={(e) => setEditForm({ ...editForm, login_password: e.target.value })}
                        placeholder="用于自动登录"
                        className="w-full ios-input px-4 py-3 rounded-xl pr-12"
                      />
                      <button
                        type="button"
                        onClick={() => setEditForm({ ...editForm, showLoginPassword: !editForm.showLoginPassword })}
                        className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
                      >
                        {editForm.showLoginPassword ? <EyeOff className="w-5 h-5" /> : <Eye className="w-5 h-5" />}
                      </button>
                    </div>
                  </div>
                  <div className="flex items-center justify-between">
                    <div>
                      <div className="font-bold text-gray-900">登录时显示浏览器</div>
                      <div className="text-xs text-gray-500">调试时可开启查看登录过程</div>
                    </div>
                    <button
                      type="button"
                      onClick={() => setEditForm({ ...editForm, show_browser: !editForm.show_browser })}
                      className={`w-14 h-8 rounded-full transition-colors duration-300 relative ${
                        editForm.show_browser ? 'bg-[#FFE815]' : 'bg-gray-300'
                      }`}
                    >
                      <span
                        className={`absolute top-1 w-6 h-6 bg-white rounded-full shadow-md transition-transform duration-300 ${
                          editForm.show_browser ? 'translate-x-7' : 'translate-x-1'
                        }`}
                      />
                    </button>
                  </div>
                </div>
              </div>
            </div>

            <div className="modal-footer">
              <div className="flex gap-3 w-full">
                <button
                  onClick={() => setActiveModal(null)}
                  className="flex-1 px-6 py-3 rounded-xl font-bold bg-gray-100 text-gray-700 hover:bg-gray-200 transition-colors"
                  disabled={saving}
                >
                  取消
                </button>
                <button
                  onClick={handleSaveEdit}
                  className="flex-1 ios-btn-primary px-6 py-3 rounded-xl font-bold flex items-center justify-center gap-2"
                  disabled={saving}
                >
                  {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
                  {saving ? '保存中...' : '保存'}
                </button>
              </div>
            </div>
          </div>
        </div>,
        document.body
      )}

      {/* AI设置弹窗 */}
      {activeModal === 'ai-settings' && editingAccount && createPortal(
        <div className="modal-overlay-centered">
          <div className="modal-container" style={{maxWidth: '600px'}}>
            <div className="modal-header">
              <div>
                <h3 className="text-2xl font-extrabold text-gray-900 flex items-center gap-2">
                  <Bot className="w-6 h-6 text-purple-500" />
                  AI助手设置
                </h3>
                <p className="text-sm text-gray-500 mt-1">{editingAccount.nickname || editingAccount.remark || editingAccount.id}</p>
              </div>
              <button
                onClick={() => setActiveModal(null)}
                className="p-2 rounded-xl hover:bg-gray-100 transition-colors flex-shrink-0"
              >
                <X className="w-5 h-5 text-gray-500" />
              </button>
            </div>

            <div className="modal-body space-y-6">
              {/* 启用AI */}
              <div className="flex items-center justify-between p-4 bg-purple-50 rounded-xl">
                <div>
                  <div className="font-bold text-gray-900 flex items-center gap-2">
                    <Bot className="w-4 h-4 text-purple-500" />
                    启用AI自动回复
                  </div>
                  <div className="text-xs text-gray-500">AI将自动处理买家的砍价消息</div>
                </div>
                <button
                  type="button"
                  onClick={() => setAiSettings({ ...aiSettings, ai_enabled: !aiSettings.ai_enabled })}
                  className={`w-14 h-8 rounded-full transition-colors duration-300 relative ${
                    aiSettings.ai_enabled ? 'bg-[#FFE815]' : 'bg-gray-300'
                  }`}
                >
                  <span
                    className={`absolute top-1 w-6 h-6 bg-white rounded-full shadow-md transition-transform duration-300 ${
                      aiSettings.ai_enabled ? 'translate-x-7' : 'translate-x-1'
                    }`}
                  />
                </button>
              </div>

              {/* 砍价策略 */}
              <div className="border-t border-gray-200 pt-6">
                <h3 className="text-lg font-bold text-gray-900 mb-4">砍价策略</h3>
                <div className="grid grid-cols-3 gap-4">
                  <div>
                    <label className="block text-sm font-bold text-gray-700 mb-2">最大折扣比例 (%)</label>
                    <input
                      type="number"
                      value={aiSettings.max_discount_percent}
                      onChange={(e) => setAiSettings({ ...aiSettings, max_discount_percent: parseInt(e.target.value) || 0 })}
                      className="w-full ios-input px-4 py-3 rounded-xl"
                      min="0"
                      max="100"
                    />
                    <p className="text-xs text-gray-500 mt-1">例如：10表示最多降价10%</p>
                  </div>
                  <div>
                    <label className="block text-sm font-bold text-gray-700 mb-2">最大折扣金额 (元)</label>
                    <input
                      type="number"
                      value={aiSettings.max_discount_amount}
                      onChange={(e) => setAiSettings({ ...aiSettings, max_discount_amount: parseInt(e.target.value) || 0 })}
                      className="w-full ios-input px-4 py-3 rounded-xl"
                      min="0"
                    />
                    <p className="text-xs text-gray-500 mt-1">例如：100表示最多降价100元</p>
                  </div>
                  <div>
                    <label className="block text-sm font-bold text-gray-700 mb-2">最大砍价轮次</label>
                    <input
                      type="number"
                      value={aiSettings.max_bargain_rounds}
                      onChange={(e) => setAiSettings({ ...aiSettings, max_bargain_rounds: parseInt(e.target.value) || 1 })}
                      className="w-full ios-input px-4 py-3 rounded-xl"
                      min="1"
                      max="10"
                    />
                    <p className="text-xs text-gray-500 mt-1">买家最多可以砍价的次数</p>
                  </div>
                </div>
              </div>

              {/* 自定义提示词 */}
              <div>
                <label className="block text-sm font-bold text-gray-700 mb-2">自定义提示词（可选）</label>
                <textarea
                  value={aiSettings.custom_prompts}
                  onChange={(e) => setAiSettings({ ...aiSettings, custom_prompts: e.target.value })}
                  placeholder="输入自定义的AI回复规则或风格指引...&#10;&#10;例如：回复时保持礼貌专业、使用简洁的语言、强调产品质量等"
                  className="w-full ios-input px-4 py-3 rounded-xl h-40 resize-none"
                />
              </div>

              {/* AI如何工作 */}
              <div className="bg-blue-50 border border-blue-200 rounded-xl p-4">
                <h4 className="font-bold text-blue-900 mb-2 flex items-center gap-2">
                  <Settings className="w-4 h-4" />
                  AI如何工作
                </h4>
                <ul className="text-xs text-blue-800 space-y-1">
                  <li>• 自动识别买家的砍价请求</li>
                  <li>• 根据设定的策略智能回复</li>
                  <li>• 在合理范围内同意降价或礼貌拒绝</li>
                  <li>• 保持专业友好的沟通风格</li>
                </ul>
              </div>
            </div>

            <div className="modal-footer">
              <div className="flex gap-3 w-full">
                <button
                  onClick={() => setActiveModal(null)}
                  className="flex-1 px-6 py-3 rounded-xl font-bold bg-gray-100 text-gray-700 hover:bg-gray-200 transition-colors"
                  disabled={saving}
                >
                  取消
                </button>
                <button
                  onClick={handleSaveAISettings}
                  className="flex-1 ios-btn-primary px-6 py-3 rounded-xl font-bold flex items-center justify-center gap-2"
                  disabled={saving}
                >
                  {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
                  {saving ? '保存中...' : '保存'}
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

export default AccountList;
