import os
import time
import hmac
import hashlib
import json
import base64
import requests

# Load Config
API_KEY = os.getenv("PARIBU_API_KEY")
API_SECRET = os.getenv("PARIBU_API_SECRET")
BASE_URL = "https://api.paribu.com"

print("--- PARIBU HIZLI TEST (SADECE VARLIKLAR) ---")
print(f"API Key: {API_KEY[:5] if API_KEY else 'YOK'}...")

def get_signature(query_string, body):
    data_to_sign = query_string + body
    secret_bytes = API_SECRET.encode('utf-8')
    data_bytes = data_to_sign.encode('utf-8')
    signature = hmac.new(secret_bytes, data_bytes, hashlib.sha256).digest()
    return base64.b64encode(signature).decode('utf-8')

def test_request(name, endpoint):
    print(f"\nTEST: {name}")
    url = f"{BASE_URL}{endpoint}"
    
    # Empty body/query for assets
    sig = get_signature("", "")
    
    headers = {
        "Authorization": API_KEY,
        "X-Signature": sig,
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0"
    }
    
    try:
        r = requests.get(url, headers=headers)
        print(f"  Durum Kodu: {r.status_code}")
        print(f"  Cevap: {r.text}")
    except Exception as e:
        print(f"  HATA: {e}")

test_request("Varliklar", "/user/assets")
