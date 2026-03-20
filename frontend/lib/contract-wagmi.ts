// Contract ABI for wagmi hooks
export const SIGNAL_ACCESS_ADDRESS = (process.env.NEXT_PUBLIC_CONTRACT_ADDRESS_BASE || "0x901c169aa21a9eC593c52bc6F0eaA814eDf41091") as `0x${string}`;

export const SIGNAL_ACCESS_ABI = [
  {
    inputs: [{ name: "months", type: "uint256" }],
    name: "subscribe",
    outputs: [],
    stateMutability: "payable",
    type: "function",
  },
  {
    inputs: [{ name: "months", type: "uint256" }],
    name: "subscribePremium",
    outputs: [],
    stateMutability: "payable",
    type: "function",
  },
  {
    inputs: [{ name: "user", type: "address" }],
    name: "isSubscribed",
    outputs: [{ name: "", type: "bool" }],
    stateMutability: "view",
    type: "function",
  },
  {
    inputs: [{ name: "user", type: "address" }],
    name: "getSubscription",
    outputs: [
      { name: "expiresAt", type: "uint256" },
      { name: "tier", type: "uint256" },
      { name: "active", type: "bool" },
    ],
    stateMutability: "view",
    type: "function",
  },
  {
    inputs: [],
    name: "monthlyPrice",
    outputs: [{ name: "", type: "uint256" }],
    stateMutability: "view",
    type: "function",
  },
  {
    inputs: [],
    name: "subscriberCount",
    outputs: [{ name: "", type: "uint256" }],
    stateMutability: "view",
    type: "function",
  },
  {
    inputs: [],
    name: "forecastCount",
    outputs: [{ name: "", type: "uint256" }],
    stateMutability: "view",
    type: "function",
  },
  {
    inputs: [{ name: "count", type: "uint256" }],
    name: "getRecentForecasts",
    outputs: [
      {
        components: [
          { name: "hash", type: "bytes32" },
          { name: "timestamp", type: "uint256" },
          { name: "instrument", type: "string" },
        ],
        name: "",
        type: "tuple[]",
      },
    ],
    stateMutability: "view",
    type: "function",
  },
] as const;
