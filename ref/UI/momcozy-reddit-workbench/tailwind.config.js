import tokens from './src/design-tokens.json' with { type: 'json' };

const chartColors = Object.fromEntries(
  tokens.colors.chart.map((color, index) => [String(index), color]),
);

const fontSizes = Object.fromEntries(
  Object.entries(tokens.typography.sizes).map(([name, value]) => [
    name === 'bodySm' ? 'body-sm' : name,
    [
      value.size,
      {
        lineHeight: value.lineHeight,
        fontWeight: String(value.weight),
        letterSpacing: value.letterSpacing,
      },
    ],
  ]),
);

const fontFamily = tokens.typography.fontFamily.split(',').map((name) => {
  const trimmed = name.trim();
  return trimmed.includes(' ') ? `"${trimmed}"` : trimmed;
});

/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        primary: tokens.colors.primary,
        surface: tokens.colors.surface,
        foreground: tokens.colors.foreground,
        border: tokens.colors.border,
        status: tokens.colors.status,
        brand: tokens.colors.brand,
        info: tokens.colors.status.info,
        success: tokens.colors.status.success,
        chart: chartColors,
      },
      fontFamily: {
        sans: fontFamily,
      },
      fontSize: fontSizes,
      borderRadius: tokens.radius,
      boxShadow: {
        card: tokens.shadows.card,
        'card-hover': tokens.shadows.cardHover,
        elevated: tokens.shadows.elevated,
        button: tokens.shadows.button,
        'card-warm': tokens.shadows.card,
      },
      maxWidth: {
        container: tokens.maxWidth.container,
      },
      spacing: {
        '18': '4.5rem',
        '22': '5.5rem',
        '30': '7.5rem',
      },
      transitionTimingFunction: {
        smooth: tokens.animation.easing,
      },
      keyframes: {
        'fade-in': {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' },
        },
        'slide-up': {
          '0%': { opacity: '0', transform: 'translateY(8px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        'slide-in-right': {
          '0%': { opacity: '0', transform: 'translateX(12px)' },
          '100%': { opacity: '1', transform: 'translateX(0)' },
        },
        'pulse-soft': {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '0.7' },
        },
      },
      animation: {
        'fade-in': 'fade-in 0.5s ease-out forwards',
        'slide-up': 'slide-up 0.5s ease-out forwards',
        'slide-in-right': 'slide-in-right 0.4s ease-out forwards',
        'pulse-soft': 'pulse-soft 2s ease-in-out infinite',
      },
    },
  },
  plugins: [],
}
