import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        base: {
          blue: "#0052FF",
          dark: "#0A0B0D",
          card: "#111214",
          border: "#1E2025",
          muted: "#6B7280",
          green: "#22C55E",
          red: "#EF4444",
        },
      },
    },
  },
  plugins: [],
};
export default config;
