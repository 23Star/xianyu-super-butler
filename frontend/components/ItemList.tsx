import React, { useEffect, useMemo, useState } from 'react';
import { createPortal } from 'react-dom';
import {
  Box,
  Edit,
  Loader2,
  ListChecks,
  PackageCheck,
  Plus,
  RefreshCw,
  Save,
  Settings2,
  ShoppingBag,
  Sparkles,
  ShieldAlert,
  Trash2,
  X,
} from 'lucide-react';
import {
  AccountDetail,
  Card,
  Item,
  ItemDeliveryConfigSummary,
  ShippingRule,
} from '../types';
import {
  createManualItem,
  deleteItem,
  deleteShippingRule,
  getAccountDetails,
  getCards,
  getItemDeliveryConfig,
  getItemDeliveryConfigs,
  getItems,
  getShippingRules,
  saveItemDeliveryConfig,
  polishItems,
  syncItemsFromAccount,
  updateItemDetail,
  updateItemMultiQuantity,
  updateShippingRule,
} from '../services/api';
import { confirmAction } from '../services/feedback';
import DeliveryProtection from './DeliveryProtection';
import GeneralDeliveryRules from './GeneralDeliveryRules';
import {
  EmptyState,
  NoticeBanner,
  PageHeader,
  PageLoading,
  PageTabs,
  SectionHeader,
} from './ui';

type Notice = { type: 'success' | 'error'; message: string } | null;
type ItemSection = 'products' | 'rules' | 'protection';

interface DeliveryVariantForm {
  clientId: string;
  displayName: string;
  specText: string;
  platformSkuId: string;
  cardId: string;
  deliveryCount: number;
  enabled: boolean;
}

interface DeliveryForm {
  enabled: boolean;
  isMultiSpec: boolean;
  variants: DeliveryVariantForm[];
}

interface ManualItemForm {
  cookieId: string;
  itemId: string;
  title: string;
  price: string;
  imageUrl: string;
  description: string;
  detail: string;
}

const emptyManualItem: ManualItemForm = {
  cookieId: '',
  itemId: '',
  title: '',
  price: '',
  imageUrl: '',
  description: '',
  detail: '',
};

const createEmptyVariant = (index = 0): DeliveryVariantForm => ({
  clientId: `${Date.now()}-${index}-${Math.random().toString(36).slice(2)}`,
  displayName: '',
  specText: '',
  platformSkuId: '',
  cardId: '',
  deliveryCount: 1,
  enabled: true,
});

const itemKey = (item: Pick<Item, 'cookie_id' | 'item_id'>) =>
  `${item.cookie_id}:${item.item_id}`;

const formatPrice = (price?: string) => {
  const value = price?.trim().replace(/^[¥￥]\s*/, '');
  return value ? `¥${value}` : '价格未知';
};

const normalizeImageUrl = (url?: string) => {
  const value = url?.trim();
  if (!value) return '';
  return value.startsWith('//') ? `https:${value}` : value;
};

const cardTypeLabels: Record<Card['type'], string> = {
  api: 'API 动态内容',
  text: '固定文本',
  data: '批量库存',
  image: '图片内容',
};

const getCardStockLabel = (card?: Card) => {
  if (!card) return '尚未选择发货库存';
  if (!card.enabled) return '该库存已停用';
  if (card.type === 'data') {
    const count = (card.data_content || '').split(/\r?\n/).filter(line => line.trim()).length;
    return `当前可用 ${count} 条`;
  }
  return cardTypeLabels[card.type];
};

const ItemImage: React.FC<{ item: Item }> = ({ item }) => {
  const src = normalizeImageUrl(item.item_image);
  const [failed, setFailed] = useState(false);

  useEffect(() => setFailed(false), [src]);

  if (!src || failed) {
    return (
      <div className="flex h-full w-full items-center justify-center text-gray-300">
        <Box className="h-8 w-8" />
      </div>
    );
  }

  return (
    <img
      src={src}
      alt={item.item_title || '商品图片'}
      className="h-full w-full object-cover"
      loading="lazy"
      referrerPolicy="no-referrer"
      onError={() => setFailed(true)}
    />
  );
};

const Toggle: React.FC<{
  checked: boolean;
  disabled?: boolean;
  label: string;
  onChange: () => void;
}> = ({ checked, disabled, label, onChange }) => (
  <button
    type="button"
    role="switch"
    aria-checked={checked}
    aria-label={label}
    disabled={disabled}
    onClick={onChange}
    className={`relative inline-flex h-6 w-11 flex-none items-center rounded-full transition-colors ${
      checked ? 'bg-green-500' : 'bg-gray-300'
    } disabled:cursor-not-allowed disabled:opacity-50`}
  >
    <span
      className={`h-4 w-4 rounded-full bg-white shadow-sm transition-transform ${
        checked ? 'translate-x-6' : 'translate-x-1'
      }`}
    />
  </button>
);

const ItemList: React.FC = () => {
  const [items, setItems] = useState<Item[]>([]);
  const [accounts, setAccounts] = useState<AccountDetail[]>([]);
  const [cards, setCards] = useState<Card[]>([]);
  const [shippingRules, setShippingRules] = useState<ShippingRule[]>([]);
  const [deliveryConfigs, setDeliveryConfigs] = useState<ItemDeliveryConfigSummary[]>([]);
  const [activeSection, setActiveSection] = useState<ItemSection>('products');
  const [selectedAccount, setSelectedAccount] = useState('');
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [polishing, setPolishing] = useState(false);
  // 商品列表按账号过滤，多账号时避免混在一起看不清归属
  const [listAccountFilter, setListAccountFilter] = useState('');
  const [savingKey, setSavingKey] = useState('');
  const [notice, setNotice] = useState<Notice>(null);

  const [detailItem, setDetailItem] = useState<Item | null>(null);
  const [itemDetail, setItemDetail] = useState('');
  const [deliveryItem, setDeliveryItem] = useState<Item | null>(null);
  const [deliveryLoading, setDeliveryLoading] = useState(false);
  const [deliveryForm, setDeliveryForm] = useState<DeliveryForm>({
    enabled: true,
    isMultiSpec: false,
    variants: [createEmptyVariant()],
  });
  const [showManualModal, setShowManualModal] = useState(false);
  const [manualForm, setManualForm] = useState<ManualItemForm>(emptyManualItem);

  const accountNames = useMemo(
    () => new Map(accounts.map(account => [
      account.id,
      account.nickname || account.remark || `账号 ${account.id.substring(0, 6)}`,
    ])),
    [accounts],
  );

  const accountAvatars = useMemo(
    () => new Map(accounts.map(account => [account.id, account.avatar_url || ''])),
    [accounts],
  );

  const ruleMap = useMemo(() => {
    const map = new Map<string, ShippingRule>();
    shippingRules.forEach(rule => {
      if (rule.cookie_id && rule.item_id) {
        map.set(`${rule.cookie_id}:${rule.item_id}`, rule);
      }
    });
    return map;
  }, [shippingRules]);

  const genericRules = useMemo(
    () => shippingRules.filter(rule => !rule.item_id),
    [shippingRules],
  );

  const deliveryConfigMap = useMemo(
    () => new Map(deliveryConfigs.map(config => [
      `${config.cookie_id}:${config.item_id}`,
      config,
    ])),
    [deliveryConfigs],
  );

  const visibleItems = useMemo(
    () => (listAccountFilter ? items.filter(item => item.cookie_id === listAccountFilter) : items),
    [items, listAccountFilter],
  );

  const configuredItemCount = useMemo(() => {
    const configuredKeys = new Set(
      deliveryConfigs.map(config => `${config.cookie_id}:${config.item_id}`),
    );
    shippingRules.forEach(rule => {
      if (rule.cookie_id && rule.item_id) {
        configuredKeys.add(`${rule.cookie_id}:${rule.item_id}`);
      }
    });
    return configuredKeys.size;
  }, [deliveryConfigs, shippingRules]);

  const loadData = async () => {
    setLoading(true);
    try {
      const [accountData, itemData, cardData, ruleData, configData] = await Promise.all([
        getAccountDetails(),
        getItems(),
        getCards(),
        getShippingRules(),
        getItemDeliveryConfigs(),
      ]);
      setAccounts(accountData);
      setItems(itemData);
      setCards(cardData);
      setShippingRules(ruleData);
      setDeliveryConfigs(configData);
      setSelectedAccount(current => current || accountData[0]?.id || '');
    } catch (error) {
      setNotice({
        type: 'error',
        message: error instanceof Error ? error.message : '商品数据加载失败',
      });
    } finally {
      setLoading(false);
    }
  };

  const reloadRules = async () => {
    const rules = await getShippingRules();
    setShippingRules(rules);
  };

  const reloadDeliveryConfigs = async () => {
    setDeliveryConfigs(await getItemDeliveryConfigs());
  };

  useEffect(() => {
    void loadData();
  }, []);

  const handleSync = async () => {
    if (!selectedAccount) {
      setNotice({ type: 'error', message: '请先选择需要同步的账号' });
      return;
    }

    setSyncing(true);
    setNotice(null);
    try {
      const result = await syncItemsFromAccount(selectedAccount);
      if (result?.success === false) throw new Error(result.message || '同步失败');
      setItems(await getItems());
      setNotice({ type: 'success', message: result?.message || '商品同步完成' });
    } catch (error) {
      setNotice({ type: 'error', message: error instanceof Error ? error.message : '同步失败' });
    } finally {
      setSyncing(false);
    }
  };

  // 擦亮把商品重新推到搜索前列，平台对每日次数有限制，超出的会在结果里标记失败
  const handlePolish = async () => {
    setPolishing(true);
    setNotice(null);
    try {
      const result = await polishItems(selectedAccount || undefined);
      if (result?.success === false) throw new Error(result.message || '擦亮失败');
      setNotice({ type: 'success', message: result?.message || '商品擦亮完成' });
    } catch (error) {
      setNotice({ type: 'error', message: error instanceof Error ? error.message : '擦亮失败' });
    } finally {
      setPolishing(false);
    }
  };

  const openManualModal = () => {
    setManualForm({ ...emptyManualItem, cookieId: selectedAccount || accounts[0]?.id || '' });
    setShowManualModal(true);
  };

  const handleCreateManualItem = async () => {
    if (!manualForm.cookieId || !manualForm.itemId.trim() || !manualForm.title.trim()) {
      setNotice({ type: 'error', message: '账号、商品 ID 和商品标题为必填项' });
      return;
    }

    setSavingKey('manual-item');
    try {
      await createManualItem({
        cookie_id: manualForm.cookieId,
        item_id: manualForm.itemId.trim(),
        title: manualForm.title.trim(),
        price: manualForm.price.trim(),
        image_url: manualForm.imageUrl.trim(),
        description: manualForm.description.trim(),
        detail: manualForm.detail.trim(),
      });
      setItems(await getItems());
      setShowManualModal(false);
      setNotice({ type: 'success', message: '商品已添加，可继续配置自动发货' });
    } catch (error) {
      setNotice({ type: 'error', message: error instanceof Error ? error.message : '商品添加失败' });
    } finally {
      setSavingKey('');
    }
  };

  const openDetail = (item: Item) => {
    setDetailItem(item);
    setItemDetail(item.item_detail || '');
  };

  const handleSaveDetail = async () => {
    if (!detailItem) return;
    const key = itemKey(detailItem);
    setSavingKey(key);
    try {
      await updateItemDetail(detailItem.cookie_id, detailItem.item_id, itemDetail);
      setItems(current => current.map(item =>
        itemKey(item) === key ? { ...item, item_detail: itemDetail } : item,
      ));
      setDetailItem(null);
      setNotice({ type: 'success', message: '商品详情已保存' });
    } catch (error) {
      setNotice({ type: 'error', message: error instanceof Error ? error.message : '保存失败' });
    } finally {
      setSavingKey('');
    }
  };

  const openDelivery = async (item: Item) => {
    const legacyRule = ruleMap.get(itemKey(item));
    setDeliveryItem(item);
    setDeliveryLoading(true);
    try {
      const config = await getItemDeliveryConfig(item.cookie_id, item.item_id);
      if (config.configured && config.variants.length > 0) {
        setDeliveryForm({
          enabled: config.enabled,
          isMultiSpec: config.is_multi_spec,
          variants: config.variants.map((variant, index) => ({
            clientId: String(variant.id || createEmptyVariant(index).clientId),
            displayName: variant.display_name || '',
            specText: variant.spec_text || '',
            platformSkuId: variant.platform_sku_id || '',
            cardId: variant.card_id ? String(variant.card_id) : '',
            deliveryCount: Math.max(1, variant.delivery_count || 1),
            enabled: variant.enabled && variant.binding_enabled,
          })),
        });
      } else {
        setDeliveryForm({
          enabled: legacyRule?.enabled ?? true,
          isMultiSpec: false,
          variants: [{
            ...createEmptyVariant(),
            displayName: '默认规格',
            cardId: legacyRule?.card_group_id ? String(legacyRule.card_group_id) : '',
            deliveryCount: Math.max(1, legacyRule?.priority || 1),
          }],
        });
      }
    } catch (error) {
      setDeliveryItem(null);
      setNotice({
        type: 'error',
        message: error instanceof Error ? error.message : '发货配置加载失败',
      });
    } finally {
      setDeliveryLoading(false);
    }
  };

  const updateDeliveryVariant = (
    clientId: string,
    patch: Partial<DeliveryVariantForm>,
  ) => {
    setDeliveryForm(current => ({
      ...current,
      variants: current.variants.map(variant =>
        variant.clientId === clientId ? { ...variant, ...patch } : variant,
      ),
    }));
  };

  const addDeliveryVariant = () => {
    setDeliveryForm(current => ({
      ...current,
      variants: [...current.variants, createEmptyVariant(current.variants.length)],
    }));
  };

  const removeDeliveryVariant = (clientId: string) => {
    setDeliveryForm(current => {
      if (current.variants.length <= 1) return current;
      return {
        ...current,
        variants: current.variants.filter(variant => variant.clientId !== clientId),
      };
    });
  };

  const handleSaveDelivery = async () => {
    if (!deliveryItem) return;
    const variantsToSave = deliveryForm.isMultiSpec
      ? deliveryForm.variants
      : deliveryForm.variants.slice(0, 1);
    if (variantsToSave.length === 0) {
      setNotice({ type: 'error', message: '至少需要保留一个商品规格' });
      return;
    }
    const invalidIndex = variantsToSave.findIndex(variant =>
      !variant.cardId || (
        deliveryForm.isMultiSpec
        && (!variant.displayName.trim() || !variant.specText.trim())
      ),
    );
    if (invalidIndex >= 0) {
      setNotice({
        type: 'error',
        message: deliveryForm.isMultiSpec
          ? `请完整填写第 ${invalidIndex + 1} 个规格名称、规格组合和发货库存`
          : '请选择自动发货使用的卡密或内容',
      });
      return;
    }

    const key = itemKey(deliveryItem);
    const legacyRule = ruleMap.get(key);
    setSavingKey(key);
    try {
      await saveItemDeliveryConfig(deliveryItem.cookie_id, deliveryItem.item_id, {
        enabled: deliveryForm.enabled,
        is_multi_spec: deliveryForm.isMultiSpec,
        variants: variantsToSave.map(variant => ({
          display_name: deliveryForm.isMultiSpec
            ? variant.displayName.trim()
            : '默认规格',
          spec_text: deliveryForm.isMultiSpec ? variant.specText.trim() : '',
          spec_payload: undefined,
          platform_sku_id: deliveryForm.isMultiSpec ? variant.platformSkuId.trim() : '',
          card_id: Number(variant.cardId),
          delivery_count: Math.max(1, Math.floor(variant.deliveryCount || 1)),
          enabled: variant.enabled,
          binding_enabled: variant.enabled,
          source: 'manual',
        })),
      });
      if (legacyRule) {
        await deleteShippingRule(legacyRule.id);
        setShippingRules(current => current.filter(rule => rule.id !== legacyRule.id));
      }
      setItems(current => current.map(item =>
        itemKey(item) === key
          ? { ...item, is_multi_spec: deliveryForm.isMultiSpec }
          : item,
      ));
      await reloadDeliveryConfigs();
      setDeliveryItem(null);
      setNotice({ type: 'success', message: '商品自动发货配置已保存' });
    } catch (error) {
      setNotice({ type: 'error', message: error instanceof Error ? error.message : '发货配置保存失败' });
    } finally {
      setSavingKey('');
    }
  };

  const handleToggleDelivery = async (item: Item) => {
    const key = itemKey(item);
    const configSummary = deliveryConfigMap.get(key);
    const legacyRule = ruleMap.get(key);
    if (!configSummary && !legacyRule) {
      void openDelivery(item);
      return;
    }

    setSavingKey(key);
    try {
      if (configSummary) {
        const config = await getItemDeliveryConfig(item.cookie_id, item.item_id);
        await saveItemDeliveryConfig(item.cookie_id, item.item_id, {
          enabled: !config.enabled,
          is_multi_spec: config.is_multi_spec,
          variants: config.variants.map(variant => ({
            display_name: variant.display_name,
            spec_text: variant.spec_text,
            spec_payload: variant.spec_payload,
            platform_sku_id: variant.platform_sku_id,
            card_id: variant.card_id,
            delivery_count: variant.delivery_count,
            enabled: variant.enabled,
            binding_enabled: variant.binding_enabled,
            source: variant.source || 'manual',
          })),
        });
        await reloadDeliveryConfigs();
      } else if (legacyRule) {
        await updateShippingRule({ ...legacyRule, enabled: !legacyRule.enabled });
        setShippingRules(current => current.map(currentRule =>
          currentRule.id === legacyRule.id
            ? { ...currentRule, enabled: !legacyRule.enabled }
            : currentRule,
        ));
      }
    } catch (error) {
      setNotice({ type: 'error', message: error instanceof Error ? error.message : '状态更新失败' });
    } finally {
      setSavingKey('');
    }
  };

  const handleDelete = async (item: Item) => {
    if (!await confirmAction(`确认删除商品“${item.item_title || item.item_id}”的本地记录吗？`)) return;
    const key = itemKey(item);
    const rule = ruleMap.get(key);
    setSavingKey(key);
    try {
      if (rule) await deleteShippingRule(rule.id);
      await deleteItem(item.cookie_id, item.item_id);
      setItems(current => current.filter(currentItem => itemKey(currentItem) !== key));
      setShippingRules(current => current.filter(currentRule => currentRule.id !== rule?.id));
      setDeliveryConfigs(current => current.filter(config =>
        `${config.cookie_id}:${config.item_id}` !== key,
      ));
      setNotice({ type: 'success', message: '商品及其专属发货配置已删除' });
    } catch (error) {
      setNotice({ type: 'error', message: error instanceof Error ? error.message : '删除失败' });
    } finally {
      setSavingKey('');
    }
  };

  const toggleSetting = async (
    item: Item,
    field: 'multi_quantity_delivery',
  ) => {
    const key = itemKey(item);
    const enabled = !Boolean(item[field]);
    setSavingKey(key);
    try {
      await updateItemMultiQuantity(item.cookie_id, item.item_id, enabled);
      setItems(current => current.map(currentItem =>
        itemKey(currentItem) === key ? { ...currentItem, [field]: enabled } : currentItem,
      ));
    } catch (error) {
      setNotice({ type: 'error', message: error instanceof Error ? error.message : '状态更新失败' });
    } finally {
      setSavingKey('');
    }
  };

  if (loading) {
    return <PageLoading label="正在加载商品与发货配置" />;
  }

  return (
    <div className="page-stack animate-fade-in">
      <PageHeader
        title="商品与发货"
        description="同步闲鱼商品，在同一处维护本地详情、专属发货、通用兜底规则和发货保护。"
        icon={Box}
        badge={<span className="status-badge status-badge-info">{items.length} 件商品</span>}
      />

      <PageTabs
        value={activeSection}
        onChange={setActiveSection}
        items={[
          { id: 'products', label: '商品与专属发货', icon: ShoppingBag, count: items.length },
          { id: 'rules', label: '通用发货规则', icon: ListChecks, count: genericRules.length },
          { id: 'protection', label: '发货保护与黑名单', icon: ShieldAlert },
        ]}
        ariaLabel="商品与发货功能"
      />

      {notice && (
        <NoticeBanner
          type={notice.type}
          message={notice.message}
          onClose={() => setNotice(null)}
        />
      )}

      <section hidden={activeSection !== 'products'} className="space-y-4">
        <div className="section-panel">
          <SectionHeader
            title="商品同步"
            description="选择闲鱼账号后同步在售商品；未同步到的商品可手动添加并配置发货。"
            icon={RefreshCw}
          />
          <div className="toolbar border-0 shadow-none">
            <div className="toolbar__group">
              <label className="min-w-0 sm:min-w-64">
                <span className="field-label">同步账号</span>
                <select
                  className="ios-input w-full rounded-md px-3 py-2 text-sm"
                  value={selectedAccount}
                  onChange={event => setSelectedAccount(event.target.value)}
                  aria-label="选择同步账号"
                >
                  <option value="">请选择闲鱼账号</option>
                  {accounts.map(account => (
                    <option key={account.id} value={account.id}>{accountNames.get(account.id)}</option>
                  ))}
                </select>
              </label>
            </div>
            <div className="toolbar__group self-end">
              <button
                type="button"
                onClick={openManualModal}
                className="ios-btn-secondary flex items-center justify-center gap-2 rounded-md px-4 py-2 text-sm"
              >
                <Plus className="h-4 w-4" />
                手动添加
              </button>
              <button
                type="button"
                onClick={handleSync}
                disabled={syncing || !selectedAccount}
                className="ios-btn-primary flex items-center justify-center gap-2 rounded-md px-4 py-2 text-sm"
              >
                <RefreshCw className={`h-4 w-4 ${syncing ? 'animate-spin' : ''}`} />
                {syncing ? '正在同步' : '同步商品'}
              </button>
              <button
                type="button"
                onClick={handlePolish}
                disabled={polishing || items.length === 0}
                className="ios-btn-secondary flex items-center justify-center gap-2 rounded-md px-4 py-2 text-sm"
                title="重新获取搜索曝光，平台对每日擦亮次数有限制"
              >
                <Sparkles className={`h-4 w-4 ${polishing ? 'animate-pulse' : ''}`} />
                {polishing ? '正在擦亮' : '一键擦亮'}
              </button>
            </div>
          </div>
        </div>

        <section className="section-panel">
          <SectionHeader
            title="商品列表"
            description={`共 ${items.length} 件商品，已配置专属发货 ${configuredItemCount} 件，覆盖 ${new Set(items.map(item => item.cookie_id)).size} 个账号。`}
            icon={ShoppingBag}
          />

          {accounts.length > 1 && (
            <div className="flex items-center gap-3 border-b border-gray-100 px-4 py-3">
              <span className="text-xs font-semibold text-gray-500">按账号查看</span>
              <select
                value={listAccountFilter}
                onChange={(event) => setListAccountFilter(event.target.value)}
                className="ios-input rounded-md px-3 py-2 text-sm"
                aria-label="按账号筛选商品"
              >
                <option value="">全部账号（{items.length}）</option>
                {accounts.map(account => (
                  <option key={account.id} value={account.id}>
                    {accountNames.get(account.id)}（{items.filter(i => i.cookie_id === account.id).length}）
                  </option>
                ))}
              </select>
            </div>
          )}

          {visibleItems.length > 0 ? (
            <>
              <div className="hidden grid-cols-[minmax(260px,1.4fr)_minmax(130px,.7fr)_minmax(200px,1fr)_minmax(150px,.7fr)_96px] gap-5 border-b border-gray-200 bg-gray-50 px-4 py-3 text-xs font-bold text-gray-500 xl:grid">
                <span>商品信息</span>
                <span>所属账号</span>
                <span>专属自动发货</span>
                <span>商品能力</span>
                <span className="text-right">操作</span>
              </div>
              <div className="divide-y divide-gray-100">
                {visibleItems.map(item => {
                  const key = itemKey(item);
                  const busy = savingKey === key;
                  const rule = ruleMap.get(key);
                  const configSummary = deliveryConfigMap.get(key);
                  const deliveryConfigured = Boolean(configSummary || rule);
                  const deliveryEnabled = configSummary?.enabled ?? Boolean(rule?.enabled);
                  const deliveryIncomplete = Boolean(configSummary && !configSummary.complete);
                  const statusClass = deliveryEnabled
                    ? (deliveryIncomplete ? 'status-badge-warning' : 'status-badge-success')
                    : (deliveryConfigured ? 'status-badge-warning' : 'status-badge-info');
                  const statusText = deliveryEnabled
                    ? (deliveryIncomplete ? '待完善' : '发货中')
                    : (deliveryConfigured ? '已暂停' : '未配置');
                  const deliveryTitle = configSummary
                    ? (
                      configSummary.is_multi_spec
                        ? `${configSummary.configured_count}/${configSummary.variant_count} 个规格已绑定`
                        : '普通商品发货'
                    )
                    : (
                      rule?.card_group_name
                      || (rule ? `卡密 ${rule.card_group_id}` : '尚未绑定发货内容')
                    );
                  const deliveryDescription = configSummary
                    ? (
                      configSummary.complete
                        ? `累计发货 ${configSummary.delivery_times} 次`
                        : '存在未启用或不可用的规格库存'
                    )
                    : (rule ? `每单发货 ${rule.priority} 份` : '配置后可按订单自动发货');
                  return (
                    <article
                      key={key}
                      className="grid gap-4 px-4 py-4 transition-colors hover:bg-[#fffdf0] xl:grid-cols-[minmax(260px,1.4fr)_minmax(130px,.7fr)_minmax(200px,1fr)_minmax(150px,.7fr)_96px] xl:items-center xl:gap-5"
                    >
                      <div className="flex min-w-0 gap-3">
                        <div className="h-20 w-20 flex-none overflow-hidden rounded-md border border-gray-200 bg-gray-100">
                          <ItemImage item={item} />
                        </div>
                        <div className="min-w-0 flex-1">
                          <div className="flex min-w-0 flex-wrap items-start gap-2">
                            <h3 className="min-w-0 flex-1 text-sm font-bold leading-5 text-gray-900">
                              {item.item_title || '未命名商品'}
                            </h3>
                            <span className={`status-badge shrink-0 ${statusClass}`}>
                              {statusText}
                            </span>
                          </div>
                          <p className="mt-1 text-lg font-bold text-[#d92d20]">{formatPrice(item.item_price)}</p>
                          <p className="mt-1 truncate font-mono text-xs text-gray-400">商品 ID {item.item_id}</p>
                        </div>
                      </div>

                      <div className="flex items-center gap-2 border-t border-gray-100 pt-3 xl:border-0 xl:pt-0">
                        {accountAvatars.get(item.cookie_id) ? (
                          <img
                            src={accountAvatars.get(item.cookie_id)}
                            alt=""
                            className="h-7 w-7 flex-none rounded-full object-cover"
                            referrerPolicy="no-referrer"
                          />
                        ) : (
                          <span className="flex h-7 w-7 flex-none items-center justify-center rounded-full bg-gray-200 text-[10px] text-gray-500">
                            {(accountNames.get(item.cookie_id) || '?').slice(0, 1)}
                          </span>
                        )}
                        <div className="min-w-0">
                          <p className="truncate text-xs font-semibold text-gray-800">
                            {accountNames.get(item.cookie_id) || '未命名账号'}
                          </p>
                          <p className="truncate font-mono text-[10px] text-gray-400">{item.cookie_id}</p>
                        </div>
                      </div>

                      <div className="border-t border-gray-100 pt-3 xl:border-0 xl:pt-0">
                        <div className="flex items-center justify-between gap-3">
                          <div className="min-w-0">
                            <div className="flex items-center gap-2">
                              <PackageCheck className={`h-4 w-4 shrink-0 ${deliveryEnabled ? 'text-green-600' : 'text-gray-400'}`} />
                              <span className="text-sm font-bold text-gray-800">
                                {deliveryTitle}
                              </span>
                            </div>
                            <p className="mt-1 truncate text-xs text-gray-500">
                              {deliveryDescription}
                            </p>
                          </div>
                          <Toggle
                            checked={deliveryEnabled}
                            disabled={busy}
                            label={`${item.item_title || item.item_id} 自动发货`}
                            onChange={() => handleToggleDelivery(item)}
                          />
                        </div>
                        <button
                          type="button"
                          onClick={() => openDelivery(item)}
                          disabled={busy}
                          className="ios-btn-secondary mt-3 flex w-full items-center justify-center gap-2 rounded-md px-3 py-2 text-xs"
                        >
                          <Settings2 className="h-4 w-4" />
                          {deliveryConfigured ? '编辑发货策略' : '配置自动发货'}
                        </button>
                      </div>

                      <div className="grid grid-cols-2 gap-3 border-t border-gray-100 pt-3 xl:grid-cols-1 xl:border-0 xl:pt-0">
                        <div className="flex items-center justify-between gap-3">
                          <span className="text-xs font-semibold text-gray-600">规格模式</span>
                          <span className="text-xs font-bold text-gray-800">
                            {configSummary
                              ? (
                                configSummary.is_multi_spec
                                  ? `${configSummary.variant_count} 个规格`
                                  : '普通商品'
                              )
                              : (item.is_multi_spec ? '旧版多规格' : '普通商品')}
                          </span>
                        </div>
                        <div className="flex items-center justify-between gap-3">
                          <span className="text-xs font-semibold text-gray-600">多数量</span>
                          <Toggle
                            checked={Boolean(item.multi_quantity_delivery)}
                            disabled={busy}
                            label={`${item.item_title || item.item_id} 多数量发货`}
                            onChange={() => toggleSetting(item, 'multi_quantity_delivery')}
                          />
                        </div>
                      </div>

                      <div className="flex items-center justify-between gap-3 border-t border-gray-100 pt-3 xl:flex-col xl:items-end xl:border-0 xl:pt-0">
                        <span className="text-xs text-gray-400 xl:text-right">
                          {item.item_detail ? '详情已维护' : '暂无详情'}
                        </span>
                        <div className="flex items-center gap-1">
                          <button
                            type="button"
                            onClick={() => openDetail(item)}
                            disabled={busy}
                            className="rounded-md p-2 text-gray-600 hover:bg-gray-100"
                            title="编辑本地详情"
                            aria-label="编辑本地详情"
                          >
                            <Edit className="h-4 w-4" />
                          </button>
                          <button
                            type="button"
                            onClick={() => handleDelete(item)}
                            disabled={busy}
                            className="rounded-md p-2 text-red-500 hover:bg-red-50"
                            title="删除本地记录"
                            aria-label="删除本地记录"
                          >
                            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Trash2 className="h-4 w-4" />}
                          </button>
                        </div>
                      </div>
                    </article>
                  );
                })}
              </div>
            </>
          ) : (
            <EmptyState
              title="暂无商品数据"
              description="先选择闲鱼账号同步在售商品，也可以手动添加商品并直接配置自动发货。"
              icon={ShoppingBag}
              action={(
                <button type="button" onClick={openManualModal} className="ios-btn-secondary rounded-md px-4 py-2 text-sm">
                  手动添加商品
                </button>
              )}
            />
          )}
        </section>
      </section>

      <section hidden={activeSection !== 'rules'}>
        <GeneralDeliveryRules
          accounts={accounts}
          cards={cards}
          rules={genericRules}
          onReload={reloadRules}
        />
      </section>

      <section hidden={activeSection !== 'protection'}>
        <DeliveryProtection
          accounts={accounts}
          items={items}
          selectedAccount={selectedAccount}
          onSelectedAccountChange={setSelectedAccount}
        />
      </section>

      {deliveryItem && createPortal(
        <div className="modal-overlay">
          <div className="modal-container modal-container-lg">
            <div className="modal-header flex items-start justify-between gap-4">
              <div>
                <h3 className="text-lg font-bold text-gray-900">商品自动发货</h3>
                <p className="mt-1 line-clamp-1 text-sm text-gray-500">
                  {deliveryItem.item_title || deliveryItem.item_id}
                </p>
              </div>
              <button type="button" onClick={() => setDeliveryItem(null)} className="rounded-md p-2 hover:bg-gray-100" aria-label="关闭">
                <X className="h-5 w-5" />
              </button>
            </div>
            <div className="modal-body space-y-5">
              {deliveryLoading ? (
                <PageLoading label="正在加载商品发货配置" />
              ) : (
                <>
                  <div className="grid gap-3 rounded-md border border-gray-200 bg-gray-50 p-4 sm:grid-cols-3">
                    <div className="min-w-0">
                      <p className="text-xs font-semibold text-gray-500">所属账号</p>
                      <p className="mt-1 truncate text-sm font-bold text-gray-900">
                        {accountNames.get(deliveryItem.cookie_id) || deliveryItem.cookie_id}
                      </p>
                    </div>
                    <div className="min-w-0">
                      <p className="text-xs font-semibold text-gray-500">商品 ID</p>
                      <p className="mt-1 truncate font-mono text-sm text-gray-900">{deliveryItem.item_id}</p>
                    </div>
                    <div className="flex items-center justify-between gap-3 sm:justify-end">
                      <div className="sm:text-right">
                        <p className="text-sm font-bold text-gray-900">自动发货</p>
                        <p className="mt-1 text-xs text-gray-500">关闭后保留全部绑定</p>
                      </div>
                      <Toggle
                        checked={deliveryForm.enabled}
                        label="启用商品自动发货"
                        onChange={() => setDeliveryForm(current => ({ ...current, enabled: !current.enabled }))}
                      />
                    </div>
                  </div>

                  <div>
                    <p className="mb-2 text-sm font-bold text-gray-800">商品规格模式</p>
                    <div className="grid grid-cols-2 rounded-md border border-gray-200 bg-gray-100 p-1" role="radiogroup" aria-label="商品规格模式">
                      <button
                        type="button"
                        role="radio"
                        aria-checked={!deliveryForm.isMultiSpec}
                        onClick={() => setDeliveryForm(current => ({ ...current, isMultiSpec: false }))}
                        className={`rounded px-3 py-2 text-sm font-semibold ${
                          !deliveryForm.isMultiSpec
                            ? 'bg-white text-gray-900 shadow-sm'
                            : 'text-gray-500 hover:text-gray-800'
                        }`}
                      >
                        普通商品
                      </button>
                      <button
                        type="button"
                        role="radio"
                        aria-checked={deliveryForm.isMultiSpec}
                        onClick={() => setDeliveryForm(current => ({ ...current, isMultiSpec: true }))}
                        className={`rounded px-3 py-2 text-sm font-semibold ${
                          deliveryForm.isMultiSpec
                            ? 'bg-white text-gray-900 shadow-sm'
                            : 'text-gray-500 hover:text-gray-800'
                        }`}
                      >
                        多规格商品
                      </button>
                    </div>
                    <p className="mt-2 text-xs leading-5 text-gray-500">
                      {deliveryForm.isMultiSpec
                        ? '订单规格必须与下方某一规格组合精确匹配，否则系统会阻止发货，不会使用其他规格库存兜底。'
                        : '所有订单使用同一个发货库存；如商品有套餐、周期或版本差异，请切换为多规格商品。'}
                    </p>
                  </div>

                  <div className="space-y-3">
                    {(deliveryForm.isMultiSpec
                      ? deliveryForm.variants
                      : deliveryForm.variants.slice(0, 1)
                    ).map((variant, index) => {
                      const selectedCard = cards.find(card => String(card.id) === variant.cardId);
                      return (
                        <article key={variant.clientId} className="rounded-md border border-gray-200 bg-white">
                          <div className="flex items-center justify-between gap-3 border-b border-gray-100 px-4 py-3">
                            <div className="min-w-0">
                              <h4 className="truncate text-sm font-bold text-gray-900">
                                {deliveryForm.isMultiSpec
                                  ? (variant.displayName.trim() || `规格 ${index + 1}`)
                                  : '默认发货配置'}
                              </h4>
                              <p className="mt-0.5 truncate text-xs text-gray-500">
                                {deliveryForm.isMultiSpec
                                  ? (variant.specText.trim() || '等待填写规格组合')
                                  : '适用于该商品的全部订单'}
                              </p>
                            </div>
                            <div className="flex items-center gap-2">
                              <Toggle
                                checked={variant.enabled}
                                label={`${variant.displayName || `规格 ${index + 1}`} 启用状态`}
                                onChange={() => updateDeliveryVariant(variant.clientId, { enabled: !variant.enabled })}
                              />
                              {deliveryForm.isMultiSpec && deliveryForm.variants.length > 1 && (
                                <button
                                  type="button"
                                  onClick={() => removeDeliveryVariant(variant.clientId)}
                                  className="rounded-md p-2 text-red-500 hover:bg-red-50"
                                  title="删除规格"
                                  aria-label={`删除规格 ${index + 1}`}
                                >
                                  <Trash2 className="h-4 w-4" />
                                </button>
                              )}
                            </div>
                          </div>

                          <div className="grid gap-4 p-4 sm:grid-cols-2">
                            {deliveryForm.isMultiSpec && (
                              <>
                                <div>
                                  <label className="field-label" htmlFor={`variant-name-${variant.clientId}`}>规格显示名称</label>
                                  <input
                                    id={`variant-name-${variant.clientId}`}
                                    value={variant.displayName}
                                    onChange={event => updateDeliveryVariant(variant.clientId, { displayName: event.target.value })}
                                    className="ios-input w-full rounded-md px-3 py-2.5"
                                    placeholder="例如：周卡 / 独享"
                                  />
                                </div>
                                <div>
                                  <label className="field-label" htmlFor={`variant-spec-${variant.clientId}`}>规格组合</label>
                                  <input
                                    id={`variant-spec-${variant.clientId}`}
                                    value={variant.specText}
                                    onChange={event => updateDeliveryVariant(variant.clientId, { specText: event.target.value })}
                                    className="ios-input w-full rounded-md px-3 py-2.5"
                                    placeholder="周期=周卡 | 版本=独享"
                                  />
                                </div>
                                <div className="sm:col-span-2">
                                  <label className="field-label" htmlFor={`variant-sku-${variant.clientId}`}>
                                    闲鱼 SKU ID <span className="font-normal text-gray-400">（可选，填写后优先匹配）</span>
                                  </label>
                                  <input
                                    id={`variant-sku-${variant.clientId}`}
                                    value={variant.platformSkuId}
                                    onChange={event => updateDeliveryVariant(variant.clientId, { platformSkuId: event.target.value })}
                                    className="ios-input w-full rounded-md px-3 py-2.5 font-mono"
                                    placeholder="从订单或商品接口获取的平台规格 ID"
                                  />
                                </div>
                              </>
                            )}

                            <div>
                              <label className="field-label" htmlFor={`variant-card-${variant.clientId}`}>绑定发货库存</label>
                              <select
                                id={`variant-card-${variant.clientId}`}
                                value={variant.cardId}
                                onChange={event => updateDeliveryVariant(variant.clientId, { cardId: event.target.value })}
                                className="ios-input w-full rounded-md px-3 py-2.5"
                              >
                                <option value="">请选择卡密或内容</option>
                                {cards.map(card => (
                                  <option key={card.id} value={card.id} disabled={!card.enabled}>
                                    {card.name || `卡密 ${card.id}`} · {cardTypeLabels[card.type]}
                                    {card.enabled ? '' : '（已停用）'}
                                  </option>
                                ))}
                              </select>
                              <p className={`mt-1.5 text-xs ${selectedCard?.enabled === false ? 'text-red-600' : 'text-gray-500'}`}>
                                {getCardStockLabel(selectedCard)}
                              </p>
                            </div>

                            <div>
                              <label className="field-label" htmlFor={`variant-count-${variant.clientId}`}>每购买 1 件发货份数</label>
                              <input
                                id={`variant-count-${variant.clientId}`}
                                type="number"
                                min={1}
                                step={1}
                                value={variant.deliveryCount}
                                onChange={event => updateDeliveryVariant(variant.clientId, {
                                  deliveryCount: Math.max(1, Math.floor(Number(event.target.value) || 1)),
                                })}
                                className="ios-input w-full rounded-md px-3 py-2.5"
                              />
                              <p className="mt-1.5 text-xs text-gray-500">
                                {deliveryItem.multi_quantity_delivery
                                  ? '已开启多数量：会再乘以订单购买数量。'
                                  : '当前按单件计算；可在商品列表开启多数量。'}
                              </p>
                            </div>
                          </div>
                        </article>
                      );
                    })}
                  </div>

                  {deliveryForm.isMultiSpec && (
                    <button
                      type="button"
                      onClick={addDeliveryVariant}
                      className="ios-btn-secondary flex w-full items-center justify-center gap-2 rounded-md border-dashed px-4 py-2.5 text-sm"
                    >
                      <Plus className="h-4 w-4" />
                      添加商品规格
                    </button>
                  )}
                </>
              )}
            </div>
            <div className="modal-footer flex justify-end gap-2">
              <button type="button" onClick={() => setDeliveryItem(null)} className="ios-btn-secondary rounded-md px-4 py-2.5">
                取消
              </button>
              <button
                type="button"
                onClick={handleSaveDelivery}
                disabled={Boolean(savingKey) || deliveryLoading}
                className="ios-btn-primary flex items-center gap-2 rounded-md px-4 py-2.5"
              >
                {savingKey ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                保存策略
              </button>
            </div>
          </div>
        </div>,
        document.body,
      )}

      {detailItem && createPortal(
        <div className="modal-overlay">
          <div className="modal-container">
            <div className="modal-header flex items-start justify-between gap-4">
              <div>
                <h3 className="text-lg font-bold text-gray-900">编辑商品详情</h3>
                <p className="mt-1 line-clamp-1 text-sm text-gray-500">{detailItem.item_title || detailItem.item_id}</p>
              </div>
              <button type="button" onClick={() => setDetailItem(null)} className="rounded-md p-2 hover:bg-gray-100" aria-label="关闭">
                <X className="h-5 w-5" />
              </button>
            </div>
            <div className="modal-body">
              <label className="mb-2 block text-sm font-bold text-gray-700" htmlFor="item-detail">本地商品详情</label>
              <textarea
                id="item-detail"
                value={itemDetail}
                onChange={event => setItemDetail(event.target.value)}
                className="ios-input min-h-64 w-full resize-y rounded-md p-3 font-mono text-sm"
                placeholder="补充商品说明，供自动回复和发货逻辑读取。"
              />
            </div>
            <div className="modal-footer flex justify-end gap-2">
              <button type="button" onClick={() => setDetailItem(null)} className="ios-btn-secondary rounded-md px-4 py-2.5">取消</button>
              <button
                type="button"
                onClick={handleSaveDetail}
                disabled={Boolean(savingKey)}
                className="ios-btn-primary flex items-center gap-2 rounded-md px-4 py-2.5"
              >
                {savingKey ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                保存
              </button>
            </div>
          </div>
        </div>,
        document.body,
      )}

      {showManualModal && createPortal(
        <div className="modal-overlay">
          <div className="modal-container">
            <div className="modal-header flex items-start justify-between gap-4">
              <div>
                <h3 className="text-lg font-bold text-gray-900">手动添加商品</h3>
                <p className="mt-1 text-sm text-gray-500">适用于暂未同步到列表、但需要配置自动发货的商品。</p>
              </div>
              <button type="button" onClick={() => setShowManualModal(false)} className="rounded-md p-2 hover:bg-gray-100" aria-label="关闭">
                <X className="h-5 w-5" />
              </button>
            </div>
            <div className="modal-body grid grid-cols-1 gap-4 sm:grid-cols-2">
              <div className="sm:col-span-2">
                <label className="mb-2 block text-sm font-bold text-gray-700" htmlFor="manual-account">所属账号</label>
                <select
                  id="manual-account"
                  value={manualForm.cookieId}
                  onChange={event => setManualForm(current => ({ ...current, cookieId: event.target.value }))}
                  className="ios-input w-full rounded-md px-3 py-2.5"
                >
                  <option value="">请选择账号</option>
                  {accounts.map(account => (
                    <option key={account.id} value={account.id}>{accountNames.get(account.id)}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="mb-2 block text-sm font-bold text-gray-700" htmlFor="manual-item-id">商品 ID</label>
                <input
                  id="manual-item-id"
                  value={manualForm.itemId}
                  onChange={event => setManualForm(current => ({ ...current, itemId: event.target.value }))}
                  className="ios-input w-full rounded-md px-3 py-2.5"
                  placeholder="例如 1070863591807"
                />
              </div>
              <div>
                <label className="mb-2 block text-sm font-bold text-gray-700" htmlFor="manual-price">价格</label>
                <input
                  id="manual-price"
                  value={manualForm.price}
                  onChange={event => setManualForm(current => ({ ...current, price: event.target.value }))}
                  className="ios-input w-full rounded-md px-3 py-2.5"
                  placeholder="例如 80"
                />
              </div>
              <div className="sm:col-span-2">
                <label className="mb-2 block text-sm font-bold text-gray-700" htmlFor="manual-title">商品标题</label>
                <input
                  id="manual-title"
                  value={manualForm.title}
                  onChange={event => setManualForm(current => ({ ...current, title: event.target.value }))}
                  className="ios-input w-full rounded-md px-3 py-2.5"
                />
              </div>
              <div className="sm:col-span-2">
                <label className="mb-2 block text-sm font-bold text-gray-700" htmlFor="manual-image">图片 URL</label>
                <input
                  id="manual-image"
                  value={manualForm.imageUrl}
                  onChange={event => setManualForm(current => ({ ...current, imageUrl: event.target.value }))}
                  className="ios-input w-full rounded-md px-3 py-2.5"
                  placeholder="https://..."
                />
              </div>
              <div className="sm:col-span-2">
                <label className="mb-2 block text-sm font-bold text-gray-700" htmlFor="manual-description">商品简介</label>
                <input
                  id="manual-description"
                  value={manualForm.description}
                  onChange={event => setManualForm(current => ({ ...current, description: event.target.value }))}
                  className="ios-input w-full rounded-md px-3 py-2.5"
                />
              </div>
              <div className="sm:col-span-2">
                <label className="mb-2 block text-sm font-bold text-gray-700" htmlFor="manual-detail">本地详情</label>
                <textarea
                  id="manual-detail"
                  value={manualForm.detail}
                  onChange={event => setManualForm(current => ({ ...current, detail: event.target.value }))}
                  className="ios-input min-h-28 w-full resize-y rounded-md p-3"
                />
              </div>
            </div>
            <div className="modal-footer flex justify-end gap-2">
              <button type="button" onClick={() => setShowManualModal(false)} className="ios-btn-secondary rounded-md px-4 py-2.5">
                取消
              </button>
              <button
                type="button"
                onClick={handleCreateManualItem}
                disabled={savingKey === 'manual-item'}
                className="ios-btn-primary flex items-center gap-2 rounded-md px-4 py-2.5"
              >
                {savingKey === 'manual-item' ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
                添加商品
              </button>
            </div>
          </div>
        </div>,
        document.body,
      )}
    </div>
  );
};

export default ItemList;
