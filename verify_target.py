
import json
import time

# Mock BOT_STATE
BOT_STATE = {
    "active_trades": {},
    "take_profit_percent": 5.0
}

def update_active_trade_buy(coin, price, cost_tl):
    coin = coin.upper()
    current_trade = BOT_STATE["active_trades"].get(coin)
    
    new_price = float(price)
    new_cost = float(cost_tl)
    new_amount = new_cost / new_price if new_price > 0 else 0
    
    if current_trade:
        # DCA Logic
        old_cost = float(current_trade.get("cost", 0))
        old_amount = float(current_trade.get("amount", 0))
        
        total_cost = old_cost + new_cost
        total_amount = old_amount + new_amount
        avg_price = total_cost / total_amount if total_amount > 0 else new_price
        
        # Recalculate Target
        tp_pct = float(BOT_STATE.get("take_profit_percent", 5.0))
        target_price = avg_price * (1 + (tp_pct / 100))
        
        BOT_STATE["active_trades"][coin] = {
            "price": avg_price,
            "target_price": target_price,
            "cost": total_cost,
            "amount": total_amount
        }
        print(f"DCA Update: Avg {avg_price:.2f}, Target {target_price:.2f}")
    else:
        # New Trade
        tp_pct = float(BOT_STATE.get("take_profit_percent", 5.0))
        target_price = new_price * (1 + (tp_pct / 100))
        
        BOT_STATE["active_trades"][coin] = {
            "price": new_price,
            "target_price": target_price,
            "cost": new_cost,
            "amount": new_amount
        }
        print(f"New Trade: Price {new_price:.2f}, Target {target_price:.2f}")

# TEST SCENARIO
print("--- TEST 1: New Buy ---")
update_active_trade_buy("TEST", 100, 1000)
# Expected Target: 105.0

print("\n--- TEST 2: DCA Buy (Price Drops to 90) ---")
update_active_trade_buy("TEST", 90, 1000)
# Total Cost: 2000
# Amt1: 10, Amt2: 11.11 => Total Amt: 21.11
# Avg Price: 2000 / 21.11 = ~94.74
# New Target: 94.74 * 1.05 = ~99.47

trade = BOT_STATE["active_trades"]["TEST"]
print(f"\nFINAL STATE: Price {trade['price']:.2f}, Target {trade['target_price']:.2f}")

if trade['target_price'] > trade['price']:
    print("✅ SUCCESS: Target Price is correctly set above Avg Price")
else:
    print("❌ FAIL: Target Price logic error")
