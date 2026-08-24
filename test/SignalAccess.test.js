const { expect } = require("chai");
const { ethers } = require("hardhat");

describe("SignalAccess", function () {
  let contract, owner, user1, user2;
  const MONTHLY_PRICE = ethers.parseEther("0.005");

  beforeEach(async function () {
    [owner, user1, user2] = await ethers.getSigners();
    const SignalAccess = await ethers.getContractFactory("SignalAccess");
    contract = await SignalAccess.deploy(MONTHLY_PRICE);
    await contract.waitForDeployment();
  });

  describe("Deployment", function () {
    it("sets owner and price", async function () {
      expect(await contract.owner()).to.equal(owner.address);
      expect(await contract.monthlyPrice()).to.equal(MONTHLY_PRICE);
    });
  });

  describe("Subscription", function () {
    it("allows subscribing for 1 month", async function () {
      await contract.connect(user1).subscribe(1, { value: MONTHLY_PRICE });
      expect(await contract.isSubscribed(user1.address)).to.be.true;
      const [expiresAt, tier, active] = await contract.getSubscription(user1.address);
      expect(tier).to.equal(1n);
      expect(active).to.be.true;
    });

    it("allows subscribing for multiple months", async function () {
      await contract.connect(user1).subscribe(3, { value: MONTHLY_PRICE * 3n });
      expect(await contract.isSubscribed(user1.address)).to.be.true;
    });

    it("rejects insufficient payment", async function () {
      await expect(
        contract.connect(user1).subscribe(1, { value: MONTHLY_PRICE / 2n })
      ).to.be.revertedWith("Insufficient payment");
    });

    it("extends existing subscription", async function () {
      await contract.connect(user1).subscribe(1, { value: MONTHLY_PRICE });
      const [expires1] = await contract.getSubscription(user1.address);
      await contract.connect(user1).subscribe(1, { value: MONTHLY_PRICE });
      const [expires2] = await contract.getSubscription(user1.address);
      expect(expires2).to.be.greaterThan(expires1);
    });

    it("allows premium subscription at 2x price", async function () {
      await contract.connect(user1).subscribePremium(1, { value: MONTHLY_PRICE * 2n });
      const [, tier] = await contract.getSubscription(user1.address);
      expect(tier).to.equal(2n);
    });

    it("tracks subscriber count", async function () {
      await contract.connect(user1).subscribe(1, { value: MONTHLY_PRICE });
      await contract.connect(user2).subscribe(1, { value: MONTHLY_PRICE });
      expect(await contract.subscriberCount()).to.equal(2n);
    });

    it("tracks total revenue", async function () {
      await contract.connect(user1).subscribe(2, { value: MONTHLY_PRICE * 2n });
      expect(await contract.totalRevenue()).to.equal(MONTHLY_PRICE * 2n);
    });
  });

  describe("Forecasts", function () {
    it("owner can post forecast hash", async function () {
      const hash = ethers.keccak256(ethers.toUtf8Bytes("MNQ-long-0.72-1234567890"));
      await contract.postForecast("MNQ", hash);
      expect(await contract.forecastCount()).to.equal(1n);
    });

    it("non-owner cannot post forecast", async function () {
      const hash = ethers.keccak256(ethers.toUtf8Bytes("test"));
      await expect(contract.connect(user1).postForecast("MNQ", hash)).to.be.revertedWith("Not owner");
    });

    it("returns recent forecasts", async function () {
      const h1 = ethers.keccak256(ethers.toUtf8Bytes("forecast1"));
      const h2 = ethers.keccak256(ethers.toUtf8Bytes("forecast2"));
      await contract.postForecast("MNQ", h1);
      await contract.postForecast("MYM", h2);
      const recent = await contract.getRecentForecasts(2);
      expect(recent.length).to.equal(2);
      expect(recent[1].instrument).to.equal("MYM");
    });
  });

  describe("Admin", function () {
    it("owner can update price", async function () {
      const newPrice = ethers.parseEther("0.01");
      await contract.setPrice(newPrice);
      expect(await contract.monthlyPrice()).to.equal(newPrice);
    });

    it("owner can withdraw", async function () {
      await contract.connect(user1).subscribe(1, { value: MONTHLY_PRICE });
      const balBefore = await ethers.provider.getBalance(owner.address);
      await contract.withdraw();
      const balAfter = await ethers.provider.getBalance(owner.address);
      expect(balAfter).to.be.greaterThan(balBefore);
    });

    it("owner can transfer ownership", async function () {
      await contract.transferOwnership(user1.address);
      expect(await contract.owner()).to.equal(user1.address);
    });
  });

  describe("Receive ETH", function () {
    it("direct ETH transfer creates subscription", async function () {
      await user1.sendTransaction({ to: await contract.getAddress(), value: MONTHLY_PRICE });
      expect(await contract.isSubscribed(user1.address)).to.be.true;
    });
  });
});
