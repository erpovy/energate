
import json
import os

# 1. Clean Active Trades (Remove the fake AVAX from testing)
if os.path.exists("active_trades.json"):
    print("Removing fake test data from active_trades.json...")
    os.remove("active_trades.json")
    with open("active_trades.json", "w") as f:
        json.dump({}, f)

# 2. Initialize Trade History (So UI table isn't broken)
if not os.path.exists("trade_history.json"):
    print("Creating empty trade_history.json...")
    with open("trade_history.json", "w") as f:
        json.dump([], f)
else:
    print("trade_history.json already exists.")

print("✅ State Cleaned. Ready for Real Wallet Sync.")
