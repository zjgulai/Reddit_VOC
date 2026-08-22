/**
 * Runtime TypeScript facade for the authoritative design token source.
 * Edit `design-tokens.json`; Tailwind, charts and exports consume the same file.
 */
import rawTokens from './design-tokens.json';

export const tokens = rawTokens;

/** Tokens 推导类型 */
export type Tokens = typeof tokens;

/** 颜色 Token 类型（浅层提取） */
export type ColorToken = string;

/** 阴影 Token 类型 */
export type ShadowToken = keyof Tokens['shadows'];

/** 字号 Token 类型 */
export type FontSizeToken = keyof Tokens['typography']['sizes'];

/** 圆角 Token 类型 */
export type RadiusToken = keyof Tokens['radius'];
