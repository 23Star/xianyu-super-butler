/** @type {import('tailwindcss').Config} */

// 这里刻意**覆盖** Tailwind 的默认取值，而不是去改组件里的类名：
// 全站有 395 处 rounded-md、130+ 处 bg-gray-*，逐处替换既容易漏又难回退。
// 把 md 圆角调大、把 gray 色阶换成暖调，所有组件一次到位。
export default {
  darkMode: 'class',
  content: [
    "./index.html",
    "./*.{js,ts,jsx,tsx}",
    "./components/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        brand: {
          DEFAULT: '#FFE100',
          50: '#FFFDF0',
          100: '#FFF8D1',
          200: '#FFEFA3',
          300: '#FFE566',
          400: '#FFE100',
          500: '#FFD700',
          600: '#F5C800',
          700: '#D9A800',
          800: '#A67F00',
          900: '#6B5200',
          ink: '#2A2416',
        },
        // 中性色阶：只带极轻微的暖调，避免和黄色强调元素冲突。
        // 不做成黄色系 —— 全站 130+ 处 bg-gray-* 一旦变黄会让整页发闷。
        gray: {
          50: 'rgb(var(--gray-50) / <alpha-value>)',
          100: 'rgb(var(--gray-100) / <alpha-value>)',
          200: 'rgb(var(--gray-200) / <alpha-value>)',
          300: 'rgb(var(--gray-300) / <alpha-value>)',
          400: 'rgb(var(--gray-400) / <alpha-value>)',
          500: 'rgb(var(--gray-500) / <alpha-value>)',
          600: 'rgb(var(--gray-600) / <alpha-value>)',
          700: 'rgb(var(--gray-700) / <alpha-value>)',
          800: 'rgb(var(--gray-800) / <alpha-value>)',
          900: 'rgb(var(--gray-900) / <alpha-value>)',
        },
      },
      borderRadius: {
        // 覆盖默认值：DEFAULT 4px→8px、md 6px→10px、lg 8px→16px、xl 12px→20px
        DEFAULT: '8px',
        sm: '6px',
        md: '10px',
        lg: '16px',
        xl: '20px',
        '2xl': '24px',
        '3xl': '32px',
      },
      boxShadow: {
        brand: '0 6px 18px rgba(255, 214, 0, 0.35)',
        'brand-lg': '0 10px 28px rgba(255, 214, 0, 0.45)',
        soft: '0 1px 2px rgba(122, 96, 20, 0.06)',
        card: '0 6px 20px rgba(122, 96, 20, 0.10)',
      },
      fontFamily: {
        sans: [
          '-apple-system',
          'BlinkMacSystemFont',
          '"PingFang SC"',
          '"Hiragino Sans GB"',
          '"Microsoft YaHei"',
          '"Helvetica Neue"',
          'Helvetica',
          'Arial',
          'sans-serif',
        ],
      },
    },
  },
  plugins: [],
}
