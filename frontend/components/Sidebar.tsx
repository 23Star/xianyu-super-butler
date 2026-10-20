import React, { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import {
  BellRing,
  Bot,
  Box,
  ChevronUp,
  CreditCard,
  KeyRound,
  LayoutDashboard,
  ListFilter,
  Loader2,
  LogOut,
  MessageSquare,
  Settings,
  ShoppingBag,
  Star,
  UserCog,
  UserRound,
  Users,
  Workflow,
  X,
  Info,
} from 'lucide-react';
import ThemeToggle from './ThemeToggle';
import { changePassword, updateUsername } from '../services/api';
import { notify } from '../services/feedback';
import { validatePassword, validateUsername } from '../lib/authValidation';

interface SidebarProps {
  activeTab: string;
  setActiveTab: (tab: string) => void;
  onLogout: () => void;
  mobileOpen: boolean;
  onMobileClose: () => void;
  isAdmin?: boolean;
  /** 当前登录用户名，左下角账号区展示 */
  username: string;
  /** 改名成功后回传新用户名，App 同步登录态显示 */
  onUsernameChange?: (name: string) => void;
}

const Sidebar: React.FC<SidebarProps> = ({ activeTab, setActiveTab, onLogout, mobileOpen, onMobileClose, isAdmin = false, username, onUsernameChange }) => {
  const [accountMenuOpen, setAccountMenuOpen] = useState(false);
  // 'rename' | 'password' | null：当前打开的账号设置弹窗
  const [accountModal, setAccountModal] = useState<'rename' | 'password' | null>(null);
  const accountRef = useRef<HTMLDivElement>(null);

  // 系统级页面只对管理员开放：普通用户看不到入口，后端接口也会拒绝其访问。
  // 「通知与日志」保留：通知渠道按用户隔离（页面内系统日志已单独按权限隐藏）。
  const adminOnly = (item: { id: string }) => isAdmin || !['settings', 'users'].includes(item.id);

  // 点击账号区外部时收起弹出菜单
  useEffect(() => {
    if (!accountMenuOpen) return;
    const onDocClick = (e: MouseEvent) => {
      if (accountRef.current && !accountRef.current.contains(e.target as Node)) {
        setAccountMenuOpen(false);
      }
    };
    document.addEventListener('mousedown', onDocClick);
    return () => document.removeEventListener('mousedown', onDocClick);
  }, [accountMenuOpen]);

  const menuGroups = [
    {
      label: '经营概览',
      items: [
        { id: 'dashboard', icon: LayoutDashboard, label: '总览' },
      ],
    },
    {
      label: '闲鱼业务',
      items: [
        { id: 'accounts', icon: Users, label: '账号管理' },
        { id: 'items', icon: Box, label: '商品与发货' },
        { id: 'orders', icon: ShoppingBag, label: '订单管理' },
        { id: 'buyer-interaction', icon: Star, label: '买家互动' },
        { id: 'cards', icon: CreditCard, label: '卡密库存' },
      ],
    },
    {
      label: '客户沟通',
      items: [
        { id: 'messages', icon: ListFilter, label: '消息中心' },
        { id: 'auto-reply', icon: MessageSquare, label: '自动回复' },
        { id: 'ai-reply', icon: Bot, label: 'AI 回复' },
      ],
    },
    {
      label: '自动化',
      items: [
        { id: 'product-automation', icon: Workflow, label: '商品自动化' },
      ],
    },
    {
      label: '系统',
      items: [
        { id: 'users', icon: UserCog, label: '用户管理' },
        { id: 'notifications', icon: BellRing, label: '通知与日志' },
        { id: 'settings', icon: Settings, label: '系统设置' },
        { id: 'about', icon: Info, label: '关于' },
      ].filter(adminOnly),
    },
  ];

  return (
    <>
    {mobileOpen && (
      <button
        type="button"
        className="fixed inset-0 z-30 bg-black/40 lg:hidden"
        onClick={onMobileClose}
        aria-label="关闭导航"
      />
    )}
    <aside className={`fixed left-0 top-0 z-40 flex h-screen w-[248px] flex-col bg-[var(--surface)] transition-transform lg:translate-x-0 ${
      mobileOpen ? 'translate-x-0' : '-translate-x-full'
    }`} style={{ borderRight: '1px solid var(--border)' }}>
      <div className="flex min-h-0 flex-1 flex-col">
        {/* 品牌区：黄色渐变徽标 + 圆角，作为整站视觉锚点 */}
        <div className="flex h-[76px] shrink-0 items-center gap-3 px-5">
          <div
            className="flex h-10 w-10 items-center justify-center rounded-xl"
            style={{
              background: 'linear-gradient(140deg, var(--brand-300), var(--brand))',
              boxShadow: 'var(--shadow-brand)',
            }}
          >
            <span className="text-lg font-black text-[#2a2416]">闲</span>
          </div>
          <div className="min-w-0 flex-1">
            <p className="truncate text-base font-extrabold text-[var(--text)]">闲鱼超级管家</p>
            <p className="mt-0.5 text-[11px] font-medium text-[var(--text-soft)]">运营工作台</p>
          </div>
          <button type="button" onClick={onMobileClose} className="rounded-full p-2 hover:bg-[var(--surface-hover)] lg:hidden" aria-label="关闭导航">
            <X className="w-5 h-5" />
          </button>
        </div>

        <nav className="min-h-0 flex-1 overflow-y-auto px-3 pb-4">
          {menuGroups.map((group, groupIndex) => (
            <div key={group.label} className={groupIndex === 0 ? '' : 'mt-5'}>
              <p className="mb-2 px-3 text-[11px] font-bold uppercase tracking-wide text-[var(--text-soft)]">{group.label}</p>
              <div className="space-y-1">
                {group.items.map((item) => {
                  const Icon = item.icon;
                  const isActive = activeTab === item.id;
                  return (
                    <button
                      key={item.id}
                      type="button"
                      onClick={() => setActiveTab(item.id)}
                      className={`group flex min-h-11 w-full items-center gap-3 rounded-xl px-3 text-left transition-all ${
                        isActive
                          ? 'font-bold text-[#2a2416]'
                          : 'font-medium text-[var(--text-muted)] hover:bg-[var(--surface-hover)] hover:text-[var(--text)]'
                      }`}
                      style={isActive ? {
                        background: 'linear-gradient(135deg, var(--brand-300), var(--brand))',
                        boxShadow: 'var(--shadow-brand)',
                      } : undefined}
                    >
                      <Icon className={`h-[18px] w-[18px] shrink-0 ${isActive ? 'text-[#2a2416]' : 'text-[var(--text-soft)] group-hover:text-[var(--text-muted)]'}`} />
                      <span className="truncate text-sm">{item.label}</span>
                    </button>
                  );
                })}
              </div>
            </div>
          ))}
        </nav>
      </div>

      <div className="shrink-0 p-3" style={{ borderTop: '1px solid var(--border)' }}>
        <ThemeToggle className="mb-2" />
        {/* 账号区：点开是账号设置菜单（改用户名/改密码/退出） */}
        <div className="relative" ref={accountRef}>
          <button
            type="button"
            onClick={() => setAccountMenuOpen(v => !v)}
            aria-expanded={accountMenuOpen}
            aria-haspopup="menu"
            className="flex min-h-11 w-full items-center gap-3 rounded-xl px-3 text-left transition-colors hover:bg-[var(--surface-hover)]"
          >
            <span
              className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-xs font-black text-[#2a2416]"
              style={{ background: 'linear-gradient(140deg, var(--brand-300), var(--brand))' }}
            >
              {(username || '?').slice(0, 1).toUpperCase()}
            </span>
            <span className="min-w-0 flex-1">
              <span className="block truncate text-sm font-semibold text-[var(--text)]">{username || '未登录'}</span>
              <span className="block text-[11px] font-medium text-[var(--text-soft)]">{isAdmin ? '管理员' : '用户'}</span>
            </span>
            <ChevronUp className={`h-4 w-4 shrink-0 text-[var(--text-soft)] transition-transform ${accountMenuOpen ? '' : 'rotate-180'}`} />
          </button>

          {accountMenuOpen && (
            <div
              role="menu"
              className="absolute bottom-full left-0 right-0 mb-2 space-y-0.5 rounded-xl border bg-[var(--surface)] p-1.5 shadow-[var(--shadow-card,0_8px_24px_rgba(20,24,28,0.16))]"
              style={{ borderColor: 'var(--border)' }}
            >
              {!isAdmin && (
                <button
                  type="button"
                  role="menuitem"
                  onClick={() => { setAccountMenuOpen(false); setAccountModal('rename'); }}
                  className="flex min-h-10 w-full items-center gap-3 rounded-lg px-3 text-left text-sm font-medium text-[var(--text-muted)] transition-colors hover:bg-[var(--surface-hover)] hover:text-[var(--text)]"
                >
                  <UserRound className="h-4 w-4 shrink-0" />
                  修改用户名
                </button>
              )}
              <button
                type="button"
                role="menuitem"
                onClick={() => { setAccountMenuOpen(false); setAccountModal('password'); }}
                className="flex min-h-10 w-full items-center gap-3 rounded-lg px-3 text-left text-sm font-medium text-[var(--text-muted)] transition-colors hover:bg-[var(--surface-hover)] hover:text-[var(--text)]"
              >
                <KeyRound className="h-4 w-4 shrink-0" />
                修改密码
              </button>
              <div className="my-1" style={{ borderTop: '1px solid var(--border)' }} />
              <button
                type="button"
                role="menuitem"
                onClick={onLogout}
                className="flex min-h-10 w-full items-center gap-3 rounded-lg px-3 text-left text-sm font-medium text-[var(--text-muted)] transition-colors hover:bg-[var(--danger-soft)] hover:text-[var(--danger)]"
              >
                <LogOut className="h-4 w-4 shrink-0" />
                退出登录
              </button>
            </div>
          )}
        </div>
      </div>

      {accountModal && createPortal(
        <AccountModal
          mode={accountModal}
          isAdmin={isAdmin}
          onClose={() => setAccountModal(null)}
          onRenamed={(name) => {
            setAccountModal(null);
            onUsernameChange?.(name);
          }}
        />,
        // aside 带 transition-transform，transform 非 none 会让内部 fixed 元素
        // 相对侧边栏定位，弹窗被挤进 248px 宽的栏里；portal 到 body 躲开
        document.body,
      )}
    </aside>
    </>
  );
};

/** 账号设置弹窗：修改用户名 / 修改密码。字段校验与登录注册共用同一套规则。 */
const AccountModal: React.FC<{
  mode: 'rename' | 'password';
  isAdmin: boolean;
  onClose: () => void;
  onRenamed: (name: string) => void;
}> = ({ mode, isAdmin, onClose, onRenamed }) => {
  const [currentPassword, setCurrentPassword] = useState('');
  const [newValue, setNewValue] = useState('');
  const [confirmValue, setConfirmValue] = useState('');
  const [saving, setSaving] = useState(false);

  const isRename = mode === 'rename';

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = newValue.trim();
    if (isRename) {
      const valid = validateUsername(trimmed);
      if (!valid) { notify('用户名需 3-32 位，仅限字母、数字、下划线或短横线', 'warning'); return; }
    } else {
      const valid = validatePassword(trimmed);
      if (!valid) { notify('新密码至少 8 位，且同时包含字母和数字', 'warning'); return; }
      if (trimmed !== confirmValue) { notify('两次输入的新密码不一致', 'warning'); return; }
    }

    setSaving(true);
    try {
      const res = isRename
        ? await updateUsername(trimmed, currentPassword)
        : await changePassword(currentPassword, trimmed);
      if (res.success) {
        notify(isRename ? '用户名修改成功' : '密码修改成功，下次登录请使用新密码', 'success');
        if (isRename) onRenamed(trimmed);
        else onClose();
      } else {
        notify(res.message || '修改失败，请稍后重试', 'error');
      }
    } catch {
      notify('网络异常，修改失败', 'error');
    } finally {
      setSaving(false);
    }
  };

  const inputCls = 'ios-input h-11 w-full rounded-md px-4 text-sm';

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={saving ? undefined : onClose}>
      <form
        className="w-full max-w-sm rounded-2xl bg-[var(--surface)] p-6 shadow-[0_12px_40px_rgba(20,24,28,0.24)]"
        onClick={e => e.stopPropagation()}
        onSubmit={e => void handleSubmit(e)}
      >
        <h3 className="text-base font-extrabold text-[var(--text)]">{isRename ? '修改用户名' : '修改密码'}</h3>
        <p className="mt-1 text-xs text-[var(--text-soft)]">
          {isRename ? '用户名是登录凭证，修改后请用新用户名登录' : '修改成功后当前登录保持有效'}
        </p>

        <label className="mt-4 block">
          <span className="mb-1.5 block text-xs font-bold text-[var(--text-muted)]">当前密码</span>
          <input
            type="password"
            autoComplete="current-password"
            value={currentPassword}
            onChange={e => setCurrentPassword(e.target.value)}
            className={inputCls}
            placeholder="请输入当前密码"
            disabled={saving}
          />
        </label>

        <label className="mt-3 block">
          <span className="mb-1.5 block text-xs font-bold text-[var(--text-muted)]">{isRename ? '新用户名' : '新密码'}</span>
          <input
            type={isRename ? 'text' : 'password'}
            autoComplete={isRename ? 'username' : 'new-password'}
            value={newValue}
            onChange={e => setNewValue(e.target.value)}
            className={inputCls}
            placeholder={isRename ? '3-32 位字母/数字/下划线/短横线' : '至少 8 位，含字母和数字'}
            disabled={saving}
          />
        </label>

        {!isRename && (
          <label className="mt-3 block">
            <span className="mb-1.5 block text-xs font-bold text-[var(--text-muted)]">确认新密码</span>
            <input
              type="password"
              autoComplete="new-password"
              value={confirmValue}
              onChange={e => setConfirmValue(e.target.value)}
              className={inputCls}
              placeholder="再次输入新密码"
              disabled={saving}
            />
          </label>
        )}

        <div className="mt-6 flex gap-3">
          <button type="button" onClick={onClose} disabled={saving} className="ios-btn-secondary h-11 flex-1 rounded-md text-sm font-bold">
            取消
          </button>
          <button type="submit" disabled={saving || !currentPassword || !newValue.trim()} className="ios-btn-primary h-11 flex-1 rounded-md text-sm font-bold disabled:opacity-60">
            {saving ? <Loader2 className="mx-auto h-4 w-4 animate-spin" /> : '确认修改'}
          </button>
        </div>
      </form>
    </div>
  );
};

export default Sidebar;
