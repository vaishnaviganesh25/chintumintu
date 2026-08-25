/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],

  // Theming is done with CSS custom properties in `src/index.css`, not with
  // Tailwind's `dark:` variant. Two reasons: the palette has three states
  // (light / dark / system) rather than two, and routing every colour through a
  // token means a component cannot accidentally hardcode one that only works in
  // the theme it was written in. Nothing here needs a colour extension.
  theme: { extend: {} },
  plugins: [],
};
