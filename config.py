import os
from dotenv import load_dotenv

load_dotenv()

# Paribu Credentials
PARIBU_API_KEY = os.getenv("PARIBU_API_KEY")
PARIBU_API_SECRET = os.getenv("PARIBU_API_SECRET")

# Trading Config
SYMBOL_PARIBU = "BTC_TL" # Example: BTC_TL
SYMBOL_BINANCE = "BTCUSDT" # Example: BTCUSDT
TRADE_AMOUNT_TL = float(os.getenv("TRADE_AMOUNT_TL", "100")) # Amount in TL to buy
PRICE_DIFFERENCE_THRESHOLD = float(os.getenv("PRICE_DIFFERENCE_THRESHOLD", "1.0")) # Percentage difference to trigger trade
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "5")) # Seconds
DRY_RUN = os.getenv("DRY_RUN", "True").lower() == "true"


# URLs
PARIBU_API_URL = "https://api.paribu.com"
BINANCE_API_URL = "https://api.binance.com/api/v3"
