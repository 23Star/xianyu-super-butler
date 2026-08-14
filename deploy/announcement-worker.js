/**
 * 闲鱼智控 —— 公告与版本发布服务
 *
 * 部署在 connect.corleom.com，供各客户端拉取公告和检查更新。
 *
 * 路由：
 *   GET  /announcement.json  公开，客户端定时拉取（无需鉴权）
 *   GET  /admin              管理界面，由 Cloudflare Access 保护
 *   GET  /api/config         读取当前配置（需 Access）
 *   PUT  /api/config         保存配置（需 Access）
 *
 * 安全策略：
 *   - /admin 与 /api/* 由 Cloudflare Access 在边缘拦截；Worker 内再校验一次
 *     Cf-Access-Jwt-Assertion 头，避免 Access 配置失误导致后台裸奔（纵深防御）。
 *   - 公开接口只读、只返回公告数据，不暴露任何配置或身份信息。
 *   - 写入做结构校验与体积上限，防止把畸形数据或超大内容写进 KV。
 *   - 统一附加安全响应头，管理页用严格 CSP 禁止外部脚本。
 */

const CONFIG_KEY = 'announcement:config';

// 单条公告与整体配置的体积上限，避免 KV 被写入超大内容
const MAX_ITEMS = 20;
const MAX_CONTENT_LEN = 2000;
const MAX_BODY_BYTES = 64 * 1024;

const DEFAULT_CONFIG = {
  announcements: [],
  latest_version: '',
  download_url: '',
  release_notes: '',
};

/** 通用安全响应头。管理页额外加 CSP。 */
function securityHeaders(extra = {}) {
  return {
    'X-Content-Type-Options': 'nosniff',
    'X-Frame-Options': 'DENY',
    'Referrer-Policy': 'no-referrer',
    'Permissions-Policy': 'geolocation=(), microphone=(), camera=()',
    'Strict-Transport-Security': 'max-age=31536000; includeSubDomains',
    ...extra,
  };
}

function json(data, status = 200, extra = {}) {
  return new Response(JSON.stringify(data), {
    status,
    headers: securityHeaders({
      'Content-Type': 'application/json; charset=utf-8',
      ...extra,
    }),
  });
}

/**
 * 校验并清洗配置。
 * 客户端只认识固定几个字段，这里做白名单过滤，顺便把脏数据挡在 KV 之外。
 */
function sanitizeConfig(input) {
  if (!input || typeof input !== 'object') {
    throw new Error('配置必须是对象');
  }

  const str = (v, max = 500) => String(v ?? '').trim().slice(0, max);

  const rawList = Array.isArray(input.announcements) ? input.announcements : [];
  if (rawList.length > MAX_ITEMS) {
    throw new Error(`公告条数不能超过 ${MAX_ITEMS} 条`);
  }

  const announcements = [];
  for (const item of rawList) {
    if (!item || typeof item !== 'object') continue;
    const content = str(item.content, MAX_CONTENT_LEN);
    if (!content) continue; // 没内容的条目直接丢弃，客户端也用不上

    const level = str(item.level, 20).toLowerCase();
    announcements.push({
      id: str(item.id, 100) || `a-${Date.now()}-${announcements.length}`,
      title: str(item.title, 100),
      content,
      level: ['info', 'warning', 'danger'].includes(level) ? level : 'info',
      published_at: str(item.published_at, 40),
    });
  }

  // 下载地址只允许 https，避免把用户导向明文或自定义协议
  const downloadUrl = str(input.download_url, 500);
  if (downloadUrl && !/^https:\/\//i.test(downloadUrl)) {
    throw new Error('下载地址必须以 https:// 开头');
  }

  return {
    announcements,
    latest_version: str(input.latest_version, 40),
    download_url: downloadUrl,
    release_notes: str(input.release_notes, MAX_CONTENT_LEN),
    updated_at: new Date().toISOString(),
  };
}

async function readConfig(env) {
  try {
    const raw = await env.ANNOUNCEMENT_KV.get(CONFIG_KEY);
    if (!raw) return { ...DEFAULT_CONFIG };
    return { ...DEFAULT_CONFIG, ...JSON.parse(raw) };
  } catch {
    return { ...DEFAULT_CONFIG };
  }
}

/**
 * 纵深防御：Access 已在边缘拦截，这里再确认请求确实经过了 Access。
 * 只要 Access 策略被误删或路径没覆盖到，这一层就会兜住。
 */
function assertAccess(request) {
  const jwt = request.headers.get('Cf-Access-Jwt-Assertion');
  if (!jwt) {
    throw new Error('未经 Cloudflare Access 授权');
  }
}

/** 从 Access 注入的头里取登录邮箱，仅用于界面展示。 */
function accessEmail(request) {
  return request.headers.get('Cf-Access-Authenticated-User-Email') || '未知用户';
}

const ADMIN_HTML = `<!doctype html>
<html lang="zh-CN"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>公告发布 · 闲鱼智控</title>
<style>
*{box-sizing:border-box}
body{margin:0;font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif;background:#f5f6f7;color:#1f2328}
.wrap{max-width:940px;margin:0 auto;padding:24px 16px 64px}
h1{font-size:20px;margin:0 0 4px}
.sub{color:#6b7280;font-size:13px;margin-bottom:20px}
.card{background:#fff;border:1px solid #e5e7eb;border-radius:8px;padding:16px;margin-bottom:16px}
.card h2{font-size:14px;margin:0 0 12px;color:#374151}
label{display:block;font-size:12px;font-weight:600;color:#4b5563;margin:12px 0 4px}
input,textarea,select{width:100%;padding:8px 10px;border:1px solid #d1d5db;border-radius:6px;font-size:13px;font-family:inherit}
textarea{min-height:64px;resize:vertical}
.row{display:grid;gap:12px;grid-template-columns:1fr 1fr}
.item{border:1px solid #e5e7eb;border-radius:6px;padding:12px;margin-bottom:10px;background:#fafafa}
.item-head{display:flex;justify-content:space-between;align-items:center;gap:8px}
.btn{border:0;border-radius:6px;padding:9px 16px;font-size:13px;font-weight:700;cursor:pointer}
.btn-primary{background:#ffe100;color:#1f2328}
.btn-ghost{background:#f3f4f6;color:#374151}
.btn-danger{background:#fee2e2;color:#b91c1c}
.bar{position:sticky;bottom:0;background:#fff;border-top:1px solid #e5e7eb;padding:12px 16px;display:flex;gap:10px;justify-content:flex-end;margin:0 -16px -64px}
.msg{padding:10px 12px;border-radius:6px;font-size:13px;margin-bottom:12px;display:none}
.ok{background:#dcfce7;color:#166534}
.err{background:#fee2e2;color:#b91c1c}
.hint{font-size:11px;color:#9ca3af;margin-top:4px}
</style></head><body>
<div class="wrap">
  <h1>公告与版本发布</h1>
  <div class="sub">当前登录：<b id="who">—</b>　·　客户端拉取地址：<code>/announcement.json</code></div>
  <div id="msg" class="msg"></div>

  <div class="card">
    <h2>版本更新</h2>
    <div class="row">
      <div><label>最新版本号</label><input id="ver" placeholder="1.1.0">
        <div class="hint">高于客户端本地版本才会提示更新</div></div>
      <div><label>下载地址</label><input id="url" placeholder="https://github.com/23Star/xianyu-super-butler/releases">
        <div class="hint">必须 https 开头</div></div>
    </div>
    <label>更新说明</label><textarea id="notes" placeholder="修复了哪些问题"></textarea>
  </div>

  <div class="card">
    <h2>公告列表 <span class="hint" id="cnt"></span></h2>
    <div id="list"></div>
    <button class="btn btn-ghost" onclick="addItem()">+ 添加公告</button>
  </div>

  <div class="bar">
    <button class="btn btn-ghost" onclick="load()">重新载入</button>
    <button class="btn btn-primary" onclick="save()">保存并发布</button>
  </div>
</div>
<script>
let data={announcements:[],latest_version:'',download_url:'',release_notes:''};
const $=id=>document.getElementById(id);
function show(t,ok){const m=$('msg');m.textContent=t;m.className='msg '+(ok?'ok':'err');m.style.display='block';setTimeout(()=>m.style.display='none',4000)}
function esc(s){return String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]))}
function render(){
  $('ver').value=data.latest_version||'';
  $('url').value=data.download_url||'';
  $('notes').value=data.release_notes||'';
  $('cnt').textContent='共 '+data.announcements.length+' 条';
  $('list').innerHTML=data.announcements.map((a,i)=>
    '<div class="item"><div class="item-head">'+
    '<select onchange="upd('+i+',\\'level\\',this.value)">'+
    ['info','warning','danger'].map(l=>'<option value="'+l+'"'+(a.level===l?' selected':'')+'>'+({info:'通知（蓝）',warning:'注意（黄）',danger:'重要（红）'})[l]+'</option>').join('')+
    '</select><button class="btn btn-danger" onclick="del('+i+')">删除</button></div>'+
    '<label>标题</label><input value="'+esc(a.title)+'" oninput="upd('+i+',\\'title\\',this.value)">'+
    '<label>内容</label><textarea oninput="upd('+i+',\\'content\\',this.value)">'+esc(a.content)+'</textarea>'+
    '<label>发布时间</label><input value="'+esc(a.published_at)+'" placeholder="2026-08-14 10:00" oninput="upd('+i+',\\'published_at\\',this.value)">'+
    '</div>').join('');
}
function upd(i,k,v){data.announcements[i][k]=v;if(k==='level')render()}
function del(i){data.announcements.splice(i,1);render()}
function addItem(){
  const d=new Date(),p=n=>String(n).padStart(2,'0');
  data.announcements.push({id:'a-'+Date.now(),title:'',content:'',level:'info',
    published_at:d.getFullYear()+'-'+p(d.getMonth()+1)+'-'+p(d.getDate())+' '+p(d.getHours())+':'+p(d.getMinutes())});
  render();
}
async function load(){
  try{const r=await fetch('/api/config');if(!r.ok)throw new Error('HTTP '+r.status);
    const j=await r.json();data={...data,...j.config};$('who').textContent=j.email||'—';render();
  }catch(e){show('载入失败：'+e.message,false)}
}
async function save(){
  data.latest_version=$('ver').value.trim();
  data.download_url=$('url').value.trim();
  data.release_notes=$('notes').value;
  try{
    const r=await fetch('/api/config',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
    const j=await r.json();
    if(!r.ok)throw new Error(j.error||('HTTP '+r.status));
    data=j.config;render();show('已发布，客户端 10 分钟内生效',true);
  }catch(e){show('保存失败：'+e.message,false)}
}
load();
</script></body></html>`;

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const path = url.pathname;

    // ---- 公开接口：客户端拉取公告 ----
    if (path === '/announcement.json' || path === '/') {
      if (request.method !== 'GET' && request.method !== 'HEAD') {
        return json({ error: 'Method Not Allowed' }, 405);
      }
      const config = await readConfig(env);
      // 只吐客户端需要的字段，updated_at 之类内部信息不外泄
      return json({
        announcements: config.announcements,
        latest_version: config.latest_version,
        download_url: config.download_url,
        release_notes: config.release_notes,
      }, 200, {
        // 客户端自身也有缓存，这里给边缘一个短缓存降低回源
        'Cache-Control': 'public, max-age=60',
        'Access-Control-Allow-Origin': '*',
      });
    }

    // ---- 管理界面 ----
    if (path === '/admin') {
      try {
        assertAccess(request);
      } catch (e) {
        return json({ error: e.message }, 403);
      }
      return new Response(ADMIN_HTML, {
        headers: securityHeaders({
          'Content-Type': 'text/html; charset=utf-8',
          // 页面所有脚本样式都内联，禁止任何外部资源与框架嵌套
          'Content-Security-Policy':
            "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
        }),
      });
    }

    // ---- 配置读写 ----
    if (path === '/api/config') {
      try {
        assertAccess(request);
      } catch (e) {
        return json({ error: e.message }, 403);
      }

      if (request.method === 'GET') {
        return json({
          config: await readConfig(env),
          email: accessEmail(request),
        }, 200, { 'Cache-Control': 'no-store' });
      }

      if (request.method === 'PUT') {
        const raw = await request.text();
        if (raw.length > MAX_BODY_BYTES) {
          return json({ error: '内容过大' }, 413);
        }
        let parsed;
        try {
          parsed = JSON.parse(raw);
        } catch {
          return json({ error: 'JSON 格式错误' }, 400);
        }

        let config;
        try {
          config = sanitizeConfig(parsed);
        } catch (e) {
          return json({ error: e.message }, 400);
        }

        await env.ANNOUNCEMENT_KV.put(CONFIG_KEY, JSON.stringify(config));
        return json({ ok: true, config }, 200, { 'Cache-Control': 'no-store' });
      }

      return json({ error: 'Method Not Allowed' }, 405);
    }

    return json({ error: 'Not Found' }, 404);
  },
};
