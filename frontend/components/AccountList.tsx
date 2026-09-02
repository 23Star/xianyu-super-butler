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
  getRiskControlStatus,
  startManualCaptchaSession,
  requestFreshCaptchaUrl,
} from '../services/api';
import { confirmAction, notify } from '../services/feedback';
import {Power, Edit2, Trash2, QrCode, X, Check, Loader2, MessageSquare, RefreshCw, Save, User, Clock, Key, Eye, EyeOff, Bot, Settings, MapPin, Users, ShieldCheck} from 'lucide-react';
import { EmptyState, PageHeader, PageLoading } from './ui';

type ModalType = 'edit' | 'ai-settings' | null;

const AccountList: React.FC = () => {
  const [accounts, setAccounts] = useState<AccountDetail[]>([]);
  const [loading, setLoading] = useState(true);
  // 风控熔断状态：命中后账号会暂停请求，需要让用户看到而不是只报 409
  const [riskBlocked, setRiskBlocked] = useState<Array<{
    cookie_id: string;
    blocked: boolean;
    remaining_seconds: number;
    verification_type: 'none' | 'slider' | 'face' | 'qr' | 'risk_control';
    verification_message: string;
    verification_url?: string;
  }>>([]);
  const [showQRModal, setShowQRModal] = useState(false);
  const [qrCodeUrl, setQrCodeUrl] = useState<string>('');
  const [qrStatus, setQrStatus] = useState<string>('pending');
  const [qrMessage, setQrMessage] = useState<string>('');
  const [verificationQrUrl, setVerificationQrUrl] = useState<string>('');
  const [verificationUrl, setVerificationUrl] = useState<string>('');
  const qrPollTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const qrSessionRef = useRef<string>('');
  const [activeModal, setActiveModal] = useState<ModalType>(null);
  const [editingAccount, setEditingAccount] = useState<AccountDetail | null>(null);
  const [refreshingProfileId, setRefreshingProfileId] = useState<string | null>(null);
  // 正在取新验证链接的账号
  const [freshUrlLoadingId, setFreshUrlLoadingId] = useState<string | null>(null);
  const [manualCaptchaId, setManualCaptchaId] = useState<string | null>(null);
  // 人工滑块验证弹窗：把服务器端浏览器的画面镜像到本页
  const [captchaAccount, setCaptchaAccount] = useState<AccountDetail | null>(null);
  const [captchaShot, setCaptchaShot] = useState('');
  const [captchaStage, setCaptchaStage] = useState<'starting' | 'ready' | 'done' | 'failed'>('starting');
  const [captchaMessage, setCaptchaMessage] = useState('');
  const captchaWsRef = useRef<WebSocket | null>(null);
  const captchaImgRef = useRef<HTMLImageElement>(null);
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

  // AI设置表单状态（字段必须齐全：PUT 是整行 INSERT OR REPLACE，
  // 少一个字段保存时就会被后端默认值静默覆盖）
  const [aiSettings, setAiSettings] = useState<AIReplySettings>({
    ai_enabled: false,
    model_name: 'qwen-plus',
    api_key: '',
    base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
    user_agent: '',
    max_discount_percent: 10,
    max_discount_amount: 100,
    max_bargain_rounds: 3,
    context_enabled: true,
    context_message_limit: 12,
    context_expire_minutes: 120,
    custom_prompts: '',
  });
  const [saving, setSaving] = useState(false);

  const loadAccounts = async (options?: { silent?: boolean }) => {
    // 轮询刷新走静默模式，避免每 30 秒把整个列表闪成加载态
    if (!options?.silent) setLoading(true);
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
      if (!options?.silent) setLoading(false);
    }
  };

  useEffect(() => {
    const poll = () => {
      getRiskControlStatus()
        .then(res => setRiskBlocked((res.accounts || []).filter(a => a.blocked || (a.verification_type && a.verification_type !== 'none'))))
        .catch(() => setRiskBlocked([]));
    };
    poll();
    const timer = setInterval(poll, 30000);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    loadAccounts();
    // 账号的 runtime_state 会随后端连接情况变化（连上、断线重连、进出风控），
    // 只在挂载时拉一次会让页面一直停在旧快照上 —— 表现为账号已在正常收发心跳，
    // 界面却仍显示「未运行」且状态点是灰的。与风控轮询保持同一节奏。
    const timer = setInterval(() => {
      loadAccounts({ silent: true });
    }, 30000);
    return () => {
      clearInterval(timer);
      qrSessionRef.current = '';
      if (qrPollTimerRef.current) clearTimeout(qrPollTimerRef.current);
    };
  }, []);

  const handleToggle = async (id: string, currentStatus: boolean) => {
    await updateAccountStatus(id, !currentStatus);
    loadAccounts();
  };

  // 点按钮时实时取链接，而不是用风控日志里的历史链接 ——
  // punish 链接的 x5secdata 只能用一次、约 1 小时失效，
  // 旧链接打开只会看到「抱歉，页面访问出现了问题」。
  const handleOpenFreshCaptcha = async (id: string) => {
    setFreshUrlLoadingId(id);
    try {
      const result = await requestFreshCaptchaUrl(id);
      if (!result.need_verify) {
        notify(result.message || '该账号风控已解除，无需验证', 'success');
        await loadAccounts({ silent: true });
        const status = await getRiskControlStatus();
        setRiskBlocked((status.accounts || []).filter(
          item => item.blocked || (item.verification_type && item.verification_type !== 'none')
        ));
        return;
      }
      if (result.verification_url) {
        window.open(result.verification_url, '_blank', 'noopener,noreferrer');
        notify('已打开验证页，请用鼠标拖动滑块完成验证', 'info');
      }
    } catch (error) {
      notify(error instanceof Error ? error.message : '获取验证链接失败', 'error');
    } finally {
      setFreshUrlLoadingId(null);
    }
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

  // 人工滑块验证：在本页开弹窗，通过 WebSocket 把服务器端浏览器的截图推过来，
  // 鼠标事件再回传驱动服务器上的真实浏览器 —— 相当于把远端浏览器镜像到这里。
  // 这样部署在没有桌面的服务器上也能人工过验证，不需要访问服务器屏幕。
  const handleManualCaptcha = async (account: AccountDetail) => {
    setCaptchaAccount(account);
    setCaptchaShot('');
    setCaptchaStage('starting');
    setCaptchaMessage('正在服务器上启动验证页面，请稍候…');
    setManualCaptchaId(account.id);

    try {
      const result = await startManualCaptchaSession(account.id);
      if (!result.success) throw new Error(result.message || '人工验证未完成');
      setCaptchaStage('done');
      setCaptchaMessage(result.message || '验证完成，账号 Cookie 已更新');
      notify(result.message || '人工验证完成，账号 Cookie 已更新', 'success');
      const status = await getRiskControlStatus();
      setRiskBlocked((status.accounts || []).filter(item => item.blocked || (item.verification_type && item.verification_type !== 'none')));
      await loadAccounts({ silent: true });
    } catch (error) {
      const msg = error instanceof Error ? error.message : '人工验证启动失败';
      setCaptchaStage('failed');
      setCaptchaMessage(msg);
      notify(msg, 'error');
    } finally {
      setManualCaptchaId(null);
    }
  };

  // 弹窗打开后连上服务器端会话，持续接收截图；关闭时断开
  useEffect(() => {
    if (!captchaAccount) {
      captchaWsRef.current?.close();
      captchaWsRef.current = null;
      return;
    }

    let closed = false;
    let retry = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const connect = () => {
      if (closed) return;
      const scheme = location.protocol === 'https:' ? 'wss' : 'ws';
      const ws = new WebSocket(
        `${scheme}://${location.host}/api/captcha/ws/${encodeURIComponent(captchaAccount.id)}`
      );
      captchaWsRef.current = ws;

      ws.onmessage = event => {
        let data: any;
        try {
          data = JSON.parse(event.data);
        } catch {
          return;
        }
        if (data.type === 'session_info' || data.type === 'screenshot_update') {
          if (data.screenshot) {
            setCaptchaShot(
              String(data.screenshot).startsWith('data:')
                ? data.screenshot
                : `data:image/jpeg;base64,${data.screenshot}`
            );
            setCaptchaStage('ready');
            setCaptchaMessage('按住滑块向右拖动完成验证');
          }
        } else if (data.type === 'completed') {
          setCaptchaStage('done');
          setCaptchaMessage('验证通过，正在回收 Cookie…');
        } else if (data.type === 'error') {
          // 会话尚未建立时后端会立刻返回 error，稍后重试即可
          if (retry < 20) {
            retry += 1;
            timer = setTimeout(connect, 1000);
          }
        }
      };

      ws.onclose = () => {
        if (!closed && retry < 20) {
          retry += 1;
          timer = setTimeout(connect, 1000);
        }
      };
    };

    connect();
    return () => {
      closed = true;
      if (timer) clearTimeout(timer);
      captchaWsRef.current?.close();
      captchaWsRef.current = null;
    };
  }, [captchaAccount]);

  // 把本页的鼠标坐标换算成服务器端浏览器的坐标后回传
  const sendCaptchaMouse = (eventType: 'down' | 'move' | 'up', e: React.MouseEvent) => {
    const ws = captchaWsRef.current;
    const img = captchaImgRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN || !img || !img.naturalWidth) return;

    const rect = img.getBoundingClientRect();
    // 截图在页面上被等比缩放显示，坐标要按缩放比还原回原始分辨率
    const x = (e.clientX - rect.left) * (img.naturalWidth / rect.width);
    const y = (e.clientY - rect.top) * (img.naturalHeight / rect.height);
    ws.send(JSON.stringify({
      type: 'mouse_event',
      event_type: eventType,
      x: Math.round(x),
      y: Math.round(y),
    }));
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
      // 全量加载：PUT 是整行覆盖保存，漏掉的字段（user_agent、
      // context_* 等）会被后端默认值静默重置
      setAiSettings({
        ai_enabled: settings.ai_enabled ?? false,
        model_name: settings.model_name || 'qwen-plus',
        api_key: settings.api_key || '',
        base_url: settings.base_url || 'https://dashscope.aliyuncs.com/compatible-mode/v1',
        user_agent: settings.user_agent ?? '',
        max_discount_percent: settings.max_discount_percent ?? 10,
        max_discount_amount: settings.max_discount_amount ?? 100,
        max_bargain_rounds: settings.max_bargain_rounds ?? 3,
        context_enabled: settings.context_enabled ?? true,
        context_message_limit: settings.context_message_limit ?? 12,
        context_expire_minutes: settings.context_expire_minutes ?? 120,
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
    setVerificationQrUrl('');
    setVerificationUrl('');
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
              // 不能在这里停止轮询：用户正要去手机上完成人脸验证，
              // 验证走完后状态才会变成 success。原实现清掉 session 直接 return，
              // 于是验证做完页面永远停在「请完成验证」，只能关掉重来。
              setQrStatus('verification_required');
              setQrMessage(statusRes.message || '请使用手机扫描二维码完成安全验证');
              if (statusRes.verification_qr_code_url) {
                setVerificationQrUrl(statusRes.verification_qr_code_url);
              }
              if (statusRes.verification_url) {
                setVerificationUrl(statusRes.verification_url);
              }
              // 验证要花上一两分钟，放慢轮询节奏即可
              qrPollTimerRef.current = setTimeout(pollStatus, 2000);
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
    // 登录态过期是终态：等待和过验证都没用，必须重新扫码。
    // 与「连接中」分开显示，否则用户会一直等一个不会变好的状态。
    if (account.runtime_state === 'need_relogin') {
      return { label: '需重新扫码', className: 'bg-red-100 text-red-700' };
    }
    if (account.runtime_state === 'failed') {
      return { label: '监听异常', className: 'bg-red-100 text-red-700' };
    }
    // 反复重连通常意味着账号被风控拦住：Token 取不到，消息、发货、自动回复
    // 实际都不通。必须与「监听中」区分开，否则界面会给出一个假的健康状态。
    if (account.runtime_state === 'connecting') {
      return { label: '连接中 / 重连', className: 'bg-amber-100 text-amber-800' };
    }
    return { label: '已启用 / 未运行', className: 'bg-amber-100 text-amber-800' };
  };

  if (loading) return <PageLoading label="正在加载账号和运行状态" />;

  return (
    <div className="page-stack animate-fade-in relative">
      {riskBlocked.length > 0 && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3">
          <p className="text-sm font-bold text-amber-900">
            闲鱼要求人机验证，{riskBlocked.length} 个账号无法获取令牌
          </p>
          <p className="mt-1 text-xs leading-5 text-amber-800">
            {riskBlocked.map(item => `${item.cookie_id}：${item.verification_message || '平台风控'}`).join('；')}。
            {/* 只有本地熔断中才有确切的恢复时间；闲鱼侧的验证要求要靠过验证解除，
                写死「N 分钟后恢复」会让用户干等一个不会自动好的状态 */}
            {riskBlocked.some(a => a.blocked) ? (
              <>
                {' '}系统会自动退避并重试，预计
                {' '}
                {Math.max(1, Math.ceil(Math.max(...riskBlocked.map(a => a.remaining_seconds || 0)) / 60))}
                {' '}
                分钟后恢复。此期间请勿频繁操作 —— 持续请求会让验证状态持续更久。
              </>
            ) : (
              <>
                {' '}本地冷却已结束，但闲鱼仍要求完成验证。请用下方账号卡片里的
                「在我的浏览器打开验证页」用真实鼠标过一次滑块，通过后会自动恢复。
              </>
            )}
          </p>
        </div>
      )}

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

      <p className="text-xs leading-5 text-gray-400">
        提示：挂 VPN、代理或部署在海外服务器时，闲鱼风控会明显收紧，滑块和人脸验证的通过率大幅下降，建议使用国内网络环境登录与运行。
      </p>

      {/* Account Grid */}
      <div className="grid grid-cols-1 gap-3">
        {accounts.map((account) => {
          const runtimeBadge = getRuntimeBadge(account);
          const isListening = account.enabled && account.runtime_state === 'running';
          const blockedState = riskBlocked.find(item => item.cookie_id === account.id);
          return (
          <article key={account.id} className="ios-card flex flex-col gap-4 p-4 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex min-w-0 items-start gap-4 sm:items-center">
              <div className="relative">
                {account.avatar_url && !failedAvatars.has(account.avatar_url) ? (
                  <img
                    src={account.avatar_url.startsWith('//') ? `https:${account.avatar_url}` : account.avatar_url}
                    alt=""
                    className="h-14 w-14 rounded-md object-cover"
                    referrerPolicy="no-referrer"
                    loading="lazy"
                    // 按图片地址记录失败，而不是按账号 —— 否则头像换了新地址
                    // 也会一直显示首字母占位，只能靠手动刷新绕过
                    onError={() => setFailedAvatars(previous => new Set(previous).add(account.avatar_url!))}
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
                      <span className="text-gray-400">/</span>
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
                   {blockedState && <span className="status-badge bg-red-100 text-red-700">{blockedState.verification_type === 'slider' ? '滑块验证' : blockedState.verification_type === 'face' ? '人脸验证' : '平台风控'}{blockedState.blocked ? ` · ${Math.max(1, Math.ceil(blockedState.remaining_seconds / 60))} 分钟` : ''}</span>}
                   {account.auto_confirm && <span className="status-badge status-badge-warning flex items-center gap-1.5"><MessageSquare className="w-3 h-3"/> 自动确认</span>}
                   {account.pause_duration > 0 && <span className="status-badge status-badge-info flex items-center gap-1.5"><Clock className="w-3 h-3"/> 暂停 {account.pause_duration} 分钟</span>}
                </div>
                {/* 登录态过期给出明确动作，只挂一个徽标用户不知道该做什么 */}
                {account.runtime_state === 'need_relogin' && (
                  <p className="mt-2 rounded-md bg-red-50 px-3 py-2 text-xs leading-5 text-red-700">
                    闲鱼登录态已过期，人机验证和等待都无法恢复。请点右上角「扫码添加账号」
                    用同一个闲鱼账号重新扫码，即可覆盖并恢复该账号。
                  </p>
                )}
                {/* 闲鱼要求人机验证时给出「自己浏览器打开」的入口。
                    服务器端用 CDP 拖滑块通过率很低（风控查的是合并前子事件密度，
                    自动化派发每帧只有一个），用真实鼠标过一次要可靠得多。 */}
                {blockedState?.verification_url && (
                  <div className="mt-2 rounded-md bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-900">
                    <p className="font-bold">闲鱼要求完成人机验证，账号暂时拿不到令牌</p>
                    <p className="mt-1">
                      推荐用你自己的浏览器打开验证页、用真实鼠标拖动滑块，通过率远高于服务器自动拖动。
                      验证通过后本页会自动恢复，无需重新扫码。
                    </p>
                    <button
                      type="button"
                      onClick={() => handleOpenFreshCaptcha(account.id)}
                      disabled={freshUrlLoadingId === account.id}
                      className="mt-2 inline-flex items-center gap-1.5 rounded-full bg-[#ffe100] px-3 py-1.5 font-bold text-[#2a2416] hover:bg-[#ffd700] disabled:opacity-60"
                    >
                      {freshUrlLoadingId === account.id
                        ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
                        : <ShieldCheck className="h-3.5 w-3.5" />}
                      在我的浏览器打开验证页
                    </button>
                  </div>
                )}
              </div>
            </div>
            <div className="flex items-center justify-end gap-1 border-t border-gray-100 pt-3 sm:border-0 sm:pt-0">
                <button
                    onClick={() => handleManualCaptcha(account)}
                    disabled={manualCaptchaId !== null || !blockedState}
                    className={`flex items-center gap-1.5 rounded-md px-2.5 py-2 text-xs font-bold disabled:cursor-not-allowed disabled:opacity-40 ${blockedState ? 'bg-amber-100 text-amber-800 hover:bg-amber-200' : 'text-gray-400'}`}
                    title={blockedState
                      ? '账号被闲鱼要求人机验证，点此在页面内手动拖动滑块解除'
                      : '账号当前不在风控状态，无需人工验证'}
                    aria-label={blockedState ? '人工滑块验证' : '账号未处于风控，无需验证'}
                >
                    {manualCaptchaId === account.id
                      ? <Loader2 className="h-4 w-4 animate-spin" />
                      : <ShieldCheck className="h-4 w-4" />}
                    <span>人工验证</span>
                </button>
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
                          <div className="media-light-surface relative mx-auto flex h-60 w-60 items-center justify-center overflow-hidden rounded-md border border-gray-200 bg-gray-50">
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
                              {qrStatus === 'verification_required' && (
                                  <div className="flex h-full w-full flex-col items-center justify-center bg-white p-2 text-center">
                                      {verificationQrUrl ? (
                                        <img src={verificationQrUrl} alt="闲鱼人脸验证二维码" className="h-44 w-44" />
                                      ) : (
                                        <ShieldCheck className="mb-3 h-12 w-12 text-amber-600" />
                                      )}
                                      <span className="mt-1 text-sm font-bold text-amber-800">手机扫码完成人脸验证</span>
                                      <span className="mt-1 text-xs text-gray-500">验证通过后本页会自动继续，请勿关闭</span>
                                      {verificationUrl && (
                                        <a href={verificationUrl} target="_blank" rel="noreferrer" className="mt-2 text-xs text-blue-600 underline">在当前设备打开验证页</a>
                                      )}
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
                    editForm.auto_confirm ? 'bg-[#ffe100]' : 'bg-gray-300'
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
                        editForm.show_browser ? 'bg-[#ffe100]' : 'bg-gray-300'
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
                    aiSettings.ai_enabled ? 'bg-[#ffe100]' : 'bg-gray-300'
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

      {captchaAccount && createPortal(
        <div className="modal-overlay">
          <div className="modal-container modal-container-lg">
            <div className="modal-header flex items-start justify-between gap-4">
              <div>
                <h3 className="text-lg font-bold text-gray-900">人工滑块验证</h3>
                <p className="mt-1 text-sm text-gray-500">
                  {captchaAccount.nickname || captchaAccount.id}
                </p>
              </div>
              <button
                type="button"
                onClick={() => setCaptchaAccount(null)}
                className="rounded-md p-2 hover:bg-gray-100"
                aria-label="关闭"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            <div className="modal-body space-y-4">
              <div className="rounded-md border border-blue-200 bg-blue-50 px-3 py-2 text-xs leading-relaxed text-blue-800">
                <p className="font-bold">这是什么？</p>
                <p className="mt-1">
                  闲鱼要求人机验证时，系统会自动尝试滑动，但成功率有限。此处把
                  <b>服务器上浏览器的画面实时投屏</b>到这里，你用鼠标拖动，
                  操作会回传到服务器驱动真实浏览器 —— 因此部署在无桌面的服务器上也能用。
                </p>
                <p className="mt-1">
                  验证通过后系统会自动回收新的登录凭证，账号立即恢复运行。
                </p>
              </div>

              <div className={`rounded-md px-3 py-2 text-sm font-semibold ${
                captchaStage === 'done'
                  ? 'bg-green-50 text-green-700'
                  : captchaStage === 'failed'
                    ? 'bg-red-50 text-red-700'
                    : 'bg-amber-50 text-amber-800'
              }`}>
                {captchaMessage || '正在准备…'}
              </div>

              <div className="flex min-h-[320px] items-center justify-center rounded-md border-2 border-dashed border-gray-200 bg-gray-50 p-2">
                {captchaShot ? (
                  <img
                    ref={captchaImgRef}
                    src={captchaShot}
                    alt="服务器端验证页面"
                    draggable={false}
                    className="max-h-[460px] w-auto cursor-crosshair select-none rounded"
                    onMouseDown={e => { e.preventDefault(); sendCaptchaMouse('down', e); }}
                    onMouseMove={e => { if (e.buttons === 1) sendCaptchaMouse('move', e); }}
                    onMouseUp={e => sendCaptchaMouse('up', e)}
                    onMouseLeave={e => { if (e.buttons === 1) sendCaptchaMouse('up', e); }}
                  />
                ) : (
                  <div className="text-center text-sm text-gray-500">
                    <Loader2 className="mx-auto mb-2 h-6 w-6 animate-spin text-gray-400" />
                    正在服务器上打开验证页面…
                    <p className="mt-1 text-xs text-gray-400">
                      首次启动需要几秒，若账号当前不在风控状态则不会出现滑块
                    </p>
                  </div>
                )}
              </div>

              <p className="text-xs text-gray-500">
                操作方式：在上方画面的滑块按钮上 <b>按住鼠标左键</b>，
                <b>向右拖到底</b> 后松开。画面会随你的操作实时刷新。
              </p>
            </div>

            <div className="modal-footer flex justify-end">
              <button
                type="button"
                onClick={() => setCaptchaAccount(null)}
                className="ios-btn-secondary rounded-md px-4 py-2 text-sm"
              >
                关闭
              </button>
            </div>
          </div>
        </div>,
        document.body
      )}
    </div>
  );
};

export default AccountList;
