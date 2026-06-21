/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["var(--font-sans)", "ui-sans-serif", "system-ui", "sans-serif"],
        display: ["var(--font-display)", "var(--font-sans)", "ui-sans-serif", "sans-serif"],
      },
      colors: {
        // One confident corporate blue carries every primary action across the app.
        brand: {
          DEFAULT: "#1F5BD6",
          50: "#EFF4FD",
          100: "#DCE7FB",
          600: "#1F5BD6",
          700: "#1A4CB8",
          900: "#143E96",
        },
        // The deep navy-slate used for the "New meeting" hero panel.
        ink: {
          DEFAULT: "#0E1626",
          800: "#16203A",
          700: "#1E2A45",
        },
      },
      boxShadow: {
        card: "0 1px 2px 0 rgb(15 23 42 / 0.04), 0 1px 3px 0 rgb(15 23 42 / 0.06)",
        "card-hover": "0 18px 40px -14px rgb(15 23 42 / 0.18)",
        ink: "0 24px 50px -18px rgb(14 22 38 / 0.55)",
        brand: "0 12px 26px -10px rgb(20 62 150 / 0.45)",
      },
    },
  },
  plugins: [],
};
