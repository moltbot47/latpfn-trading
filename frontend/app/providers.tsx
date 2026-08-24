"use client";

import { PrivyProvider } from "@privy-io/react-auth";
import { WagmiProvider, createConfig, http } from "wagmi";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { base, baseSepolia } from "viem/chains";

const queryClient = new QueryClient();

// CDP Paymaster RPC — sponsors gas fees for subscribers
// Set NEXT_PUBLIC_CDP_API_KEY in Vercel env vars to enable gasless transactions
const cdpApiKey = process.env.NEXT_PUBLIC_CDP_API_KEY;
const baseRpc = cdpApiKey
  ? `https://api.developer.coinbase.com/rpc/v1/base/${cdpApiKey}`
  : undefined;

const wagmiConfig = createConfig({
  chains: [base, baseSepolia],
  transports: {
    [base.id]: http(baseRpc),
    [baseSepolia.id]: http(),
  },
  ssr: true,
});

export function Providers({ children }: { children: React.ReactNode }) {
  return (
    <PrivyProvider
      appId={process.env.NEXT_PUBLIC_PRIVY_APP_ID || ""}
      config={{
        appearance: {
          theme: "dark",
          accentColor: "#EB9D2A",
        },
        loginMethods: ["email", "google", "twitter", "apple", "wallet"],
        defaultChain: base,
        supportedChains: [base, baseSepolia],
        embeddedWallets: {
          ethereum: {
            createOnLogin: "users-without-wallets",
          },
        },
      }}
    >
      <WagmiProvider config={wagmiConfig}>
        <QueryClientProvider client={queryClient}>
          {children}
        </QueryClientProvider>
      </WagmiProvider>
    </PrivyProvider>
  );
}
