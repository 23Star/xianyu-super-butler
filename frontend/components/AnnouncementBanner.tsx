import React, { useEffect, useState } from 'react';
import { Megaphone, Download, ExternalLink } from 'lucide-react';
import { getAnnouncement } from '../services/api';
import { AnnouncementPayload } from '../types';

// info 走品牌黄而不是蓝：公告常驻页面顶部，蓝色会和整站黄色主题打架
const levelStyles: Record<string, string> = {
  info: 'border-[#ffe566] bg-[#fffdf0] text-[#6b5200]',
  warning: 'border-[#f5c800] bg-[#fff7e6] text-[#8a6300]',
  danger: 'border-red-200 bg-red-50 text-red-700',
};

const levelBadge: Record<string, string> = {
  info: 'bg-[#ffe100] text-[#2a2416]',
  warning: 'bg-[#f5c800] text-[#2a2416]',
  danger: 'bg-red-600 text-white',
};

/**
 * 全局公告跑马灯。
 *
 * 常驻顶部、不提供关闭：公告由发布方推送，通常是维护通知或风险提示，
 * 允许关闭会让用户错过关键信息。需要撤下时由发布方从远端 JSON 移除。
 *
 * 多条公告首尾相接横向滚动；鼠标悬停时暂停，方便阅读长文本。
 */
const AnnouncementBanner: React.FC = () => {
  const [data, setData] = useState<AnnouncementPayload | null>(null);

  useEffect(() => {
    const load = () => {
      getAnnouncement()
        .then(setData)
        .catch(() => undefined);
    };
    load();
    // 后端已缓存 10 分钟，这里 5 分钟问一次，命中缓存开销极小
    const timer = setInterval(load, 300000);
    return () => clearInterval(timer);
  }, []);

  const announcements = data?.announcements || [];
  const showUpdate = Boolean(data?.has_update);

  if (!announcements.length && !showUpdate) return null;

  // 取最高级别决定整条跑马灯的配色，重要公告不会被普通公告的样式淹没
  const topLevel = announcements.some(a => a.level === 'danger')
    ? 'danger'
    : announcements.some(a => a.level === 'warning')
      ? 'warning'
      : 'info';

  // 轨道内容重复一份，配合 -50% 位移实现无缝首尾相接
  const track = announcements.map(item => (
    <span key={item.id} className="inline-flex items-center gap-2 px-8">
      <span className={`rounded px-1.5 py-0.5 text-[10px] font-bold ${levelBadge[item.level] || levelBadge.info}`}>
        {item.level === 'danger' ? '重要' : item.level === 'warning' ? '注意' : '通知'}
      </span>
      {item.title && <b className="font-bold">{item.title}</b>}
      {/* 跑马灯里换行没有意义，压成单行显示 */}
      <span>{item.content.replace(/\s*\n\s*/g, ' ')}</span>
      {item.published_at && (
        <span className="text-[11px] opacity-60">{item.published_at}</span>
      )}
    </span>
  ));

  return (
    <div className="mx-auto max-w-[1320px] space-y-2 px-4 pt-4 sm:px-6 lg:px-8">
      {showUpdate && (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-amber-200 bg-amber-50 px-4 py-3">
          <div className="min-w-0">
            <p className="text-sm font-bold text-amber-900">
              发现新版本 {data?.latest_version}
              <span className="ml-2 font-normal text-amber-700">
                当前 {data?.local_version}
              </span>
            </p>
            {data?.release_notes && (
              <p className="mt-1 whitespace-pre-wrap text-xs leading-relaxed text-amber-800">
                {data.release_notes}
              </p>
            )}
          </div>
          {data?.download_url && (
            <a
              href={data.download_url}
              target="_blank"
              rel="noopener noreferrer"
              className="ios-btn-primary inline-flex flex-none items-center gap-2 rounded-md px-3 py-2 text-xs"
            >
              <Download className="h-4 w-4" />
              前往下载
              <ExternalLink className="h-3 w-3" />
            </a>
          )}
        </div>
      )}

      {announcements.length > 0 && (
        <div className={`flex items-center gap-3 overflow-hidden rounded-md border px-3 py-2 ${levelStyles[topLevel]}`}>
          <Megaphone className="h-4 w-4 flex-none" />
          <div className="marquee min-w-0 flex-1">
            <div className="marquee__track text-xs leading-relaxed">
              {track}
              {/* 复制一份用于无缝衔接，对读屏软件隐藏避免重复朗读 */}
              <span aria-hidden="true">{track}</span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default AnnouncementBanner;
