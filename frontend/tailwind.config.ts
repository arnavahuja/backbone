import type { Config } from 'tailwindcss'
import { tokens } from './src/theme/tokens'

// Tailwind's default palette includes purple/violet/indigo/fuchsia; we replace the whole
// color palette with design tokens so those classes do not exist at all.
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    colors: {
      transparent: 'transparent',
      current: 'currentColor',
      canvas: tokens.bg.base,
      surface: tokens.bg.surface,
      elevated: tokens.bg.elevated,
      border: tokens.border,
      primary: tokens.text.primary,
      secondary: tokens.text.secondary,
      muted: tokens.text.muted,
      accent: tokens.accent,
      'accent-strong': tokens.accentStrong,
      positive: tokens.positive,
      negative: tokens.negative,
      warning: tokens.warning,
      info: tokens.info,
    },
    extend: {
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'SFMono-Regular', 'monospace'],
      },
      fontSize: { '2xs': ['0.6875rem', '1rem'] },
    },
  },
  plugins: [],
} satisfies Config
