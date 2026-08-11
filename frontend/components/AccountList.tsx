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
  refreshAccountProfile,
  getAutoRatingSettings,
  updateAutoRatingSettings,
  saveAutoRatingTemplate,
  runAutoRatingNow
} from '../services/api';
import { confirmAction, notify } from '../services/feedback';
import {
  Power, Edit2, Trash2, QrCode, X, Check, Loader2,
  MessageSquare, RefreshCw, Save, User, Clock, MessageCircle,
  Key, Eye, EyeOff, Bot, Settings, MapPin, Users, Star
} from 'lucide-react';
import { EmptyState, PageHeader, PageLoading } from './ui';

type ModalType = 'edit' | 'ai-settings' | 'auto-rating' | null;

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
  const [ratingForm, setRatingForm] = useState({
    enabled: false,
    name: '默认好评',
    content: '不错的买家，沟通愉快，期待再次交易！',
  });

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
      notify(error instanceof Error ? error.message : '账号资料刷新失败');
    } finally {
      setRefreshingProfileId(null);
    }
  };

  const handleDelete = async (id: string) => {
    if (await confirmAction('确认删除该账号吗？')) {
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

  const openAutoRatingModal = async (account: AccountDetail) => {
    setEditingAccount(account);
    setSaving(true);
    try {
      const settings = await getAutoRatingSettings(account.id);
      setRatingForm({
        enabled: settings.enabled,
        name: settings.template?.name || '默认好评',
        content: settings.template?.content || '不错的买家，沟通愉快，期待再次交易！',
      });
    } catch (error) {
      notify(error instanceof Error ? error.message : '自动评价设置加载失败');
    } finally {
      setSaving(false);
    }
    setActiveModal('auto-rating');
  };

  const handleSaveAutoRating = async () => {
    if (!editingAccount || !ratingForm.content.trim()) return;
    setSaving(true);
    try {
      await saveAutoRatingTemplate(editingAccount.id, ratingForm.name, ratingForm.content);
      await updateAutoRatingSettings(editingAccount.id, ratingForm.enabled);
      setActiveModal(null);
      notify('自动评价设置已保存');
    } catch (error) {
      notify(error instanceof Error ? error.message : '自动评价设置保存失败');
    } finally {
      setSaving(false);
    }
  };

  const handleRunAutoRating = async () => {
    setSaving(true);
    try {
      const result = await runAutoRatingNow();
      const stats = result?.data || {};
      notify(`执行完成：成功 ${stats.success || 0}，失败 ${stats.failed || 0}，跳过 ${stats.skipped || 0}`);
    } catch (error) {
      notify(error instanceof Error ? error.message : '自动评价执行失败');
    } finally {
      setSaving(false);
    }
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
      notify('更新失败，请重试');
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
      notify('更新失败，请重试');
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

  const getRuntimeBadge = (account: AccountDetail) => {
    if (!account.enabled) {
      return { label: '已暂停', className: 'bg-gray-100 text-gray-500' };
    }
    if (account.runtime_state === 'running') {
      return { label: '监听中', className: 'bg-green-100 text-green-700' };
    }
    if (account.runtime_state === 'failed') {
      return { label: '监听异常', className: 'bg-red-100 text-red-700' };
    }
    return { label: '已启用 / 未运行', className: 'bg-amber-100 text-amber-800' };
  };

  if (loading) return <PageLoading label="正在加载账号和运行状态" />;

  return (
    <div className="page-stack animate-fade-in relative">
      <PageHeader
        title="账号管理"
        description="管理闲鱼账号授权、监听状态、基础资料和账号级回复策略。"
        icon={Users}
        badge={<span className="status-badge status-badge-info">{accounts.length} 个账号</span>}
        actions={(
          <button
            onClick={startQRLogin}
            className="ios-btn-primary flex items-center justify-center gap-2 rounded-md px-4 py-2 text-sm"
          >
            <QrCode className="h-4 w-4" />
            扫码添加账号
          </button>
        )}
      />

      {/* Account Grid */}
      <div className="grid grid-cols-1 gap-3">
        {accounts.map((account) => {
          const runtimeBadge = getRuntimeBadge(account);
          const isListening = account.enabled && account.runtime_state === 'running';
          return (
          <article key={account.id} className="ios-card flex flex-col gap-4 p-4 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex min-w-0 items-start gap-4 sm:items-center">
              <div className="relative">
                {account.avatar_url && !failedAvatars.has(account.id) ? (
                  <img
                    src={account.avatar_url.startsWith('//') ? `https:${account.avatar_url}` : account.avatar_url}
                    alt=""
                    className="h-14 w-14 rounded-md object-cover"
                    referrerPolicy="no-referrer"
                    onError={() => setFailedAvatars(previous => new Set(previous).add(account.id))}
                  />
                ) : (
                  <div className="flex h-14 w-14 items-center justify-center rounded-md bg-yellow-100 text-lg font-bold text-yellow-800">
                    {account.nickname?.trim().charAt(0) || account.remark?.trim().charAt(0) || '闲'}
                  </div>
                )}
                <div className={`absolute -bottom-1 -right-1 w-6 h-6 rounded-full border-4 border-white flex items-center justify-center ${isListening ? 'bg-green-500' : account.runtime_state === 'failed' ? 'bg-red-500' : 'bg-gray-300'}`}>
                    {isListening && <Check className="w-3 h-3 text-white" />}
                </div>
              </div>
              <div className="min-w-0">
                <div className="mb-1 flex flex-wrap items-center gap-2">
                    <h3 className="break-words text-lg font-bold text-gray-900">{account.nickname || account.remark || '未命名账号'}</h3>
                    <span className={`status-badge ${runtimeBadge.className}`}>
                      {runtimeBadge.label}
                    </span>
                    {account.ai_enabled && (
                        <span className="status-badge status-badge-warning flex items-center gap-1">
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
                   {account.auto_confirm && <span className="status-badge status-badge-warning flex items-center gap-1.5"><MessageSquare className="w-3 h-3"/> 自动确认</span>}
                   {account.pause_duration > 0 && <span className="status-badge status-badge-info flex items-center gap-1.5"><Clock className="w-3 h-3"/> 暂停 {account.pause_duration} 分钟</span>}
                </div>
              </div>
            </div>
            <div className="flex items-center justify-end gap-1 border-t border-gray-100 pt-3 sm:border-0 sm:pt-0">
                <button
                    onClick={() => handleRefreshProfile(account.id)}
                    disabled={refreshingProfileId === account.id}
                    className="rounded-md p-2.5 text-amber-700 hover:bg-amber-50 disabled:cursor-wait disabled:opacity-50"
                    title="刷新闲鱼资料"
                    aria-label="刷新闲鱼资料"
                >
                    <RefreshCw className={`w-5 h-5 ${refreshingProfileId === account.id ? 'animate-spin' : ''}`} />
                </button>
                <button
                    onClick={() => openEditModal(account)}
                    className="rounded-md p-2.5 text-gray-600 hover:bg-gray-100"
                    title="编辑账号"
                >
                    <Edit2 className="w-5 h-5" />
                </button>
                <button
                    onClick={() => openAIModal(account)}
                    className="rounded-md p-2.5 text-amber-700 hover:bg-amber-50"
                    title="AI设置"
                >
                    <Bot className="w-5 h-5" />
                </button>
                <button
                    onClick={() => openAutoRatingModal(account)}
                    className="rounded-md p-2.5 text-orange-600 hover:bg-orange-50"
                    title="自动评价"
                    aria-label="自动评价"
                >
                    <Star className="w-5 h-5" />
                </button>
                <button
                    onClick={() => handleToggle(account.id, account.enabled)}
                    className={`rounded-md p-2.5 ${account.enabled ? 'text-green-600 hover:bg-green-50' : 'text-gray-400 hover:bg-gray-100'}`}
                    title={account.enabled ? '暂停账号' : '启用账号'}
                    aria-label={account.enabled ? '暂停账号' : '启用账号'}
                >
                    <Power className="w-5 h-5" />
                </button>
                <button
                    onClick={() => handleDelete(account.id)}
                    className="rounded-md p-2.5 text-red-500 hover:bg-red-100"
                    title="删除账号"
                    aria-label="删除账号"
                >
                    <Trash2 className="w-5 h-5" />
                </button>
            </div>
          </article>
          );
        })}

        {accounts.length === 0 && (
            <EmptyState
              title="暂无闲鱼账号"
              description="扫码登录后，系统会保存授权并开始获取账号资料、商品、消息和订单状态。"
              icon={User}
              action={(
                <button type="button" onClick={startQRLogin} className="ios-btn-primary rounded-md px-4 py-2 text-sm">
                  扫码添加账号
                </button>
              )}
            />
        )}
      </div>

      {/* QR Code Modal */}
      {showQRModal && createPortal(
          <div className="modal-overlay">
              <div className="modal-container" style={{maxWidth: '24rem'}}>
                  <div className="modal-header flex items-start justify-between gap-4">
                    <div>
                      <h3 className="text-lg font-bold text-gray-900">扫码登录</h3>
                      <p className="mt-1 text-xs text-gray-500">使用闲鱼 App 扫码并在手机端确认。</p>
                    </div>
                    <button
                      type="button"
                      onClick={closeQRModal}
                      className="rounded-md p-2 hover:bg-gray-100"
                      aria-label="关闭扫码登录"
                    >
                      <X className="h-5 w-5 text-gray-600" />
                    </button>
                  </div>

                  <div className="modal-body py-5">
                      <div className="text-center">
                          <div className="relative mx-auto flex h-60 w-60 items-center justify-center overflow-hidden rounded-md border border-gray-200 bg-gray-50">
                              {qrStatus === 'loading' && <Loader2 className="h-9 w-9 animate-spin text-amber-500" />}
                              {(qrStatus === 'waiting' || qrStatus === 'scanned') && (
                                  <img src={qrCodeUrl} alt="闲鱼登录二维码" className="h-full w-full p-2" />
                              )}
                              {qrStatus === 'scanned' && (
                                  <div className="absolute inset-x-3 bottom-3 border border-gray-200 bg-white/95 px-3 py-2 text-sm font-semibold text-gray-800">
                                      已扫码，请在手机确认
                                  </div>
                              )}
                              {qrStatus === 'processing' && (
                                  <div className="absolute inset-0 flex flex-col items-center justify-center bg-white/95 text-gray-800">
                                      <Loader2 className="mb-4 h-9 w-9 animate-spin text-amber-500" />
                                      <span className="font-bold">正在准备账号</span>
                                      <span className="mt-2 text-xs text-gray-500">无需重复扫码</span>
                                  </div>
                              )}
                              {qrStatus === 'success' && (
                                  <div className="absolute inset-0 flex animate-fade-in flex-col items-center justify-center bg-white/95 text-green-700">
                                      <div className="mb-4 flex h-14 w-14 items-center justify-center rounded-md bg-green-50">
                                         <Check className="h-7 w-7" />
                                      </div>
                                      <span className="text-base font-bold">登录成功</span>
                                  </div>
                              )}
                              {qrStatus === 'error' && (
                                  <div className="flex flex-col items-center px-4 text-center">
                                      <span className="mb-2 font-bold text-red-600">账号未登录完成</span>
                                      {qrMessage && <span className="mb-3 text-xs text-gray-500">{qrMessage}</span>}
                                      <button
                                        type="button"
                                        onClick={startQRLogin}
                                        className="ios-btn-secondary flex items-center gap-1.5 rounded-md px-3 py-2 text-xs"
                                      >
                                        <RefreshCw className="h-3.5 w-3.5" />
                                        重新生成
                                      </button>
                                  </div>
                              )}
                          </div>

                          <p className="mt-4 rounded-md border border-gray-200 bg-gray-50 px-3 py-2 text-xs font-medium text-gray-500">
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
        <div className="modal-overlay">
          <div className="modal-container" style={{maxWidth: '600px'}}>
            <div className="modal-header flex items-start justify-between gap-4">
              <div>
                <h3 className="text-lg font-bold text-gray-900">编辑账号</h3>
                <p className="mt-1 text-xs text-gray-500">{editingAccount.nickname || editingAccount.remark || editingAccount.id}</p>
              </div>
              <button
                type="button"
                onClick={() => setActiveModal(null)}
                className="shrink-0 rounded-md p-2 hover:bg-gray-100"
                aria-label="关闭编辑账号"
              >
                <X className="w-5 h-5 text-gray-500" />
              </button>
            </div>

            <div className="modal-body space-y-5">
              {/* 账号ID */}
              <div>
                <label className="block text-sm font-bold text-gray-700 mb-2">账号ID</label>
                <input
                  type="text"
                  value={editingAccount.id}
                  disabled
                  className="ios-input w-full rounded-md bg-gray-50 px-3 py-2.5 text-gray-500"
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
                  className="ios-input w-full rounded-md px-3 py-2.5"
                />
              </div>

              {/* Cookie */}
              <div>
                <label className="block text-sm font-bold text-gray-700 mb-2">Cookie</label>
                <textarea
                  value={editForm.cookie}
                  onChange={(e) => setEditForm({ ...editForm, cookie: e.target.value })}
                  placeholder="更新账号Cookie"
                  className="ios-input h-28 w-full resize-y rounded-md px-3 py-2.5 font-mono text-xs"
                />
                <p className="text-xs text-gray-500 mt-1">当前Cookie长度: {editForm.cookie.length} 字符</p>
              </div>

              {/* 自动确认收货 */}
              <div className="flex items-center justify-between gap-4 rounded-md border border-gray-200 bg-gray-50 p-4">
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
                  className={`relative h-6 w-11 shrink-0 rounded-full transition-colors ${
                    editForm.auto_confirm ? 'bg-[#FFE815]' : 'bg-gray-300'
                  }`}
                >
                  <span
                    className={`absolute left-1 top-1 h-4 w-4 rounded-full bg-white shadow-sm transition-transform ${
                      editForm.auto_confirm ? 'translate-x-5' : ''
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
                  className="ios-input w-full rounded-md px-3 py-2.5"
                />
                <p className="text-xs text-gray-500 mt-1">设置后会暂停处理该账号的订单，到时间后自动恢复</p>
              </div>

              {/* 登录信息 */}
              <div className="border-t border-gray-200 pt-5">
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
                      className="ios-input w-full rounded-md px-3 py-2.5"
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
                        className="ios-input w-full rounded-md px-3 py-2.5 pr-11"
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
                      className={`relative h-6 w-11 shrink-0 rounded-full transition-colors ${
                        editForm.show_browser ? 'bg-[#FFE815]' : 'bg-gray-300'
                      }`}
                    >
                      <span
                        className={`absolute left-1 top-1 h-4 w-4 rounded-full bg-white shadow-sm transition-transform ${
                          editForm.show_browser ? 'translate-x-5' : ''
                        }`}
                      />
                    </button>
                  </div>
                </div>
              </div>
            </div>

            <div className="modal-footer">
              <div className="flex w-full gap-2">
                <button
                  type="button"
                  onClick={() => setActiveModal(null)}
                  className="ios-btn-secondary flex-1 rounded-md px-4 py-2.5 text-sm"
                  disabled={saving}
                >
                  取消
                </button>
                <button
                  type="button"
                  onClick={handleSaveEdit}
                  className="ios-btn-primary flex flex-1 items-center justify-center gap-2 rounded-md px-4 py-2.5 text-sm"
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
        <div className="modal-overlay">
          <div className="modal-container" style={{maxWidth: '600px'}}>
            <div className="modal-header flex items-start justify-between gap-4">
              <div>
                <h3 className="flex items-center gap-2 text-lg font-bold text-gray-900">
                  <Bot className="h-5 w-5 text-amber-600" />
                  AI 助手设置
                </h3>
                <p className="mt-1 text-xs text-gray-500">{editingAccount.nickname || editingAccount.remark || editingAccount.id}</p>
              </div>
              <button
                type="button"
                onClick={() => setActiveModal(null)}
                className="shrink-0 rounded-md p-2 hover:bg-gray-100"
                aria-label="关闭 AI 助手设置"
              >
                <X className="w-5 h-5 text-gray-500" />
              </button>
            </div>

            <div className="modal-body space-y-6">
              {/* 启用AI */}
              <div className="flex items-center justify-between gap-4 rounded-md border border-gray-200 bg-gray-50 p-4">
                <div>
                  <div className="font-bold text-gray-900 flex items-center gap-2">
                    <Bot className="h-4 w-4 text-amber-600" />
                    启用 AI 自动回复
                  </div>
                  <div className="text-xs text-gray-500">AI将自动处理买家的砍价消息</div>
                </div>
                <button
                  type="button"
                  onClick={() => setAiSettings({ ...aiSettings, ai_enabled: !aiSettings.ai_enabled })}
                  className={`relative h-6 w-11 shrink-0 rounded-full transition-colors ${
                    aiSettings.ai_enabled ? 'bg-[#FFE815]' : 'bg-gray-300'
                  }`}
                >
                  <span
                    className={`absolute left-1 top-1 h-4 w-4 rounded-full bg-white shadow-sm transition-transform ${
                      aiSettings.ai_enabled ? 'translate-x-5' : ''
                    }`}
                  />
                </button>
              </div>

              {/* 砍价策略 */}
              <div className="border-t border-gray-200 pt-6">
                <h3 className="text-lg font-bold text-gray-900 mb-4">砍价策略</h3>
                <div className="grid gap-4 sm:grid-cols-3">
                  <div>
                    <label className="block text-sm font-bold text-gray-700 mb-2">最大折扣比例 (%)</label>
                    <input
                      type="number"
                      value={aiSettings.max_discount_percent}
                      onChange={(e) => setAiSettings({ ...aiSettings, max_discount_percent: parseInt(e.target.value) || 0 })}
                      className="ios-input w-full rounded-md px-3 py-2.5"
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
                      className="ios-input w-full rounded-md px-3 py-2.5"
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
                      className="ios-input w-full rounded-md px-3 py-2.5"
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
                  className="ios-input h-36 w-full resize-y rounded-md px-3 py-2.5"
                />
              </div>

              {/* AI如何工作 */}
              <div className="rounded-md border border-blue-200 bg-blue-50 p-4">
                <h4 className="mb-2 flex items-center gap-2 font-bold text-blue-900">
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
              <div className="flex w-full gap-2">
                <button
                  type="button"
                  onClick={() => setActiveModal(null)}
                  className="ios-btn-secondary flex-1 rounded-md px-4 py-2.5 text-sm"
                  disabled={saving}
                >
                  取消
                </button>
                <button
                  type="button"
                  onClick={handleSaveAISettings}
                  className="ios-btn-primary flex flex-1 items-center justify-center gap-2 rounded-md px-4 py-2.5 text-sm"
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

      {activeModal === 'auto-rating' && editingAccount && createPortal(
        <div className="modal-overlay">
          <div className="modal-container" style={{maxWidth: '600px'}}>
            <div className="modal-header flex items-start justify-between gap-4">
              <div>
                <h3 className="flex items-center gap-2 text-lg font-bold text-gray-900">
                  <Star className="h-5 w-5 text-orange-500" /> 自动评价
                </h3>
                <p className="mt-1 text-xs text-gray-500">订单完成后自动给买家好评；默认每 5 分钟检查一次。</p>
              </div>
              <button type="button" onClick={() => setActiveModal(null)} className="rounded-md p-2 hover:bg-gray-100">
                <X className="h-5 w-5 text-gray-500" />
              </button>
            </div>
            <div className="modal-body space-y-5">
              <div className="flex items-center justify-between gap-4 rounded-md border border-gray-200 bg-gray-50 p-4">
                <div>
                  <div className="font-bold text-gray-900">启用自动评价</div>
                  <div className="mt-1 text-xs text-gray-500">仅处理近 10 天、状态为交易完成且尚未评价的本地订单。</div>
                </div>
                <button
                  type="button"
                  onClick={() => setRatingForm({...ratingForm, enabled: !ratingForm.enabled})}
                  className={`relative h-6 w-11 shrink-0 rounded-full transition-colors ${ratingForm.enabled ? 'bg-[#FFE815]' : 'bg-gray-300'}`}
                >
                  <span className={`absolute left-1 top-1 h-4 w-4 rounded-full bg-white shadow-sm transition-transform ${ratingForm.enabled ? 'translate-x-5' : ''}`} />
                </button>
              </div>
              <div>
                <label className="mb-2 block text-sm font-bold text-gray-700">模板名称</label>
                <input className="ios-input w-full rounded-md px-3 py-2.5" value={ratingForm.name}
                  onChange={(event) => setRatingForm({...ratingForm, name: event.target.value})} maxLength={80} />
              </div>
              <div>
                <label className="mb-2 block text-sm font-bold text-gray-700">评价内容</label>
                <textarea className="ios-input h-28 w-full resize-y rounded-md px-3 py-2.5" value={ratingForm.content}
                  onChange={(event) => setRatingForm({...ratingForm, content: event.target.value})} maxLength={500} />
                <p className="mt-1 text-xs text-gray-500">{ratingForm.content.length}/500 字</p>
              </div>
              <div className="rounded-md border border-amber-200 bg-amber-50 p-3 text-xs leading-5 text-amber-900">
                自动评价会直接调用闲鱼评价接口，无法撤回。建议先保存但保持关闭，确认模板后再启用。
              </div>
            </div>
            <div className="modal-footer">
              <div className="flex w-full flex-wrap gap-2">
                <button type="button" onClick={handleRunAutoRating} disabled={saving || !ratingForm.enabled}
                  className="ios-btn-secondary flex items-center justify-center gap-2 rounded-md px-4 py-2.5 text-sm disabled:opacity-50">
                  <RefreshCw className={`h-4 w-4 ${saving ? 'animate-spin' : ''}`} /> 立即检查
                </button>
                <button type="button" onClick={() => setActiveModal(null)} disabled={saving}
                  className="ios-btn-secondary flex-1 rounded-md px-4 py-2.5 text-sm">取消</button>
                <button type="button" onClick={handleSaveAutoRating} disabled={saving || !ratingForm.content.trim()}
                  className="ios-btn-primary flex flex-1 items-center justify-center gap-2 rounded-md px-4 py-2.5 text-sm disabled:opacity-50">
                  {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />} 保存
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
