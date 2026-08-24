const hre = require("hardhat");
const fs = require("fs");

async function main() {
  const [deployer] = await hre.ethers.getSigners();
  console.log("Deploying with account:", deployer.address);

  const balance = await hre.ethers.provider.getBalance(deployer.address);
  console.log("Account balance:", hre.ethers.formatEther(balance), "ETH");

  // Monthly price: 0.005 ETH (~$12-15 on Base)
  const monthlyPrice = hre.ethers.parseEther("0.005");

  console.log("Deploying SignalAccess...");
  console.log("Monthly price:", hre.ethers.formatEther(monthlyPrice), "ETH");

  const SignalAccess = await hre.ethers.getContractFactory("SignalAccess");
  const contract = await SignalAccess.deploy(monthlyPrice);
  await contract.waitForDeployment();

  const address = await contract.getAddress();
  console.log("SignalAccess deployed to:", address);
  console.log("Owner:", deployer.address);
  console.log("Network:", hre.network.name);

  const deploymentInfo = {
    contract: "SignalAccess",
    address: address,
    network: hre.network.name,
    chainId: hre.network.config.chainId,
    deployer: deployer.address,
    monthlyPrice: hre.ethers.formatEther(monthlyPrice),
    deployedAt: new Date().toISOString(),
    txHash: contract.deploymentTransaction()?.hash,
  };

  const deployDir = "./deployments";
  if (!fs.existsSync(deployDir)) fs.mkdirSync(deployDir, { recursive: true });

  fs.writeFileSync(
    `${deployDir}/${hre.network.name}.json`,
    JSON.stringify(deploymentInfo, null, 2)
  );
  console.log(`Deployment info saved to ${deployDir}/${hre.network.name}.json`);

  if (hre.network.name !== "hardhat" && hre.network.name !== "localhost") {
    console.log("Waiting 30s for block confirmations before verification...");
    await new Promise((r) => setTimeout(r, 30000));

    try {
      await hre.run("verify:verify", {
        address: address,
        constructorArguments: [monthlyPrice],
      });
      console.log("Contract verified on Basescan!");
    } catch (e) {
      console.log("Verification failed (can retry manually):", e.message);
    }
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
