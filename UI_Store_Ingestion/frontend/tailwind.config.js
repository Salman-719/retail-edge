/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        navy: {
          700: '#1B3A5C',
          500: '#2E75B6',
        },
      }
    },
  },
  plugins: [],
}
