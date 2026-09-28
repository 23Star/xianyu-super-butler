import React, { useState } from 'react';
import { ScanLine } from 'lucide-react';
import { buyerTestDeliverySkuOptions, getDeliverySkuOptions, DeliverySkuDiscovery, DeliverySkuOption } from '../services/api';
import { confirmAction } from '../services/feedback';

type Props = { cookieId: string; itemId: string };

export default function SkuRecognitionPanel({ cookieId, itemId }: Props) {
  const [options, setOptions] = useState<DeliverySkuOption[]>([]);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [detectionStatus, setDetectionStatus] = useState('');

  const applyDiscovery = (data: DeliverySkuDiscovery) => {
    setOptions(data.options);
    setDetectionStatus(data.detection_status);
    if (data.detection_status === 'unauthorized') {
      setMessage('该账号没有卖家 SKU 权限，可尝试买家接口（风控风险更高，只调一次）');
    } else if (data.detection_status === 'risk_control') {
      const minutes = Math.max(1, Math.ceil((data.retry_after_seconds || 0) / 60));
      setMessage(`触发平台风控，请约 ${minutes} 分钟后再试`);
    } else if (data.options.length) {
      setMessage(`已识别 ${data.options.length} 个 SKU`);
    } else {
      setMessage(data.warning ? `商家接口暂不可用：${data.warning}` : '暂无可识别 SKU');
    }
  };

  const discover = async () => {
    setBusy(true); setMessage('');
    try {
      applyDiscovery(await getDeliverySkuOptions(cookieId, itemId));
    } catch (error) {
      setDetectionStatus(''); setMessage(error instanceof Error ? error.message : 'SKU 识别失败');
    } finally {
      setBusy(false);
    }
  };

  const probeBuyer = async () => {
    const confirmed = await confirmAction(
      '买家接口会以买家身份读取商品详情，风控风险更高，只调用一次且失败不会自动重试。确认继续吗？',
      { title: '尝试买家接口', confirmLabel: '仍然调用一次', danger: true },
    );
    if (!confirmed) return;
    setBusy(true); setMessage('');
    try {
      applyDiscovery(await buyerTestDeliverySkuOptions(cookieId, itemId));
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '买家接口识别失败');
    } finally {
      setBusy(false);
    }
  };

  return <section className="mt-4 rounded-md border border-cyan-200 bg-cyan-50/40 p-4">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div><h4 className="text-sm font-bold text-gray-900">SKU 识别</h4><p className="mt-1 text-xs text-gray-600">只读取并展示商品规格，不在这里设置防薅限制。</p></div>
      <div className="flex gap-2">
        {detectionStatus === 'unauthorized' && (
          <button type="button" onClick={probeBuyer} disabled={busy} className="inline-flex items-center gap-1 rounded-md border border-amber-500 px-3 py-2 text-xs font-semibold text-amber-700 disabled:opacity-50"><ScanLine size={14} />尝试买家接口</button>
        )}
        <button type="button" onClick={discover} disabled={busy} className="inline-flex items-center gap-1 rounded-md border border-cyan-600 px-3 py-2 text-xs font-semibold text-cyan-700 disabled:opacity-50"><ScanLine size={14} />{busy ? '处理中' : '识别 SKU'}</button>
      </div>
    </div>
    {message && <p className="mt-2 text-xs text-cyan-800">{message}</p>}
    {options.length > 0 && <div className="mt-3 grid gap-2 sm:grid-cols-2">{options.map(row => <div key={row.key} className="rounded border border-cyan-100 bg-white p-3"><p className="truncate text-xs font-semibold text-gray-800">{row.name}</p><p className="truncate font-mono text-[10px] text-gray-500">{row.key}</p></div>)}</div>}
  </section>;
}
