import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#0f172a",
        paper: "#f6f7f9",
        brand: {
          50: "#eefbf7",
          100: "#d5f5ec",
          200: "#aeead9",
          300: "#78d8c1",
          400: "#41bda4",
          500: "#1f9f89",
          600: "#137f70",
          700: "#12655b",
          800: "#12514a",
          900: "#11433e",
        },
      },
      fontFamily: {
        sans: [
          "-apple-system",
          "PingFang SC",
          "Microsoft YaHei",
          "Hiragino Sans GB",
          "Source Han Sans SC",
          "sans-serif",
        ],
      },
      boxShadow: {
        card: "0 1px 2px rgba(15,23,42,.04), 0 8px 24px -12px rgba(15,23,42,.18)",
      },
      keyframes: {
        blink: { "0%,100%": { opacity: "1" }, "50%": { opacity: "0" } },
        rise: { from: { opacity: "0", transform: "translateY(6px)" }, to: { opacity: "1", transform: "none" } },
      },
      animation: {
        blink: "blink 1s steps(2,start) infinite",
        rise: "rise .28s ease-out both",
      },
    },
  },
  plugins: [],
};

export default config;
