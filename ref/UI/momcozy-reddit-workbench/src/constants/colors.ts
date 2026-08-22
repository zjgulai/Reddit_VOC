/** Design Tokens — 统一颜色常量（扁平重新导出）
 *  源定义在 ../design-tokens.ts，本文件仅提供便捷命名导出。
 *  所有组件中的硬编码颜色应从此文件导入。
 */

import { tokens } from '../design-tokens';

export const BRAND_COLORS = tokens.colors.brand;
export const SENTIMENT_COLORS = tokens.colors.sentiment;
export const CHART_PALETTE = [...tokens.colors.chart];
export const EXPORT_COLORS = tokens.colors.export;
export const NEUTRAL_COLORS = tokens.colors.neutral;
export const EXPORT_BRAND_HEX = tokens.colors.export.brandHex;
