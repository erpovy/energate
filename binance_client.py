import requests
import json
from config import BINANCE_API_URL

class BinanceClient:
    def __init__(self):
        self.base_url = BINANCE_API_URL

    def get_price(self, symbol):
        """
        Fetches the latest price for a symbol.
        Symbol format example: "BTCUSDT"
        """
        try:
            url = f"{self.base_url}/ticker/price?symbol={symbol}"
            response = requests.get(url)
            response.raise_for_status()
            data = response.json()
            return float(data['price'])
        except Exception as e:
            print(f"Error fetching Binance price: {e}")
            return None

    def get_all_prices(self):
        """
        Fetches all prices from Binance.
        Returns a dict: {'BTCUSDT': 42000.0, ...}
        """
        try:
            url = f"{self.base_url}/ticker/price"
            response = requests.get(url)
            response.raise_for_status()
            data = response.json()
            # Convert list to dict for fast lookup
            return {item['symbol']: float(item['price']) for item in data}
        except Exception as e:
            print(f"Error fetching all Binance prices: {e}")
            return {}

    def get_klines(self, symbol, interval='15m', limit=50):
        """
        Fetches OHLCV candlesticks for TA.
        Returns list of floats [close_prices]
        """
        try:
            url = f"{self.base_url}/klines?symbol={symbol}&interval={interval}&limit={limit}"
            response = requests.get(url, timeout=5)
            if response.status_code == 200:
                data = response.json()
                # Binance kline: [time, open, high, low, close, vol...]
                # We mainly need Close prices for RSI
                # Binance kline: [time, open, high, low, close, vol...]
                # We need High, Low, Close (ATR) and Volume (Confirmation)
                candles = []
                for k in data:
                    candles.append({
                        'h': float(k[2]),
                        'l': float(k[3]),
                        'c': float(k[4]),
                        'v': float(k[5])
                    })
                return candles
        except Exception as e:
            print(f"Error fetching klines: {e}")
            return []

if __name__ == "__main__":
    client = BinanceClient()
    price = client.get_price("BTCUSDT")
    print(f"Binance BTCUSDT Price: {price}")
    klines = client.get_klines("BTCUSDT", "15m", 50)
    print(f"Last 5 candles: {klines[-5:]}")
