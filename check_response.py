from paribu_client import ParibuClient
import requests
import json
import os
from dotenv import load_dotenv

# Force load env
load_dotenv()

print(f"DEBUG: API Key present? {bool(os.getenv('PARIBU_API_KEY'))}")
print(f"DEBUG: Secret present? {bool(os.getenv('PARIBU_API_SECRET'))}")

client = ParibuClient()
# Try to find the history endpoint
endpoints = [
    "/history/transactions",
    "/history/orders",
    "/orders/history",
    "/user/history",
    "/user/orders",
    "/user/trades",   # Likely candidate
    "/trades/history"
]

for ep in endpoints:
    try:
        if ep != "/trades/history": continue
        print(f"\n--- Testing {ep} ---")
        headers = client._get_headers(ep)
        url = f"{client.base_url}{ep}"
        resp = requests.get(url, headers=headers)
        print(f"Status: {resp.status_code}")
        
        if resp.status_code == 200:
             data = resp.json()
             trades = data.get("trades", [])
             found = False
             for t in trades:
                 if t.get("marketCurrency") == "tlm":
                     print(f"FOUND TLM: {json.dumps(t, indent=4)}")
                     found = True
             if not found:
                 print("No TLM trades found in recent history.")
             break
    except Exception as e:
        print(f"Error testing {ep}: {e}")
