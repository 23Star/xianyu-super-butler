import { Fragment, useCallback, useEffect, useMemo, useState } from 'react';
import {
  Bot,
  CheckCircle2,
  CircleAlert,
  FileSpreadsheet,
  RefreshCw,
  Save,
  Trash2,
  Upload,
} from 'lucide-react';
import {
  deleteRouteImport,
  getAgentSettings,
  getAgentStatus,
  importRouteBook,
  listRouteImports,
  saveAgentSettings,
  type AgentRouteImport,
  type AgentSettings,
  type AgentStatus,
} from '../../../services/logisticsAgent';
import { getAccountDetails } from '../../../services/api';
import { extractParseError, supportedQuoteFilePattern } from '../../../services/logisticsQuote';
import { buildAgentSeed, hasLegacyQuoteConfig } from '../../../utils/agentSettingsSeed';
import FloatingSaveButton from '../../FloatingSaveButton';
import { CollapsibleSection } from '../../ui';
import QuoteAgentTestChat from './QuoteAgentTestChat';
const MODEL_OPTIONS = [
  { value: 'deepseek-v4-flash', label: 'DeepSeek V4 Flash（默认，更快）' },
  { value: 'deepseek-v4-pro', label: 'DeepSeek V4 Pro（更准）' },
];

const ACCOUNT_STORAGE_KEY = 'logistics_quote_agent_account_v1';

/** 记住上次选择的账号，刷新或切换步骤回来时默认选中同一账号。 */
const loadStoredAccountId = (): string => {
  try {
    return window.localStorage.getItem(ACCOUNT_STORAGE_KEY) || '';
  } catch {
    return '';
  }
};

const storeAccountId = (cookieId: string) => {
  try {
    window.localStorage.setItem(ACCOUNT_STORAGE_KEY, cookieId);
  } catch {
    // localStorage 不可用（如隐私模式）时退化为本次会话内生效。
  }
};

/** 仅 Agent 独有的文案；报价、差价、引导、追问、首次回复沿用第二/三步配置。 */
const TEMPLATE_FIELDS: Array<{ key: keyof AgentSettings['templates']; label: string; hint: string }> = [
  { key: 'no_route', label: '无匹配线路', hint: '查不到线路时发送，{发货省} {收货省} 为买家地址' },
  { key: 'failure', label: '报价失败', hint: '计算失败或引擎异常时发送' },
];

const formatDateTime = (value: string | null) =>
  value ? new Date(value.replace(' ', 'T')).toLocaleString('zh-CN', { hour12: false }) : '—';

type AgentSeed = ReturnType<typeof buildAgentSeed>;

interface QuoteAgentPanelProps {
  onNavigateStep?: (step: 'settings' | 'apply') => void;
}

/** 把第二/三步带入的配置合并到 Agent 配置：覆盖金额、抛比与模板，其余字段保留。 */
const mergeSeed = (
  base: AgentSettings,
  seed: NonNullable<AgentSeed>,
): AgentSettings => ({
  ...base,
  ...seed,
  pricing: { ...base.pricing, ...seed.pricing },
  default_volume_ratios: seed.default_volume_ratios,
  templates: { ...base.templates, ...seed.templates },
});

const QuoteAgentPanel = ({ onNavigateStep }: QuoteAgentPanelProps) => {
  const [accounts, setAccounts] = useState<Array<{ id: string; label: string }>>([]);
  const [cookieId, setCookieId] = useState('');
  const [settings, setSettings] = useState<AgentSettings | null>(null);
  const [savedSettings, setSavedSettings] = useState<AgentSettings | null>(null);
  const [imports, setImports] = useState<AgentRouteImport[]>([]);
  const [status, setStatus] = useState<AgentStatus | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isImporting, setIsImporting] = useState(false);
  const [isDeletingId, setIsDeletingId] = useState<number | null>(null);
  const [isChecking, setIsChecking] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [errorMessage, setErrorMessage] = useState('');
  const [infoMessage, setInfoMessage] = useState('');

  const refreshImports = useCallback(async () => {
    try {
      const response = await listRouteImports();
      setImports(response.imports);
    } catch {
      setImports([]);
    }
  }, []);

  const loadForAccount = useCallback(async (target: string) => {
    if (!target) return;
    setIsLoading(true);
    setErrorMessage('');
    setInfoMessage('');
    try {
      const [settingsResponse] = await Promise.all([getAgentSettings(target), refreshImports()]);
      let incoming = settingsResponse.settings;
      // 首次配置账号时带入第二/三步的金额、抛比和模板。已有第五步配置时
      // 保留店家已经编辑过的第五步模板，避免进入页面时被默认文案覆盖。
      const seed = buildAgentSeed(target);
      if (seed) {
        if (!settingsResponse.has_saved_settings) {
          incoming = mergeSeed(incoming, seed);
          setInfoMessage('已带入第二/三步的金额构成、抛比与回复模板，点击保存生效');
        } else {
          incoming = {
            ...incoming,
            pricing: { ...incoming.pricing, ...seed.pricing },
            default_volume_ratios: seed.default_volume_ratios,
            carrier_config: seed.carrier_config,
          };
          setInfoMessage('已同步第二步金额与抛比；第五步自定义模板已保留');
        }
      }
      setSettings(incoming);
      setSavedSettings(settingsResponse.settings);
    } catch (error) {
      setSettings(null);
      setSavedSettings(null);
      setErrorMessage(extractParseError(error));
    } finally {
      setIsLoading(false);
    }
  }, [refreshImports]);

  useEffect(() => {
    void (async () => {
      try {
        const details = await getAccountDetails();
        const mapped = details.map((account) => ({
          id: account.id,
          label: account.nickname || account.remark || account.id,
        }));
        setAccounts(mapped);
        if (mapped.length) {
          const stored = loadStoredAccountId();
          setCookieId((current) => {
            if (current) return current;
            return mapped.some((account) => account.id === stored) ? stored : mapped[0].id;
          });
        }
      } catch {
        setErrorMessage('读取账号列表失败，请刷新重试');
      }
    })();
  }, []);

  useEffect(() => {
    if (cookieId) storeAccountId(cookieId);
  }, [cookieId]);

  useEffect(() => {
    if (cookieId) void loadForAccount(cookieId);
  }, [cookieId, loadForAccount]);

  const dirty = useMemo(
    () => settings !== null && savedSettings !== null && JSON.stringify(settings) !== JSON.stringify(savedSettings),
    [settings, savedSettings],
  );

  const updateSettings = (patch: Partial<AgentSettings>) => {
    setSettings((prev) => (prev ? { ...prev, ...patch } : prev));
  };

  const updateTemplate = (field: keyof AgentSettings['templates'], value: string) => {
    setSettings((prev) => (prev ? { ...prev, templates: { ...prev.templates, [field]: value } } : prev));
  };

  const handleSeedFromLegacy = () => {
    if (!settings) return;
    const seed = buildAgentSeed(cookieId);
    if (!seed) {
      setInfoMessage('第二/三步还没有与默认不同的配置，无需带入');
      return;
    }
    setSettings((prev) => (prev ? mergeSeed(prev, seed) : prev));
    setInfoMessage('已带入第二/三步的金额构成、抛比与回复模板，保存后生效');
  };

  const toggleBook = (bookId: number) => {
    setSettings((prev) => {
      if (!prev) return prev;
      const selected = new Set(prev.book_ids);
      if (selected.has(bookId)) selected.delete(bookId);
      else selected.add(bookId);
      return { ...prev, book_ids: [...selected] };
    });
  };

  const handleSave = async () => {
    if (!settings || !cookieId || isSaving) return;
    setIsSaving(true);
    setErrorMessage('');
    try {
      const response = await saveAgentSettings(cookieId, settings);
      setSettings(response.settings);
      setSavedSettings(response.settings);
      setInfoMessage('物流 Agent 配置已保存');
      void refreshStatus();
    } catch (error) {
      setErrorMessage(extractParseError(error));
    } finally {
      setIsSaving(false);
    }
  };

  const refreshStatus = useCallback(async () => {
    if (!cookieId) return;
    setIsChecking(true);
    try {
      const response = await getAgentStatus(cookieId);
      setStatus(response);
    } catch (error) {
      setStatus(null);
      setErrorMessage(extractParseError(error));
    } finally {
      setIsChecking(false);
    }
  }, [cookieId]);

  useEffect(() => {
    if (cookieId) void refreshStatus();
  }, [cookieId, refreshStatus]);

  const handleImport = async (file: File) => {
    if (isImporting) return;
    if (!supportedQuoteFilePattern.test(file.name)) {
      setErrorMessage(`仅支持 .xlsx、.xlsm、.xls 或 .csv 格式的报价表：${file.name}`);
      return;
    }
    setIsImporting(true);
    setErrorMessage('');
    setInfoMessage(`正在解析并导入「${file.name}」的全部线路，大文件可能需要一点时间…`);
    try {
      const response = await importRouteBook(file);
      setInfoMessage(`「${file.name}」已导入 ${response.import.route_count} 条线路`);
      await refreshImports();
      void refreshStatus();
    } catch (error) {
      setInfoMessage('');
      setErrorMessage(extractParseError(error));
    } finally {
      setIsImporting(false);
    }
  };

  const handleDeleteImport = async (importId: number) => {
    if (isDeletingId !== null) return;
    setIsDeletingId(importId);
    try {
      await deleteRouteImport(importId);
      setImports((prev) => prev.filter((item) => item.id !== importId));
      void refreshStatus();
    } catch (error) {
      setErrorMessage(extractParseError(error));
    } finally {
      setIsDeletingId(null);
    }
  };

  return (
    <div className="logistics-page page-stack">
      <CollapsibleSection
        title="选择账号"
        description="物流 Agent 按闲鱼账号分别启用，配置保存在服务端，所有设备一致。"
        icon={Bot}
      >
        <div className="p-4">
          <label className="flex flex-wrap items-center gap-2 text-sm">
            <span className="field-label shrink-0">账号</span>
            <select
              value={cookieId}
              onChange={(event) => setCookieId(event.target.value)}
              className="ios-input min-w-0 flex-1 rounded-md px-3 py-2 text-sm sm:flex-none"
              aria-label="选择闲鱼账号"
            >
              {accounts.map((account) => (
                <option key={account.id} value={account.id}>{account.label}</option>
              ))}
            </select>
          </label>
        </div>
      </CollapsibleSection>

      {errorMessage && (
        <p className="rounded-md border border-[color:color-mix(in_srgb,var(--danger)_34%,var(--border))] bg-[var(--danger-soft)] px-3 py-2.5 text-[13px] leading-normal text-[var(--danger-ink)]" role="alert">
          {errorMessage}
        </p>
      )}
      {infoMessage && (
        <p className="rounded-md border border-[color:color-mix(in_srgb,var(--brand)_34%,var(--border))] bg-[var(--brand-soft)] px-3 py-2.5 text-[13px] leading-normal text-[var(--brand-text)]" role="status">
          {infoMessage}
        </p>
      )}

      <CollapsibleSection
        title="线路报价表明细"
        description="Agent 按收发地匹配这里的真实线路价格；第一步识别报价表时会自动同步线路明细，也可以在这里手动导入。"
        icon={FileSpreadsheet}
        actions={(
          <label className={`ios-btn-secondary flex cursor-pointer items-center gap-2 rounded-md px-3.5 py-2 text-sm ${isImporting ? 'pointer-events-none opacity-50' : ''}`}>
            <Upload className="h-4 w-4" aria-hidden="true" />
            <span>{isImporting ? '导入中' : '导入报价表'}</span>
            <input
              type="file"
              accept=".xlsx,.xlsm,.xls,.csv"
              className="sr-only"
              onChange={(event) => {
                const file = event.target.files?.[0];
                event.target.value = '';
                if (file) void handleImport(file);
              }}
              disabled={isImporting}
            />
          </label>
        )}
      >
        <div className="grid gap-3 p-4">
          {imports.length === 0 ? (
            <p className="text-[13px] leading-relaxed text-[var(--text-muted)]">
              尚未同步线路明细。回到第一步上传报价表即可自动同步到这里，也可以点击右上角直接导入同一份文件。
            </p>
          ) : (
            <ul className="grid gap-2">
              {imports.map((item) => (
                <li key={item.id} className="flex flex-wrap items-center gap-x-4 gap-y-1 rounded-md border border-[var(--border)] bg-[var(--surface-subtle)] px-3.5 py-2.5 text-[13px]">
                  <span className="font-bold text-[var(--text)]">{item.filename}</span>
                  <span className="text-[var(--text-muted)]">{item.book_kind === 'logistics' ? '物流' : '快递'} · {item.route_count} 条线路</span>
                  <span className="text-[var(--text-muted)]">导入于 {formatDateTime(item.created_at)}</span>
                  <button
                    type="button"
                    className="ml-auto inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-xs text-[var(--danger-ink)] hover:bg-[var(--danger-soft)]"
                    onClick={() => void handleDeleteImport(item.id)}
                    disabled={isDeletingId === item.id}
                  >
                    <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
                    删除
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </CollapsibleSection>

      {settings && (
        <CollapsibleSection
          title="Agent 配置"
          description="开启后，买家的物流询价消息会自动识别参数、匹配线路并按模板报价；普通咨询仍走通用 AI 回复。"
          icon={Bot}
          actions={(
            <button
              type="button"
              className="ios-btn-secondary rounded-md px-3.5 py-2 text-sm"
              onClick={handleSeedFromLegacy}
            >
              带入第二/三步配置
            </button>
          )}
        >
          <div className="grid gap-4 p-4">
            <div className="grid gap-3 sm:grid-cols-2">
              <label className="flex items-center justify-between gap-3 rounded-md border border-[var(--border)] bg-[var(--surface-subtle)] px-3.5 py-3">
                <span className="text-sm font-bold text-[var(--text)]">启用自动报价</span>
                <input
                  type="checkbox"
                  checked={settings.enabled}
                  onChange={(event) => updateSettings({ enabled: event.target.checked })}
                  className="ios-switch"
                  aria-label="启用自动报价"
                />
              </label>
              <label className="flex items-center justify-between gap-3 rounded-md border border-[var(--border)] bg-[var(--surface-subtle)] px-3.5 py-3">
                <span className="text-sm font-bold text-[var(--text)]">自动发送报价</span>
                <input
                  type="checkbox"
                  checked={settings.auto_send}
                  onChange={(event) => updateSettings({ auto_send: event.target.checked })}
                  className="ios-switch"
                  aria-label="自动发送报价"
                />
              </label>
            </div>

            <div className="grid gap-3 sm:grid-cols-2">
              <label>
                <span className="field-label">识别模型</span>
                <select
                  value={settings.model_name}
                  onChange={(event) => updateSettings({ model_name: event.target.value })}
                  className="ios-input w-full rounded-md px-3 py-2.5 text-sm"
                >
                  {MODEL_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>{option.label}</option>
                  ))}
                </select>
              </label>
              <label>
                <span className="field-label">推荐渠道</span>
                <select
                  value={settings.recommend_mode}
                  onChange={(event) => updateSettings({ recommend_mode: event.target.value as AgentSettings['recommend_mode'] })}
                  className="ios-input w-full rounded-md px-3 py-2.5 text-sm"
                >
                  <option value="lowest">推荐最低应付金额渠道</option>
                  <option value="all">展示全部可报渠道</option>
                </select>
              </label>
            </div>

            <div className="grid gap-3 sm:grid-cols-2">
              <label>
                <span className="field-label">无匹配线路时</span>
                <select
                  value={settings.no_route_policy}
                  onChange={(event) => updateSettings({ no_route_policy: event.target.value as AgentSettings['no_route_policy'] })}
                  className="ios-input w-full rounded-md px-3 py-2.5 text-sm"
                >
                  <option value="manual">回复转人工提示</option>
                  <option value="silent">仅记录草稿，不回复</option>
                </select>
              </label>
              <label>
                <span className="field-label">生效商品</span>
                <select
                  value={settings.item_scope}
                  onChange={(event) => updateSettings({ item_scope: event.target.value as AgentSettings['item_scope'] })}
                  className="ios-input w-full rounded-md px-3 py-2.5 text-sm"
                >
                  <option value="all">全部商品</option>
                  <option value="custom">仅指定商品</option>
                </select>
              </label>
            </div>

            {settings.item_scope === 'custom' && (
              <label>
                <span className="field-label">指定商品 ID（每行一个）</span>
                <textarea
                  value={settings.item_ids.join('\n')}
                  onChange={(event) => updateSettings({ item_ids: event.target.value.split('\n').map((item) => item.trim()).filter(Boolean) })}
                  rows={3}
                  placeholder="在售商品的商品 ID，可在商品管理里查看"
                  className="ios-input w-full rounded-md px-3 py-2.5 text-sm"
                />
              </label>
            )}

            {imports.length > 0 && (
              <fieldset className="rounded-md border border-[var(--border)] bg-[var(--surface-subtle)] p-3.5">
                <legend className="field-label px-1">使用的报价表（不选默认全部）</legend>
                <div className="mt-1 grid gap-2">
                  {imports.map((item) => (
                    <label key={item.id} className="flex items-center gap-2.5 text-[13px] text-[var(--text)]">
                      <input
                        type="checkbox"
                        checked={settings.book_ids.includes(item.id)}
                        onChange={() => toggleBook(item.id)}
                        className="ios-checkbox"
                      />
                      <span>{item.filename}</span>
                      <span className="text-[var(--text-muted)]">{item.book_kind === 'logistics' ? '物流' : '快递'} · {item.route_count} 条</span>
                    </label>
                  ))}
                </div>
              </fieldset>
            )}

            <details className="rounded-md border border-[var(--border)] bg-[var(--surface-subtle)] p-3.5">
              <summary className="cursor-pointer text-sm font-bold text-[var(--text)]">Agent 专属文案（支持 {'{分隔符}'} 拆分多条消息）</summary>
              <p className="mt-3 text-[13px] leading-relaxed text-[var(--text-muted)]">
                报价消息、差价、引导拍下、缺参追问、首次回复等文案沿用第二步
                <button
                  type="button"
                  onClick={() => onNavigateStep?.('settings')}
                  className="font-bold text-[var(--brand-text)] hover:underline"
                >
                  「报价设置」
                </button>
                和第三步
                <button
                  type="button"
                  onClick={() => onNavigateStep?.('apply')}
                  className="font-bold text-[var(--brand-text)] hover:underline"
                >
                  「消息模板」
                </button>
                的配置；渠道规则统一在第二步「报价设置」维护并自动同步到这里。
              </p>
              <div className="mt-3 grid gap-3">
                {TEMPLATE_FIELDS.map((field) => (
                  <label key={field.key}>
                    <span className="field-label">{field.label}</span>
                    <textarea
                      value={settings.templates[field.key]}
                      onChange={(event) => updateTemplate(field.key, event.target.value)}
                      rows={2}
                      placeholder={field.hint}
                      className="ios-input w-full rounded-md px-3 py-2.5 text-sm"
                    />
                    <span className="mt-1 block text-xs text-[var(--text-muted)]">{field.hint}</span>
                  </label>
                ))}
              </div>
            </details>
          </div>
        </CollapsibleSection>
      )}

      <CollapsibleSection
        title="启用前检测"
        description="确认报价表、计算引擎、模板与账号都就绪后再开启自动报价。"
        icon={CheckCircle2}
        actions={(
          <button
            type="button"
            className="ios-btn-secondary flex items-center gap-2 rounded-md px-3.5 py-2 text-sm disabled:cursor-not-allowed disabled:opacity-45"
            onClick={() => void refreshStatus()}
            disabled={isChecking || !cookieId}
          >
            <RefreshCw className={`h-4 w-4 ${isChecking ? 'animate-spin' : ''}`} aria-hidden="true" />
            <span>{isChecking ? '检测中' : '重新检测'}</span>
          </button>
        )}
      >
        {status ? (
          <div className="grid gap-2 p-4">
            <div className={`flex items-center gap-2 rounded-md px-3.5 py-2.5 text-sm font-bold ${status.ready ? 'text-[var(--success-ink)]' : 'text-[var(--danger-ink)]'}`}>
              {status.ready ? <CheckCircle2 className="h-4 w-4" aria-hidden="true" /> : <CircleAlert className="h-4 w-4" aria-hidden="true" />}
              <span>{status.ready ? '全部检测通过，可以启用自动报价' : '还有未通过的检测项，处理后再启用'}</span>
            </div>
            <ul className="grid gap-2">
              {status.checks.map((check) => (
                <li key={check.key} className="flex items-start gap-2.5 rounded-md border border-[var(--border)] bg-[var(--surface-subtle)] px-3.5 py-2.5 text-[13px]">
                  {check.passed ? (
                    <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-[var(--success)]" aria-hidden="true" />
                  ) : (
                    <CircleAlert className="mt-0.5 h-4 w-4 shrink-0 text-[var(--danger)]" aria-hidden="true" />
                  )}
                  <div>
                    <strong className="text-[var(--text)]">{check.label}</strong>
                    <span className="block text-[var(--text-muted)]">{check.detail}</span>
                  </div>
                </li>
              ))}
            </ul>
          </div>
        ) : (
          <p className="p-4 text-[13px] text-[var(--text-muted)]">选择账号后自动检测。</p>
        )}
      </CollapsibleSection>

      {/* 按账号重建测试会话：切换账号时完整切换 thread 与气泡上下文。 */}
      {cookieId && (
        <Fragment key={cookieId}>
          <QuoteAgentTestChat cookieId={cookieId} />
        </Fragment>
      )}

      {settings && (
        <FloatingSaveButton
          dirty={dirty}
          guardKey={`logistics-agent-${cookieId}`}
          guardLabel="物流 Agent 配置"
          label="保存配置"
          onSave={() => void handleSave()}
          onDiscard={() => setSettings(savedSettings ? { ...savedSettings } : null)}
        />
      )}
      {isSaving && <Save className="hidden" aria-hidden="true" />}
    </div>
  );
};

export default QuoteAgentPanel;
