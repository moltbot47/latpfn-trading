import type { Metadata, Viewport } from "next";
import { IBM_Plex_Sans, JetBrains_Mono, Source_Code_Pro } from "next/font/google";
import { Providers } from "./providers";
import "./globals.css";

// Force dynamic rendering — Privy provider cannot run during static generation
export const dynamic = "force-dynamic";

const ibmPlex = IBM_Plex_Sans({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-ibm-plex",
  display: "swap",
});

const jetbrainsMono = JetBrains_Mono({
  subsets: ["latin"],
  weight: ["400", "500", "700"],
  variable: "--font-jetbrains",
  display: "swap",
});

const sourceCodePro = Source_Code_Pro({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  variable: "--font-source-code",
  display: "swap",
});

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
};

export const metadata: Metadata = {
  title: "LaT-PFN Signals | AI Trading Forecasts on Base",
  description:
    "Access AI-powered trading signals from the LaT-PFN zero-shot forecasting model. Subscription via smart contract on Base L2.",
  openGraph: {
    title: "LaT-PFN Signals | AI Trading Forecasts",
    description: "Zero-shot AI forecasting for micro futures. Every signal verified on-chain via Base L2.",
    type: "website",
    siteName: "LaT-PFN Signals",
  },
  twitter: {
    card: "summary_large_image",
    title: "LaT-PFN Signals | AI Trading Forecasts",
    description: "Zero-shot AI forecasting for micro futures. Verified on-chain via Base L2.",
  },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className={`${ibmPlex.variable} ${jetbrainsMono.variable} ${sourceCodePro.variable}`}>
      <body className="min-h-screen antialiased">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
