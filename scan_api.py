import requests

hosts = ["https://api.paribu.com", "https://v4.paribu.com", "https://www.paribu.com"]
paths = [
    "/orders",
    "/order",
    "/v4/orders",
    "/v4/order",
    "/api/v4/orders",
    "/api/v4/order",
    "/app/orders",
    "/app/order",
    "/auth/orders",
    "/market/orders"
]

print(f"{'URL':<50} | {'Status':<6} | {'Content'}")
print("-" * 80)

for host in hosts:
    for path in paths:
        url = host + path
        try:
            # We use POST because creating an order is POST
            resp = requests.post(url, timeout=3)
            # We encounter lots of HTML 404s/200s (Cloudflare)
            # We are looking for JSON responses (400, 401, 200)
            is_json = False
            try:
                resp.json()
                is_json = True
            except: pass
            
            status = resp.status_code
            
            # Filter Logic:
            # Ignore 404 (Not Found)
            # Ignore 200/403 if it is HTML (Cloudflare login page)
            
            content_snippet = resp.text[:20].replace("\n", "")
            
            if status != 404:
                print(f"{url:<50} | {status:<6} | {content_snippet}")
                
        except Exception as e:
            pass
