/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        ink: "rgb(var(--ink-rgb) / <alpha-value>)",
        surface: "rgb(var(--surface-rgb) / <alpha-value>)",
        raise: "rgb(var(--raise-rgb) / <alpha-value>)",
        line: "rgb(var(--line-rgb) / <alpha-value>)",
        body: "rgb(var(--text-rgb) / <alpha-value>)",
        muted: "rgb(var(--muted-rgb) / <alpha-value>)",
        brand: "rgb(var(--brand-rgb) / <alpha-value>)",
        indigo: "rgb(var(--indigo-rgb) / <alpha-value>)",
        up: "rgb(var(--up-rgb) / <alpha-value>)",
        down: "rgb(var(--down-rgb) / <alpha-value>)",
      },
      // 5단위가 아닌 투명도(/8, /12, /14 …)도 쓰므로 0~100 전 구간을 연다
      opacity: Object.fromEntries(
        Array.from({ length: 101 }, (_, i) => [i, (i / 100).toString()]),
      ),
      fontFamily: {
        sans: ["IBM Plex Sans KR", "system-ui", "sans-serif"],
        mono: ["IBM Plex Mono", "ui-monospace", "monospace"],
      },
      borderRadius: { xs: "5px", sm: "7px", DEFAULT: "9px", md: "11px", lg: "14px", xl: "18px" },
      fontSize: {
        eyebrow: ["10.5px", { lineHeight: "1", letterSpacing: "0.16em" }],
      },
    },
  },
  plugins: [],
};
