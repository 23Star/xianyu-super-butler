import React, { useEffect, useState } from 'react';
import { getSystemSettings, updateSystemSettings } from '../services/api';
import { SystemSettings } from '../types';
import {
  Save, Sparkles, Mail, Settings as SettingsIcon,
  Eye, EyeOff, RefreshCw, Database
} from 'lucide-react';

const Settings: React.FC = () => {
  const [settings, setSettings] = useState<SystemSettings | null>(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);

  // Password visibility states
  const [showApiKey, setShowApiKey] = useState(false);
  const [showSmtpPassword, setShowSmtpPassword] = useState(false);

  useEffect(() => {
    loadSettings();
  }, []);

  const loadSettings = () => {
    setLoading(true);
    getSystemSettings().then(setSettings).finally(() => setLoading(false));
  };

  const handleSave = async () => {
      if(!settings) return;
      setSaving(true);
      try {
        await updateSystemSettings(settings);
        alert('系统配置已保存');
      } catch (e) {
        alert('保存失败：' + (e as Error).message);
      } finally {
        setSaving(false);
      }
  };

  if (!settings) return <div className="p-8 text-center text-gray-400">加载配置中...</div>;

  return (
    <div className="max-w-6xl mx-auto space-y-6 animate-fade-in">
      {/* Header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-4">
          <div className="w-12 h-12 bg-gray-100 rounded-2xl flex items-center justify-center">
              <SettingsIcon className="w-6 h-6 text-gray-600" />
          </div>
          <div>
              <h2 className="text-2xl font-bold text-gray-900">系统设置</h2>
              <p className="text-gray-500 mt-1 text-sm font-medium">配置全局自动化规则与系统参数</p>
          </div>
        </div>
        <button
          onClick={loadSettings}
          className="px-4 py-2 bg-gray-100 hover:bg-gray-200 rounded-xl font-bold text-gray-700 flex items-center gap-2 transition-colors"
        >
          <RefreshCw className="w-4 h-4" />
          刷新
        </button>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
        {/* Left Column */}
        <div className="space-y-8">
          {/* Basic Settings */}
          <section className="space-y-4">
            <h3 className="text-lg font-extrabold text-gray-800 flex items-center gap-2">
                <div className="p-1.5 rounded-lg bg-gray-100 text-gray-600">
                    <Database className="w-4 h-4" />
                </div>
                基础设置
            </h3>

            <div className="ios-card p-6 bg-white space-y-4">
              <div className="flex items-center justify-between p-4 bg-gray-50 rounded-xl">
                <div>
                  <div className="font-bold text-gray-900">允许用户注册</div>
                  <div className="text-xs text-gray-500 mt-1">开启后允许新用户注册账号</div>
                </div>
                <button
                  onClick={() => setSettings({...settings, registration_enabled: !settings.registration_enabled})}
                  className={`w-14 h-8 rounded-full transition-all relative ${
                    settings.registration_enabled ? 'bg-[#FFE815]' : 'bg-gray-300'
                  }`}
                >
                  <div
                    className={`w-6 h-6 bg-white rounded-full absolute top-1 transition-all shadow-md ${
                      settings.registration_enabled ? 'left-7' : 'left-1'
                    }`}
                  />
                </button>
              </div>

              <div className="flex items-center justify-between p-4 bg-gray-50 rounded-xl">
                <div>
                  <div className="font-bold text-gray-900">显示默认登录信息</div>
                  <div className="text-xs text-gray-500 mt-1">登录页面显示默认账号密码提示</div>
                </div>
                <button
                  onClick={() => setSettings({...settings, show_default_login_info: !settings.show_default_login_info})}
                  className={`w-14 h-8 rounded-full transition-all relative ${
                    settings.show_default_login_info ? 'bg-[#FFE815]' : 'bg-gray-300'
                  }`}
                >
                  <div
                    className={`w-6 h-6 bg-white rounded-full absolute top-1 transition-all shadow-md ${
                      settings.show_default_login_info ? 'left-7' : 'left-1'
                    }`}
                  />
                </button>
              </div>

              <div className="flex items-center justify-between p-4 bg-gray-50 rounded-xl">
                <div>
                  <div className="font-bold text-gray-900">登录滑动验证码</div>
                  <div className="text-xs text-gray-500 mt-1">开启后账号密码登录需要完成滑动验证</div>
                </div>
                <button
                  onClick={() => setSettings({...settings, login_captcha_enabled: !settings.login_captcha_enabled})}
                  className={`w-14 h-8 rounded-full transition-all relative ${
                    settings.login_captcha_enabled ? 'bg-[#FFE815]' : 'bg-gray-300'
                  }`}
                >
                  <div
                    className={`w-6 h-6 bg-white rounded-full absolute top-1 transition-all shadow-md ${
                      settings.login_captcha_enabled ? 'left-7' : 'left-1'
                    }`}
                  />
                </button>
              </div>

              <div className="flex items-center justify-between p-4 bg-gray-50 rounded-xl">
                <div>
                  <div className="font-bold text-gray-900">启用商品自动同步</div>
                  <div className="text-xs text-gray-500 mt-1">定时自动获取商品信息到本地数据库</div>
                </div>
                <button
                  onClick={() => setSettings({...settings, item_sync_enabled: !settings.item_sync_enabled})}
                  className={`w-14 h-8 rounded-full transition-all relative ${
                    settings.item_sync_enabled ? 'bg-[#FFE815]' : 'bg-gray-300'
                  }`}
                >
                  <div
                    className={`w-6 h-6 bg-white rounded-full absolute top-1 transition-all shadow-md ${
                      settings.item_sync_enabled ? 'left-7' : 'left-1'
                    }`}
                  />
                </button>
              </div>

              <div className="space-y-3 px-4">
                <label className="block text-sm font-bold text-gray-800">商品同步间隔（分钟）</label>
                <input
                  type="number"
                  value={Math.round((settings.item_sync_interval || 600) / 60)}
                  onChange={(e) => {
                    const minutes = parseInt(e.target.value) || 10;
                    setSettings({...settings, item_sync_interval: minutes * 60});
                  }}
                  className="w-full ios-input px-4 py-3 rounded-xl"
                  min="1"
                  max="1440"
                />
                <p className="text-xs text-gray-500">建议：10-60分钟</p>
              </div>

              <div className="space-y-3 px-4">
                <label className="block text-sm font-bold text-gray-800">每次最多同步页数</label>
                <input
                  type="number"
                  value={settings.item_sync_max_pages || 5}
                  onChange={(e) => setSettings({...settings, item_sync_max_pages: parseInt(e.target.value) || 5})}
                  className="w-full ios-input px-4 py-3 rounded-xl"
                  min="1"
                  max="50"
                />
                <p className="text-xs text-gray-500">每页20个商品</p>
              </div>
            </div>
          </section>

          {/* AI Configuration */}
          <section className="space-y-4">
            <h3 className="text-lg font-extrabold text-gray-800 flex items-center gap-2">
                <div className="p-1.5 rounded-lg bg-[#FFE815] text-black">
                    <Sparkles className="w-4 h-4" />
                </div>
                AI 智能回复配置
            </h3>

            <div className="ios-card p-6 bg-white space-y-6">
              <div className="space-y-3">
                <label className="block text-sm font-bold text-gray-800">API 地址</label>
                <input
                  type="text"
                  value={settings.ai_api_url || 'https://dashscope.aliyuncs.com/compatible-mode/v1'}
                  onChange={e => setSettings({...settings, ai_api_url: e.target.value})}
                  className="w-full ios-input px-4 py-3 rounded-xl text-sm"
                  placeholder="https://api.openai.com/v1"
                />
                <p className="text-xs text-gray-500">无需补全 /chat/completions</p>
              </div>

              <div className="space-y-3">
                <label className="block text-sm font-bold text-gray-800">API Key</label>
                <div className="relative">
                  <input
                    type={showApiKey ? 'text' : 'password'}
                    value={settings.ai_api_key || ''}
                    onChange={e => setSettings({...settings, ai_api_key: e.target.value})}
                    className="w-full ios-input px-4 py-3 pr-12 rounded-xl font-mono text-sm"
                    placeholder="sk-..."
                  />
                  <button
                    type="button"
                    onClick={() => setShowApiKey(!showApiKey)}
                    className="absolute right-3 top-1/2 -translate-y-1/2 p-2 text-gray-400 hover:text-gray-600 transition-colors"
                  >
                    {showApiKey ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                  </button>
                </div>
              </div>

              <div className="space-y-3">
                <label className="block text-sm font-bold text-gray-800">模型</label>
                <select
                  value={settings.ai_model || 'qwen-plus'}
                  onChange={e => setSettings({...settings, ai_model: e.target.value})}
                  className="w-full ios-input px-4 py-3 rounded-xl"
                >
                  <option value="qwen-plus">通义千问 Plus</option>
                  <option value="qwen-turbo">通义千问 Turbo</option>
                  <option value="gpt-3.5-turbo">GPT-3.5 Turbo</option>
                  <option value="gpt-4">GPT-4</option>
                </select>
              </div>

              <div className="space-y-3">
                <label className="block text-sm font-bold text-gray-800">默认自动回复内容</label>
                <textarea
                  className="w-full ios-input px-4 py-3 rounded-xl min-h-[100px] text-sm resize-none"
                  value={settings.default_reply || ''}
                  onChange={e => setSettings({...settings, default_reply: e.target.value})}
                  placeholder="设置默认的自动回复内容..."
                ></textarea>
              </div>

              <div className="p-3 bg-amber-50 rounded-xl text-xs text-amber-700">
                <strong>常见 AI 服务:</strong>
                <ul className="list-disc list-inside mt-1 space-y-0.5">
                  <li>阿里云通义千问: https://dashscope.aliyuncs.com/compatible-mode/v1</li>
                  <li>OpenAI: https://api.openai.com/v1</li>
                </ul>
              </div>
            </div>
          </section>
        </div>

        {/* Right Column */}
        <div className="space-y-8">
          {/* SMTP Settings */}
          <section className="space-y-4">
            <h3 className="text-lg font-extrabold text-gray-800 flex items-center gap-2">
                <div className="p-1.5 rounded-lg bg-blue-100 text-blue-600">
                    <Mail className="w-4 h-4" />
                </div>
                SMTP 邮件配置
            </h3>

            <div className="ios-card p-6 bg-white space-y-6">
              <p className="text-sm text-gray-500">配置SMTP服务器用于发送注册验证码等邮件通知</p>

              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-3">
                  <label className="block text-sm font-bold text-gray-800">SMTP服务器</label>
                  <input
                    type="text"
                    value={settings.smtp_server || ''}
                    onChange={e => setSettings({...settings, smtp_server: e.target.value})}
                    placeholder="smtp.qq.com"
                    className="w-full ios-input px-4 py-3 rounded-xl text-sm"
                  />
                </div>
                <div className="space-y-3">
                  <label className="block text-sm font-bold text-gray-800">SMTP端口</label>
                  <input
                    type="number"
                    value={settings.smtp_port || 587}
                    onChange={e => setSettings({...settings, smtp_port: parseInt(e.target.value)})}
                    placeholder="587"
                    className="w-full ios-input px-4 py-3 rounded-xl text-sm"
                  />
                </div>
              </div>

              <div className="space-y-3">
                <label className="block text-sm font-bold text-gray-800">发件邮箱</label>
                <input
                  type="email"
                  value={settings.smtp_user || ''}
                  onChange={e => setSettings({...settings, smtp_user: e.target.value})}
                  placeholder="your-email@qq.com"
                  className="w-full ios-input px-4 py-3 rounded-xl text-sm"
                />
              </div>

              <div className="space-y-3">
                <label className="block text-sm font-bold text-gray-800">邮箱密码/授权码</label>
                <div className="relative">
                  <input
                    type={showSmtpPassword ? 'text' : 'password'}
                    value={settings.smtp_password || ''}
                    onChange={e => setSettings({...settings, smtp_password: e.target.value})}
                    placeholder="输入密码或授权码"
                    className="w-full ios-input px-4 py-3 pr-12 rounded-xl text-sm"
                  />
                  <button
                    type="button"
                    onClick={() => setShowSmtpPassword(!showSmtpPassword)}
                    className="absolute right-3 top-1/2 -translate-y-1/2 p-2 text-gray-400 hover:text-gray-600 transition-colors"
                  >
                    {showSmtpPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                  </button>
                </div>
                <p className="text-xs text-gray-500">QQ邮箱需要使用授权码</p>
              </div>

              <div className="space-y-3">
                <label className="block text-sm font-bold text-gray-800">发件人显示名（可选）</label>
                <input
                  type="text"
                  value={settings.smtp_from || ''}
                  onChange={e => setSettings({...settings, smtp_from: e.target.value})}
                  placeholder="闲鱼自动回复系统"
                  className="w-full ios-input px-4 py-3 rounded-xl text-sm"
                />
              </div>
            </div>
          </section>
        </div>
      </div>

      {/* Save Button */}
      <div className="sticky bottom-0 z-20 flex justify-end border-t border-gray-200 bg-[#F4F5F7]/95 py-4 backdrop-blur-sm">
        <button
            onClick={handleSave}
            disabled={saving}
            className="ios-btn-primary flex w-full items-center justify-center gap-2 rounded-lg px-6 py-3 disabled:opacity-70 sm:w-auto"
        >
            <Save className="w-5 h-5" />
            {saving ? '保存中...' : '保存所有配置'}
        </button>
      </div>
    </div>
  );
};

export default Settings;
