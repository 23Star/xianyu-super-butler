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
    <aside className={`fixed left-0 top-0 z-40 flex h-screen w-[248px] flex-col border-r border-[#e4e6e8] bg-white transition-transform lg:translate-x-0 ${
      mobileOpen ? 'translate-x-0' : '-translate-x-full'
    }`}>
      <div className="flex min-h-0 flex-1 flex-col">
        <div className="flex h-[72px] shrink-0 items-center gap-3 border-b border-[#eef0f2] px-5">
          <div className="flex h-9 w-9 items-center justify-center rounded-md border border-[#e4cf00] bg-[#ffe100]">
            <span className="text-lg font-black text-[#1f2328]">闲</span>
          </div>
          <div className="min-w-0 flex-1">
            <p className="truncate text-base font-extrabold text-[#1f2328]">闲鱼智控</p>
            <p className="mt-0.5 text-[11px] font-medium text-[#939aa2]">运营工作台</p>
          </div>
          <button type="button" onClick={onMobileClose} className="p-2 rounded-md hover:bg-gray-100 lg:hidden" aria-label="关闭导航">
            <X className="w-5 h-5" />
          </button>
        </div>

        <nav className="min-h-0 flex-1 overflow-y-auto px-3 py-4">
          {menuGroups.map((group, groupIndex) => (
            <div key={group.label} className={groupIndex === 0 ? '' : 'mt-5'}>
              <p className="mb-1.5 px-3 text-[11px] font-bold text-[#9aa1a8]">{group.label}</p>
              <div className="space-y-1">
                {group.items.map((item) => {
                  const Icon = item.icon;
                  const isActive = activeTab === item.id;
                  return (
                    <button
                      key={item.id}
                      type="button"
                      onClick={() => setActiveTab(item.id)}
                      className={`group flex min-h-10 w-full items-center gap-3 rounded-md px-3 text-left transition-colors ${
                        isActive
                          ? 'bg-[#ffe100] font-bold text-[#1f2328]'
                          : 'font-medium text-[#60676f] hover:bg-[#f4f5f6] hover:text-[#1f2328]'
                      }`}
                    >
                      <Icon className={`h-[18px] w-[18px] shrink-0 ${isActive ? 'text-[#1f2328]' : 'text-[#8d949c] group-hover:text-[#60676f]'}`} />
                      <span className="truncate text-sm">{item.label}</span>
                    </button>
                  );
                })}
              </div>
            </div>
          ))}
        </nav>
      </div>

      <div className="shrink-0 border-t border-[#eef0f2] p-3">
        <button 
          type="button"
          onClick={onLogout}
          className="flex min-h-10 w-full items-center gap-3 rounded-md px-3 text-[#6d747c] transition-colors hover:bg-red-50 hover:text-red-600"
        >
          <LogOut className="h-[18px] w-[18px]" />
          <span className="text-sm">退出登录</span>
        </button>
      </div>
    </aside>
    </>
  );
};

export default Sidebar;
