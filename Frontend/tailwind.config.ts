import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["var(--font-body)", "system-ui", "sans-serif"],
        mono: ["var(--font-mono)", "Menlo", "monospace"],
      },
      colors: {
        surface: {
          DEFAULT: "#0f1117",
          1: "#161b27",
          2: "#1e2535",
          3: "#252d3d",
          4: "#2d3748",
        },
        accent: {
          DEFAULT: "#6ee7b7",
          dim: "#34d399",
          bright: "#a7f3d0",
          muted: "rgba(110,231,183,0.15)",
        },
        text: {
          primary: "#e8eaf0",
          secondary: "#8b93a8",
          muted: "#4a5568",
        },
      },
      animation: {
        "fade-up": "fadeUp 0.3s ease forwards",
        "slide-in": "slideIn 0.25s ease forwards",
        "pulse-dot": "pulseDot 1.4s ease-in-out infinite",
        "spin-slow": "spin 2s linear infinite",
      },
      keyframes: {
        fadeUp: {
          "0%": { opacity: "0", transform: "translateY(10px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        slideIn: {
          "0%": { opacity: "0", transform: "translateX(-6px)" },
          "100%": { opacity: "1", transform: "translateX(0)" },
        },
        pulseDot: {
          "0%, 80%, 100%": { transform: "scale(0.6)", opacity: "0.4" },
          "40%": { transform: "scale(1)", opacity: "1" },
        },
      },
      borderRadius: {
        "2xl": "1rem",
        "3xl": "1.5rem",
      },
      maxWidth: {
        "chat": "42rem",
      },
      backdropBlur: {
        xs: "2px",
      },
    },
  },
  plugins: [],
};

export default config;