import requests
import json

try:
    print("Fetching Paribu Ticker...")
    url = "https://www.paribu.com/ticker"
    r = requests.get(url, timeout=10)
    data = r.json()
    
    if data:
        print("✅ Data Fetched!")
        # Get first key (e.g. BTC_TL)
        first_pair = list(data.keys())[0] if isinstance(data, dict) else None
        
        if first_pair:
            item = data[first_pair]
            print(f"Sample Pair: {first_pair}")
            print(f"Keys Found: {list(item.keys())}")
            print(f"lowestAsk: {item.get('lowestAsk')}")
            print(f"highestBid: {item.get('highestBid')}")
            print(f"bid: {item.get('bid')}")
            print(f"ask: {item.get('ask')}")
        else:
            print("Data format unexpected (not a dict?)")
            print(str(data)[:200])
    else:
        print("Empty JSON response")

except Exception as e:
    print(f"Error: {e}")
