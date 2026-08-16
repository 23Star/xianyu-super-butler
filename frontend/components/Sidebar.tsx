import React from 'react';
import {
  BellRing,
  Bot,
  Box,
  CreditCard,
  LayoutDashboard,
  ListFilter,
  LogOut,
  MessageSquare,
  Settings,
  ShoppingBag,
  Star,
  Users,
  Workflow,
  X,
  Info,
} from 'lucide-react';

interface SidebarProps {
  activeTab: string;
  setActiveTab: (tab: string) => void;
  onLogout: () => void;
  mobileOpen: boolean;
  onMobileClose: () => void;
}

const Sidebar: React.FC<SidebarProps> = ({ activeTab, setActiveTab, onLogout, mobileOpen, onMobileClose }) => {
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
        { id: 'notifications', icon: BellRing, label: '通知与日志' },
        { id: 'settings', icon: Settings, label: '系统设置' },
        { id: 'about', icon: Info, label: '关于' },
      ],
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
    <aside className={`fixed left-0 top-0 z-40 flex h-screen w-[248px] flex-col bg-white transition-transform lg:translate-x-0 ${
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
            <p className="truncate text-base font-extrabold text-[#2a2416]">闲鱼超级管家</p>
            <p className="mt-0.5 text-[11px] font-medium text-[#a89e83]">运营工作台</p>
          </div>
          <button type="button" onClick={onMobileClose} className="rounded-full p-2 hover:bg-[#fff9e8] lg:hidden" aria-label="关闭导航">
            <X className="w-5 h-5" />
          </button>
        </div>

        <nav className="min-h-0 flex-1 overflow-y-auto px-3 pb-4">
          {menuGroups.map((group, groupIndex) => (
            <div key={group.label} className={groupIndex === 0 ? '' : 'mt-5'}>
              <p className="mb-2 px-3 text-[11px] font-bold uppercase tracking-wide text-[#b8ac8e]">{group.label}</p>
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
                          : 'font-medium text-[#6e654f] hover:bg-[#fffdf0] hover:text-[#2a2416]'
                      }`}
                      style={isActive ? {
                        background: 'linear-gradient(135deg, var(--brand-300), var(--brand))',
                        boxShadow: 'var(--shadow-brand)',
                      } : undefined}
                    >
                      <Icon className={`h-[18px] w-[18px] shrink-0 ${isActive ? 'text-[#2a2416]' : 'text-[#a89e83] group-hover:text-[#6e654f]'}`} />
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
        <button
          type="button"
          onClick={onLogout}
          className="flex min-h-11 w-full items-center gap-3 rounded-xl px-3 text-[#6e654f] transition-colors hover:bg-[#fff0f0] hover:text-[#e03131]"
        >
          <LogOut className="h-[18px] w-[18px]" />
          <span className="text-sm font-medium">退出登录</span>
        </button>
      </div>
    </aside>
    </>
  );
};

export default Sidebar;
