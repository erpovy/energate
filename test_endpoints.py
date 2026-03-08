import requests

base = "https://api.paribu.com"
endpoints = [
    "/auth/orders",
    "/v4/orders",
    "/order",
    "/market/orders",
    "/markets/btc_tl/orders",
    "/user/orders"
]

for ep in endpoints:
    try:
        url = base + ep
        print(f"Testing {url}...")
        resp = requests.post(url, timeout=5)
        print(f"Status: {resp.status_code}")
        print("-" * 20)
    except: pass
