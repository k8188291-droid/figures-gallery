/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      fontFamily: {
        sans: ['Inter', 'Noto Sans TC', 'ui-sans-serif', 'system-ui'],
      },
      colors: {
        ink: '#11120f',
        paper: '#f2f0e8',
        acid: '#d9ff43',
      },
    },
  },
  plugins: [],
}
