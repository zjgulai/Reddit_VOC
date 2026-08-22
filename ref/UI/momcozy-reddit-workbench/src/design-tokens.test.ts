import { describe, expect, it } from 'vitest';

import { tokens } from './design-tokens';

function relativeLuminance(hex: string): number {
  const channels = hex
    .slice(1)
    .match(/../g)
    ?.map((value) => Number.parseInt(value, 16) / 255)
    .map((value) =>
      value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4,
    );
  if (!channels || channels.length !== 3) {
    throw new Error(`invalid_hex_color:${hex}`);
  }
  return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2];
}

function contrastRatio(foreground: string, background: string): number {
  const foregroundLuminance = relativeLuminance(foreground);
  const backgroundLuminance = relativeLuminance(background);
  return (
    (Math.max(foregroundLuminance, backgroundLuminance) + 0.05) /
    (Math.min(foregroundLuminance, backgroundLuminance) + 0.05)
  );
}

describe('authoritative design token contract', () => {
  it('keeps business chart colors bound to semantic roles', () => {
    expect(tokens.colors.chart[0]).toBe(tokens.colors.brand.primary);
    expect(tokens.colors.chart[1]).toBe(tokens.colors.brand.competitor);
    expect(tokens.colors.chart[2]).toBe(tokens.colors.sentiment.negative);
    expect(tokens.colors.chart[3]).toBe(tokens.colors.sentiment.positive);
  });

  it('uses the approved deep coral for accessible interactions', () => {
    expect(tokens.colors.primary.DEFAULT).toBe(tokens.colors.brand.interaction);
    expect(
      contrastRatio(tokens.colors.primary.DEFAULT, tokens.colors.foreground.inverse),
    ).toBeGreaterThanOrEqual(4.5);
    expect(
      contrastRatio(tokens.colors.primary.hover, tokens.colors.foreground.inverse),
    ).toBeGreaterThanOrEqual(4.5);
  });

  it('does not use the light brand coral as the primary interaction color', () => {
    expect(tokens.colors.brand.primary).not.toBe(tokens.colors.primary.DEFAULT);
    expect(
      contrastRatio(tokens.colors.brand.primary, tokens.colors.foreground.inverse),
    ).toBeLessThan(4.5);
  });
});
