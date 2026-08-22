import { useState, useCallback, useEffect } from 'react';
import {
  Settings,
  Bell,
  Mail,
  Smartphone,
  Send,
  Webhook,
  Check,
  Loader2,
  AlertTriangle,
  AlertCircle,
  X,
  ChevronDown,
  ChevronUp,
  MessageSquare,
  Zap,
  Shield,
  Search,
  Plus,
  Trash2,
  Clock,
  CalendarDays,
} from 'lucide-react';
import Sidebar from '../components/Sidebar';
import CompetitorBrandConfig from '../components/CompetitorBrandConfig';
import SearchConfig from '../components/SearchConfig';
import { useWebhookConfig } from '../hooks';
import type { WebhookConfig } from '../types';
import { getStorage, setStorage } from '../utils/storage';

const channelLabelMap: Record<WebhookConfig['channels'][number], string> = {
  alert: '警报',
  task: '任务',
  insight: '洞察',
  system: '系统',
};

const channelIconMap: Record<WebhookConfig['channels'][number], typeof AlertTriangle> = {
  alert: Shield,
  task: MessageSquare,
  insight: Zap,
  system: Settings,
};

const severityLabelMap: Record<WebhookConfig['severityFilter'][number], string> = {
  critical: '严重',
  warning: '警告',
  info: '信息',
};

const NOTIFICATION_SETTINGS_KEY = 'momcozy_notification_settings_v1';
const NOTIFICATION_SETTINGS_VERSION = 1;

function loadNotificationSettings(): { app: boolean; email: boolean; feishu: boolean } {
  return getStorage<{ app: boolean; email: boolean; feishu: boolean }>(NOTIFICATION_SETTINGS_KEY, NOTIFICATION_SETTINGS_VERSION, { app: true, email: true, feishu: false });
}

function saveNotificationSettings(settings: { app: boolean; email: boolean; feishu: boolean }) {
  setStorage(NOTIFICATION_SETTINGS_KEY, NOTIFICATION_SETTINGS_VERSION, settings);
}

const SCHEDULED_PUSH_KEY = 'momcozy_scheduled_push_v1';
const SCHEDULED_PUSH_VERSION = 1;

interface ScheduledPushSettings {
  enabled: boolean;
  daily: { enabled: boolean; time: string };
  weekly: { enabled: boolean; time: string; dayOfWeek: number };
  monthly: { enabled: boolean; time: string; dayOfMonth: number };
}

function loadScheduledPushSettings(): ScheduledPushSettings {
  return getStorage<ScheduledPushSettings>(SCHEDULED_PUSH_KEY, SCHEDULED_PUSH_VERSION, {
    enabled: false,
    daily: { enabled: true, time: '09:00' },
    weekly: { enabled: true, time: '09:00', dayOfWeek: 1 },
    monthly: { enabled: true, time: '09:00', dayOfMonth: 1 },
  });
}

function saveScheduledPushSettings(settings: ScheduledPushSettings) {
  setStorage(SCHEDULED_PUSH_KEY, SCHEDULED_PUSH_VERSION, settings);
}

export default function SettingsPage() {
  const [notifications, setNotifications] = useState(loadNotificationSettings);
  const [scheduledPush, setScheduledPush] = useState(loadScheduledPushSettings);

  useEffect(() => {
    saveNotificationSettings(notifications);
  }, [notifications]);

  useEffect(() => {
    saveScheduledPushSettings(scheduledPush);
  }, [scheduledPush]);

  const {
    configs,
    updateConfig,
    toggleEnabled,
    toggleChannel,
    toggleSeverity,
    testConnection,
    addConfig,
    removeConfig,
  } = useWebhookConfig();

  const [testingId, setTestingId] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<{
    id: string;
    success: boolean;
    message: string;
  } | null>(null);

  const [expandedId, setExpandedId] = useState<string | null>(null);

  const handleTest = useCallback(
    async (id: string) => {
      setTestingId(id);
      setTestResult(null);
      const res = await testConnection(id);
      setTestResult({ id, ...res });
      setTestingId(null);
    },
    [testConnection]
  );

  return (
    <div className="flex min-h-screen bg-surface-tertiary">
      <Sidebar />

      <main className="flex-1 min-w-0">
        <header className="sticky top-0 z-40 bg-white/80 backdrop-blur-xl border-b border-border-divider/60">
          <div className="flex items-center justify-between px-4 sm:px-6 py-3.5">
            <div className="flex items-center gap-2">
              <Settings className="w-5 h-5 text-primary" strokeWidth={1.5} />
              <h1 className="text-h1 text-foreground">设置</h1>
            </div>
          </div>
        </header>

        <div className="p-4 sm:p-6 space-y-6 max-w-5xl">
          {/* 通知渠道 */}
          <div className="card p-4 sm:p-6">
            <div className="flex items-center gap-2 mb-5">
              <Bell className="w-5 h-5 text-primary" strokeWidth={1.5} />
              <h2 className="text-h2 text-foreground">通知渠道</h2>
            </div>
            <div className="space-y-4">
              {[
                { key: 'app' as const, label: '应用内通知', icon: Smartphone, desc: '在消息中心接收实时通知' },
                { key: 'email' as const, label: '邮件通知', icon: Mail, desc: '每日简报和紧急警报发送至邮箱' },
                { key: 'feishu' as const, label: '飞书通知', icon: Send, desc: '通过飞书机器人接收关键警报' },
              ].map((item) => {
                const Icon = item.icon;
                return (
                  <div
                    key={item.key}
                    className="flex items-center justify-between p-4 rounded-icon bg-surface-tertiary"
                  >
                    <div className="flex items-center gap-3">
                      <div className="w-9 h-9 rounded-icon bg-white flex items-center justify-center flex-shrink-0">
                        <Icon className="w-4 h-4 text-foreground-secondary" strokeWidth={1.5} />
                      </div>
                      <div>
                        <p className="text-body-sm font-medium text-foreground">{item.label}</p>
                        <p className="text-caption text-foreground-muted">{item.desc}</p>
                      </div>
                    </div>
                    <button
                      onClick={() =>
                        setNotifications((prev) => ({ ...prev, [item.key]: !prev[item.key] }))
                      }
                      className={`relative w-11 h-6 rounded-full transition-all duration-200 flex-shrink-0 ${
                        notifications[item.key] ? 'bg-primary' : 'bg-foreground-muted/30'
                      }`}
                    >
                      <span
                        className={`absolute top-1 w-4 h-4 bg-white rounded-full shadow-sm transition-all duration-200 ${
                          notifications[item.key] ? 'left-6' : 'left-1'
                        }`}
                      />
                    </button>
                  </div>
                );
              })}
            </div>
          </div>

          {/* 钉钉 / 飞书 Webhook 配置 */}
          <div className="card p-4 sm:p-6">
            <div className="flex items-center gap-2 mb-5">
              <Webhook className="w-5 h-5 text-primary" strokeWidth={1.5} />
              <div className="flex-1">
                <h2 className="text-h2 text-foreground">机器人 Webhook 配置</h2>
                <p className="text-caption text-foreground-muted mt-0.5">
                  配置钉钉/飞书机器人 Webhook，支持按事件类型和严重等级自动推送
                </p>
              </div>
            </div>

            <div className="space-y-4">
              {configs.map((config) => {
                const isExpanded = expandedId === config.id;
                const Icon = config.provider === 'dingtalk' ? Send : Webhook;
                return (
                  <div
                    key={config.id}
                    className={`rounded-card border transition-all ${
                      config.enabled ? 'bg-white border-border-divider' : 'bg-surface-tertiary border-transparent'
                    }`}
                  >
                    {/* Header row */}
                    <div className="flex items-center justify-between p-4 sm:p-5">
                      <div className="flex items-center gap-3">
                        <div
                          className={`w-10 h-10 rounded-icon flex items-center justify-center flex-shrink-0 ${
                            config.provider === 'dingtalk'
                              ? 'bg-info/10 text-info'
                              : 'bg-success/10 text-success'
                          }`}
                        >
                          <Icon className="w-5 h-5" strokeWidth={1.5} />
                        </div>
                        <div className="min-w-0">
                          <p className="text-body-sm font-medium text-foreground">
                            {config.name}
                          </p>
                          <p className="text-tiny text-foreground-muted">
                            {config.provider === 'dingtalk' ? '钉钉自定义机器人' : '飞书自定义机器人'}
                          </p>
                        </div>
                      </div>

                      <div className="flex items-center gap-2">
                        <button
                          onClick={() => setExpandedId(isExpanded ? null : config.id)}
                          className="w-8 h-8 rounded-icon flex items-center justify-center text-foreground-muted hover:bg-surface-tertiary transition-all"
                          aria-label={isExpanded ? '收起' : '展开'}
                        >
                          {isExpanded ? (
                            <ChevronUp className="w-4 h-4" strokeWidth={1.5} />
                          ) : (
                            <ChevronDown className="w-4 h-4" strokeWidth={1.5} />
                          )}
                        </button>
                        <button
                          onClick={() => toggleEnabled(config.id)}
                          className={`relative w-11 h-6 rounded-full transition-all duration-200 flex-shrink-0 ${
                            config.enabled ? 'bg-primary' : 'bg-foreground-muted/30'
                          }`}
                        >
                          <span
                            className={`absolute top-1 w-4 h-4 bg-white rounded-full shadow-sm transition-all duration-200 ${
                              config.enabled ? 'left-6' : 'left-1'
                            }`}
                          />
                        </button>
                      </div>
                    </div>

                    {/* Expandable config area */}
                    {isExpanded && (
                      <div className="px-4 sm:px-5 pb-5 space-y-4 animate-fade-in">
                        <div className="h-px bg-border-divider" />

                        {/* Name */}
                        <div>
                          <label className="block text-body-sm font-medium text-foreground mb-2">
                            配置名称
                          </label>
                          <input
                            type="text"
                            value={config.name}
                            onChange={(e) =>
                              updateConfig(config.id, { name: e.target.value })
                            }
                            placeholder="输入机器人名称"
                            className="input-field w-full text-body-sm"
                          />
                        </div>

                        {/* Webhook URL */}
                        <div>
                          <label className="block text-body-sm font-medium text-foreground mb-2">
                            Webhook URL
                          </label>
                          <input
                            type="text"
                            value={config.url}
                            onChange={(e) =>
                              updateConfig(config.id, { url: e.target.value })
                            }
                            placeholder={
                              config.provider === 'dingtalk'
                                ? 'https://oapi.dingtalk.com/robot/send?access_token=...'
                                : 'https://open.feishu.cn/open-apis/bot/v2/hook/...'
                            }
                            className="input-field w-full text-body-sm"
                          />
                          <p className="text-tiny text-foreground-muted mt-1.5">
                            {config.provider === 'dingtalk'
                              ? '从钉钉群设置 → 智能群助手 → 机器人管理 → 获取 Webhook URL'
                              : '从飞书群设置 → 群机器人 → 添加自定义机器人 → 获取 Webhook URL'}
                          </p>
                        </div>

                        {/* Secret / Token */}
                        <div>
                          <label className="block text-body-sm font-medium text-foreground mb-2">
                            {config.provider === 'dingtalk' ? '加签 Secret' : '验证 Token'}
                          </label>
                          <input
                            type="password"
                            value={config.secret}
                            onChange={(e) =>
                              updateConfig(config.id, { secret: e.target.value })
                            }
                            placeholder={
                              config.provider === 'dingtalk'
                                ? 'SECxxxxxxxx...'
                                : '可选，用于安全验证'
                            }
                            className="input-field w-full text-body-sm"
                          />
                          <p className="text-tiny text-foreground-muted mt-1.5">
                            {config.provider === 'dingtalk'
                              ? '钉钉机器人加签模式下需要填写，用于计算签名'
                              : '如飞书机器人设置了安全验证，请填写对应的 Token'}
                          </p>
                        </div>

                        {/* Channel filter */}
                        <div>
                          <label className="block text-body-sm font-medium text-foreground mb-2">
                            推送事件类型
                          </label>
                          <div className="flex flex-wrap gap-2">
                            {(
                              Object.keys(channelLabelMap) as WebhookConfig['channels'][number][]
                            ).map((ch) => {
                              const ChIcon = channelIconMap[ch];
                              const active = config.channels.includes(ch);
                              return (
                                <button
                                  key={ch}
                                  onClick={() => toggleChannel(config.id, ch)}
                                  className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-button text-tiny font-medium transition-all ${
                                    active
                                      ? 'bg-primary text-white'
                                      : 'bg-surface-tertiary text-foreground-muted hover:text-foreground'
                                  }`}
                                >
                                  <ChIcon className="w-3.5 h-3.5" strokeWidth={1.5} />
                                  {channelLabelMap[ch]}
                                </button>
                              );
                            })}
                          </div>
                        </div>

                        {/* Severity filter */}
                        <div>
                          <label className="block text-body-sm font-medium text-foreground mb-2">
                            推送严重等级
                          </label>
                          <div className="flex flex-wrap gap-2">
                            {(
                              Object.keys(
                                severityLabelMap
                              ) as WebhookConfig['severityFilter'][number][]
                            ).map((sev) => {
                              const active = config.severityFilter.includes(sev);
                              return (
                                <button
                                  key={sev}
                                  onClick={() => toggleSeverity(config.id, sev)}
                                  className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-button text-tiny font-medium transition-all ${
                                    active
                                      ? sev === 'critical'
                                        ? 'bg-status-errorBg text-status-error border border-status-error'
                                        : sev === 'warning'
                                          ? 'bg-status-warningBg text-status-warning border border-status-warning'
                                          : 'bg-status-infoBg text-status-info border border-status-info'
                                      : 'bg-surface-tertiary text-foreground-muted hover:text-foreground'
                                  }`}
                                >
                                  {severityLabelMap[sev]}
                                </button>
                              );
                            })}
                          </div>
                        </div>

                        {/* Actions */}
                        <div className="flex items-center justify-between pt-1">
                          <div className="flex items-center gap-3">
                            <button
                              onClick={() => handleTest(config.id)}
                              disabled={testingId === config.id}
                              className="btn-secondary text-body-sm px-4 py-2"
                            >
                              {testingId === config.id ? (
                                <>
                                  <Loader2 className="w-4 h-4 animate-spin mr-1.5" strokeWidth={1.5} />
                                  测试中...
                                </>
                              ) : (
                                <>
                                  <Send className="w-4 h-4 mr-1.5" strokeWidth={1.5} />
                                  测试发送
                                </>
                              )}
                            </button>

                            {testResult && testResult.id === config.id && (
                              <div
                                className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-button text-tiny font-medium ${
                                  testResult.success
                                    ? 'bg-status-successBg text-status-success'
                                    : 'bg-status-errorBg text-status-error'
                                }`}
                              >
                                {testResult.success ? (
                                  <Check className="w-3.5 h-3.5" strokeWidth={1.5} />
                                ) : (
                                  <AlertCircle className="w-3.5 h-3.5" strokeWidth={1.5} />
                                )}
                                {testResult.message}
                                <button
                                  onClick={() => setTestResult(null)}
                                  className="ml-1"
                                >
                                  <X className="w-3 h-3" strokeWidth={1.5} />
                                </button>
                              </div>
                            )}
                          </div>
                          <button
                            onClick={() => {
                              if (confirm('确定删除此 Webhook 配置？')) {
                                removeConfig(config.id);
                                if (expandedId === config.id) setExpandedId(null);
                                if (testResult?.id === config.id) setTestResult(null);
                              }
                            }}
                            className="inline-flex items-center gap-1 text-body-sm text-status-error hover:bg-status-errorBg px-3 py-2 rounded-button transition-all"
                          >
                            <Trash2 className="w-4 h-4" strokeWidth={1.5} />
                            删除
                          </button>
                        </div>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>

            <div className="mt-4 p-3 rounded-icon bg-status-warningBg/50 flex items-start gap-2">
              <AlertTriangle className="w-4 h-4 text-status-warning flex-shrink-0 mt-0.5" strokeWidth={1.5} />
              <p className="text-tiny text-foreground-secondary">
                Webhook URL 和 Secret 仅保存在当前页面内存中，不会上传到服务器或持久化到本地存储。请确保使用 HTTPS 链接，刷新页面后需重新输入 Secret。
              </p>
            </div>

            {/* Add webhook buttons */}
            <div className="mt-4 flex flex-wrap gap-3">
              <button
                onClick={() => addConfig('dingtalk')}
                className="inline-flex items-center gap-1.5 px-4 py-2 rounded-button text-body-sm font-medium border border-border-divider hover:bg-surface-tertiary transition-all"
              >
                <Plus className="w-4 h-4 text-info" strokeWidth={1.5} />
                添加钉钉机器人
              </button>
              <button
                onClick={() => addConfig('feishu')}
                className="inline-flex items-center gap-1.5 px-4 py-2 rounded-button text-body-sm font-medium border border-border-divider hover:bg-surface-tertiary transition-all"
              >
                <Plus className="w-4 h-4 text-success" strokeWidth={1.5} />
                添加飞书机器人
              </button>
            </div>
          </div>

          {/* 定时推送配置 */}
          <div className="card p-4 sm:p-6">
            <div className="flex items-center gap-2 mb-5">
              <Clock className="w-5 h-5 text-primary" strokeWidth={1.5} />
              <div className="flex-1">
                <h2 className="text-h2 text-foreground">定时推送配置</h2>
                <p className="text-caption text-foreground-muted mt-0.5">
                  日报/周报/月报生成后自动推送摘要到已启用的 Webhook
                </p>
              </div>
              <button
                onClick={() => setScheduledPush((prev) => ({ ...prev, enabled: !prev.enabled }))}
                className={`relative w-11 h-6 rounded-full transition-all duration-200 flex-shrink-0 ${
                  scheduledPush.enabled ? 'bg-primary' : 'bg-foreground-muted/30'
                }`}
              >
                <span
                  className={`absolute top-1 w-4 h-4 bg-white rounded-full shadow-sm transition-all duration-200 ${
                    scheduledPush.enabled ? 'left-6' : 'left-1'
                  }`}
                />
              </button>
            </div>

            <div className={`space-y-4 ${!scheduledPush.enabled ? 'opacity-50 pointer-events-none' : ''}`}>
              {[
                { key: 'daily' as const, label: '日报', defaultTime: '09:00' },
                { key: 'weekly' as const, label: '周报', defaultTime: '09:00' },
                { key: 'monthly' as const, label: '月报', defaultTime: '09:00' },
              ].map((item) => {
                const setting = scheduledPush[item.key];
                return (
                  <div
                    key={item.key}
                    className="flex items-center justify-between p-4 rounded-icon bg-surface-tertiary"
                  >
                    <div className="flex items-center gap-3">
                      <div className="w-9 h-9 rounded-icon bg-white flex items-center justify-center flex-shrink-0">
                        <CalendarDays className="w-4 h-4 text-foreground-secondary" strokeWidth={1.5} />
                      </div>
                      <div>
                        <p className="text-body-sm font-medium text-foreground">{item.label}推送</p>
                        <p className="text-caption text-foreground-muted">
                          {item.label}生成后自动推送摘要
                        </p>
                      </div>
                    </div>
                    <div className="flex items-center gap-3">
                      <input
                        type="time"
                        value={setting.time}
                        onChange={(e) =>
                          setScheduledPush((prev) => ({
                            ...prev,
                            [item.key]: { ...prev[item.key], time: e.target.value },
                          }))
                        }
                        className="input-field text-body-sm py-1.5 px-2"
                      />
                      <button
                        onClick={() =>
                          setScheduledPush((prev) => ({
                            ...prev,
                            [item.key]: { ...prev[item.key], enabled: !prev[item.key].enabled },
                          }))
                        }
                        className={`relative w-11 h-6 rounded-full transition-all duration-200 flex-shrink-0 ${
                          setting.enabled ? 'bg-primary' : 'bg-foreground-muted/30'
                        }`}
                      >
                        <span
                          className={`absolute top-1 w-4 h-4 bg-white rounded-full shadow-sm transition-all duration-200 ${
                            setting.enabled ? 'left-6' : 'left-1'
                          }`}
                        />
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* 搜索监测配置 */}
          <div className="space-y-4">
            <div className="flex items-center gap-2">
              <Search className="w-5 h-5 text-primary" strokeWidth={1.5} />
              <h2 className="text-h2 text-foreground">搜索监测配置</h2>
            </div>
            <SearchConfig />
          </div>

          {/* 竞品品牌配置 */}
          <CompetitorBrandConfig />
        </div>
      </main>
    </div>
  );
}
