import requests
import time
import hmac
import hashlib
import json
import base64
from urllib.parse import urlencode
from config import PARIBU_API_KEY, PARIBU_API_SECRET, PARIBU_API_URL

class ParibuClient:
    def __init__(self):
        self.base_url = PARIBU_API_URL
        self.api_key = PARIBU_API_KEY
        self.api_secret = PARIBU_API_SECRET

    def _get_headers(self, endpoint, params=None, body=None):
        """
        Generates headers based on Paribu Docs:
        Authorization: API Key
        X-Signature: Base64(HMAC-SHA256(Secret, QueryString + Body))
        """
        request_body = ""
        if body:
             request_body = json.dumps(body)
        
        data_to_sign = request_body # Default for GET with no params
        
        signature = hmac.new(
            self.api_secret.encode('utf-8'),
            data_to_sign.encode('utf-8'),
            hashlib.sha256
        ).digest()
        
        signature_b64 = base64.b64encode(signature).decode('utf-8')

        return {
            "Authorization": self.api_key,
            "X-Signature": signature_b64,
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }

    def get_balances(self):
        """
        Fetch user assets.
        Endpoint: /user/assets (Scope: asset:get)
        """
        try:
            endpoint = "/user/assets"
            url = f"{self.base_url}{endpoint}"
            headers = self._get_headers(endpoint) 
            
            response = requests.get(url, headers=headers, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                print(f"✅ RAW ASSETS: {str(data)[:100]}...") # Debug Print

                parsed_wallet = {}
                assets_list = []

                # Handle various response formats
                if isinstance(data, list):
                    assets_list = data
                elif isinstance(data, dict):
                    if "data" in data and isinstance(data["data"], list): assets_list = data["data"]
                    elif "payload" in data and isinstance(data["payload"], list): assets_list = data["payload"]
                    elif "assets" in data and isinstance(data["assets"], list): assets_list = data["assets"]
                    else:
                        # Iterate keys if it's a dict of assets
                        for k, v in data.items():
                            if isinstance(v, dict):
                                v['symbol'] = k
                                assets_list.append(v)

                for asset in assets_list:
                       symbol = asset.get('symbol') or asset.get('asset') or asset.get('currency')
                       if not symbol: continue

                       total = float(asset.get('total') or asset.get('balance') or asset.get('amount') or 0)
                       available = float(asset.get('available') or asset.get('free') or 0)
                       locked = float(asset.get('locked') or asset.get('frozen') or 0)
                       
                       if total == 0 and available > 0: total = available + locked

                       val_obj = {"total": total, "available": available, "locked": locked}
                       
                       symbol = symbol.upper()
                       if "_TL" in symbol: symbol = symbol.replace("_TL", "")
                       
                       if symbol == "TL" or symbol == "TRY": 
                           parsed_wallet["TL"] = val_obj
                       else:
                           parsed_wallet[symbol] = val_obj
                
                if "TL" not in parsed_wallet:
                    parsed_wallet["TL"] = {"total": 0.0, "available": 0.0, "locked": 0.0}
                    
                return parsed_wallet
                
            elif response.status_code == 401:
                 print("⚠️ Auth Error in Wallet: 401")
                 return {"TL": "Yetki Yok (401)"}
            else:
                 print(f"❌ Wallet Error {response.status_code}: {response.text}")
                 return {"TL": f"Err: {response.status_code}"}
        except Exception as e:
            print(f"❌ Wallet Exception: {e}")
            return {"TL": "Conn Err"}

    def get_tickers(self):
        """
        Get all tickers from Paribu Public API (Better Data).
        Endpoint: https://www.paribu.com/ticker
        """
        try:
            # Use Public URL for richer data (Bid/Ask)
            url = "https://www.paribu.com/ticker"
            
            response = requests.get(url, timeout=10)
            
            if response.status_code == 200:
                raw_data = response.json()
                data_list = []

                # Handle Wrappers
                if isinstance(raw_data, list):
                    data_list = raw_data
                elif isinstance(raw_data, dict):
                    if "data" in raw_data and isinstance(raw_data["data"], list): 
                        data_list = raw_data["data"]
                    elif "payload" in raw_data and isinstance(raw_data["payload"], list): 
                        data_list = raw_data["payload"]
                    else:
                        # Dict format: {"BTC_TL": {...}}
                        for k, v in raw_data.items():
                            if isinstance(v, dict):
                                v["market"] = k
                                data_list.append(v)
                
                tickers = {}
                for item in data_list:
                    symbol = item.get("market", "")
                    if not symbol: continue
                    
                    symbol = symbol.upper()
                    tickers[symbol] = {
                        "last": float(item.get("last", 0)),
                        "low": float(item.get("low", 0)),
                        "high": float(item.get("high", 0)),
                        "vol": float(item.get("volume", 0)),
                        "change": float(item.get("change", 0)) if item.get("change") else 0,
                        "lowestAsk": float(item.get("lowestAsk", 0)),
                        "highestBid": float(item.get("highestBid", 0))
                    }
                return tickers
            else:
                 print(f"❌ Ticker Error {response.status_code}: {response.text}")
                 return {}
        except Exception as e:
            print(f"❌ Ticker Exception: {e}")
            return {}

    def get_orderbook(self, symbol):
        try:
            url = f"{self.base_url}/orderbook"
            params = {"market": symbol.lower()}
            response = requests.get(url, params=params, timeout=5)
            
            if response.status_code == 200:
                data = response.json()
                if "data" in data: data = data["data"] # Wrapper check
                return data
            return None
        except:
            return None

    def place_order(self, symbol, amount, side="buy"):
        """
        Place Market Order
        symbol: "btc_tl"
        amount: Amount in TL (for buy) or BTC (for sell)
        """
        try:
            endpoint = "/order"
            url = f"{self.base_url}{endpoint}"
            
            # Correct Paribu V4 Payload
            body = {
                "market": symbol.lower(),
                "trade": side, # Was "side"
                "type": "market"
            }
            
            # For Market Buy: We spend TL -> "total" (2 decimals for TL)
            # For Market Sell: We sell Coin -> "amount" (6 decimals for precision)
            if side == "buy":
                # TL amounts usually require 2 decimal precision max, sent as a STRING to avoid float issues
                body["total"] = f"{amount:.2f}"
            else:
                # Crypto amounts can have more precision
                body["amount"] = f"{amount:.6f}"
            
            print(f"📡 API PAYLOAD: {json.dumps(body)}") # Debug Print
            
            headers = self._get_headers(endpoint, body=body)
            response = requests.post(url, headers=headers, json=body, timeout=10)
            
            if response.status_code == 200 or response.status_code == 201:
                return response.json()
            else:
                return f"Err: {response.text}"
        except Exception as e:
            return f"Ex: {e}"

    def get_trade_history(self):
        """
        Fetches full trade history.
        """
        try:
            endpoint = "/trades/history"
            url = f"{self.base_url}{endpoint}"
            headers = self._get_headers(endpoint)
            resp = requests.get(url, headers=headers, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                return data.get("trades", [])
            return []
        except:
            return []

    def get_last_buy_price(self, coin):
        """
        Scans history to find the last BUY price for a specific coin.
        Returns (price, amount) or (0, 0) if not found.
        """
        coin = coin.lower()
        trades = self.get_trade_history()
        
        for t in trades:
            # Check Coin
            if t.get("marketCurrency") == coin:
                # Check Direction
                if t.get("direction") == "BUY":
                    price = float(t.get("price", 0))
                    amount = float(t.get("amount", 0))
                    return price, amount
        return 0, 0
