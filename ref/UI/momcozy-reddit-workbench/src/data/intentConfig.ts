import {
  ShoppingCart,
  Heart,
  Bug,
  GitCompare,
  HelpCircle,
  MessageSquare,
} from 'lucide-react';
import type { PostIntent, IntentConfigItem } from '../types';

/**
 * 6种大疆标准意图配置
 * 统一使用 Pascal Case + 空格 作为标识，确保全站一致
 */
export const intentConfig: Record<PostIntent, IntentConfigItem> = {
  'Purchase Intent': {
    label: '购买意向',
    color: 'text-status-success',
    bg: 'bg-status-successBg',
    actionLabel: '优先回复',
    icon: ShoppingCart,
  },
  UGC: {
    label: '口碑分享',
    color: 'text-primary',
    bg: 'bg-primary-light',
    actionLabel: '收集素材',
    icon: Heart,
  },
  'Bug Report': {
    label: 'Bug报告',
    color: 'text-status-error',
    bg: 'bg-status-errorBg',
    actionLabel: '升级处理',
    icon: Bug,
  },
  Comparison: {
    label: '竞品对比',
    color: 'text-status-warning',
    bg: 'bg-status-warningBg',
    actionLabel: '介入回复',
    icon: GitCompare,
  },
  Question: {
    label: '求助提问',
    color: 'text-status-info',
    bg: 'bg-status-infoBg',
    actionLabel: '提供帮助',
    icon: HelpCircle,
  },
  General: {
    label: '一般讨论',
    color: 'text-foreground-muted',
    bg: 'bg-surface-tertiary',
    actionLabel: '观察',
    icon: MessageSquare,
  },
};

/** 获取意图的显示标签 */
export function getIntentLabel(intent: PostIntent): string {
  return intentConfig[intent].label;
}

/** 获取意图的配色 */
export function getIntentColor(intent: PostIntent): string {
  return intentConfig[intent].color;
}

/** 获取意图的背景色 */
export function getIntentBg(intent: PostIntent): string {
  return intentConfig[intent].bg;
}

/** 获取意图的操作标签 */
export function getIntentActionLabel(intent: PostIntent): string {
  return intentConfig[intent].actionLabel;
}

/** 所有6种意图的数组 */
export const allIntents: PostIntent[] = [
  'Purchase Intent',
  'UGC',
  'Bug Report',
  'Comparison',
  'Question',
  'General',
];
