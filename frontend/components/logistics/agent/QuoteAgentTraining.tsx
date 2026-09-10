import { useEffect, useRef, useState } from 'react';
import { Download, GraduationCap, LoaderCircle } from 'lucide-react';
import {
  exportAgentTrainingRound, listAgentTrainingRounds, saveAgentTrainingRound,
  type AgentTrainingMessage, type AgentTrainingRound,
} from '../../../services/logisticsAgent';

const defaultName = () => `训练回合 ${new Date().toLocaleString('zh-CN', { hour12: false })}`;
const buttonClass = 'ios-btn-secondary min-h-[44px] rounded-md px-3 py-2 text-sm disabled:cursor-not-allowed disabled:opacity-50';

interface Props {
  cookieId: string;
  threadId: string;
  messages: AgentTrainingMessage[];
  busy: boolean;
  saving: boolean;
  onSaving: (saving: boolean) => void;
  onSaved: () => void;
  onSelectAll: (selected: boolean) => void;
}

/** 选择预览、一次保存一个回合，以及账号下已采集数据的回看与导出。 */
export default function QuoteAgentTraining({ cookieId, threadId, messages, busy, saving, onSaving, onSaved, onSelectAll }: Props) {
  const [name, setName] = useState(defaultName);
  const [rounds, setRounds] = useState<AgentTrainingRound[]>([]);
  const [loading, setLoading] = useState(true);
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');
  const [historyError, setHistoryError] = useState('');
  const [reload, setReload] = useState(0);
  const [exporting, setExporting] = useState('');
  const pending = useRef({ key: '', id: '' });
  const saveLock = useRef(false);
  const buyers = messages.filter((item) => item.role === 'buyer').length;
  const agents = messages.length - buyers;
  const selectionError = !buyers || !agents
    ? '请至少勾选一条买家消息和一条试算回复。'
    : messages[0].role !== 'buyer' || messages[messages.length - 1].role !== 'agent'
      ? '请选择以买家消息开始、以试算回复结束的内容。'
      : messages.length > 200 ? '每个训练回合最多保存 200 条消息，请分回合保存。' : '';

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setHistoryError('');
    listAgentTrainingRounds(cookieId).then((result) => {
      if (!cancelled) setRounds(result.rounds);
    }).catch((err) => {
      if (!cancelled) setHistoryError(err instanceof Error ? err.message : '读取训练回合失败');
    }).finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [cookieId, reload]);

  useEffect(() => { setName(defaultName()); setNotice(''); setError(''); }, [threadId]);

  const save = async () => {
    if (busy || saveLock.current) return;
    setError('');
    setNotice('');
    if (selectionError || !name.trim()) {
      setError(selectionError || '请填写训练回合名称。');
      return;
    }
    const payload = { thread_id: threadId, name: name.trim(), messages };
    const key = JSON.stringify(payload);
    // 超时后以同一标识重试，避免服务端已保存、客户端未收到响应时生成重复回合。
    if (pending.current.key !== key) pending.current = { key, id: crypto.randomUUID() };
    saveLock.current = true;
    onSaving(true);
    try {
      const result = await saveAgentTrainingRound(cookieId, { ...payload, id: pending.current.id });
      if (!result.success || !result.round?.id) throw new Error('服务端未确认保存成功，请重试。');
      setRounds((prev) => [result.round, ...prev.filter((item) => item.id !== result.round.id)].slice(0, 50));
      setNotice(`已保存「${result.round.name}」，共 ${messages.length} 条消息（买家 ${buyers} 条、试算 ${agents} 条），已加入训练数据。`);
      pending.current = { key: '', id: '' };
      onSaved();
      setName(defaultName());
    } catch (err) {
      setError(err instanceof Error && err.name === 'TimeoutError'
        ? '保存响应超时，勾选内容已保留；请重试确认保存结果。'
        : err instanceof Error ? err.message : '保存训练回合失败');
    } finally {
      saveLock.current = false;
      onSaving(false);
    }
  };

  const download = async (round: AgentTrainingRound) => {
    setExporting(round.id);
    setError('');
    try {
      const data = await exportAgentTrainingRound(cookieId, round.id);
      const url = URL.createObjectURL(new Blob([JSON.stringify(data) + '\n'], { type: 'application/x-ndjson;charset=utf-8' }));
      const link = document.createElement('a');
      link.href = url;
      link.download = `${round.name.replace(/[<>:"/\\|?*\x00-\x1f]/g, '_')}.jsonl`;
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (err) {
      setError(err instanceof Error ? err.message : '导出失败');
    } finally { setExporting(''); }
  };

  return (
    <div className="min-w-0 space-y-3 rounded-md border border-[var(--border)] p-3" aria-labelledby="training-title" aria-busy={saving}>
      <h3 id="training-title" className="flex items-center gap-2 text-sm font-bold">
        <GraduationCap className="h-4 w-4" aria-hidden="true" />训练数据回合
      </h3>
      <p className="text-sm text-[var(--text-muted)]">勾选买家模拟消息和试算回复，一次保存为一个回合，可包含多轮对话。保存的内容用于后续模型训练；当前状态为已采集，待训练。</p>
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm" role="status">已选 {messages.length} 条 · 买家 {buyers} 条 · 试算 {agents} 条</span>
        <button type="button" className={buttonClass} disabled={busy} onClick={() => onSelectAll(true)}>全选消息</button>
        <button type="button" className={buttonClass} disabled={busy || !messages.length} onClick={() => onSelectAll(false)}>取消勾选</button>
      </div>
      {messages.length > 0 && (
        <details className="rounded-md bg-[var(--surface-subtle)] p-3">
          <summary className="cursor-pointer text-sm">预览本回合将保存的 {messages.length} 条消息</summary>
          <ol className="mt-2 max-h-64 space-y-2 overflow-auto text-sm">
            {messages.map((item) => <li key={item.position} className="whitespace-pre-wrap break-words"><strong>#{item.position + 1} {item.role === 'buyer' ? '买家' : '试算'}：</strong>{item.content}</li>)}
          </ol>
        </details>
      )}
      <div className="grid gap-2 sm:grid-cols-[1fr_auto] sm:items-end">
        <label className="grid min-w-0 gap-1 text-sm" htmlFor="training-round-name">
          回合名称
          <input id="training-round-name" className="ios-input min-h-[44px] w-full rounded-md px-3 py-2" value={name} maxLength={100} disabled={busy} onChange={(event) => setName(event.target.value)} />
        </label>
        <button type="button" className="ios-btn-primary flex min-h-[44px] items-center justify-center gap-2 rounded-md px-4 py-2 text-sm disabled:cursor-not-allowed disabled:opacity-50" disabled={busy || loading || !messages.length} onClick={() => void save()}>
          {saving ? <LoaderCircle className="h-4 w-4 animate-spin motion-reduce:animate-none" aria-hidden="true" /> : <GraduationCap className="h-4 w-4" aria-hidden="true" />}
          {saving ? '正在保存回合…' : '保存为一个训练回合'}
        </button>
      </div>
      {selectionError && <p className="text-sm text-[var(--text-muted)]">{selectionError}</p>}
      {notice && <p role="status" className="rounded-md bg-[var(--surface-subtle)] p-3 text-sm">{notice}</p>}
      {error && <p role="alert" className="rounded-md bg-[var(--danger-soft)] p-3 text-sm text-[var(--danger-ink)]">{error}</p>}
      <div className="space-y-2 border-t border-[var(--border)] pt-3">
        <h4 className="text-sm font-bold">已保存回合 · 当前账号最近 50 个</h4>
        {loading && <p role="status" className="text-sm">正在读取训练回合…</p>}
        {historyError && <p role="alert" className="text-sm text-[var(--danger-ink)]">{historyError} <button type="button" className={buttonClass} onClick={() => setReload((value) => value + 1)}>重新读取</button></p>}
        {!loading && !historyError && !rounds.length && <p className="text-sm text-[var(--text-muted)]">暂无已保存的训练回合。</p>}
        {rounds.map((round) => (
          <details key={round.id} className="min-w-0 rounded-md border border-[var(--border)] p-3">
            <summary className="cursor-pointer break-words text-sm"><strong>{round.name}</strong> · {round.messages.length} 条消息 · 已采集，待训练</summary>
            <p className="mt-2 break-all text-xs text-[var(--text-muted)]">保存时间：{new Date(round.created_at.replace(' ', 'T') + 'Z').toLocaleString('zh-CN')} · 来源会话：{round.thread_id}</p>
            <ol className="my-3 max-h-64 space-y-2 overflow-auto text-sm">
              {round.messages.map((item) => <li key={item.position} className="whitespace-pre-wrap break-words"><strong>#{item.position + 1} {item.role === 'buyer' ? '买家' : '试算'}：</strong>{item.content}</li>)}
            </ol>
            <button type="button" className={`${buttonClass} inline-flex items-center gap-2`} disabled={Boolean(exporting)} onClick={() => void download(round)}>
              <Download className="h-4 w-4" aria-hidden="true" />{exporting === round.id ? '导出中…' : '导出训练 JSONL'}
            </button>
          </details>
        ))}
      </div>
    </div>
  );
}
