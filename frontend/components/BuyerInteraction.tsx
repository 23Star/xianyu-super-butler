import React, { useEffect, useState } from 'react';
import { Star, Flower2, Save, RefreshCw, ShieldAlert, MessageSquareText } from 'lucide-react';

import {
  getSystemSettings,
  updateSystemSettings,
  getSellerFeatureFlags,
  updateSellerFeatureFlags,
  getAccountDetails,
  BuyerInteractionFlags,
} from '../services/api';
import { notify } from '../services/feedback';
import { AccountDetail, SystemSettings } from '../types';
import { NoticeBanner, PageHeader, PageLoading, SectionHeader } from './ui';

const MAX_TEMPLATE_LENGTH = 200;

const DEFAULT_TEMPLATE = '宝贝收到了，很满意，感谢老板，欢迎下次再来！';

const DEFAULT_THANKS = '亲，感谢支持！有任何问题随时找我~';

const SWITCH_LABELS = {
  auto_rate_enabled: '评价买家',
  auto_flower_enabled: '索要小红花',
  auto_thanks_enabled: '收货致谢',
} as const;

/** 兜底轮询间隔。确认收货已由消息事件即时触发，这里只是漏收消息时的补救，
 *  所以给的都是偏长的档位；太频繁会因反复拉取卖出订单列表而招来风控。 */
const INTERVAL_OPTIONS = [
  { value: 300, label: '5 分钟' },
  { value: 900, label: '15 分钟' },
  { value: 1800, label: '30 分钟' },
  { value: 3600, label: '1 小时' },
  { value: 7200, label: '2 小时（默认）' },
  { value: 21600, label: '6 小时' },
  { value: 86400, label: '24 小时' },
];

/**
 * 买家互动。
 *
 * 评价和求花会对买家产生真实且不可撤销的动作，之前藏在系统设置的一个分区里，
 * 用起来不好找。单独成页，顺便把默认评价文案也放进来——原先每单都要重新手打。
 */
const BuyerInteraction: React.FC = () => {
  const [settings, setSettings] = useState<SystemSettings | null>(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  // 开关按账号存：不同账号经营策略不同，不能一开就是全部账号一起开
  const [accounts, setAccounts] = useState<AccountDetail[]>([]);
  const [flagsByAccount, setFlagsByAccount] = useState<Record<string, BuyerInteractionFlags>>({});

  const load = () => {
    setLoading(true);
    Promise.all([
      getSystemSettings(),
      // 模板有内置默认值，只存在于接口返回里，系统设置接口可能还没有这一项
      getSellerFeatureFlags().catch(() => null),
      getAccountDetails().catch(() => [] as AccountDetail[]),
    ])
      .then(([base, flags, accountList]) => {
        setSettings({
          ...base,
          auto_rate_template:
            (base.auto_rate_template ?? '').trim() || flags?.auto_rate_template || DEFAULT_TEMPLATE,
        });
        setAccounts(accountList);
        setFlagsByAccount(flags?.accounts ?? {});
      })
      .finally(() => setLoading(false));
  };

  /** 开关立即生效并落库，不跟「保存设置」耦合 —— 逐账号勾选时每次都点保存太啰嗦。 */
  const toggleAccountFlag = async (
    cookieId: string,
    key: keyof BuyerInteractionFlags,
  ) => {
    const current = flagsByAccount[cookieId] ?? {
      auto_rate_enabled: false,
      auto_flower_enabled: false,
      auto_thanks_enabled: false,
    };
    const next = { ...current, [key]: !current[key] };
    setFlagsByAccount(prev => ({ ...prev, [cookieId]: next }));
    try {
      await updateSellerFeatureFlags(cookieId, { [key]: next[key] });
    } catch (error) {
      // 失败要回滚，否则界面显示的和后端存的不一致
      setFlagsByAccount(prev => ({ ...prev, [cookieId]: current }));
      notify(`保存失败：${(error as Error).message}`);
    }
  };

  useEffect(() => { load(); }, []);

  const handleSave = async () => {
    if (!settings) return;
    const template = (settings.auto_rate_template || '').trim();
    if (!template) {
      notify('默认评价内容不能为空');
      return;
    }
    if (template.length > MAX_TEMPLATE_LENGTH) {
      notify(`默认评价内容不能超过 ${MAX_TEMPLATE_LENGTH} 字`);
      return;
    }

    setSaving(true);
    try {
      // 开关已按账号即时保存，这里只提交全账号共用的文案与兜底间隔
      await updateSystemSettings({
        auto_rate_template: template,
        auto_thanks_template: (settings.auto_thanks_template || '').trim(),
        buyer_interaction_interval: String(interval),
      });
      notify('买家互动配置已保存');
    } catch (error) {
      notify(`保存失败：${(error as Error).message}`);
    } finally {
      setSaving(false);
    }
  };

  if (!settings) return <PageLoading label="正在加载买家互动配置" />;

  const accountFlags = (cookieId: string): BuyerInteractionFlags =>
    flagsByAccount[cookieId] ?? {
      auto_rate_enabled: false,
      auto_flower_enabled: false,
      auto_thanks_enabled: false,
    };
  // 只要有账号开了评价，就允许编辑共用的评价文案
  const rateEnabled = accounts.some(account => accountFlags(account.id).auto_rate_enabled);
  const thanksEnabled = accounts.some(account => accountFlags(account.id).auto_thanks_enabled);
  const template = settings.auto_rate_template ?? '';
  const thanksTemplate = settings.auto_thanks_template ?? '';
  const interval = Number(settings.buyer_interaction_interval) || 7200;

  return (
    <div className="page-stack animate-fade-in">
      <PageHeader
        title="买家互动"
        description="评价买家与索要小红花。这两项会对买家产生实际动作，开启前请确认。"
        icon={Star}
        actions={(
          <>
            <button
              type="button"
              onClick={load}
              disabled={loading}
              className="ios-btn-secondary flex items-center justify-center gap-2 rounded-md px-4 py-2 text-sm"
            >
              <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
              刷新
            </button>
            <button
              type="button"
              onClick={() => void handleSave()}
              disabled={saving}
              className="ios-btn-primary flex items-center justify-center gap-2 rounded-md px-4 py-2 text-sm"
            >
              <Save className="h-4 w-4" />
              {saving ? '保存中' : '保存设置'}
            </button>
          </>
        )}
      />

      <NoticeBanner
        type="warning"
        message="评价提交后无法撤销，求花会向买家发送一条消息。建议先用测试订单验证效果。"
      />

      <div className="grid gap-4 xl:grid-cols-2">
        <section className="section-panel">
          <SectionHeader
            title="按账号开启"
            description="逐个账号控制。关闭的账号不会自动执行，订单页也不显示入口、后端拒绝请求。"
            icon={ShieldAlert}
          />
          {accounts.length === 0 ? (
            <p className="px-4 py-6 text-sm text-gray-500">还没有账号，请先在账号管理里添加。</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-gray-200 text-left text-xs text-gray-500">
                    <th className="px-4 py-2 font-semibold">账号</th>
                    <th className="px-4 py-2 text-center font-semibold">评价买家</th>
                    <th className="px-4 py-2 text-center font-semibold">索要小红花</th>
                    <th className="px-4 py-2 text-center font-semibold">收货致谢</th>
                  </tr>
                </thead>
                <tbody>
                  {accounts.map(account => {
                    const flags = accountFlags(account.id);
                    return (
                      <tr key={account.id} className="border-b border-gray-100 last:border-b-0">
                        <td className="px-4 py-3">
                          <p className="font-semibold text-gray-900">
                            {account.nickname || account.id}
                          </p>
                          <p className="mt-0.5 font-mono text-xs text-gray-400">{account.id}</p>
                        </td>
                        {([
                          'auto_rate_enabled',
                          'auto_flower_enabled',
                          'auto_thanks_enabled',
                        ] as const).map(key => (
                          <td key={key} className="px-4 py-3 text-center">
                            <button
                              type="button"
                              role="switch"
                              aria-checked={flags[key]}
                              aria-label={`${account.nickname || account.id} ${
                                SWITCH_LABELS[key]
                              }`}
                              onClick={() => void toggleAccountFlag(account.id, key)}
                              className={`relative h-6 w-11 shrink-0 rounded-full transition-colors ${
                                flags[key] ? 'bg-[#ffe100]' : 'bg-gray-300'
                              }`}
                            >
                              <span
                                className={`absolute left-1 top-1 h-4 w-4 rounded-full bg-white transition-transform ${
                                  flags[key] ? 'translate-x-5' : ''
                                }`}
                              />
                            </button>
                          </td>
                        ))}
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
          <p className="border-t border-gray-100 px-4 py-3 text-xs leading-5 text-gray-500">
            三项都在<strong className="font-semibold text-gray-700">买家确认收货</strong>后触发。
            致谢文本立即发送；评价和求花要等闲鱼把订单切到「交易成功」，通常几十秒内完成，
            失败则由下面的兜底轮询稍后重试。
          </p>
        </section>

        <section className="section-panel">
          <SectionHeader
            title="默认评价内容"
            description="订单页打开评价框时自动填入，仍可逐单修改后再提交。"
            icon={Flower2}
          />
          <div className="px-4 py-3">
            <label className="field-label">评价文案</label>
            <textarea
              value={template}
              onChange={e => setSettings({ ...settings, auto_rate_template: e.target.value })}
              maxLength={MAX_TEMPLATE_LENGTH}
              placeholder={DEFAULT_TEMPLATE}
              className="ios-input mt-1 min-h-28 w-full resize-y rounded-md px-3 py-2.5 text-sm"
              disabled={!rateEnabled}
            />
            <div className="mt-1 flex items-center justify-between">
              <span className="text-xs text-gray-500">
                {rateEnabled ? '闲鱼对评价内容有长度和内容限制，过长可能被拒绝。' : '为任一账号开启「评价买家」后可编辑。'}
              </span>
              <span className="text-xs text-gray-400">{template.length}/{MAX_TEMPLATE_LENGTH}</span>
            </div>
          </div>
        </section>

        <section className="section-panel">
          <SectionHeader
            title="收货致谢文本"
            description="买家确认收货后立即发送这条消息。留空则不发送。"
            icon={MessageSquareText}
          />
          <div className="px-4 py-3">
            <label className="field-label">致谢文案</label>
            <textarea
              value={thanksTemplate}
              onChange={e => setSettings({ ...settings, auto_thanks_template: e.target.value })}
              maxLength={MAX_TEMPLATE_LENGTH}
              placeholder={DEFAULT_THANKS}
              className="ios-input mt-1 min-h-28 w-full resize-y rounded-md px-3 py-2.5 text-sm"
              disabled={!thanksEnabled}
            />
            <div className="mt-1 flex items-center justify-between">
              <span className="text-xs text-gray-500">
                {thanksEnabled
                  ? '同一笔交易只发一次，不会因多条系统消息重复打扰买家。'
                  : '为任一账号开启「收货致谢」后可编辑。'}
              </span>
              <span className="text-xs text-gray-400">
                {thanksTemplate.length}/{MAX_TEMPLATE_LENGTH}
              </span>
            </div>
          </div>
        </section>

        <section className="section-panel">
          <SectionHeader
            title="兜底检查间隔"
            description="确认收货已由消息事件即时触发，这里只在漏收消息或服务重启时补做。"
            icon={RefreshCw}
          />
          <div className="px-4 py-3">
            <label className="field-label">检查频率</label>
            <select
              value={interval}
              onChange={e => setSettings({
                ...settings,
                buyer_interaction_interval: e.target.value,
              })}
              className="ios-input mt-1 w-full rounded-md px-3 py-2.5 text-sm"
            >
              {INTERVAL_OPTIONS.map(option => (
                <option key={option.value} value={option.value}>{option.label}</option>
              ))}
            </select>
            <p className="mt-1 text-xs leading-5 text-gray-500">
              每轮都会拉取一次卖出订单列表，设得太密容易触发平台风控。
              正常情况下靠即时触发就够了，这里保持较长间隔即可。
            </p>
          </div>
        </section>
      </div>
    </div>
  );
};

export default BuyerInteraction;
