import React, { Suspense, lazy, useState, useEffect } from 'react';
import Sidebar from './components/Sidebar';
import { login, verifyToken } from './services/api';
import { ShieldCheck, ArrowRight, Loader2, User, Lock, Menu } from 'lucide-react';

const Dashboard = lazy(() => import('./components/Dashboard'));
const AccountList = lazy(() => import('./components/AccountList'));
const OrderList = lazy(() => import('./components/OrderList'));
const CardList = lazy(() => import('./components/CardList'));
const ItemList = lazy(() => import('./components/ItemList'));
const Settings = lazy(() => import('./components/Settings'));
const Keywords = lazy(() => import('./components/Keywords'));

const PageLoader = () => (
  <div className="py-24 flex justify-center">
    <Loader2 className="w-8 h-8 text-yellow-500 animate-spin" />
  </div>
);

const App: React.FC = () => {
  const [isLoggedIn, setIsLoggedIn] = useState(false);
  const [activeTab, setActiveTab] = useState('dashboard');
  const [checkingAuth, setCheckingAuth] = useState(true);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [loginLoading, setLoginLoading] = useState(false);
  const [loginError, setLoginError] = useState('');
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

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

  const handleLogin = async (e: React.FormEvent) => {
      e.preventDefault();
      setLoginLoading(true);
      setLoginError('');
      
      try {
          const res = await login({ username, password });
          if (res.success && res.token) {
              localStorage.setItem('auth_token', res.token);
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
          <div className="min-h-screen flex items-center justify-center bg-[#f5f5f7]">
              <Loader2 className="w-8 h-8 text-[#FFE815] animate-spin" />
          </div>
      );
  }

  // Login Screen Component
  if (!isLoggedIn) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-[#F4F5F7] p-4 font-sans">
        <div className="bg-white p-7 md:p-10 rounded-lg shadow-sm w-full max-w-md border border-gray-200 animate-fade-in">
          
          {/* Header with Logo */}
          <div className="text-center mb-10">
             <div className="w-16 h-16 bg-[#FFE815] rounded-lg flex items-center justify-center mx-auto mb-5">
                <span className="text-black font-extrabold text-3xl">闲</span>
             </div>
             <h1 className="text-2xl font-extrabold text-gray-900 mb-2">闲鱼智控</h1>
             <p className="text-gray-500">登录后管理账号、订单与自动发货</p>
          </div>
          
          <form onSubmit={handleLogin} className="space-y-5">
            <div className="space-y-4">
                <div className="relative group">
                    <User className="absolute left-5 top-1/2 -translate-y-1/2 w-5 h-5 text-gray-400 group-focus-within:text-black transition-colors" />
                    <input 
                        type="text" 
                        placeholder="管理员账号" 
                        value={username}
                        onChange={e => setUsername(e.target.value)}
                        autoComplete="username"
                        required
                        className="w-full ios-input pl-14 pr-5 py-4 rounded-lg text-base h-14"
                    />
                </div>
                <div className="relative group">
                    <Lock className="absolute left-5 top-1/2 -translate-y-1/2 w-5 h-5 text-gray-400 group-focus-within:text-black transition-colors" />
                    <input 
                        type="password" 
                        placeholder="密码" 
                        value={password}
                        onChange={e => setPassword(e.target.value)}
                        autoComplete="current-password"
                        required
                        className="w-full ios-input pl-14 pr-5 py-4 rounded-lg text-base h-14"
                    />
                </div>
            </div>
            
            {loginError && (
                <div role="alert" className="p-3 rounded-lg bg-red-50 text-red-600 text-sm text-center font-semibold flex items-center justify-center gap-2">
                    <ShieldCheck className="w-4 h-4" /> {loginError}
                </div>
            )}

            <button 
              type="submit" 
              disabled={loginLoading}
              className="w-full ios-btn-primary h-14 rounded-lg text-base mt-2 flex items-center justify-center gap-2 group disabled:opacity-70"
            >
              {loginLoading ? <Loader2 className="w-5 h-5 animate-spin" /> : <>立即登录 <ArrowRight className="w-5 h-5 group-hover:translate-x-1 transition-transform" /></>}
            </button>
          </form>
          
          <div className="mt-7 pt-5 border-t border-gray-100">
             <div className="text-center">
                 <span className="text-xs text-gray-400 font-medium tracking-widest uppercase">
                    Xianyu Auto-Dispatch Pro v2.5
                 </span>
             </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen bg-[#F4F5F7] text-[#111]">
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
            setIsLoggedIn(false);
        }} 
      />
      
      <main className="flex-1 lg:ml-64 min-w-0 overflow-y-auto min-h-screen">
        <header className="lg:hidden sticky top-0 z-20 h-14 bg-white border-b border-gray-200 flex items-center gap-3 px-4">
          <button
            type="button"
            onClick={() => setMobileMenuOpen(true)}
            className="p-2 -ml-2 rounded-md hover:bg-gray-100"
            title="打开导航"
            aria-label="打开导航"
          >
            <Menu className="w-5 h-5" />
          </button>
          <span className="font-bold">闲鱼智控</span>
        </header>
        <div className="max-w-[1400px] mx-auto p-4 sm:p-6 lg:p-8 pb-10">
          <section hidden={activeTab !== 'dashboard'}>
            <Suspense fallback={activeTab === 'dashboard' ? <PageLoader /> : null}><Dashboard /></Suspense>
          </section>
          <section hidden={activeTab !== 'accounts'}>
            <Suspense fallback={activeTab === 'accounts' ? <PageLoader /> : null}><AccountList /></Suspense>
          </section>
          <section hidden={activeTab !== 'items'}>
            <Suspense fallback={activeTab === 'items' ? <PageLoader /> : null}><ItemList /></Suspense>
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
          <section hidden={activeTab !== 'auto-delivery'}>
            <Suspense fallback={activeTab === 'auto-delivery' ? <PageLoader /> : null}><Keywords mode="delivery" /></Suspense>
          </section>
          <section hidden={activeTab !== 'settings'}>
            <Suspense fallback={activeTab === 'settings' ? <PageLoader /> : null}><Settings /></Suspense>
          </section>
        </div>
      </main>
    </div>
  );
};

export default App;
