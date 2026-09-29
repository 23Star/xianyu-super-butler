import React, { useEffect, useState } from 'react';
import {
  KeyRound,
  Loader2,
  RefreshCw,
  ShieldCheck,
  Trash2,
  UserRound,
  Users,
} from 'lucide-react';

import { AdminUser } from '../types';
import {
  deleteAdminUser,
  getAdminUsers,
  resetAdminUserPassword,
  setAdminUserStatus,
} from '../services/api';
import { confirmAction, notify } from '../services/feedback';
import { validatePassword } from '../lib/authValidation';
import { EmptyState, PageHeader, SectionHeader } from './ui';

const formatDateTime = (value?: string) => {
  if (!value) return '-';
  const date = new Date(value.includes('T') ? value : value.replace(' ', 'T'));
  return Number.isNaN(date.getTime())
    ? value
    : date.toLocaleString('zh-CN', {
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
      });
};

const UserManagement: React.FC = () => {
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [busyUserId, setBusyUserId] = useState<number | null>(null);
  // 正在重置密码的用户：展开内联输入框，一次只处理一个
  const [resettingUserId, setResettingUserId] = useState<number | null>(null);
  const [newPassword, setNewPassword] = useState('');

  const loadUsers = async () => {
    setLoading(true);
    try {
      setUsers(await getAdminUsers());
    } catch (error) {
      notify(`加载用户列表失败：${(error as Error).message}`, 'error');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadUsers();
  }, []);

  const toggleStatus = async (user: AdminUser) => {
    if (busyUserId !== null) return;
    const disabling = user.is_active !== false;
    if (disabling && !await confirmAction(
      `禁用用户「${user.username}」？其所有在线会话将立即下线，且无法再登录。`,
      { title: '禁用用户', confirmLabel: '禁用', danger: true },
    )) return;

    setBusyUserId(user.id);
    try {
      const res = await setAdminUserStatus(user.id, !disabling);
      notify(res.message || '状态已更新', 'success');
      await loadUsers();
    } catch (error) {
      notify(`操作失败：${(error as Error).message}`, 'error');
    } finally {
      setBusyUserId(null);
    }
  };

  const submitPasswordReset = async (user: AdminUser) => {
    const [valid, reason] = validatePassword(newPassword);
    if (!valid) {
      notify(reason, 'warning');
      return;
    }
    if (busyUserId !== null) return;
    setBusyUserId(user.id);
    try {
      const res = await resetAdminUserPassword(user.id, newPassword);
      notify(res.message || '密码已重置', 'success');
      setResettingUserId(null);
      setNewPassword('');
    } catch (error) {
      notify(`重置失败：${(error as Error).message}`, 'error');
    } finally {
      setBusyUserId(null);
    }
  };

  const removeUser = async (user: AdminUser) => {
    if (busyUserId !== null) return;
    if (!await confirmAction(
      `删除用户「${user.username}」？其名下的闲鱼账号、卡密、回复规则等数据将一并删除，不可恢复。`,
      { title: '删除用户', confirmLabel: '删除', danger: true },
    )) return;

    setBusyUserId(user.id);
    try {
      const res = await deleteAdminUser(user.id);
      notify(res.message || '用户已删除', 'success');
      await loadUsers();
    } catch (error) {
      notify(`删除失败：${(error as Error).message}`, 'error');
    } finally {
      setBusyUserId(null);
    }
  };

  return (
    <div className="page-stack">
      <PageHeader
        title="用户管理"
        description="管理注册用户与登录权限。普通用户仅能操作分配给其名下的账号数据。"
        icon={Users}
        actions={
          <button
            type="button"
            onClick={() => void loadUsers()}
            className="ios-btn-secondary flex items-center gap-2 rounded-md px-4 py-2.5 text-sm"
          >
            <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
            刷新
          </button>
        }
      />

      <section className="section-panel">
        <SectionHeader
          title="权限说明"
          icon={ShieldCheck}
        />
        <div className="grid gap-3 p-4 sm:grid-cols-2">
          <div className="rounded-lg border border-[var(--border)] bg-[var(--surface-subtle)] p-3.5">
            <p className="flex items-center gap-2 text-sm font-bold text-[var(--text)]">
              <ShieldCheck className="h-4 w-4 text-[#8a6300]" />
              管理员（admin）
            </p>
            <p className="mt-1.5 text-xs leading-5 text-[var(--text-muted)]">
              拥有全部权限：系统设置、通知与系统日志、用户管理，以及所有闲鱼账号和数据。
            </p>
          </div>
          <div className="rounded-lg border border-[var(--border)] bg-[var(--surface-subtle)] p-3.5">
            <p className="flex items-center gap-2 text-sm font-bold text-[var(--text)]">
              <UserRound className="h-4 w-4 text-[var(--text-soft)]" />
              普通用户
            </p>
            <p className="mt-1.5 text-xs leading-5 text-[var(--text-muted)]">
              只能看到并操作自己名下的闲鱼账号、商品、订单与消息；侧栏不显示系统设置与用户管理，接口层也会拒绝其访问。
            </p>
          </div>
        </div>
      </section>

      <section className="section-panel">
        <SectionHeader
          title="用户列表"
          description={`共 ${users.length} 个用户`}
          icon={Users}
        />
        <div className="divide-y divide-[var(--border)]">
          {users.map((user) => {
            const isBuiltinAdmin = user.username === 'admin';
            const disabled = user.is_active === false;
            const busy = busyUserId === user.id;
            const resetting = resettingUserId === user.id;
            return (
              <div key={user.id} className="p-4">
                <div className="flex flex-wrap items-center gap-3">
                  <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-[var(--brand)] text-sm font-black text-[#2a2416]">
                    {user.username.slice(0, 1).toUpperCase()}
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <p className="text-sm font-bold text-[var(--text)]">{user.username}</p>
                      {isBuiltinAdmin && (
                        <span className="rounded-full bg-[var(--brand)] px-2 py-0.5 text-[10px] font-bold text-[#2a2416]">
                          内置管理员
                        </span>
                      )}
                      <span className={`rounded-full px-2 py-0.5 text-[10px] font-bold ${
                        disabled
                          ? 'bg-red-50 text-red-600'
                          : 'bg-emerald-50 text-emerald-600'
                      }`}>
                        {disabled ? '已禁用' : '正常'}
                      </span>
                    </div>
                    <p className="mt-0.5 truncate text-xs text-[var(--text-muted)]">{user.email}</p>
                    <p className="mt-1 text-[11px] text-[var(--text-soft)]">
                      {user.cookie_count ?? 0} 个闲鱼账号 · {user.card_count ?? 0} 张卡密 · 注册于 {formatDateTime(user.created_at)}
                    </p>
                  </div>

                  {!isBuiltinAdmin && (
                    <div className="flex shrink-0 items-center gap-2">
                      <button
                        type="button"
                        onClick={() => void toggleStatus(user)}
                        disabled={busy}
                        className={disabled
                          ? 'rounded-md bg-emerald-50 px-3 py-2 text-xs font-bold text-emerald-700 hover:bg-emerald-100 disabled:opacity-50'
                          : 'rounded-md bg-amber-50 px-3 py-2 text-xs font-bold text-amber-700 hover:bg-amber-100 disabled:opacity-50'}
                      >
                        {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : (disabled ? '启用' : '禁用')}
                      </button>
                      <button
                        type="button"
                        onClick={() => {
                          setResettingUserId(resetting ? null : user.id);
                          setNewPassword('');
                        }}
                        disabled={busy}
                        title="重置密码"
                        className="flex h-9 w-9 items-center justify-center rounded-md bg-[var(--surface-subtle)] text-[var(--text-muted)] hover:bg-[var(--surface-hover)] hover:text-[var(--text)] disabled:opacity-50"
                      >
                        <KeyRound className="h-4 w-4" />
                      </button>
                      <button
                        type="button"
                        onClick={() => void removeUser(user)}
                        disabled={busy}
                        title="删除用户"
                        className="flex h-9 w-9 items-center justify-center rounded-md bg-red-50 text-red-600 hover:bg-red-100 disabled:opacity-50"
                      >
                        <Trash2 className="h-4 w-4" />
                      </button>
                    </div>
                  )}
                </div>

                {resetting && !isBuiltinAdmin && (
                  <div className="mt-3 flex flex-wrap items-center gap-2 rounded-lg border border-[var(--border)] bg-[var(--surface-subtle)] p-3">
                    <input
                      type="password"
                      value={newPassword}
                      onChange={(event) => setNewPassword(event.target.value)}
                      placeholder="新密码：至少 8 位，含字母和数字"
                      autoComplete="new-password"
                      className="ios-input h-10 min-w-0 flex-1 rounded-md px-3 text-sm"
                    />
                    <button
                      type="button"
                      onClick={() => void submitPasswordReset(user)}
                      disabled={busy}
                      className="ios-btn-primary h-10 rounded-md px-4 text-sm disabled:opacity-50"
                    >
                      {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : '确认重置'}
                    </button>
                    <button
                      type="button"
                      onClick={() => { setResettingUserId(null); setNewPassword(''); }}
                      className="ios-btn-secondary h-10 rounded-md px-4 text-sm"
                    >
                      取消
                    </button>
                  </div>
                )}
              </div>
            );
          })}
          {!loading && users.length === 0 && (
            <EmptyState
              compact
              title="暂无用户"
              description="开放注册后，新注册的用户会出现在这里。"
              icon={Users}
            />
          )}
          {loading && (
            <div className="flex justify-center py-12">
              <Loader2 className="h-6 w-6 animate-spin text-[#d6b600]" />
            </div>
          )}
        </div>
      </section>
    </div>
  );
};

export default UserManagement;
