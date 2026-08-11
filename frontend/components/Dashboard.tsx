import React, { useEffect, useState } from 'react';
import { AdminStats, OrderAnalytics, Order, OrderStatus, Item } from '../types';
import { getAdminStats, getOrderAnalytics, getValidOrders, getItems } from '../services/api';
import { TrendingUp, Users, ShoppingCart, AlertCircle, DollarSign, Activity, Package, ArrowUpRight, Calendar, X, BarChart3, PackageCheck, ExternalLink, Eye, Edit, RefreshCw } from 'lucide-react';
import { XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, BarChart, Bar, PieChart, Pie, Cell, Legend } from 'recharts';
import { EmptyState, PageHeader, PageLoading, PageTabs, SectionHeader } from './ui';

// 状态徽章组件
const StatusBadge: React.FC<{ status: OrderStatus }> = ({ status }) => {
  const styles = {
    processing: 'bg-yellow-100 text-yellow-800',
    pending_ship: 'bg-[#FFE815] text-black',
    shipped: 'bg-blue-100 text-blue-700',
    completed: 'bg-green-100 text-green-700',
    cancelled: 'bg-gray-100 text-gray-500',
    refunding: 'bg-red-100 text-red-600',
  };

  const labels = {
    processing: '处理中',
    pending_ship: '待发货',
    shipped: '已发货',
    completed: '已完成',
    cancelled: '已取消',
    refunding: '退款中',
  };

  return (
    <span className={`status-badge ${styles[status] || styles.cancelled}`}>
      {labels[status] || status}
    </span>
  );
};

const StatCard: React.FC<{ title: string; value: string | number; icon: React.ElementType; colorClass: string; trend?: string }> = ({ title, value, icon: Icon, colorClass, trend }) => (
  <div className="metric-card">
    <div className="flex items-start justify-between gap-3">
      <span className={`flex h-9 w-9 items-center justify-center rounded-md ${colorClass}`}>
        <Icon className="h-4 w-4 text-white" />
      </span>
      {trend && <span className="status-badge status-badge-success flex items-center gap-1">
        <TrendingUp className="w-3 h-3" /> {trend}
      </span>}
    </div>
    <p className="metric-card__value">{value}</p>
    <p className="metric-card__label mt-1">{title}</p>
  </div>
);

type TimeRange = 'today' | 'yesterday' | '3days' | '7days' | '30days' | 'custom';

const Dashboard: React.FC = () => {
  const [stats, setStats] = useState<AdminStats | null>(null);
  const [analytics, setAnalytics] = useState<OrderAnalytics | null>(null);
  const [timeRange, setTimeRange] = useState<TimeRange>('7days');
  const [customStartDate, setCustomStartDate] = useState('');
  const [customEndDate, setCustomEndDate] = useState('');
  const [previousAnalytics, setPreviousAnalytics] = useState<OrderAnalytics | null>(null); // 用于计算趋势
  const [dashboardLoading, setDashboardLoading] = useState(true);
  const [dashboardError, setDashboardError] = useState<string | null>(null);
  const [reloadToken, setReloadToken] = useState(0);

  // 搜索词
  const [searchTerm, setSearchTerm] = useState('');
  // 参与统计的订单列表
  const [validOrders, setValidOrders] = useState<Order[]>([]);
  const [ordersLoading, setOrdersLoading] = useState(false);
  // 商品列表
  const [items, setItems] = useState<Item[]>([]);
  const [itemNames, setItemNames] = useState<Record<string, string>>({});

  // 颜色配置
  const COLORS = ['#FFE815', '#3B82F6', '#10B981', '#F59E0B', '#8B5CF6'];

  const loadAnalytics = async (range: TimeRange) => {
    // 使用本地时间而不是UTC时间
    const now = new Date();
    const year = now.getFullYear();
    const month = String(now.getMonth() + 1).padStart(2, '0');
    const day = String(now.getDate()).padStart(2, '0');
    const todayStr = `${year}-${month}-${day}`;

    let params: { start_date: string; end_date: string };

    switch (range) {
      case 'today':
        // 今天：从今天00:00:00到今天23:59:59
        params = {
          start_date: todayStr,
          end_date: todayStr
        };
        break;
      case 'yesterday':
        // 昨天：从昨天00:00:00到昨天23:59:59
        const yesterday = new Date(now);
        yesterday.setDate(yesterday.getDate() - 1);
        const yYear = yesterday.getFullYear();
        const yMonth = String(yesterday.getMonth() + 1).padStart(2, '0');
        const yDay = String(yesterday.getDate()).padStart(2, '0');
        const yesterdayStr = `${yYear}-${yMonth}-${yDay}`;
        params = {
          start_date: yesterdayStr,
          end_date: yesterdayStr
        };
        break;
      case '3days':
        // 3天：从3天前到今天
        const threeDaysAgo = new Date(now);
        threeDaysAgo.setDate(threeDaysAgo.getDate() - 3);
        const tdYear = threeDaysAgo.getFullYear();
        const tdMonth = String(threeDaysAgo.getMonth() + 1).padStart(2, '0');
        const tdDay = String(threeDaysAgo.getDate()).padStart(2, '0');
        params = {
          start_date: `${tdYear}-${tdMonth}-${tdDay}`,
          end_date: todayStr
        };
        break;
      case '7days':
        // 7天：从7天前到今天
        const sevenDaysAgo = new Date(now);
        sevenDaysAgo.setDate(sevenDaysAgo.getDate() - 7);
        const sdYear = sevenDaysAgo.getFullYear();
        const sdMonth = String(sevenDaysAgo.getMonth() + 1).padStart(2, '0');
        const sdDay = String(sevenDaysAgo.getDate()).padStart(2, '0');
        params = {
          start_date: `${sdYear}-${sdMonth}-${sdDay}`,
          end_date: todayStr
        };
        break;
      case '30days':
        // 30天：从30天前到今天
        const thirtyDaysAgo = new Date(now);
        thirtyDaysAgo.setDate(thirtyDaysAgo.getDate() - 30);
        const tdYear2 = thirtyDaysAgo.getFullYear();
        const tdMonth2 = String(thirtyDaysAgo.getMonth() + 1).padStart(2, '0');
        const tdDay2 = String(thirtyDaysAgo.getDate()).padStart(2, '0');
        params = {
          start_date: `${tdYear2}-${tdMonth2}-${tdDay2}`,
          end_date: todayStr
        };
        break;
      case 'custom':
        // 自定义范围
        if (customStartDate && customEndDate) {
          params = {
            start_date: customStartDate,
            end_date: customEndDate
          };
        } else {
          // 默认7天
          const defaultDaysAgo = new Date(now);
          defaultDaysAgo.setDate(defaultDaysAgo.getDate() - 7);
          const ddYear = defaultDaysAgo.getFullYear();
          const ddMonth = String(defaultDaysAgo.getMonth() + 1).padStart(2, '0');
          const ddDay = String(defaultDaysAgo.getDate()).padStart(2, '0');
          params = {
            start_date: `${ddYear}-${ddMonth}-${ddDay}`,
            end_date: todayStr
          };
        }
        break;
      default:
        // 默认7天
        const defaultStart = new Date(now);
        defaultStart.setDate(defaultStart.getDate() - 7);
        const dsYear = defaultStart.getFullYear();
        const dsMonth = String(defaultStart.getMonth() + 1).padStart(2, '0');
        const dsDay = String(defaultStart.getDate()).padStart(2, '0');
        params = {
          start_date: `${dsYear}-${dsMonth}-${dsDay}`,
          end_date: todayStr
        };
    }

    // 同时获取上一个周期的数据用于趋势对比
    const previousParams = getPreviousPeriodParams(range, now);
    const previousRequest = previousParams
      ? getOrderAnalytics(previousParams).catch(error => {
          console.error('加载上期订单分析失败:', error);
          return null;
        })
      : Promise.resolve(null);

    const [currentAnalytics, previousPeriodAnalytics] = await Promise.all([
      getOrderAnalytics(params),
      previousRequest,
    ]);
    setAnalytics(currentAnalytics);
    setPreviousAnalytics(previousPeriodAnalytics);
  };

  // 获取上一个时间段的参数
  const getPreviousPeriodParams = (range: TimeRange, now: Date) => {
    const year = now.getFullYear();
    const month = String(now.getMonth() + 1).padStart(2, '0');
    const day = String(now.getDate()).padStart(2, '0');

    switch (range) {
      case 'today':
        // 今天对比昨天
        const yesterday = new Date(now);
        yesterday.setDate(yesterday.getDate() - 1);
        const yYear = yesterday.getFullYear();
        const yMonth = String(yesterday.getMonth() + 1).padStart(2, '0');
        const yDay = String(yesterday.getDate()).padStart(2, '0');
        return {
          start_date: `${yYear}-${yMonth}-${yDay}`,
          end_date: `${yYear}-${yMonth}-${yDay}`
        };
      case 'yesterday':
        // 昨天对比前天
        const dayBefore = new Date(now);
        dayBefore.setDate(dayBefore.getDate() - 2);
        const dbYear = dayBefore.getFullYear();
        const dbMonth = String(dayBefore.getMonth() + 1).padStart(2, '0');
        const dbDay = String(dayBefore.getDate()).padStart(2, '0');
        return {
          start_date: `${dbYear}-${dbMonth}-${dbDay}`,
          end_date: `${dbYear}-${dbMonth}-${dbDay}`
        };
      case '7days':
        // 7天对比上一个7天
        const prev7DaysEnd = new Date(now);
        prev7DaysEnd.setDate(prev7DaysEnd.getDate() - 7);
        const prev7DaysStart = new Date(prev7DaysEnd);
        prev7DaysStart.setDate(prev7DaysStart.getDate() - 7);
        return {
          start_date: `${prev7DaysStart.getFullYear()}-${String(prev7DaysStart.getMonth() + 1).padStart(2, '0')}-${String(prev7DaysStart.getDate()).padStart(2, '0')}`,
          end_date: `${prev7DaysEnd.getFullYear()}-${String(prev7DaysEnd.getMonth() + 1).padStart(2, '0')}-${String(prev7DaysEnd.getDate()).padStart(2, '0')}`
        };
      case '30days':
        // 30天对比上一个30天
        const prev30DaysEnd = new Date(now);
        prev30DaysEnd.setDate(prev30DaysEnd.getDate() - 30);
        const prev30DaysStart = new Date(prev30DaysEnd);
        prev30DaysStart.setDate(prev30DaysStart.getDate() - 30);
        return {
          start_date: `${prev30DaysStart.getFullYear()}-${String(prev30DaysStart.getMonth() + 1).padStart(2, '0')}-${String(prev30DaysStart.getDate()).padStart(2, '0')}`,
          end_date: `${prev30DaysEnd.getFullYear()}-${String(prev30DaysEnd.getMonth() + 1).padStart(2, '0')}-${String(prev30DaysEnd.getDate()).padStart(2, '0')}`
        };
      default:
        return null;
    }
  };

  // 计算趋势百分比
  const getTrendPercent = () => {
    if (!analytics || !previousAnalytics) return null;

    const currentAmount = analytics.revenue_stats.total_amount;
    const previousAmount = previousAnalytics.revenue_stats.total_amount;

    if (previousAmount === 0) {
      return currentAmount > 0 ? '+100%' : '0%';
    }

    const percent = ((currentAmount - previousAmount) / previousAmount) * 100;
    const sign = percent >= 0 ? '+' : '';
    return `${sign}${percent.toFixed(1)}%`;
  };

  useEffect(() => {
    let cancelled = false;

    const loadDashboard = async () => {
      setDashboardLoading(true);
      setDashboardError(null);

      try {
        const [statsData, itemData] = await Promise.all([
          getAdminStats(),
          getItems(),
          loadAnalytics(timeRange),
        ]);

        if (cancelled) return;

        setStats(statsData);
        setItems(itemData);

        const nameMap: Record<string, string> = {};
        itemData.forEach(item => {
          nameMap[item.item_id] = item.item_title || item.item_id;
        });
        setItemNames(nameMap);
      } catch (error) {
        if (cancelled) return;
        console.error('加载仪表盘失败:', error);
        setDashboardError(error instanceof Error ? error.message : '仪表盘数据加载失败');
      } finally {
        if (!cancelled) setDashboardLoading(false);
      }
    };

    void loadDashboard();
    return () => {
      cancelled = true;
    };
  }, [timeRange, reloadToken]);

  // 加载订单列表
  useEffect(() => {
    const { startDate, endDate } = getDatesForRange(timeRange);

    // 获取参与统计的订单列表
    setOrdersLoading(true);
    getValidOrders({ start_date: startDate, end_date: endDate })
      .then(orders => {
        setValidOrders(orders);
      })
      .catch(console.error)
      .finally(() => setOrdersLoading(false));
  }, [timeRange]);

  // 辅助函数：获取时间范围的日期
  const getDatesForRange = (range: TimeRange) => {
    const now = new Date();
    const endDate = now.toISOString().split('T')[0];
    let startDate = endDate;

    if (range === '7days') {
      const sevenDaysAgo = new Date(now);
      sevenDaysAgo.setDate(sevenDaysAgo.getDate() - 7);
      startDate = sevenDaysAgo.toISOString().split('T')[0];
    } else if (range === '30days') {
      const thirtyDaysAgo = new Date(now);
      thirtyDaysAgo.setDate(thirtyDaysAgo.getDate() - 30);
      startDate = thirtyDaysAgo.toISOString().split('T')[0];
    }
    // 其他范围类似处理...

    return { startDate, endDate };
  };

  if (dashboardLoading) {
    return <PageLoading label="正在汇总经营数据" />;
  }

  if (dashboardError || !stats || !analytics) {
    return (
      <div className="p-4 sm:p-8">
        <div className="section-panel mx-auto max-w-xl border-red-200 bg-red-50 p-5">
          <div className="flex items-start gap-3">
            <AlertCircle className="w-5 h-5 text-red-600 mt-0.5 shrink-0" />
            <div className="flex-1">
              <h2 className="font-bold text-gray-900">仪表盘加载失败</h2>
              <p className="text-sm text-gray-600 mt-1">{dashboardError || '服务器未返回完整数据'}</p>
              <button
                type="button"
                onClick={() => setReloadToken(value => value + 1)}
                className="ios-btn-secondary mt-4 inline-flex items-center gap-2 rounded-md px-4 py-2 text-sm"
              >
                <RefreshCw className="w-4 h-4" />
                重试
              </button>
            </div>
          </div>
        </div>
      </div>
    );
  }

  // 趋势图按日期正序展示，后端返回的是倒序
  const chartData = (analytics.daily_stats ? [...analytics.daily_stats].reverse() : [])
    .map(d => ({
      name: d.date.slice(5), // MM-DD
      amount: d.amount,
      confirmed: d.confirmed_amount ?? 0,
      refunded: d.refunded_amount ?? 0,
      orders: d.order_count,
      avgAmount: d.order_count > 0 ? (d.amount / d.order_count).toFixed(2) : 0
    }));

  // 计算图表数据（在渲染时直接计算）
  const itemStats = analytics.item_stats || [];
  // 订单数用全量口径，和订单页的数字保持一致
  const totalOrders = analytics.revenue_stats.all_orders ?? analytics.revenue_stats.total_orders ?? 0;
  const totalAmount = analytics.revenue_stats.total_amount || 0;

  // 1. 商品销量排行：按订单数量排序
  const productSalesData = itemStats.length > 0 ? itemStats
    .map(item => ({
      name: (itemNames[item.item_id] || item.item_id).length > 12
        ? (itemNames[item.item_id] || item.item_id).substring(0, 12) + '...'
        : (itemNames[item.item_id] || item.item_id),
      sales: item.order_count
    }))
    .sort((a, b) => b.sales - a.sales)
    .slice(0, 10) : [];

  // 2. 商品下单占比：每个商品的订单数占总订单数的百分比
  const sourceDataData = itemStats.length > 0 ? itemStats
    .map(item => ({
      name: (itemNames[item.item_id] || item.item_id).length > 10
        ? (itemNames[item.item_id] || item.item_id).substring(0, 10) + '...'
        : (itemNames[item.item_id] || item.item_id),
      value: item.order_count,
      percent: totalOrders > 0 ? (item.order_count / totalOrders) * 100 : 0
    }))
    .sort((a, b) => b.value - a.value)
    .slice(0, 6)
    .map((item, index) => ({
      ...item,
      color: COLORS[index % COLORS.length]
    })) : [];

  // 3. 商品金额分析：按金额排序，取前5
  const categoryDataData = itemStats.length > 0 ? itemStats
    .map(item => ({
      name: (itemNames[item.item_id] || item.item_id).length > 12
        ? (itemNames[item.item_id] || item.item_id).substring(0, 12) + '...'
        : (itemNames[item.item_id] || item.item_id),
      value: item.total_amount,
      orderCount: item.order_count,
      percentage: totalAmount > 0
        ? (item.total_amount / totalAmount) * 100
        : 0
    }))
    .sort((a, b) => b.value - a.value)
    .slice(0, 5)
    .map((item, index) => ({
      ...item,
      color: COLORS[index % COLORS.length],
      percentage: item.percentage.toFixed(1)
    })) : [];

  const timeRangeOptions = [
    { key: 'today' as TimeRange, label: '今天' },
    { key: 'yesterday' as TimeRange, label: '昨天' },
    { key: '3days' as TimeRange, label: '三天内' },
    { key: '7days' as TimeRange, label: '7天内' },
    { key: '30days' as TimeRange, label: '一个月内' },
    { key: 'custom' as TimeRange, label: '自定义' },
  ];

  return (
    <div className="page-stack animate-fade-in">
      <PageHeader
        title="运营概览"
        description="汇总账号、订单、营收和库存数据，快速判断当前经营状态。"
        icon={BarChart3}
        badge={(
          <span className="status-badge status-badge-success flex items-center gap-1.5">
            <span className="h-1.5 w-1.5 rounded-full bg-green-600" />
            系统运行中
          </span>
        )}
      />

      {/* Time Range Selector */}
      <div className="toolbar">
        <PageTabs
          value={timeRange}
          onChange={setTimeRange}
          items={timeRangeOptions.map(option => ({ id: option.key, label: option.label }))}
          ariaLabel="统计时间范围"
        />
        {timeRange === 'custom' && (
          <div className="toolbar__group">
            <input
              type="date"
              value={customStartDate}
              onChange={(e) => setCustomStartDate(e.target.value)}
              className="ios-input rounded-md px-3 py-2 text-sm"
            />
            <span className="self-center text-gray-400">-</span>
            <input
              type="date"
              value={customEndDate}
              onChange={(e) => setCustomEndDate(e.target.value)}
              className="ios-input rounded-md px-3 py-2 text-sm"
            />
            <button
              onClick={() => setReloadToken(value => value + 1)}
              className="ios-btn-secondary rounded-md px-4 py-2 text-sm"
            >
              应用
            </button>
          </div>
        )}
      </div>

      {/* Stats Grid */}
      <div className="metric-grid">
        <StatCard
          title="有效成交额 (CNY)"
          value={`¥${analytics.revenue_stats.total_amount.toLocaleString('zh-CN', { minimumFractionDigits: 2 })}`}
          icon={DollarSign}
          colorClass="bg-yellow-400"
          trend={getTrendPercent() || undefined}
        />
        <StatCard
          title="已到账 (CNY)"
          value={`¥${(analytics.revenue_stats.confirmed_amount ?? 0).toLocaleString('zh-CN', { minimumFractionDigits: 2 })}`}
          icon={DollarSign}
          colorClass="bg-green-500"
        />
        <StatCard
          title="已退款 (CNY)"
          value={`¥${(analytics.revenue_stats.refunded_amount ?? 0).toLocaleString('zh-CN', { minimumFractionDigits: 2 })}`}
          icon={DollarSign}
          colorClass="bg-gray-400"
        />
        <StatCard
          title="订单总数"
          value={totalOrders.toLocaleString()}
          icon={ShoppingCart}
          colorClass="bg-orange-500"
        />
        <StatCard
          title="活跃账号 / 总数"
          value={`${stats.active_cookies} / ${stats.total_cookies}`}
          icon={Users}
          colorClass="bg-blue-500"
        />
        <StatCard
          title="库存卡密余量"
          value={stats.total_cards}
          icon={Package}
          colorClass="bg-purple-500"
        />
      </div>

      {/* Main Chart Section */}
      <div className="section-panel">
        <SectionHeader title="成交趋势" description="所选时间范围内的成交额变化，含已退款订单。" icon={TrendingUp} />
        <div className="h-[340px] w-full p-4 sm:p-5">
          {chartData.length === 0 ? (
            <EmptyState compact title="暂无订单数据" description="所选时间范围内暂无订单记录。" icon={ShoppingCart} />
          ) : (
            /* 统一用柱状图：每天的成交额是离散值而非连续趋势，
               而且图形不会因为数据点多少在柱状和折线之间跳变。 */
            <ResponsiveContainer width="100%" height="100%">
              <BarChart
                data={chartData}
                margin={{ top: 18, right: 16, left: -20, bottom: 18 }}
                barCategoryGap={chartData.length <= 2 ? 30 : chartData.length <= 10 ? '20%' : '10%'}
              >
                <CartesianGrid vertical={false} stroke="#eef0f2" strokeDasharray="3 3" />
                <XAxis
                  dataKey="name"
                  axisLine={false}
                  tickLine={false}
                  tick={{fill: '#6d747c', fontSize: 12, fontWeight: 600}}
                  dy={10}
                  interval="preserveStartEnd"
                />
                <YAxis
                  axisLine={false}
                  tickLine={false}
                  tick={{fill: '#939aa2', fontSize: 12, fontWeight: 500}}
                  tickFormatter={(value) => `¥${value}`}
                />
                <Tooltip
                  contentStyle={{
                    backgroundColor: '#ffffff',
                    borderRadius: '6px',
                    border: '1px solid #e4e6e8',
                    boxShadow: '0 4px 16px rgba(20, 24, 28, 0.08)',
                    padding: '10px 12px'
                  }}
                  itemStyle={{ color: '#1f2328', fontWeight: 600 }}
                  labelStyle={{ color: '#6d747c' }}
                  cursor={{ fill: 'rgba(214, 188, 0, 0.08)' }}
                  formatter={(value, name) => {
                    const label = name === 'confirmed' ? '已到账' : '成交额';
                    return [`¥${Number(value).toFixed(2)}`, label];
                  }}
                />
                <Legend
                  verticalAlign="top"
                  height={28}
                  iconType="circle"
                  iconSize={8}
                  formatter={(value) => (
                    <span style={{ color: '#6d747c', fontSize: 12 }}>
                      {value === 'confirmed' ? '已到账' : '成交额'}
                    </span>
                  )}
                />
                <Bar dataKey="amount" fill="#d6bc00" radius={[3, 3, 0, 0]} strokeWidth={0} />
                <Bar dataKey="confirmed" fill="#22c55e" radius={[3, 3, 0, 0]} strokeWidth={0} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </div>
      </div>

      {/* 商品销量排行和订单来源分布 */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {/* 商品销量排行 */}
        <div className="section-panel p-4 sm:p-5">
          <h3 className="section-title mb-5">商品销量排行</h3>
          <div className="h-[280px]">
            {productSalesData.length === 0 ? (
              <EmptyState compact title="暂无商品销售数据" description="当前时间范围内没有可统计的商品订单。" icon={Package} />
            ) : (
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={productSalesData} layout="vertical">
                  <CartesianGrid strokeDasharray="3 3" horizontal={true} vertical={false} stroke="#f0f0f0" />
                  <XAxis
                    type="number"
                    axisLine={false}
                    tickLine={false}
                    tick={{ fill: '#9CA3AF', fontSize: 12 }}
                  />
                  <YAxis
                    type="category"
                    dataKey="name"
                    axisLine={false}
                    tickLine={false}
                    tick={{ fill: '#6B7280', fontSize: 12 }}
                    width={100}
                  />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: '#fff',
                      border: '1px solid #e5e7eb',
                      borderRadius: '6px',
                      boxShadow: '0 4px 16px rgba(20, 24, 28, 0.08)'
                    }}
                  />
                  <Bar dataKey="sales" fill="#c7ad00" radius={[0, 3, 3, 0]} />
                </BarChart>
              </ResponsiveContainer>
            )}
          </div>
        </div>

        {/* 商品下单占比 */}
        <div className="section-panel p-4 sm:p-5">
          <h3 className="section-title mb-5">商品下单占比</h3>
          <div className="h-[280px]">
            {sourceDataData.length === 0 ? (
              <EmptyState compact title="暂无订单状态数据" description="当前时间范围内没有可统计的订单。" icon={ShoppingCart} />
            ) : (
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie
                    data={sourceDataData}
                    cx="50%"
                    cy="50%"
                    innerRadius={60}
                    outerRadius={90}
                    paddingAngle={2}
                    dataKey="value"
                    label={({ name, percent }) => `${name} ${(percent * 100).toFixed(0)}%`}
                    labelLine={false}
                  >
                    {sourceDataData.map((entry, index) => (
                      <Cell key={`cell-${index}`} fill={entry.color} />
                    ))}
                  </Pie>
                  <Legend
                    verticalAlign="bottom"
                    height={36}
                    iconType="circle"
                    formatter={(value) => <span style={{ color: '#6B7280', fontWeight: 500 }}>{value}</span>}
                  />
                </PieChart>
              </ResponsiveContainer>
            )}
          </div>
        </div>
      </div>

      {/* 收支明细和品类营收 */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        {/* 参与统计的订单列表 */}
        <div className="section-panel flex flex-col lg:col-span-2">
          <div className="flex items-center justify-between gap-3 border-b border-gray-100 bg-gray-50 px-4 py-3">
            <h3 className="section-title">参与统计的订单</h3>
            <div className="relative">
              <input
                placeholder="搜索订单号/商品/买家..."
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                className="ios-input w-48 rounded-md px-3 py-2 text-sm"
                type="text"
              />
            </div>
          </div>
          <div className="overflow-x-auto flex-1 max-h-[400px]">
            {ordersLoading ? (
              <div className="flex items-center justify-center py-20 text-gray-400">
                <Activity className="w-6 h-6 animate-spin mr-2" />
                加载中...
              </div>
            ) : validOrders.filter((order) =>
              order.order_id?.toLowerCase().includes(searchTerm.toLowerCase()) ||
              order.item_id?.toLowerCase().includes(searchTerm.toLowerCase()) ||
              order.buyer_id?.toLowerCase().includes(searchTerm.toLowerCase())
            ).length === 0 ? (
              <div className="flex items-center justify-center py-20 text-gray-400">
                暂无订单数据
              </div>
            ) : (
              <table className="data-table min-w-[760px]">
                <thead>
                  <tr>
                    <th>订单信息</th>
                    <th>买家信息</th>
                    <th>金额</th>
                    <th>状态</th>
                    <th className="text-right">操作</th>
                  </tr>
                </thead>
                <tbody>
                  {validOrders
                    .filter((order) =>
                      order.order_id?.toLowerCase().includes(searchTerm.toLowerCase()) ||
                      order.item_id?.toLowerCase().includes(searchTerm.toLowerCase()) ||
                      order.buyer_id?.toLowerCase().includes(searchTerm.toLowerCase())
                    )
                    .map((order) => (
                      <tr key={order.order_id}>
                        <td>
                          <div className="flex items-center gap-3">
                            <div className="h-11 w-11 flex-shrink-0 overflow-hidden rounded-md border border-gray-100 bg-gray-100">
                              <PackageCheck className="w-full h-full text-gray-300 p-2" />
                            </div>
                            <div className="min-w-0">
                              <div className="font-bold text-gray-900 text-sm line-clamp-1">
                                {order.item_title || order.item_id || '未知商品'}
                              </div>
                              <div className="text-xs text-gray-500 mt-1 font-mono">{order.order_id}</div>
                              <div className="text-xs text-gray-400 mt-0.5">数量: {order.quantity || 1}</div>
                            </div>
                          </div>
                        </td>
                        <td>
                          <div className="text-sm font-bold text-gray-800">{order.buyer_id}</div>
                          {order.created_at && (
                            <div className="text-xs text-gray-400 mt-1">{order.created_at}</div>
                          )}
                        </td>
                        <td className="text-sm font-extrabold text-gray-900 font-feature-settings-tnum">
                          ¥{order.amount || '0.00'}
                        </td>
                        <td>
                          <StatusBadge status={order.status || order.order_status || 'unknown'} />
                        </td>
                        <td className="text-right">
                          <a
                            href={`https://www.goofish.com/order-detail?orderId=${order.order_id}&role=seller`}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="inline-flex rounded-md p-2 text-gray-400 hover:bg-amber-50 hover:text-amber-600"
                            title="查看闲鱼详情"
                          >
                            <ExternalLink className="w-4 h-4" />
                          </a>
                        </td>
                      </tr>
                    ))}
                </tbody>
              </table>
            )}
          </div>
        </div>

        {/* 商品金额分析 */}
        <div className="section-panel p-4 sm:p-5">
          <h3 className="section-title mb-5">商品金额分析（TOP 5）</h3>
          {categoryDataData.length === 0 ? (
            <EmptyState compact title="暂无商品占比数据" description="当前时间范围内没有可统计的商品销售记录。" icon={Package} />
          ) : (
            <>
              <div className="h-[300px] relative">
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart>
                    <Pie
                      data={categoryDataData}
                      cx="50%"
                      cy="50%"
                      innerRadius={60}
                      outerRadius={100}
                      paddingAngle={2}
                      dataKey="value"
                      label={({ name, percent }) => `${name} ${(percent * 100).toFixed(0)}%`}
                    >
                      {categoryDataData.map((entry, index) => (
                        <Cell key={`cell-${index}`} fill={entry.color || COLORS[index % COLORS.length]} />
                      ))}
                    </Pie>
                    <Tooltip
                      contentStyle={{
                        backgroundColor: '#fff',
                        border: '1px solid #e5e7eb',
                        borderRadius: '6px',
                        boxShadow: '0 4px 16px rgba(20, 24, 28, 0.08)'
                      }}
                      formatter={(value: number) => `¥${value.toLocaleString()}`}
                    />
                  </PieChart>
                </ResponsiveContainer>
              </div>
              <div className="space-y-3 mt-4">
                {categoryDataData.map((cat) => (
                  <div key={cat.name} className="flex justify-between items-center text-sm">
                    <div className="flex items-center gap-2">
                      <div
                        className="w-3 h-3 rounded-full"
                        style={{ backgroundColor: cat.color || COLORS[categoryDataData.indexOf(cat) % COLORS.length] }}
                      ></div>
                      <span className="text-gray-600 font-medium">{cat.name}</span>
                    </div>
                    <div className="flex items-center gap-3">
                      <span className="font-bold text-gray-900">¥{cat.value.toLocaleString()}</span>
                      <span className="text-xs text-gray-500 bg-gray-100 px-2 py-0.5 rounded">{cat.percentage}%</span>
                    </div>
                  </div>
                ))}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
};

export default Dashboard;
