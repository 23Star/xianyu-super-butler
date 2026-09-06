import { useCallback, useEffect, useMemo, useState } from 'react';
import { AlertCircle, CheckCircle2, MessageCircle, RefreshCw, ScanSearch, Send, Truck } from 'lucide-react';
import { listQuoteBooks, type LogisticsQuoteBook, type LogisticsQuoteParseRow } from '../../services/api';
import { extractParseError } from '../../services/logisticsQuote';
import { loadQuoteReplyTemplates } from '../../services/quoteReply';
import { loadQuoteSettings } from '../../services/quoteSettings';
import { buildSampleValues, renderTemplate } from '../../utils/quoteTemplate';
import { calculateSampleFreight, parseBuyerMessage, type ParsedBuyerMessage } from '../../utils/quoteMessageParser';
import { SectionHeader } from '../ui';

const defaultMessage = '你好，我从浙江杭州发到广东深圳，包裹大约 8kg，尺寸 40×30×20cm，走顺心捷达，线上支付，麻烦帮我算一下运费。';
const pickSample = (book: LogisticsQuoteBook | null): LogisticsQuoteParseRow | null => book?.payload.sample_row ?? null;
const formatValue = (value: string | number | null | undefined, fallback = '未识别') => value === null || value === undefined || value === '' ? fallback : String(value);

const QuoteDiagnostics = () => {
  const [books, setBooks] = useState<LogisticsQuoteBook[]>([]);
  const [message, setMessage] = useState(defaultMessage);
  const [parsed, setParsed] = useState<ParsedBuyerMessage>(() => parseBuyerMessage(defaultMessage));
  const [isLoading, setIsLoading] = useState(true);
  const [isRecognizing, setIsRecognizing] = useState(false);
  const [errorMessage, setErrorMessage] = useState('');
  const [checkedAt, setCheckedAt] = useState<string | null>(null);
  const loadBooks = useCallback(async () => { setIsLoading(true); setErrorMessage(''); try { const response = await listQuoteBooks(); setBooks(response.books); setCheckedAt(new Date().toLocaleString('zh-CN', { hour12: false })); } catch (error) { setBooks([]); setErrorMessage(extractParseError(error)); } finally { setIsLoading(false); } }, []);
  useEffect(() => { void loadBooks(); }, [loadBooks]);
  const sample = useMemo(() => pickSample(books[0] ?? null), [books]);
  const freight = useMemo(() => calculateSampleFreight(parsed, sample), [parsed, sample]);
  const reply = useMemo(() => { const settings = loadQuoteSettings(); const templates = loadQuoteReplyTemplates(); const values = buildSampleValues(settings, sample ? { service: sample.carrier, route: sample.route, origin: parsed.origin ?? sample.origin, destination: parsed.destination ?? sample.destination, freight: freight.freight, firstWeightKg: sample.first_weight_kg, firstPrice: sample.first_price, continuedUnitKg: sample.continued_unit_kg, continuedPrice: sample.continued_price } : null); return parsed.missing.length ? renderTemplate(templates.missingParams, values) : renderTemplate(templates.quoteMessage, values); }, [freight.freight, parsed, sample]);
  const recognize = () => { setIsRecognizing(true); window.setTimeout(() => { setParsed(parseBuyerMessage(message)); setIsRecognizing(false); }, 220); };
  const parameterItems: Array<[string, string | null]> = [['发货地', parsed.origin], ['收货地', parsed.destination], ['重量', parsed.weightKg === null ? null : `${parsed.weightKg.toFixed(2)} kg`], ['尺寸', parsed.dimensions ? `${parsed.dimensions.lengthCm} × ${parsed.dimensions.widthCm} × ${parsed.dimensions.heightCm} cm` : null], ['支付方式', parsed.paymentMode === 'offline' ? '线下支付' : parsed.paymentMode === 'online' ? '线上支付' : null], ['承运商', parsed.carrier]];
  return (
    <div className="logistics-page page-stack">
      <section className="section-panel" aria-labelledby="quote-simulation-title">
        <SectionHeader title="模拟会话测试" description="输入一条买家询价消息，检查参数识别、运费核价与回复模板的实际效果。" icon={MessageCircle} actions={<button type="button" className="ios-btn-secondary flex items-center gap-2 rounded-md px-3.5 py-2 text-sm disabled:cursor-not-allowed disabled:opacity-45" onClick={() => void loadBooks()} disabled={isLoading}><RefreshCw className={`h-4 w-4 ${isLoading ? 'animate-spin' : ''}`} aria-hidden="true" /><span>{isLoading ? '读取中' : '刷新报价源'}</span></button>} />
        {errorMessage && <p className="mx-4 mt-4 rounded-md border border-[color:color-mix(in_srgb,var(--danger)_34%,var(--border))] bg-[var(--danger-soft)] px-3 py-2.5 text-[13px] text-[var(--danger-ink)]" role="alert">{errorMessage}</p>}
        <div className="quote-sim-layout">
          <div className="quote-sim-chat">
            <div className="quote-sim-chat__topline"><span className="quote-sim-avatar">买</span><div><strong>买家模拟会话</strong><small>仅用于验证识别与回复效果</small></div><span className="quote-sim-live"><i />本地测试</span></div>
            <div className="quote-sim-thread" aria-live="polite"><div className="quote-sim-bubble quote-sim-bubble--buyer"><span>{message || '请输入买家消息'}</span><time>刚刚</time></div><div className="quote-sim-bubble quote-sim-bubble--assistant"><span>{reply}</span><time>模拟回复</time></div></div>
            <div className="quote-sim-compose"><label htmlFor="quote-sim-message" className="sr-only">买家消息</label><textarea id="quote-sim-message" value={message} onChange={(event) => setMessage(event.target.value)} placeholder="例如：从杭州发到深圳，8kg，40×30×20cm，线上支付" rows={4} /><div className="quote-sim-compose__footer"><span>支持自然语言、数字与常见单位</span><button type="button" className="ios-btn-primary flex min-h-[42px] items-center gap-2 rounded-md px-4 py-2 text-sm disabled:cursor-not-allowed disabled:opacity-50" onClick={recognize} disabled={isRecognizing || !message.trim()}><ScanSearch className="h-4 w-4" aria-hidden="true" />{isRecognizing ? '识别中' : '识别并试算'}</button></div></div>
          </div>
          <aside className="quote-sim-inspector" aria-label="参数识别结果">
            <div className="quote-sim-inspector__heading"><div><span className="quote-sim-kicker">PARAMETER CHECK</span><h3>识别结果</h3></div><span className={parsed.missing.length ? 'quote-sim-status quote-sim-status--review' : 'quote-sim-status quote-sim-status--pass'}>{parsed.missing.length ? '待补充' : '可试算'}</span></div>
            <div className="quote-sim-params">{parameterItems.map(([label, value]) => <div className="quote-sim-param" key={label}><span>{label}</span><strong>{formatValue(value, '待买家提供')}</strong></div>)}</div>
            <div className="quote-sim-calc"><div className="quote-sim-calc__title"><Truck className="h-4 w-4" aria-hidden="true" /><strong>试算摘要</strong></div><div><span>计费重量</span><b>{freight.chargeableWeightKg === null ? '待核价' : `${freight.chargeableWeightKg} kg`}</b></div><div><span>体积重</span><b>{freight.volumeWeightKg === null ? '未提供尺寸' : `${freight.volumeWeightKg.toFixed(2)} kg`}</b></div><div><span>报价表样本运费</span><b>{freight.freight === null ? '待核价' : `¥${freight.freight.toFixed(2)}`}</b></div></div>
            {parsed.missing.length ? <div className="quote-sim-missing"><AlertCircle className="h-4 w-4 shrink-0" aria-hidden="true" /><span>还需要：{parsed.missing.join('、')}</span></div> : <div className="quote-sim-ready"><CheckCircle2 className="h-4 w-4 shrink-0" aria-hidden="true" /><span>核心参数已识别，可继续检查模板回复</span></div>}
            <div className="quote-sim-source"><span>当前报价源</span><strong>{sample?.carrier || books[0]?.filename || '尚未识别报价表'}</strong><small>{checkedAt ? `最近读取 ${checkedAt}` : '识别报价表后自动带入样本线路'}</small></div>
            <button type="button" className="ios-btn-secondary flex min-h-[42px] w-full items-center justify-center gap-2 rounded-md px-3 py-2 text-sm" disabled title="模拟会话不会发送真实消息"><Send className="h-4 w-4" aria-hidden="true" />发送测试消息</button>
          </aside>
        </div>
      </section>
    </div>
  );
};
export default QuoteDiagnostics;
