/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        // Cyber-themed dark mode colors
        'cyber-dark': '#0a0e27',
        'cyber-darker': '#060913',
        'cyber-blue': '#00d9ff',
        'cyber-purple': '#b026ff',
        'cyber-pink': '#ff006e',
        'cyber-green': '#00ff88',
      },
    },
  },
  plugins: [],
};
