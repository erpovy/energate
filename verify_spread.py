
from paribu_client import ParibuClient

client = ParibuClient()
print("Fetching Tickers from Public API...")
tickers = client.get_tickers()

if tickers:
    # Check BTC
    btc = tickers.get("BTC_TL") or tickers.get("BTC")
    if btc:
        ask = btc.get("lowestAsk", 0)
        bid = btc.get("highestBid", 0)
        print(f"BTC -> Ask: {ask}, Bid: {bid}")
        
        if ask > 0 and bid > 0:
            spread = ((ask - bid) / bid) * 100
            print(f"✅ Spread Calculation Possible: {spread:.2f}%")
        else:
             print("❌ Bid/Ask still 0")
    else:
        print("❌ BTC not found (Keys issue?)")
        print(f"First 5 Keys: {list(tickers.keys())[:5]}")
else:
    print("❌ No tickers returned")
