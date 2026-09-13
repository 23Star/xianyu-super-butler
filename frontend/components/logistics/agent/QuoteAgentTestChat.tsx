import { useCallback, useEffect, useRef, useState } from 'react';
import { Check, CheckCircle2, Eraser, LoaderCircle, MessagesSquare, Plus, ScanSearch } from 'lucide-react';
import {
  createAgentThread,
  deleteAgentThread,
  fetchAgentThread,
  runAgentTest,
  type AgentTestDecision,
} from '../../../services/logisticsAgent';
import { SectionHeader } from '../../ui';
import QuoteAgentTraining from './QuoteAgentTraining';

interface TestTurn {
  role: 'buyer' | 'agent';
  text: string;
  decision?: AgentTestDecision;
  training?: boolean;
}

const DEFAULT_MESSAGE = '江西赣州寄河北石家庄，纸箱2公斤，尺寸20*30*80，运费多少？';
const TEST_CHAT_ID = 'agent-test';

const newThreadId = () => `test-${crypto.randomUUID()}`;
const newMessageId = () => crypto.randomUUID();

// 会话 ID 按账号持久化：刷新页面或切换步骤后重新挂载，也能恢复同一会话。
const threadStorageKey = (cookieId: string) => `agent-test-thread:${cookieId}`;

const loadStoredThreadId = (cookieId: string): string => {
  try {
    const stored = localStorage.getItem(threadStorageKey(cookieId)) || '';
    return stored.startsWith('test-') ? stored : '';
  } catch {
    return '';
  }
};

const storeThreadId = (cookieId: string, threadId: string) => {
  try {
    localStorage.setItem(threadStorageKey(cookieId), threadId);
  } catch {
    // localStorage 不可用（如隐私模式）时退化为仅会话内存活。
  }
};

const formatField = (value: unknown) =>
  value === null || value === undefined || value === '' ? '待买家提供' : String(value);

const ACTION_LABELS: Record<AgentTestDecision['action'], string> = {
  reply: '将发送给买家',
  draft: '仅生成草稿（自动发送未开启）',
  manual: '转人工/失败提示',
  ignore: '忽略（重复消息）',
};

const STATUS_LABELS: Record<string, string> = {
  collecting: '收集中',
  quoted: '已报价',
  failed: '失败',
  manual: '转人工',
};

const formatDims = (fields: Record<string, unknown>) => {
  const dims = [fields.length_cm, fields.width_cm, fields.height_cm];
  if (dims.some((value) => value === null || value === undefined)) return '待买家提供';
  return `${dims.join('×')}cm`;
};

/** 最近一次决策明细：全部来自服务端 AgentDecision，不在浏览器重新计算。 */
const DecisionDetails = ({ decision }: { decision: AgentTestDecision }) => {
  const fields = decision.fields as Record<string, unknown>;
  const rows: Array<[string, unknown]> = [
    ['处理动作', ACTION_LABELS[decision.action] || decision.action],
    ['失败原因', decision.reason],
    ['会话状态', STATUS_LABELS[decision.session_status] || decision.session_status],
    ['当前轮次', fields.round_id],
    ['状态版本', decision.state_version],
    ['缺失字段', decision.missing_fields.length ? decision.missing_fields.join('、') : ''],
    ['发货地', fields.sender],
    ['收货地', fields.receiver],
    ['实重', fields.weight_kg ? `${fields.weight_kg}kg` : ''],
    ['长宽高', formatDims(fields)],
    ['件数', fields.quantity],
    ['承运商', fields.carrier],
  ];
  return (
    <details className="rounded-md border border-[var(--border)] bg-[var(--surface-subtle)] p-3.5">
      <summary className="cursor-pointer text-sm font-bold text-[var(--text)]">最近一次决策明细</summary>
      <dl className="mt-2 grid gap-2 text-[13px]">
        {rows.map(([label, value]) => (
          <div key={String(label)} className="flex gap-3">
            <dt className="w-20 shrink-0 text-[var(--text-muted)]">{label}</dt>
            <dd className="text-[var(--text)]">{formatField(value)}</dd>
          </div>
        ))}
        {decision.routes.length > 0 && (
          <div className="flex gap-3">
            <dt className="w-20 shrink-0 text-[var(--text-muted)]">命中线路</dt>
            <dd className="text-[var(--text)]">
              {decision.routes.map((route, index) => (
                <span key={index} className="block">
                  {route.carrier}（{route.match_level_label}）：{route.origin?.province || ''}
                  {route.origin?.city || ''}→{route.destination?.province || ''}
                  {route.destination?.city || ''}
                </span>
              ))}
            </dd>
          </div>
        )}
        {decision.quotes.length > 0 && (
          <div className="flex gap-3">
            <dt className="w-20 shrink-0 text-[var(--text-muted)]">Workflow 报价</dt>
            <dd className="text-[var(--text)]">
              {decision.quotes.map((quote, index) => (
                <span key={index} className="block">
                  {String(quote.carrier)}：计费重 {String(quote.chargeable_weight_kg)}kg，运费 ¥{String(quote.total_price)}
                </span>
              ))}
            </dd>
          </div>
        )}
        {decision.messages.length > 0 && (
          <div className="flex gap-3">
            <dt className="w-20 shrink-0 text-[var(--text-muted)]">消息拆分</dt>
            <dd className="text-[var(--text)]">
              {decision.messages.map((message, index) => (
                <span key={index} className="block whitespace-pre-wrap">第{index + 1}条：{message}</span>
              ))}
            </dd>
          </div>
        )}
      </dl>
    </details>
  );
};

/** 第五步测试会话：调用真实后端 Agent 图链路，支持会话恢复、新建与清空。 */
const QuoteAgentTestChat = ({ cookieId }: { cookieId: string }) => {
  // threadId 按账号持久化到 localStorage；父组件按账号 key 重建本组件，
  // 账号切换、刷新或步骤切换后都能恢复同一会话，不再串用其他账号的会话。
  const [threadId, setThreadId] = useState(() => (cookieId ? loadStoredThreadId(cookieId) : '') || newThreadId());
  const [message, setMessage] = useState('');
  const [turns, setTurns] = useState<TestTurn[]>([]);
  const [lastDecision, setLastDecision] = useState<AgentTestDecision | null>(null);
  const [isRunning, setIsRunning] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [threadAction, setThreadAction] = useState<'clear' | 'new' | null>(null);
  const [confirmClear, setConfirmClear] = useState(false);
  const [wasCleared, setWasCleared] = useState(false);
  const [errorMessage, setErrorMessage] = useState('');
  const [notice, setNotice] = useState('');
  const [savingTraining, setSavingTraining] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  const scrollToEnd = () =>
    requestAnimationFrame(() => bottomRef.current?.scrollIntoView({ behavior: 'smooth' }));

  // 会话 ID 与账号绑定关系本地留存。
  useEffect(() => {
    if (cookieId && threadId) storeThreadId(cookieId, threadId);
  }, [cookieId, threadId]);

  // 组件重新挂载（切换步骤/刷新页面）后按 thread_id 恢复气泡与结构化状态。
  useEffect(() => {
    if (!cookieId) return;
    let cancelled = false;
    setIsLoading(true);
    (async () => {
      try {
        const snapshot = await fetchAgentThread(threadId, cookieId);
        if (cancelled || !snapshot.exists) return;
        setTurns(snapshot.messages.map((item) => ({ role: item.role, text: item.content })));
        setLastDecision(snapshot.decision || null);
        setNotice('已恢复当前测试会话的历史记录');
      } catch {
        // 会话不存在（首次进入）属正常情况，不打扰用户。
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [cookieId, threadId]);

  const send = useCallback(async () => {
    if (!cookieId || isRunning || !message.trim()) return;
    setIsRunning(true);
    setErrorMessage('');
    setNotice('');
    setWasCleared(false);
    setConfirmClear(false);
    const buyerText = message.trim();
    const messageId = newMessageId();
    setTurns((prev) => [...prev, { role: 'buyer', text: buyerText }]);
    setMessage('');
    try {
      const response = await runAgentTest({
        cookie_id: cookieId,
        message: buyerText,
        thread_id: threadId,
        chat_id: TEST_CHAT_ID,
        message_id: messageId,
      });
      if (!response.handled || !response.decision) {
        setTurns((prev) => [...prev, { role: 'agent', text: response.detail || '消息未被识别为物流询价，将走通用 AI 回复' }]);
      } else {
        const decision = response.decision;
        const text = decision.messages.length ? decision.messages.join('\n―――――――\n') : `（${ACTION_LABELS[decision.action] || decision.action}）`;
        setTurns((prev) => [...prev, { role: 'agent', text, decision }]);
        setLastDecision(decision);
      }
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '试算失败');
    } finally {
      setIsRunning(false);
      scrollToEnd();
    }
  }, [cookieId, isRunning, message, threadId]);

  const startNewThread = useCallback(async () => {
    setThreadAction('new');
    setConfirmClear(false);
    setWasCleared(false);
    setErrorMessage('');
    setNotice('');
    try {
      const created = await createAgentThread(cookieId);
      setThreadId(created.thread_id || newThreadId());
    } catch {
      // 创建失败时退回本地生成，保证会话隔离不受服务端影响。
      setThreadId(newThreadId());
    }
    setTurns([]);
    setMessage('');
    setLastDecision(null);
    setNotice('已新建测试会话，旧会话记录仍可追溯');
    setThreadAction(null);
  }, [cookieId]);

  const clearCurrentThread = useCallback(async () => {
    setThreadAction('clear');
    setErrorMessage('');
    setNotice('');
    try {
      await deleteAgentThread(threadId, cookieId);
      // 只在服务端确认删除成功后才清空本地气泡，避免“窗口已清空、
      // 服务端上下文仍在”的状态不一致。
      setTurns([]);
      setLastDecision(null);
      setMessage('');
      setWasCleared(true);
      setConfirmClear(false);
      setNotice('已删除当前测试会话的消息记录、地址、重量和报价结果');
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '清空失败');
    } finally {
      setThreadAction(null);
    }
  }, [cookieId, threadId]);

  const fields = (lastDecision?.fields ?? {}) as Record<string, unknown>;
  const statusText = lastDecision
    ? STATUS_LABELS[lastDecision.session_status] || lastDecision.session_status
    : '';
  const busy = isRunning || isLoading || threadAction !== null || savingTraining;
  const channelResults = lastDecision?.channel_results || [];
  const lowestPrice = channelResults.find((item) => item.status === 'quoted')?.total_price;

  return (
    <section className="section-panel" aria-labelledby="agent-test-title" aria-busy={busy}>
      <SectionHeader
        title="测试会话"
        description="多轮试算：与正式自动报价共用同一条服务端链路（识别参数、状态合并、线路匹配、Workflow 计费、模板渲染）；不会发送真实消息。"
        icon={MessagesSquare}
        actions={(
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              className="ios-btn-secondary flex items-center gap-2 rounded-md px-3.5 py-2 text-sm disabled:cursor-not-allowed disabled:opacity-45"
              onClick={() => void startNewThread()}
              disabled={busy}
            >
              <Plus className="h-4 w-4" aria-hidden="true" />
              <span>新建会话</span>
            </button>
            <button
              type="button"
              className="ios-btn-secondary flex items-center gap-2 rounded-md px-3.5 py-2 text-sm disabled:cursor-not-allowed disabled:opacity-45"
              onClick={() => setConfirmClear(true)}
              disabled={busy || (turns.length === 0 && !lastDecision)}
            >
              <Eraser className="h-4 w-4" aria-hidden="true" />
              <span>{threadAction === 'clear' ? '清空中' : '清空当前会话'}</span>
            </button>
          </div>
        )}
      />
      <div className="grid gap-3 p-4">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 rounded-md border border-[var(--border)] bg-[var(--surface-subtle)] px-3 py-2 text-[12px] text-[var(--text-muted)]">
          <span className="min-w-0 break-all">会话 ID：{threadId}</span>
          {lastDecision && (
            <>
              <span>轮次：{String(fields.round_id ?? '待买家提供')}</span>
              <span>状态：{statusText}</span>
              <span>状态版本：{lastDecision.state_version}</span>
              <span>
                缺失字段：{lastDecision.missing_fields.length ? lastDecision.missing_fields.join('、') : '无'}
              </span>
            </>
          )}
        </div>

        {notice && (
          <p className="rounded-md border border-[var(--border)] bg-[var(--surface-subtle)] px-3 py-2 text-[12px] text-[var(--text-muted)]" role="status">
            {notice}
          </p>
        )}

        {confirmClear && (
          <div className="flex flex-wrap items-center gap-3 rounded-md border border-[var(--border)] p-3" role="alert">
            <p className="min-w-0 flex-1 text-sm">删除当前测试会话的消息记录、已识别参数和报价结果？</p>
            <button type="button" className="ios-btn-secondary rounded-md px-3 py-2 text-sm" disabled={busy} onClick={() => setConfirmClear(false)}>取消</button>
            <button type="button" className="ios-btn-secondary flex items-center gap-2 rounded-md px-3 py-2 text-sm text-[var(--danger-ink)]" disabled={busy} onClick={() => void clearCurrentThread()}>
              {threadAction === 'clear' ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Eraser className="h-4 w-4" />}
              {threadAction === 'clear' ? '清空中' : '确认清空'}
            </button>
          </div>
        )}

        <div className="quote-sim-thread" aria-live="polite">
          {turns.length === 0 && (
            <p className="flex items-center gap-2 text-[13px] text-[var(--text-muted)]">
              {wasCleared && <CheckCircle2 className="h-5 w-5 shrink-0 text-[var(--success)]" aria-hidden="true" />}
              {isLoading ? '正在读取会话…' : wasCleared ? '会话已清空，等待新的询价' : `暂无消息。例如：${DEFAULT_MESSAGE}`}
            </p>
          )}
          {turns.map((turn, index) => (
            <div key={index} className={`quote-sim-bubble ${turn.role === 'buyer' ? 'quote-sim-bubble--buyer' : 'quote-sim-bubble--assistant'}`}>
              <button
                type="button" role="checkbox" aria-checked={Boolean(turn.training)}
                aria-label={`第 ${index + 1} 条${turn.role === 'buyer' ? '买家消息' : '试算回复'}纳入训练`}
                className="mb-1 flex min-h-[44px] items-center gap-2 rounded px-2 text-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 disabled:opacity-50"
                disabled={busy}
                onClick={() => setTurns((prev) => prev.map((item, pos) => pos === index ? { ...item, training: !item.training } : item))}
              >
                <span aria-hidden="true" className={`inline-flex h-4 w-4 items-center justify-center rounded border ${turn.training ? 'border-current' : 'border-[var(--border-strong)]'}`}>{turn.training && <Check className="h-3.5 w-3.5" />}</span>
                #{index + 1} {turn.role === 'buyer' ? '买家模拟消息' : '试算模拟回复'} · {turn.training ? '已勾选训练' : '纳入训练'}
              </button>
              <span className="whitespace-pre-wrap">{turn.text}</span>
              {turn.decision && (
                <small className="mt-1.5 block text-[11px] text-[var(--text-muted)]">
                  {ACTION_LABELS[turn.decision.action] || turn.decision.action} · {turn.decision.reason}
                  {turn.decision.routes.length > 0 && ` · 命中线路：${turn.decision.routes.map((route) => route.carrier).join('、')}`}
                </small>
              )}
            </div>
          ))}
          <div ref={bottomRef} />
        </div>

        <QuoteAgentTraining
          cookieId={cookieId} threadId={threadId} busy={busy} saving={savingTraining}
          messages={turns.flatMap((turn, position) => turn.training ? [{ role: turn.role, content: turn.text, position, ...(turn.decision ? { decision: turn.decision } : {}) }] : [])}
          onSaving={setSavingTraining}
          onSaved={() => setTurns((prev) => prev.map((turn) => ({ ...turn, training: false })))}
          onSelectAll={(training) => setTurns((prev) => prev.map((turn) => ({ ...turn, training })))}
        />

        {errorMessage && (
          <p className="rounded-md border border-[color:color-mix(in_srgb,var(--danger)_34%,var(--border))] bg-[var(--danger-soft)] px-3 py-2.5 text-[13px] text-[var(--danger-ink)]" role="alert">
            {errorMessage}
          </p>
        )}

        <div className="grid gap-2 sm:grid-cols-[1fr_auto]">
          <label className="sr-only" htmlFor="agent-test-input">买家消息</label>
          <textarea
            id="agent-test-input"
            value={message}
            disabled={busy}
            onChange={(event) => setMessage(event.target.value)}
            rows={2}
            placeholder="例如：赣州到广州130kg"
            className="ios-input w-full rounded-md px-3 py-2.5 text-sm"
          />
          <button
            type="button"
            className="ios-btn-primary flex min-h-[42px] items-center justify-center gap-2 rounded-md px-4 py-2 text-sm disabled:cursor-not-allowed disabled:opacity-50"
            onClick={() => void send()}
            disabled={busy || !message.trim()}
          >
            <ScanSearch className="h-4 w-4" aria-hidden="true" />
            {isRunning ? '试算中' : '识别并试算'}
          </button>
        </div>

        {channelResults.length > 0 && (
          <div className="min-w-0 border-t border-[var(--border)] pt-3">
            <h3 className="mb-2 text-sm font-bold">渠道比价 · {channelResults.filter((item) => item.status === 'quoted').length} 家可报价 / {channelResults.length} 家参与匹配</h3>
            <ul className="divide-y divide-[var(--border)]">
              {channelResults.map((item) => (
                <li key={item.carrier} className="grid gap-1 py-3 text-sm sm:grid-cols-[7rem_1fr_auto] sm:gap-3">
                  <strong>{item.carrier}</strong>
                  <span className="min-w-0 break-words text-[var(--text-muted)]">{item.status === 'quoted' ? `${item.rule}；计费重 ${item.chargeable_weight_kg}kg` : { missing_city: '需补充收发城市', no_route: '报价表无匹配线路', pricing_failed: '线路已匹配，计费失败' }[item.status]}</span>
                  <span className="font-bold">{item.total_price === null ? '待核价' : `¥${item.total_price.toFixed(2)}${item.total_price === lowestPrice ? ' · 最低价' : ''}`}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
        {lastDecision && <DecisionDetails decision={lastDecision} />}
      </div>
    </section>
  );
};

export default QuoteAgentTestChat;
