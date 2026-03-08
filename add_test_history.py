
import json
import time
import os

HISTORY_FILE = "trade_history.json"

def add_test_history():
    history = []
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, 'r') as f:
                history = json.load(f)
        except:
            history = []
            
    # Create Dummy Entry
    dummy = {
        "coin": "TEST_COIN",
        "action": "SELL",
        "reason": "Test Kaydı (Sistem Kontrolü)",
        "buy_price": 10.0,
        "sell_price": 12.5,
        "cost": 100.0,
        "revenue": 125.0,
        "net_pnl": 24.3, # 25 - comm
        "commission": 0.7,
        "time": time.strftime("%Y-%m-%d %H:%M")
    }
    
    history.append(dummy)
    
    with open(HISTORY_FILE, 'w') as f:
        json.dump(history, f)
        
    print("✅ Test entry added to trade_history.json")
    print("Please refresh the dashboard to see it.")

if __name__ == "__main__":
    add_test_history()
