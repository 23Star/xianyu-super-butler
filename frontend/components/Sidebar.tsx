import React from 'react';
import { LayoutDashboard, Users, ShoppingBag, CreditCard, Settings, LogOut, Box, MessageSquare, Truck, X, BellRing } from 'lucide-react';

interface SidebarProps {
  activeTab: string;
  setActiveTab: (tab: string) => void;
  onLogout: () => void;
  mobileOpen: boolean;
  onMobileClose: () => void;
}

const Sidebar: React.FC<SidebarProps> = ({ activeTab, setActiveTab, onLogout, mobileOpen, onMobileClose }) => {
  const menuItems = [
    { id: 'dashboard', icon: LayoutDashboard, label: '总览' },
    { id: 'accounts', icon: Users, label: '账号' },
    { id: 'items', icon: Box, label: '商品' },
    { id: 'orders', icon: ShoppingBag, label: '订单' },
    { id: 'cards', icon: CreditCard, label: '卡密' },
    { id: 'auto-reply', icon: MessageSquare, label: '自动回复' },
    { id: 'auto-delivery', icon: Truck, label: '自动发货' },
    { id: 'notifications', icon: BellRing, label: '通知与日志' },
    { id: 'settings', icon: Settings, label: '设置' },
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
    <aside className={`w-64 h-screen fixed left-0 top-0 bg-white border-r border-gray-200 flex flex-col justify-between z-40 transition-transform lg:translate-x-0 ${
      mobileOpen ? 'translate-x-0' : '-translate-x-full'
    }`}>
      <div className="p-6">
        <div className="flex items-center gap-3 mb-8 px-2">
          <div className="w-10 h-10 bg-[#FFE815] rounded-lg flex items-center justify-center">
            <span className="text-black font-extrabold text-xl">闲</span>
          </div>
          <h1 className="text-xl font-extrabold text-gray-900 flex-1">闲鱼智控</h1>
          <button type="button" onClick={onMobileClose} className="p-2 rounded-md hover:bg-gray-100 lg:hidden" aria-label="关闭导航">
            <X className="w-5 h-5" />
          </button>
        </div>

        <nav className="space-y-2">
          {menuItems.map((item) => {
            const Icon = item.icon;
            const isActive = activeTab === item.id;
            return (
              <button
                key={item.id}
                onClick={() => setActiveTab(item.id)}
                className={`w-full flex items-center gap-3 px-4 py-3 rounded-md transition-colors group ${
                  isActive 
                    ? 'bg-[#FFE815] text-black font-bold'
                    : 'text-gray-500 hover:bg-gray-50 hover:text-gray-900'
                }`}
              >
                <Icon className={`w-5 h-5 transition-colors ${isActive ? 'text-black' : 'text-gray-400 group-hover:text-gray-600'}`} />
                <span className="text-sm tracking-wide">{item.label}</span>
              </button>
            );
          })}
        </nav>
      </div>

      <div className="p-6 border-t border-gray-50">
        <button 
          onClick={onLogout}
          className="w-full flex items-center gap-3 px-4 py-3 text-gray-500 hover:text-red-500 hover:bg-red-50 rounded-md transition-colors font-medium"
        >
          <LogOut className="w-5 h-5" />
          <span className="text-sm">退出登录</span>
        </button>
      </div>
    </aside>
    </>
  );
};

export default Sidebar;
