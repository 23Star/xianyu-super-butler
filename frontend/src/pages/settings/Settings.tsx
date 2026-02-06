import { useState, useEffect, useRef } from 'react'
import { Settings as SettingsIcon, Save, Bot, Mail, RefreshCw, Key, Download, Upload, Archive, Eye, EyeOff, Copy } from 'lucide-react'
import { getSystemSettings, updateSystemSettings, testAIConnection, testEmailSend, changePassword, downloadDatabaseBackup, uploadDatabaseBackup, reloadSystemCache, exportUserBackup, importUserBackup } from '@/api/settings'
import { getAccounts } from '@/api/accounts'
import { useUIStore } from '@/store/uiStore'
import { useAuthStore } from '@/store/authStore'
import { PageLoading, ButtonLoading } from '@/components/common/Loading'
import { Select } from '@/components/common/Select'
import type { SystemSettings, Account } from '@/types'

export function Settings() {
  const { addToast } = useUIStore()
  const { isAuthenticated, token, _hasHydrated, user } = useAuthStore()
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [settings, setSettings] = useState<SystemSettings | null>(null)
  
  // 密码修改状态
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [changingPassword, setChangingPassword] = useState(false)
  
  // 备份管理状态
  const [uploadingBackup, setUploadingBackup] = useState(false)
  const [reloadingCache, setReloadingCache] = useState(false)
  const backupFileRef = useRef<HTMLInputElement>(null)
  const userBackupFileRef = useRef<HTMLInputElement>(null)
  
  // AI 测试账号选择
  const [accounts, setAccounts] = useState<Account[]>([])
  const [testAccountId, setTestAccountId] = useState('')
  const [testingAI, setTestingAI] = useState(false)

  // SMTP密码显示状态
  const [showSmtpPassword, setShowSmtpPassword] = useState(false)
  // API Key 显示状态
  const [showApiKey, setShowApiKey] = useState(false)
  // 密码修改显示状态
  const [showCurrentPassword, setShowCurrentPassword] = useState(false)
  const [showNewPassword, setShowNewPassword] = useState(false)
  const [showConfirmPassword, setShowConfirmPassword] = useState(false)

  const loadSettings = async () => {
    if (!_hasHydrated || !isAuthenticated || !token) return
    try {
      setLoading(true)
      const result = await getSystemSettings()
      if (result.success && result.data) {
        setSettings(result.data)
      }
    } catch {
      addToast({ type: 'error', message: '加载系统设置失败' })
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (!_hasHydrated || !isAuthenticated || !token) return
    loadSettings()
  }, [_hasHydrated, isAuthenticated, token])

  const handleSave = async () => {
    if (!settings) return
    try {
      setSaving(true)
      const result = await updateSystemSettings(settings)
      if (result.success) {
        addToast({ type: 'success', message: '设置保存成功' })
      } else {
        addToast({ type: 'error', message: result.message || '保存失败' })
      }
    } catch {
      addToast({ type: 'error', message: '保存设置失败' })
    } finally {
      setSaving(false)
    }
  }

  // 加载账号列表
  const loadAccounts = async () => {
    try {
      const data = await getAccounts()
      setAccounts(data)
      if (data.length > 0 && !testAccountId) {
        setTestAccountId(data[0].id)
      }
    } catch {
      // ignore
    }
  }

  useEffect(() => {
    if (_hasHydrated && isAuthenticated && token) {
      loadAccounts()
    }
  }, [_hasHydrated, isAuthenticated, token])

  const handleTestAI = async () => {
    if (!testAccountId) {
      addToast({ type: 'warning', message: '请先选择一个账号' })
      return
    }
    setTestingAI(true)
    try {
      // 测试前先保存当前设置，确保使用最新配置
      if (settings) {
        await updateSystemSettings(settings)
      }
      
      const result = await testAIConnection(testAccountId)
      if (result.success) {
        addToast({ type: 'success', message: result.message || 'AI 连接测试成功' })
      } else {
        addToast({ type: 'error', message: result.message || 'AI 连接测试失败' })
      }
    } catch {
      addToast({ type: 'error', message: 'AI 连接测试失败' })
    } finally {
      setTestingAI(false)
    }
  }

  const handleTestEmail = async () => {
    const email = prompt('请输入测试邮箱地址:')
    if (!email) return
    try {
      const result = await testEmailSend(email)
      if (result.success) {
        addToast({ type: 'success', message: '测试邮件发送成功' })
      } else {
        addToast({ type: 'error', message: result.message || '发送测试邮件失败' })
      }
    } catch {
      addToast({ type: 'error', message: '发送测试邮件失败' })
    }
  }

  // 修改密码
  const handleChangePassword = async () => {
    if (!currentPassword) {
      addToast({ type: 'warning', message: '请输入当前密码' })
      return
    }
    if (!newPassword) {
      addToast({ type: 'warning', message: '请输入新密码' })
      return
    }
    if (newPassword !== confirmPassword) {
      addToast({ type: 'warning', message: '两次输入的密码不一致' })
      return
    }
    if (newPassword.length < 6) {
      addToast({ type: 'warning', message: '新密码长度不能少于6位' })
      return
    }
    try {
      setChangingPassword(true)
      const result = await changePassword({ current_password: currentPassword, new_password: newPassword })
      if (result.success) {
        addToast({ type: 'success', message: '密码修改成功' })
        setCurrentPassword('')
        setNewPassword('')
        setConfirmPassword('')
      } else {
        addToast({ type: 'error', message: result.message || '密码修改失败' })
      }
    } catch {
      addToast({ type: 'error', message: '密码修改失败' })
    } finally {
      setChangingPassword(false)
    }
  }

  // 下载数据库备份（管理员）
  const handleDownloadBackup = () => {
    const url = downloadDatabaseBackup()
    window.open(url, '_blank')
  }

  // 上传数据库备份（管理员）
  const handleUploadBackup = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    if (!file.name.endsWith('.db')) {
      addToast({ type: 'error', message: '只支持 .db 格式的数据库文件' })
      return
    }
    if (!confirm('警告：恢复数据库将覆盖所有当前数据！确定要继续吗？')) {
      e.target.value = ''
      return
    }
    try {
      setUploadingBackup(true)
      const result = await uploadDatabaseBackup(file)
      if (result.success) {
        addToast({ type: 'success', message: '数据库恢复成功' })
      } else {
        addToast({ type: 'error', message: result.message || '数据库恢复失败' })
      }
    } catch {
      addToast({ type: 'error', message: '数据库恢复失败' })
    } finally {
      setUploadingBackup(false)
      e.target.value = ''
    }
  }

  // 刷新系统缓存
  const handleReloadCache = async () => {
    try {
      setReloadingCache(true)
      const result = await reloadSystemCache()
      if (result.success) {
        addToast({ type: 'success', message: '系统缓存已刷新' })
      } else {
        addToast({ type: 'error', message: result.message || '刷新缓存失败' })
      }
    } catch {
      addToast({ type: 'error', message: '刷新缓存失败' })
    } finally {
      setReloadingCache(false)
    }
  }

  // 导出用户备份
  const handleExportUserBackup = () => {
    const url = exportUserBackup()
    window.open(url, '_blank')
  }

  // 导入用户备份
  const handleImportUserBackup = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    if (!file.name.endsWith('.json')) {
      addToast({ type: 'error', message: '只支持 .json 格式的备份文件' })
      return
    }
    try {
      const result = await importUserBackup(file)
      if (result.success) {
        addToast({ type: 'success', message: '备份导入成功' })
      } else {
        addToast({ type: 'error', message: result.message || '备份导入失败' })
      }
    } catch {
      addToast({ type: 'error', message: '备份导入失败' })
    } finally {
      e.target.value = ''
    }
  }

  if (loading) {
    return <PageLoading />
  }

  const isAdmin = user?.is_admin

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="page-header flex-between flex-wrap gap-4">
        <div>
          <h1 className="page-title">系统设置</h1>
          <p className="page-description">{isAdmin ? '配置系统全局设置' : '修改个人密码'}</p>
        </div>
        <div className="flex gap-2">
          {isAdmin && (
            <>
              <button onClick={loadSettings} className="btn-ios-secondary">
                <RefreshCw className="w-4 h-4" />
                刷新
              </button>
              <button onClick={handleSave} disabled={saving} className="btn-ios-primary">
                {saving ? <ButtonLoading /> : <Save className="w-4 h-4" />}
                保存设置
              </button>
            </>
          )}
        </div>
      </div>

      {/* 双列布局 */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* 左列 - 仅管理员可见 */}
        {isAdmin && (
        <div className="space-y-4">
          {/* General Settings */}
          <div className="vben-card">
            <div className="vben-card-header">
              <h2 className="vben-card-title">
                <SettingsIcon className="w-4 h-4" />
                基础设置
              </h2>
            </div>
            <div className="vben-card-body space-y-4">
              <div className="flex items-center justify-between py-3 border-b border-slate-100 dark:border-slate-700">
                <div>
                  <p className="font-medium text-slate-900 dark:text-slate-100">允许用户注册</p>
                  <p className="text-sm text-slate-500 dark:text-slate-400">开启后允许新用户注册账号</p>
                </div>
                <label className="switch-ios">
                  <input
                    type="checkbox"
                    checked={Boolean(settings?.registration_enabled ?? false)}
                    onChange={(e) => setSettings(s => s ? { ...s, registration_enabled: e.target.checked } : null)}
                  />
                  <span className="switch-slider"></span>
                </label>
              </div>

              <div className="flex items-center justify-between py-3">
                <div>
                  <p className="font-medium text-slate-900 dark:text-slate-100">显示默认登录信息</p>
                  <p className="text-sm text-slate-500 dark:text-slate-400">登录页面显示默认账号密码提示</p>
                </div>
                <label className="switch-ios">
                  <input
                    type="checkbox"
                    checked={Boolean(settings?.show_default_login_info ?? false)}
                    onChange={(e) => setSettings(s => s ? { ...s, show_default_login_info: e.target.checked } : null)}
                  />
                  <span className="switch-slider"></span>
                </label>
              </div>

              <div className="flex items-center justify-between py-3 border-t border-slate-100 dark:border-slate-700">
                <div>
                  <p className="font-medium text-slate-900 dark:text-slate-100">登录滑动验证码</p>
                  <p className="text-sm text-slate-500 dark:text-slate-400">开启后账号密码登录需要完成滑动验证</p>
                </div>
                <label className="switch-ios">
                  <input
                    type="checkbox"
                    checked={Boolean(settings?.login_captcha_enabled ?? true)}
                    onChange={(e) => setSettings(s => s ? { ...s, login_captcha_enabled: e.target.checked } : null)}
                  />
                  <span className="switch-slider"></span>
                </label>
              </div>

              {/* 商品同步设置 */}
              <div className="flex items-center justify-between py-3 border-t border-slate-100 dark:border-slate-700">
                <div>
                  <p className="font-medium text-slate-900 dark:text-slate-100">启用商品自动同步</p>
                  <p className="text-sm text-slate-500 dark:text-slate-400">定时自动获取商品信息到本地数据库</p>
                </div>
                <label className="switch-ios">
                  <input
                    type="checkbox"
                    checked={Boolean(settings?.item_sync_enabled ?? false)}
                    onChange={(e) => setSettings(s => s ? { ...s, item_sync_enabled: e.target.checked } : null)}
                  />
                  <span className="switch-slider"></span>
                </label>
              </div>

              <div className="input-group pt-2">
                <label className="input-label">商品同步间隔（分钟）</label>
                <input
                  type="number"
                  value={Math.round((settings?.item_sync_interval ?? 600) / 60)}
                  onChange={(e) => {
                    const minutes = parseInt(e.target.value) || 10
                    setSettings(s => s ? { ...s, item_sync_interval: minutes * 60 } : null)
                  }}
                  className="input-ios"
                  min="1"
                  max="1440"
                />
                <p className="text-xs text-slate-400 mt-1">建议：10-60分钟，当前：{Math.round((settings?.item_sync_interval ?? 600) / 60)} 分钟</p>
              </div>

              <div className="input-group">
                <label className="input-label">每次最多同步页数</label>
                <input
                  type="number"
                  value={settings?.item_sync_max_pages ?? 5}
                  onChange={(e) => setSettings(s => s ? { ...s, item_sync_max_pages: parseInt(e.target.value) || 5 } : null)}
                  className="input-ios"
                  min="1"
                  max="50"
                />
                <p className="text-xs text-slate-400 mt-1">每页20个商品</p>
              </div>
            </div>
          </div>

          {/* AI Settings */}
          <div className="vben-card">
            <div className="vben-card-header">
              <h2 className="vben-card-title">
                <Bot className="w-4 h-4" />
                AI 设置
              </h2>
            </div>
            <div className="vben-card-body space-y-4">
              <div className="input-group">
                <label className="input-label">API 地址</label>
                <input
                  type="text"
                  value={settings?.ai_api_url || 'https://dashscope.aliyuncs.com/compatible-mode/v1'}
                  onChange={(e) => setSettings(s => s ? { ...s, ai_api_url: e.target.value } : null)}
                  className="input-ios"
                />
                <p className="text-xs text-slate-400 mt-1">无需补全 /chat/completions</p>
              </div>
              <div className="input-group">
                <label className="input-label">API Key</label>
                <div className="relative">
                  <input
                    type={showApiKey ? 'text' : 'password'}
                    value={settings?.ai_api_key || ''}
                    onChange={(e) => setSettings(s => s ? { ...s, ai_api_key: e.target.value } : null)}
                    placeholder="sk-..."
                    className="input-ios w-full pr-20"
                  />
                  <div className="absolute right-2 top-1/2 -translate-y-1/2 flex gap-1">
                    <button
                      type="button"
                      onClick={() => setShowApiKey(!showApiKey)}
                      className="p-1.5 text-slate-400 hover:text-slate-600 dark:hover:text-slate-300"
                      title={showApiKey ? '隐藏' : '显示'}
                    >
                      {showApiKey ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        if (settings?.ai_api_key) {
                          navigator.clipboard.writeText(settings.ai_api_key)
                          addToast({ type: 'success', message: '已复制到剪贴板' })
                        }
                      }}
                      className="p-1.5 text-slate-400 hover:text-slate-600 dark:hover:text-slate-300"
                      title="复制"
                    >
                      <Copy className="w-4 h-4" />
                    </button>
                  </div>
                </div>
              </div>
              <div className="input-group">
                <label className="input-label">模型</label>
                <input
                  type="text"
                  value={settings?.ai_model || 'qwen-plus'}
                  onChange={(e) => setSettings(s => s ? { ...s, ai_model: e.target.value } : null)}
                  className="input-ios"
                />
                <p className="text-xs text-slate-400 mt-1">如: qwen-plus、qwen-turbo、gpt-3.5-turbo、gpt-4</p>
              </div>
              <div className="flex items-end gap-2">
                <div className="flex-1">
                  <label className="input-label">测试账号</label>
                  <Select
                    value={testAccountId}
                    onChange={setTestAccountId}
                    options={accounts.map(a => ({ value: a.id, label: a.id }))}
                    placeholder="选择账号"
                  />
                </div>
                <button 
                  onClick={handleTestAI} 
                  className="btn-ios-secondary"
                  disabled={testingAI || !testAccountId}
                >
                  {testingAI ? '测试中...' : '测试 AI 连接'}
                </button>
              </div>
              <div className="bg-slate-50 dark:bg-slate-800/50 rounded-lg p-3 text-xs text-slate-500 dark:text-slate-400">
                <p className="font-medium mb-1">常见 AI 服务配置:</p>
                <ul className="space-y-0.5 list-disc list-inside">
                  <li>阿里云通义千问: https://dashscope.aliyuncs.com/compatible-mode/v1</li>
                  <li>OpenAI: https://api.openai.com/v1</li>
                  <li>国内中转: 使用服务商提供的 API 地址</li>
                </ul>
              </div>
            </div>
          </div>
        </div>
        )}

        {/* 右列 */}
        <div className="space-y-4">
          {/* Email Settings - 仅管理员可见 */}
          {isAdmin && (
          <div className="vben-card">
            <div className="vben-card-header">
              <h2 className="vben-card-title">
                <Mail className="w-4 h-4" />
                SMTP邮件配置
              </h2>
            </div>
            <div className="vben-card-body space-y-4">
              <p className="text-sm text-slate-500 dark:text-slate-400">配置SMTP服务器用于发送注册验证码等邮件通知</p>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="input-group">
                  <label className="input-label">SMTP服务器</label>
                  <input
                    type="text"
                    value={settings?.smtp_server || ''}
                    onChange={(e) => setSettings(s => s ? { ...s, smtp_server: e.target.value } : null)}
                    placeholder="smtp.qq.com"
                    className="input-ios"
                  />
                  <p className="text-xs text-slate-400 mt-1">如：smtp.qq.com、smtp.gmail.com</p>
                </div>
                <div className="input-group">
                  <label className="input-label">SMTP端口</label>
                  <input
                    type="number"
                    value={settings?.smtp_port || 587}
                    onChange={(e) => setSettings(s => s ? { ...s, smtp_port: parseInt(e.target.value) } : null)}
                    placeholder="587"
                    className="input-ios"
                  />
                  <p className="text-xs text-slate-400 mt-1">通常为587(TLS)或465(SSL)</p>
                </div>
              </div>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="input-group">
                  <label className="input-label">发件邮箱</label>
                  <input
                    type="email"
                    value={settings?.smtp_user || ''}
                    onChange={(e) => setSettings(s => s ? { ...s, smtp_user: e.target.value } : null)}
                    placeholder="your-email@qq.com"
                    className="input-ios"
                  />
                  <p className="text-xs text-slate-400 mt-1">用于发送邮件的邮箱地址</p>
                </div>
                <div className="input-group">
                  <label className="input-label">邮箱密码/授权码</label>
                  <div className="relative">
                    <input
                      type={showSmtpPassword ? 'text' : 'password'}
                      value={settings?.smtp_password || ''}
                      onChange={(e) => setSettings(s => s ? { ...s, smtp_password: e.target.value } : null)}
                      placeholder="输入密码或授权码"
                      className="input-ios w-full pr-20"
                    />
                    <div className="absolute right-2 top-1/2 -translate-y-1/2 flex gap-1">
                      <button
                        type="button"
                        onClick={() => setShowSmtpPassword(!showSmtpPassword)}
                        className="p-1.5 text-slate-400 hover:text-slate-600 dark:hover:text-slate-300"
                        title={showSmtpPassword ? '隐藏' : '显示'}
                      >
                        {showSmtpPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                      </button>
                      <button
                        type="button"
                        onClick={() => {
                          if (settings?.smtp_password) {
                            navigator.clipboard.writeText(settings.smtp_password)
                            addToast({ type: 'success', message: '已复制到剪贴板' })
                          }
                        }}
                        className="p-1.5 text-slate-400 hover:text-slate-600 dark:hover:text-slate-300"
                        title="复制"
                      >
                        <Copy className="w-4 h-4" />
                      </button>
                    </div>
                  </div>
                  <p className="text-xs text-slate-400 mt-1">邮箱密码或应用专用密码(QQ邮箱需要授权码)</p>
                </div>
              </div>
              <div className="input-group">
                <label className="input-label">发件人显示名（可选）</label>
                <input
                  type="text"
                  value={settings?.smtp_from || ''}
                  onChange={(e) => setSettings(s => s ? { ...s, smtp_from: e.target.value } : null)}
                  placeholder="闲鱼自动回复系统"
                  className="input-ios"
                />
                <p className="text-xs text-slate-400 mt-1">邮件发件人显示的名称，留空则使用邮箱地址</p>
              </div>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="flex items-center justify-between py-3 border-b border-slate-100 dark:border-slate-700">
                  <div>
                    <p className="font-medium text-slate-900 dark:text-slate-100">启用TLS</p>
                    <p className="text-sm text-slate-500 dark:text-slate-400">通常用于端口587</p>
                  </div>
                  <label className="switch-ios">
                    <input
                      type="checkbox"
                      checked={Boolean(settings?.smtp_use_tls ?? true)}
                      onChange={(e) => setSettings(s => s ? { ...s, smtp_use_tls: e.target.checked } : null)}
                    />
                    <span className="switch-slider"></span>
                  </label>
                </div>
                <div className="flex items-center justify-between py-3 border-b border-slate-100 dark:border-slate-700">
                  <div>
                    <p className="font-medium text-slate-900 dark:text-slate-100">启用SSL</p>
                    <p className="text-sm text-slate-500 dark:text-slate-400">通常用于端口465</p>
                  </div>
                  <label className="switch-ios">
                    <input
                      type="checkbox"
                      checked={Boolean(settings?.smtp_use_ssl ?? false)}
                      onChange={(e) => setSettings(s => s ? { ...s, smtp_use_ssl: e.target.checked } : null)}
                    />
                    <span className="switch-slider"></span>
                  </label>
                </div>
              </div>
              <button onClick={handleTestEmail} className="btn-ios-secondary">
                发送测试邮件
              </button>
            </div>
          </div>
          )}

          {/* 密码修改 */}
          <div className="vben-card">
            <div className="vben-card-header">
              <h2 className="vben-card-title">
                <Key className="w-4 h-4" />
                修改密码
              </h2>
            </div>
            <div className="vben-card-body space-y-4">
              <div className="input-group">
                <label className="input-label">当前密码</label>
                <div className="relative">
                  <input
                    type={showCurrentPassword ? 'text' : 'password'}
                    value={currentPassword}
                    onChange={(e) => setCurrentPassword(e.target.value)}
                    placeholder="请输入当前密码"
                    className="input-ios w-full pr-20"
                  />
                  <div className="absolute right-2 top-1/2 -translate-y-1/2 flex gap-1">
                    <button
                      type="button"
                      onClick={() => setShowCurrentPassword(!showCurrentPassword)}
                      className="p-1.5 text-slate-400 hover:text-slate-600 dark:hover:text-slate-300"
                      title={showCurrentPassword ? '隐藏' : '显示'}
                    >
                      {showCurrentPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        if (currentPassword) {
                          navigator.clipboard.writeText(currentPassword)
                          addToast({ type: 'success', message: '已复制到剪贴板' })
                        }
                      }}
                      className="p-1.5 text-slate-400 hover:text-slate-600 dark:hover:text-slate-300"
                      title="复制"
                    >
                      <Copy className="w-4 h-4" />
                    </button>
                  </div>
                </div>
              </div>
              <div className="input-group">
                <label className="input-label">新密码</label>
                <div className="relative">
                  <input
                    type={showNewPassword ? 'text' : 'password'}
                    value={newPassword}
                    onChange={(e) => setNewPassword(e.target.value)}
                    placeholder="请输入新密码"
                    className="input-ios w-full pr-20"
                  />
                  <div className="absolute right-2 top-1/2 -translate-y-1/2 flex gap-1">
                    <button
                      type="button"
                      onClick={() => setShowNewPassword(!showNewPassword)}
                      className="p-1.5 text-slate-400 hover:text-slate-600 dark:hover:text-slate-300"
                      title={showNewPassword ? '隐藏' : '显示'}
                    >
                      {showNewPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        if (newPassword) {
                          navigator.clipboard.writeText(newPassword)
                          addToast({ type: 'success', message: '已复制到剪贴板' })
                        }
                      }}
                      className="p-1.5 text-slate-400 hover:text-slate-600 dark:hover:text-slate-300"
                      title="复制"
                    >
                      <Copy className="w-4 h-4" />
                    </button>
                  </div>
                </div>
              </div>
              <div className="input-group">
                <label className="input-label">确认新密码</label>
                <div className="relative">
                  <input
                    type={showConfirmPassword ? 'text' : 'password'}
                    value={confirmPassword}
                    onChange={(e) => setConfirmPassword(e.target.value)}
                    placeholder="请再次输入新密码"
                    className="input-ios w-full pr-20"
                  />
                  <div className="absolute right-2 top-1/2 -translate-y-1/2 flex gap-1">
                    <button
                      type="button"
                      onClick={() => setShowConfirmPassword(!showConfirmPassword)}
                      className="p-1.5 text-slate-400 hover:text-slate-600 dark:hover:text-slate-300"
                      title={showConfirmPassword ? '隐藏' : '显示'}
                    >
                      {showConfirmPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        if (confirmPassword) {
                          navigator.clipboard.writeText(confirmPassword)
                          addToast({ type: 'success', message: '已复制到剪贴板' })
                        }
                      }}
                      className="p-1.5 text-slate-400 hover:text-slate-600 dark:hover:text-slate-300"
                      title="复制"
                    >
                      <Copy className="w-4 h-4" />
                    </button>
                  </div>
                </div>
              </div>
              <button
                onClick={handleChangePassword}
                disabled={changingPassword}
                className="btn-ios-primary"
              >
                {changingPassword ? <ButtonLoading /> : <Key className="w-4 h-4" />}
                修改密码
              </button>
            </div>
          </div>

          {/* 数据备份 */}
          <div className="vben-card">
            <div className="vben-card-header">
              <h2 className="vben-card-title">
                <Archive className="w-4 h-4" />
                数据备份
              </h2>
            </div>
            <div className="vben-card-body space-y-4">
              {/* 用户数据备份 */}
              <div>
                <p className="font-medium text-slate-900 dark:text-slate-100 mb-1">用户数据备份</p>
                <p className="text-sm text-slate-500 dark:text-slate-400 mb-2">导出您的账号、关键词、卡券等数据</p>
                <div className="flex flex-wrap gap-2">
                  <button onClick={handleExportUserBackup} className="btn-ios-primary">
                    <Download className="w-4 h-4" />
                    导出备份
                  </button>
                  <label className="btn-ios-secondary cursor-pointer">
                    <Upload className="w-4 h-4" />
                    导入备份
                    <input
                      ref={userBackupFileRef}
                      type="file"
                      accept=".json"
                      className="hidden"
                      onChange={handleImportUserBackup}
                    />
                  </label>
                </div>
              </div>

              {/* 管理员数据库备份 */}
              {user?.is_admin && (
                <div className="border-t border-slate-200 dark:border-slate-700 pt-4">
                  <div className="flex items-center gap-2 mb-1">
                    <p className="font-medium text-slate-900 dark:text-slate-100">数据库备份</p>
                    <span className="text-xs bg-slate-500 text-white px-1.5 py-0.5 rounded">管理员</span>
                  </div>
                  <p className="text-sm text-slate-500 dark:text-slate-400 mb-2">完整备份或恢复整个数据库</p>
                  <div className="flex flex-wrap gap-2 mb-2">
                    <button onClick={handleDownloadBackup} className="btn-ios-primary">
                      <Download className="w-4 h-4" />
                      下载数据库
                    </button>
                    <label className="btn-ios-secondary cursor-pointer">
                      {uploadingBackup ? <ButtonLoading /> : <Upload className="w-4 h-4" />}
                      恢复数据库
                      <input
                        ref={backupFileRef}
                        type="file"
                        accept=".db"
                        className="hidden"
                        onChange={handleUploadBackup}
                        disabled={uploadingBackup}
                      />
                    </label>
                    <button
                      onClick={handleReloadCache}
                      disabled={reloadingCache}
                      className="btn-ios-secondary"
                    >
                      {reloadingCache ? <ButtonLoading /> : <RefreshCw className="w-4 h-4" />}
                      刷新缓存
                    </button>
                  </div>
                  <p className="text-xs text-slate-500 dark:text-slate-400">
                    注意：恢复数据库将覆盖所有当前数据，请谨慎操作
                  </p>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
