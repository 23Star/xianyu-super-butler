import React, { Suspense, lazy, useState, useEffect } from 'react';
import Sidebar from './components/Sidebar';
import GlobalFeedback from './components/GlobalFeedback';
import AnnouncementBanner from './components/AnnouncementBanner';
import { login, verifyToken, getPublicSettings, register, sendVerificationCode } from './services/api';
import { ShieldCheck, ArrowRight, Loader2, User, Lock, Menu, Mail, KeyRound, CheckCircle2 } from 'lucide-react';

const Dashboard = lazy(() => import('./components/Dashboard'));
const AccountList = lazy(() => import('./components/AccountList'));
const OrderList = lazy(() => import('./components/OrderList'));
const CardList = lazy(() => import('./components/CardList'));
const ItemList = lazy(() => import('./components/ItemList'));
const ProductAutomation = lazy(() => import('./components/ProductAutomation'));
const AIReply = lazy(() => import('./components/AIReply'));
const Settings = lazy(() => import('./components/Settings'));
const Keywords = lazy(() => import('./components/Keywords'));
const MessageManagement = lazy(() => import('./components/MessageManagement'));
const NotificationsAndLogs = lazy(() => import('./components/NotificationsAndLogs'));
const About = lazy(() => import('./components/About'));
const BuyerInteraction = lazy(() => import('./components/BuyerInteraction'));

const PageLoader = () => (
  <div className="page-loading">
    <Loader2 className="h-5 w-5 animate-spin" />
    <span>正在加载页面</span>
  </div>
);

const pageLabels: Record<string, string> = {
  dashboard: '总览',
  accounts: '账号管理',
  items: '商品与发货',
  orders: '订单管理',
  'buyer-interaction': '买家互动',
  cards: '卡密库存',
  messages: '消息中心',
  'auto-reply': '自动回复',
  'ai-reply': 'AI 回复',
  'product-automation': '商品自动化',
  notifications: '通知与日志',
  settings: '系统设置',
  about: '关于',
};

const App: React.FC = () => {
  const [isLoggedIn, setIsLoggedIn] = useState(false);
  const [activeTab, setActiveTab] = useState(() => localStorage.getItem('active_page') || 'dashboard');
  const [checkingAuth, setCheckingAuth] = useState(true);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [loginLoading, setLoginLoading] = useState(false);
  const [loginError, setLoginError] = useState('');
  // 注册成功后回到登录页时的提示
  const [loginNotice, setLoginNotice] = useState('');
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [isAdmin, setIsAdmin] = useState(false);

  // 注册相关。是否显示入口由后台「允许用户注册」控制，
  // 是否需要填验证码由后台「注册邮箱验证」控制（没配 SMTP 时可以关掉）。
  const [authMode, setAuthMode] = useState<'login' | 'register'>('login');
  const [allowRegister, setAllowRegister] = useState(false);
  const [needEmailCode, setNeedEmailCode] = useState(true);
  const [regForm, setRegForm] = useState({ username: '', email: '', password: '', code: '' });
  const [regLoading, setRegLoading] = useState(false);
  const [regError, setRegError] = useState('');
  const [regNotice, setRegNotice] = useState('');
  const [codeSending, setCodeSending] = useState(false);
  const [codeCountdown, setCodeCountdown] = useState(0);

  useEffect(() => {
    getPublicSettings()
      .then(s => {
        setAllowRegister(String(s.registration_enabled) === 'true');
        setNeedEmailCode(String(s.email_verification_enabled ?? 'true') !== 'false');
      })
      .catch(() => setAllowRegister(false));
  }, []);

  // 验证码重发倒计时
  useEffect(() => {
    if (codeCountdown <= 0) return;
    const timer = setTimeout(() => setCodeCountdown(codeCountdown - 1), 1000);
    return () => clearTimeout(timer);
  }, [codeCountdown]);

  const handleSendCode = async () => {
    if (!regForm.email.trim()) {
      setRegError('请先填写邮箱');
      return;
    }
    setCodeSending(true);
    setRegError('');
    setRegNotice('');
    try {
      const res = await sendVerificationCode(regForm.email.trim(), 'register');
      if (res?.success === false) {
        // 多半是没配 SMTP，直接把后端原因透出来，省得对着"发送失败"猜
        setRegError(res.message || '验证码发送失败，请确认邮件服务已配置');
        return;
      }
      setRegNotice('验证码已发送，请查收邮箱');
      setCodeCountdown(60);
    } catch (err) {
      setRegError(err instanceof Error ? err.message : '验证码发送失败');
    } finally {
      setCodeSending(false);
    }
  };

  const handleRegister = async (e: React.FormEvent) => {
    e.preventDefault();
    setRegError('');
    setRegNotice('');

    if (regForm.password.length < 6) {
      setRegError('密码至少 6 位');
      return;
    }
    if (needEmailCode && !regForm.code.trim()) {
      setRegError('请填写邮箱验证码');
      return;
    }

    setRegLoading(true);
    try {
      const res = await register({
        username: regForm.username.trim(),
        email: regForm.email.trim(),
        password: regForm.password,
        ...(needEmailCode ? { verification_code: regForm.code.trim() } : {}),
      });
      if (res?.success) {
        // 注册成功后回到登录页，并把用户名带过去，少填一次
        setUsername(regForm.username.trim());
        setPassword('');
        setRegForm({ username: '', email: '', password: '', code: '' });
        setAuthMode('login');
        setLoginError('');
        setRegNotice('');
        setLoginNotice('注册成功，请使用新账号登录');
      } else {
        setRegError(res?.message || '注册失败');
      }
    } catch (err) {
      setRegError(err instanceof Error ? err.message : '注册失败，请稍后重试');
    } finally {
      setRegLoading(false);
    }
  };

  // Check auth on mount
  useEffect(() => {
      const token = localStorage.getItem('auth_token');
      if (token) {
          verifyToken()
            .then(result => {
              if (!result.authenticated) {
                localStorage.removeItem('auth_token');
                return;
              }
              setIsAdmin(Boolean(result.is_admin));
              setIsLoggedIn(true);
            })
            .catch(() => localStorage.removeItem('auth_token'))
            .finally(() => setCheckingAuth(false));
      } else {
          setCheckingAuth(false);
      }
      
      const handleLogout = () => setIsLoggedIn(false);
      window.addEventListener('auth:logout', handleLogout);
      return () => window.removeEventListener('auth:logout', handleLogout);
  }, []);

  useEffect(() => {
    localStorage.setItem('active_page', activeTab);
  }, [activeTab]);

  const handleLogin = async (e: React.FormEvent) => {
      e.preventDefault();
      setLoginLoading(true);
      setLoginError('');
      
      try {
          const res = await login({ username, password });
          if (res.success && res.token) {
              localStorage.setItem('auth_token', res.token);
              setIsAdmin(Boolean(res.is_admin));
              setIsLoggedIn(true);
          } else {
              setLoginError(res.message || '账号或密码错误');
          }
      } catch (err) {
          setLoginError(err instanceof Error ? err.message : '登录失败，请稍后重试');
      } finally {
          setLoginLoading(false);
      }
  };

  if (checkingAuth) {
      return (
          <div className="min-h-screen flex items-center justify-center bg-[#f5f6f7]">
              <div className="flex items-center gap-3 text-sm font-semibold text-gray-600">
                <Loader2 className="h-5 w-5 animate-spin text-[#b29c00]" />
                正在验证登录状态
              </div>
          </div>
      );
  }

  // Login Screen Component
  if (!isLoggedIn) {
    return (
      <div className="min-h-screen bg-[#f5f6f7] p-4 font-sans sm:p-6">
        <div className="mx-auto flex min-h-[calc(100vh-2rem)] max-w-5xl items-center justify-center sm:min-h-[calc(100vh-3rem)]">
          <div className="grid w-full overflow-hidden rounded-md border border-[#dfe2e5] bg-white shadow-sm lg:grid-cols-[1.05fr_0.95fr]">
            <div className="hidden min-h-[560px] flex-col justify-between border-r border-[#dfe2e5] bg-[#f0f1f2] p-10 lg:flex">
              <div>
                <div className="flex h-11 w-11 items-center justify-center rounded-md border border-[#e4cf00] bg-[#ffe100]">
                  <span className="text-xl font-black text-[#1f2328]">闲</span>
                </div>
                <p className="mt-6 text-xs font-bold text-[#8c7900]">Xianyu Super Butler</p>
                <h1 className="mt-2 max-w-md text-2xl font-extrabold leading-tight text-[#1f2328]">
                  闲鱼经营与自动化工作台
                </h1>
                <p className="mt-4 max-w-md text-sm leading-7 text-[#5f666e]">
                  统一处理账号、商品、订单、消息、回复和自动发货。
                </p>
              </div>
              <div className="grid grid-cols-2 gap-px overflow-hidden rounded-md border border-[#d7dade] bg-[#d7dade]">
                {['账号与商品同步', '订单与发货处理', '消息与自动回复', '通知与运行日志'].map(item => (
                  <div key={item} className="bg-white px-4 py-3 text-xs font-bold text-[#4f565e]">
                    {item}
                  </div>
                ))}
              </div>
            </div>

            <div className="flex min-h-[500px] items-center p-7 sm:p-10">
              <div className="mx-auto w-full max-w-sm animate-fade-in">
                <div className="mb-8">
                  <div className="mb-5 flex h-12 w-12 items-center justify-center rounded-md border border-[#e4cf00] bg-[#ffe100] lg:hidden">
                    <span className="text-xl font-black text-[#1f2328]">闲</span>
                  </div>
                  <h2 className="text-2xl font-extrabold text-gray-900">
                    {authMode === 'login' ? '登录管理后台' : '注册新账号'}
                  </h2>
                  <p className="mt-2 text-sm text-gray-500">
                    {authMode === 'login' ? '使用管理员账号进入工作台' : '创建账号后即可登录工作台'}
                  </p>
                </div>

                {authMode === 'login' && (
                <form onSubmit={handleLogin} className="space-y-5">
                  <div className="space-y-4">
                      <label className="block">
                          <span className="mb-1.5 block text-xs font-bold text-gray-600">管理员账号</span>
                          <div className="relative group">
                            <User className="absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400 group-focus-within:text-gray-700" />
                            <input
                                type="text"
                                placeholder="请输入账号"
                                value={username}
                                onChange={e => setUsername(e.target.value)}
                                autoComplete="username"
                                required
                                className="ios-input h-11 w-full rounded-md py-2.5 pl-10 pr-4 text-sm"
                            />
                          </div>
                      </label>
                      <label className="block">
                          <span className="mb-1.5 block text-xs font-bold text-gray-600">密码</span>
                          <div className="relative group">
                            <Lock className="absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400 group-focus-within:text-gray-700" />
                            <input
                                type="password"
                                placeholder="请输入密码"
                                value={password}
                                onChange={e => setPassword(e.target.value)}
                                autoComplete="current-password"
                                required
                                className="ios-input h-11 w-full rounded-md py-2.5 pl-10 pr-4 text-sm"
                            />
                          </div>
                      </label>
                  </div>

                  {loginNotice && (
                      <div role="status" className="flex items-center gap-2 rounded-md border border-green-200 bg-green-50 p-3 text-sm font-semibold text-green-700">
                          <CheckCircle2 className="h-4 w-4 shrink-0" /> {loginNotice}
                      </div>
                  )}

                  {loginError && (
                      <div role="alert" className="flex items-center gap-2 rounded-md border border-red-200 bg-red-50 p-3 text-sm font-semibold text-red-700">
                          <ShieldCheck className="h-4 w-4 shrink-0" /> {loginError}
                      </div>
                  )}

                  <button
                    type="submit"
                    disabled={loginLoading}
                    className="ios-btn-primary flex h-11 w-full items-center justify-center gap-2 rounded-md text-sm disabled:opacity-70"
                  >
                    {loginLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <>登录 <ArrowRight className="h-4 w-4" /></>}
                  </button>
                </form>
                )}

                {authMode === 'register' && (
                <form onSubmit={handleRegister} className="space-y-5">
                  <div className="space-y-4">
                      <label className="block">
                          <span className="mb-1.5 block text-xs font-bold text-gray-600">账号</span>
                          <div className="relative group">
                            <User className="absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400 group-focus-within:text-gray-700" />
                            <input
                                type="text"
                                placeholder="设置登录账号"
                                value={regForm.username}
                                onChange={e => setRegForm({ ...regForm, username: e.target.value })}
                                autoComplete="username"
                                required
                                className="ios-input h-11 w-full rounded-md py-2.5 pl-10 pr-4 text-sm"
                            />
                          </div>
                      </label>
                      <label className="block">
                          <span className="mb-1.5 block text-xs font-bold text-gray-600">邮箱</span>
                          <div className="relative group">
                            <Mail className="absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400 group-focus-within:text-gray-700" />
                            <input
                                type="email"
                                placeholder="用于找回账号"
                                value={regForm.email}
                                onChange={e => setRegForm({ ...regForm, email: e.target.value })}
                                autoComplete="email"
                                required
                                className="ios-input h-11 w-full rounded-md py-2.5 pl-10 pr-4 text-sm"
                            />
                          </div>
                      </label>
                      <label className="block">
                          <span className="mb-1.5 block text-xs font-bold text-gray-600">密码</span>
                          <div className="relative group">
                            <Lock className="absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400 group-focus-within:text-gray-700" />
                            <input
                                type="password"
                                placeholder="至少 6 位"
                                value={regForm.password}
                                onChange={e => setRegForm({ ...regForm, password: e.target.value })}
                                autoComplete="new-password"
                                required
                                className="ios-input h-11 w-full rounded-md py-2.5 pl-10 pr-4 text-sm"
                            />
                          </div>
                      </label>
                      {needEmailCode && (
                      <label className="block">
                          <span className="mb-1.5 block text-xs font-bold text-gray-600">邮箱验证码</span>
                          <div className="flex gap-2">
                            <div className="relative group flex-1">
                              <KeyRound className="absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400 group-focus-within:text-gray-700" />
                              <input
                                  type="text"
                                  placeholder="请输入验证码"
                                  value={regForm.code}
                                  onChange={e => setRegForm({ ...regForm, code: e.target.value })}
                                  className="ios-input h-11 w-full rounded-md py-2.5 pl-10 pr-4 text-sm"
                              />
                            </div>
                            <button
                              type="button"
                              onClick={() => void handleSendCode()}
                              disabled={codeSending || codeCountdown > 0}
                              className="ios-btn-secondary h-11 shrink-0 rounded-md px-3 text-xs font-bold disabled:opacity-60"
                            >
                              {codeCountdown > 0 ? `${codeCountdown}s` : codeSending ? '发送中' : '获取验证码'}
                            </button>
                          </div>
                      </label>
                      )}
                  </div>

                  {regNotice && (
                      <div role="status" className="flex items-center gap-2 rounded-md border border-green-200 bg-green-50 p-3 text-sm font-semibold text-green-700">
                          <CheckCircle2 className="h-4 w-4 shrink-0" /> {regNotice}
                      </div>
                  )}

                  {regError && (
                      <div role="alert" className="flex items-center gap-2 rounded-md border border-red-200 bg-red-50 p-3 text-sm font-semibold text-red-700">
                          <ShieldCheck className="h-4 w-4 shrink-0" /> {regError}
                      </div>
                  )}

                  <button
                    type="submit"
                    disabled={regLoading}
                    className="ios-btn-primary flex h-11 w-full items-center justify-center gap-2 rounded-md text-sm disabled:opacity-70"
                  >
                    {regLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <>注册 <ArrowRight className="h-4 w-4" /></>}
                  </button>
                </form>
                )}

                {allowRegister && (
                  <div className="mt-5 text-center text-xs text-gray-500">
                    {authMode === 'login' ? (
                      <>还没有账号？
                        <button
                          type="button"
                          onClick={() => { setAuthMode('register'); setLoginError(''); setLoginNotice(''); }}
                          className="ml-1 font-bold text-[#8c7900] hover:underline"
                        >
                          注册新账号
                        </button>
                      </>
                    ) : (
                      <>已有账号？
                        <button
                          type="button"
                          onClick={() => { setAuthMode('login'); setRegError(''); setRegNotice(''); }}
                          className="ml-1 font-bold text-[#8c7900] hover:underline"
                        >
                          返回登录
                        </button>
                      </>
                    )}
                  </div>
                )}

                <p className="mt-7 border-t border-gray-100 pt-5 text-xs font-medium text-gray-400">
                  闲鱼智控 · Management Console
                </p>
              </div>
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen bg-[#f5f6f7] text-[#1f2328]">
      <GlobalFeedback />
      <Sidebar 
        activeTab={activeTab} 
        setActiveTab={(tab) => {
          setActiveTab(tab);
          setMobileMenuOpen(false);
        }}
        mobileOpen={mobileMenuOpen}
        onMobileClose={() => setMobileMenuOpen(false)}
        onLogout={() => {
            localStorage.removeItem('auth_token');
            setIsAdmin(false);
            setIsLoggedIn(false);
        }} 
      />
      
      <main className="min-h-screen min-w-0 flex-1 overflow-y-auto lg:ml-[248px]">
        <header className="sticky top-0 z-20 flex h-14 items-center gap-3 border-b border-[#e4e6e8] bg-white px-4 lg:hidden">
          <button
            type="button"
            onClick={() => setMobileMenuOpen(true)}
            className="p-2 -ml-2 rounded-md hover:bg-gray-100"
            title="打开导航"
            aria-label="打开导航"
          >
            <Menu className="w-5 h-5" />
          </button>
          <div className="min-w-0">
            <p className="truncate text-sm font-bold">{pageLabels[activeTab] || '闲鱼智控'}</p>
            <p className="text-[11px] text-gray-400">闲鱼智控</p>
          </div>
        </header>
        {activeTab !== 'messages' && <AnnouncementBanner />}
        <div className={
          activeTab === 'messages'
            ? 'h-[calc(100vh-3.5rem)] lg:h-screen overflow-hidden'
            : 'mx-auto max-w-[1320px] p-4 pb-10 sm:p-6 lg:p-8'
        }>
          <section hidden={activeTab !== 'dashboard'}>
            <Suspense fallback={activeTab === 'dashboard' ? <PageLoader /> : null}><Dashboard /></Suspense>
          </section>
          <section hidden={activeTab !== 'accounts'}>
            <Suspense fallback={activeTab === 'accounts' ? <PageLoader /> : null}><AccountList /></Suspense>
          </section>
          <section hidden={activeTab !== 'items'}>
            <Suspense fallback={activeTab === 'items' ? <PageLoader /> : null}><ItemList /></Suspense>
          </section>
          <section hidden={activeTab !== 'product-automation'}>
            <Suspense fallback={activeTab === 'product-automation' ? <PageLoader /> : null}><ProductAutomation /></Suspense>
          </section>
          <section hidden={activeTab !== 'orders'}>
            <Suspense fallback={activeTab === 'orders' ? <PageLoader /> : null}><OrderList /></Suspense>
          </section>
          <section hidden={activeTab !== 'cards'}>
            <Suspense fallback={activeTab === 'cards' ? <PageLoader /> : null}><CardList /></Suspense>
          </section>
          <section hidden={activeTab !== 'auto-reply'}>
            <Suspense fallback={activeTab === 'auto-reply' ? <PageLoader /> : null}><Keywords mode="reply" /></Suspense>
          </section>
          <section hidden={activeTab !== 'ai-reply'}>
            <Suspense fallback={activeTab === 'ai-reply' ? <PageLoader /> : null}><AIReply /></Suspense>
          </section>
          <section hidden={activeTab !== 'messages'} className="h-full min-h-0">
            <Suspense fallback={activeTab === 'messages' ? <PageLoader /> : null}>
              <MessageManagement isActive={activeTab === 'messages'} />
            </Suspense>
          </section>
          <section hidden={activeTab !== 'notifications'}>
            <Suspense fallback={activeTab === 'notifications' ? <PageLoader /> : null}>
              <NotificationsAndLogs isAdmin={isAdmin} />
            </Suspense>
          </section>
          <section hidden={activeTab !== 'settings'}>
            <Suspense fallback={activeTab === 'settings' ? <PageLoader /> : null}><Settings /></Suspense>
          </section>
          <section hidden={activeTab !== 'buyer-interaction'}>
            <Suspense fallback={activeTab === 'buyer-interaction' ? <PageLoader /> : null}><BuyerInteraction /></Suspense>
          </section>
          <section hidden={activeTab !== 'about'}>
            <Suspense fallback={activeTab === 'about' ? <PageLoader /> : null}><About /></Suspense>
          </section>
        </div>
      </main>
    </div>
  );
};

export default App;
