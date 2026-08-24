// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/// @title SignalAccess — LaT-PFN Trading Signal Subscription
/// @notice Users pay ETH to subscribe. Owner posts forecast hashes on-chain for transparency.
/// @dev Deployed on Base L2 for cheap transactions.
contract SignalAccess {
    address public owner;
    uint256 public monthlyPrice;
    uint256 public constant MONTH = 30 days;

    struct Subscription {
        uint256 expiresAt;
        uint256 tier; // 0 = none, 1 = basic, 2 = premium
    }

    mapping(address => Subscription) public subscriptions;

    // On-chain forecast hashes for verifiability
    struct ForecastRecord {
        bytes32 hash;       // keccak256(instrument, direction, confidence, timestamp)
        uint256 timestamp;
        string instrument;  // e.g. "MNQ", "MYM"
    }

    ForecastRecord[] public forecasts;
    uint256 public forecastCount;

    // Revenue tracking
    uint256 public totalRevenue;
    uint256 public subscriberCount;

    event Subscribed(address indexed user, uint256 tier, uint256 expiresAt, uint256 amount);
    event SubscriptionRenewed(address indexed user, uint256 newExpiresAt);
    event ForecastPosted(uint256 indexed id, string instrument, bytes32 hash, uint256 timestamp);
    event PriceUpdated(uint256 oldPrice, uint256 newPrice);
    event Withdrawn(address indexed to, uint256 amount);

    modifier onlyOwner() {
        require(msg.sender == owner, "Not owner");
        _;
    }

    modifier onlySubscriber() {
        require(subscriptions[msg.sender].expiresAt > block.timestamp, "No active subscription");
        _;
    }

    constructor(uint256 _monthlyPrice) {
        owner = msg.sender;
        monthlyPrice = _monthlyPrice;
    }

    /// @notice Subscribe or renew for `months` months at tier 1 (basic)
    function subscribe(uint256 months) external payable {
        require(months > 0 && months <= 12, "1-12 months");
        require(msg.value >= monthlyPrice * months, "Insufficient payment");

        Subscription storage sub = subscriptions[msg.sender];

        if (sub.expiresAt == 0) {
            subscriberCount++;
        }

        // Extend from now or from current expiry (whichever is later)
        uint256 startFrom = sub.expiresAt > block.timestamp ? sub.expiresAt : block.timestamp;
        sub.expiresAt = startFrom + (MONTH * months);
        sub.tier = 1;

        totalRevenue += msg.value;

        emit Subscribed(msg.sender, 1, sub.expiresAt, msg.value);
    }

    /// @notice Subscribe to premium tier (2x price)
    function subscribePremium(uint256 months) external payable {
        require(months > 0 && months <= 12, "1-12 months");
        require(msg.value >= monthlyPrice * 2 * months, "Insufficient payment for premium");

        Subscription storage sub = subscriptions[msg.sender];

        if (sub.expiresAt == 0) {
            subscriberCount++;
        }

        uint256 startFrom = sub.expiresAt > block.timestamp ? sub.expiresAt : block.timestamp;
        sub.expiresAt = startFrom + (MONTH * months);
        sub.tier = 2;

        totalRevenue += msg.value;

        emit Subscribed(msg.sender, 2, sub.expiresAt, msg.value);
    }

    /// @notice Check if a wallet has an active subscription
    function isSubscribed(address user) external view returns (bool) {
        return subscriptions[user].expiresAt > block.timestamp;
    }

    /// @notice Get subscription details
    function getSubscription(address user) external view returns (uint256 expiresAt, uint256 tier, bool active) {
        Subscription memory sub = subscriptions[user];
        return (sub.expiresAt, sub.tier, sub.expiresAt > block.timestamp);
    }

    /// @notice Owner posts a forecast hash on-chain for transparency
    function postForecast(string calldata instrument, bytes32 hash) external onlyOwner {
        forecasts.push(ForecastRecord({
            hash: hash,
            timestamp: block.timestamp,
            instrument: instrument
        }));
        forecastCount++;

        emit ForecastPosted(forecastCount - 1, instrument, hash, block.timestamp);
    }

    /// @notice Get recent forecasts (last N)
    function getRecentForecasts(uint256 count) external view returns (ForecastRecord[] memory) {
        uint256 len = forecasts.length;
        if (count > len) count = len;

        ForecastRecord[] memory recent = new ForecastRecord[](count);
        for (uint256 i = 0; i < count; i++) {
            recent[i] = forecasts[len - count + i];
        }
        return recent;
    }

    /// @notice Update monthly price (owner only)
    function setPrice(uint256 newPrice) external onlyOwner {
        emit PriceUpdated(monthlyPrice, newPrice);
        monthlyPrice = newPrice;
    }

    /// @notice Transfer ownership
    function transferOwnership(address newOwner) external onlyOwner {
        require(newOwner != address(0), "Zero address");
        owner = newOwner;
    }

    /// @notice Withdraw contract balance to owner
    function withdraw() external onlyOwner {
        uint256 balance = address(this).balance;
        require(balance > 0, "No balance");
        (bool sent, ) = owner.call{value: balance}("");
        require(sent, "Withdraw failed");
        emit Withdrawn(owner, balance);
    }

    /// @notice Receive ETH directly (counts as 1-month basic subscription)
    receive() external payable {
        require(msg.value >= monthlyPrice, "Below minimum");
        Subscription storage sub = subscriptions[msg.sender];
        if (sub.expiresAt == 0) subscriberCount++;
        uint256 startFrom = sub.expiresAt > block.timestamp ? sub.expiresAt : block.timestamp;
        sub.expiresAt = startFrom + MONTH;
        sub.tier = 1;
        totalRevenue += msg.value;
        emit Subscribed(msg.sender, 1, sub.expiresAt, msg.value);
    }
}
