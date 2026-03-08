import sys
from unittest.mock import MagicMock

# MOCK MODULES BEFORE IMPORT
sys.modules["flask"] = MagicMock()
sys.modules["requests"] = MagicMock()

import main
import strategy
import time

def test_logic():
    print("--- 🧪 TESTING WORLD CLASS LOGIC ---")
    
    # 1. TEST WALLET SYNC
    print("\n1. Testing Wallet Sync...")
    mock_wallet = {
        "AVAX": {"available": 10.0, "total": 10.0},
        "TL": {"available": 1000.0}
    }
    mock_market = {
        "AVAX_TL": {"last": 50.0} # 10 * 50 = 500 TL Value
    }
    
    # Reset State
    main.BOT_STATE["active_trades"] = {}
    main.BOT_STATE["wallet"] = mock_wallet
    
    # Run Sync
    main.sync_wallet_to_active_trades(mock_wallet, mock_market)
    
    if "AVAX" in main.BOT_STATE["active_trades"]:
        trade = main.BOT_STATE["active_trades"]["AVAX"]
        print(f"✅ Sync SUCCESS: AVAX found at {trade['price']} TL. Cost: {trade['cost']}")
    else:
        print("❌ Sync FAILED: AVAX not added.")

    # 2. TEST DCA (Weighted Average)
    print("\n2. Testing DCA Logic...")
    # Setup: Bought 10 AVAX @ 50 TL (Cost 500)
    # Now Buy 10 AVAX @ 100 TL (High cost)
    # Average Price should be 75 TL
    
    main.update_active_trade_buy("AVAX", 100.0, 1000.0) # 10 Units * 100 Price = 1000 Cost
    
    trade = main.BOT_STATE["active_trades"]["AVAX"]
    avg_price = trade["price"]
    print(f"   Old Cost: 500, New Cost: 1000 -> Total 1500")
    print(f"   Old Amt: 10, New Amt: 10 -> Total 20")
    print(f"   Expected Avg: 75.0")
    print(f"   Actual Avg: {avg_price}")
    
    if abs(avg_price - 75.0) < 0.1:
         print("✅ DCA SUCCESS: Price averaged correctly.")
    else:
         print("❌ DCA FAILED: Price mismatch.")

    # 3. TEST SMART EXIT
    print("\n3. Testing Smart Exit Strategy...")
    strat = strategy.TradingStrategy(MagicMock(), MagicMock())
    
    # Mocking Binance Klines for Momentum
    # Case A: Strong Pump (Should HOLD)
    # Prices: 100, 101, 102 (2% gain in small window)
    klines_pump = [{'c': 100}, {'c': 101}, {'c': 102}] 
    strat.binance.get_klines.return_value = klines_pump
    
    should_sell, reason = strat.should_take_profit("BTC", 110, 100, 5.0) # 10% Profit
    
    print(f"   Pump Scenario (10% Profit, Strong Mom): Sell? {should_sell} | Reason: {reason}")
    if not should_sell:
        print("✅ Smart Exit SUCCESS: Held position during pump.")
    else:
        print("❌ Smart Exit FAILED: Sold too early.")
        
    # Case B: DUMP
    klines_dump = [{'c': 100}, {'c': 99}, {'c': 98}]
    strat.binance.get_klines.return_value = klines_dump
    should_sell, reason = strat.should_take_profit("BTC", 110, 100, 5.0)
    print(f"   Dump Scenario (10% Profit, Weak Mom): Sell? {should_sell} | Reason: {reason}")
    if should_sell:
        print("✅ Smart Exit SUCCESS: Sold on weakness.")
    else:
        print("❌ Smart Exit FAILED: Failed to sell.")

if __name__ == "__main__":
    try:
        test_logic()
    except Exception as e:
        print(f"CRITICAL ERROR: {e}")
