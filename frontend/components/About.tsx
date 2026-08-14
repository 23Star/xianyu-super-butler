import React, { useEffect, useState } from 'react';
import { Info, Megaphone, RefreshCw, Download, ExternalLink, CheckCircle2, Globe } from 'lucide-react';
import { getAnnouncement } from '../services/api';
import { AnnouncementPayload } from '../types';
import { EmptyState, PageHeader } from './ui';

const levelStyles: Record<string, string> = {
  info: 'border-blue-200 bg-blue-50 text-blue-800',
  warning: 'border-amber-200 bg-amber-50 text-amber-800',
  danger: 'border-red-200 bg-red-50 text-red-700',
};

const levelLabels: Record<string, string> = {
  info: '通知',
  warning: '注意',
  danger: '重要',
};

const About: React.FC = () => {
  const [data, setData] = useState<AnnouncementPayload | null>(null);
  const [loading, setLoading] = useState(false);

  const load = async (force = false) => {
    setLoading(true);
    try {
      setData(await getAnnouncement(force));
    } catch {
      // 拉取失败时保留上一次内容，页面不至于空白
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const announcements = data?.announcements || [];

  return (
    <div className="page-stack animate-fade-in">
      <PageHeader
        title="关于"
        description="查看当前版本、检查更新与历史公告。"
        icon={Info}
        actions={(
          <button
            type="button"
            onClick={() => load(true)}
            disabled={loading}
            className="ios-btn-secondary flex items-center gap-2 rounded-md px-4 py-2 text-sm disabled:opacity-50"
          >
            <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
            {loading ? '正在检查' : '检查更新'}
          </button>
        )}
      />

      <section className="section-panel p-4">
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="rounded-md border border-gray-200 p-4">
            <p className="text-xs font-semibold text-gray-500">当前版本</p>
            <p className="mt-1 text-2xl font-bold text-gray-900">
              {data?.local_version || '—'}
            </p>
          </div>

          <div className={`rounded-md border p-4 ${
            data?.has_update ? 'border-amber-200 bg-amber-50' : 'border-gray-200'
          }`}>
            <p className="text-xs font-semibold text-gray-500">最新版本</p>
            {data?.has_update ? (
              <>
                <p className="mt-1 text-2xl font-bold text-amber-700">
                  {data.latest_version}
                </p>
                {data.release_notes && (
                  <p className="mt-2 whitespace-pre-wrap text-xs text-amber-800">
                    {data.release_notes}
                  </p>
                )}
                {data.download_url && (
                  <a
                    href={data.download_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="ios-btn-primary mt-3 inline-flex items-center gap-2 rounded-md px-3 py-2 text-xs"
                  >
                    <Download className="h-4 w-4" />
                    前往下载
                    <ExternalLink className="h-3 w-3" />
                  </a>
                )}
              </>
            ) : (
              <p className="mt-1 flex items-center gap-2 text-sm font-bold text-green-700">
                <CheckCircle2 className="h-5 w-5" />
                {data?.source_configured ? '已是最新版本' : '未配置更新源'}
              </p>
            )}
          </div>
        </div>

        {!data?.source_configured && (
          <p className="mt-4 rounded-md border border-gray-200 bg-gray-50 px-3 py-2 text-xs text-gray-600">
            尚未配置公告与更新源。在「系统设置 → 公告与更新」里填入你的公网 JSON 地址后，
            这里会显示公告并自动检查新版本。
          </p>
        )}

        {data?.error && (
          <p className="mt-3 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
            拉取公告失败：{data.error}
          </p>
        )}

        <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-gray-100 pt-4">
          <span className="text-xs font-semibold text-gray-500">官网</span>
          <a
            href="https://xy.corleom.com"
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1.5 text-xs font-bold text-[#8c7900] hover:underline"
          >
            <Globe className="h-3.5 w-3.5" />
            xy.corleom.com
            <ExternalLink className="h-3 w-3" />
          </a>
        </div>
      </section>

      <section className="section-panel">
        <div className="flex items-center gap-2 border-b border-gray-200 px-4 py-3">
          <Megaphone className="h-4 w-4 text-gray-500" />
          <span className="text-sm font-bold text-gray-800">历史公告</span>
          <span className="text-xs text-gray-400">{announcements.length} 条</span>
        </div>

        {announcements.length > 0 ? (
          <div className="divide-y divide-gray-100">
            {announcements.map(item => (
              <article key={item.id} className="px-4 py-3">
                <div className="flex flex-wrap items-center gap-2">
                  <span className={`rounded border px-2 py-0.5 text-[10px] font-bold ${levelStyles[item.level] || levelStyles.info}`}>
                    {levelLabels[item.level] || '通知'}
                  </span>
                  {item.title && (
                    <h3 className="text-sm font-bold text-gray-900">{item.title}</h3>
                  )}
                  {item.published_at && (
                    <span className="text-xs text-gray-400">{item.published_at}</span>
                  )}
                </div>
                <p className="mt-1.5 whitespace-pre-wrap text-sm leading-relaxed text-gray-700">
                  {item.content}
                </p>
              </article>
            ))}
          </div>
        ) : (
          <EmptyState
            title="暂无公告"
            description="配置更新源后，发布方的公告会显示在这里。"
            icon={Megaphone}
          />
        )}
      </section>
    </div>
  );
};

export default About;
