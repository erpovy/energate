import requests
import json

target_coins = ["AXS_TL", "MEME_TL", "TLM_TL", "WAVES_TL", "SAND_TL"]

try:
    print("Fetching Paribu Ticker...")
    url = "https://www.paribu.com/ticker"
    r = requests.get(url, timeout=10)
    data = r.json()
    
    if data:
        print("✅ Data Fetched!")
        for pair in target_coins:
            if pair in data:
                item = data[pair]
                change = item.get("percentChange", 0)
                price = item.get("last", 0)
                print(f"✅ FOUND {pair}: Price={price} TL | Change={change}%")
            else:
                print(f"❌ MISSING {pair}")
    else:
        print("Empty JSON response")

except Exception as e:
    print(f"Error: {e}")
