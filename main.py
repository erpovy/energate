import os
import sys
import requests
import time
import threading
import json
import random # For Batch Analysis
from flask import Flask, render_template, request, redirect, url_for, jsonify
from config import CHECK_INTERVAL, DRY_RUN
from binance_client import BinanceClient
from paribu_client import ParibuClient
from strategy import TradingStrategy
from tracking import tracker
import traceback

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# --- FLASK APP ---
app = Flask(__name__)
app.config['DEBUG'] = os.getenv("FLASK_DEBUG", "false").lower() == "true"
app.config['PROPAGATE_EXCEPTIONS'] = app.config['DEBUG']

# --- SECURITY HELPER ---
from functools import wraps
from flask import Response

def check_auth(username, password):
    """Check if a username/password combination is valid."""
    env_user = os.getenv("WEB_USERNAME", "admin")
    env_pass = os.getenv("WEB_PASSWORD", "admin123")
    return username == env_user and password == env_pass

def authenticate():
    """Sends a 401 response that enables basic auth"""
    return Response(
    'Could not verify your access level for that URL.\n'
    'You have to login with proper credentials', 401,
    {'WWW-Authenticate': 'Basic realm="Login Required"'})

def requires_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or not check_auth(auth.username, auth.password):
            return authenticate()
        return f(*args, **kwargs)
    return decorated

# --- GLOBAL STATE ---
# --- PERSISTENCE HELPERS ---
TRADES_FILE = "active_trades.json"
HISTORY_FILE = "trade_history.json"
STATE_LOCK = threading.RLock()

def load_trades():
    if os.path.exists(TRADES_FILE):
        try:
            with STATE_LOCK:
                with open(TRADES_FILE, 'r') as f:
                    return json.load(f)
        except: return {}
    return {}

def save_trades(trades):
    with STATE_LOCK:
        with open(TRADES_FILE, 'w') as f:
            json.dump(trades, f, indent=4)

BLACKLIST_FILE = "blacklist.json"

def load_blacklist():
    if os.path.exists(BLACKLIST_FILE):
        try:
            with STATE_LOCK:
                with open(BLACKLIST_FILE, 'r') as f:
                    return json.load(f)
        except: return []
    return []

def save_blacklist(bl_list):
    with STATE_LOCK:
        with open(BLACKLIST_FILE, 'w') as f:
            json.dump(bl_list, f, indent=4)

def load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with STATE_LOCK:
                with open(HISTORY_FILE, 'r') as f:
                    return json.load(f)
        except: return []
    return []

def save_history(history):
    with STATE_LOCK:
        with open(HISTORY_FILE, 'w') as f:
            json.dump(history, f, indent=4)

def repair_history(history):
    """
    Recalculates PnL for old trades that might have 0 or missing values.
    """
    fixed = False
    for trade in history:
        # Check if PnL is suspiciously zero or missing, but we have Cost/Revenue
        if trade.get("net_pnl", 0) == 0 and trade.get("cost", 0) > 0:
            # Recalculate
            cost = float(trade.get("cost", 0))
            rev = float(trade.get("revenue", 0))
            
            # Re-run commission logic (0.28% Buy + 0.28% Sell)
            comm = (cost * 0.0028) + (rev * 0.0028)
            net = (rev - cost) - comm
            
            trade["net_pnl"] = net
            trade["commission"] = comm
            fixed = True
            
    if fixed:
        print("🔧 Repairing detailed history PnL values...")
        save_history(history)
    return history

def sync_past_trades():
    """
    Fetches past SELL orders from Paribu to populate history and PnL.
    Critical for showing 'Daily Net Profit' correctly after restart.
    """
    try:
        temp_client = ParibuClient()
        trades = temp_client.get_trade_history() # Fetches last 20-50 trades
        
        history = load_history()
        existing_ids = [t.get("orderId", "") for t in history]
        updates = False
        
        for t in trades:
            # Standardize Coin Name
            coin = t.get("marketCurrency", "").upper()
            tid = t.get("orderId", str(time.time()))
            
            if tid in existing_ids: continue
            
            direction = t.get("direction", "").upper()
            # Paribu History API uses 'price' and 'amount', but let's be safe with fallbacks
            price = float(t.get("price") or t.get("rate") or 0)
            amount = float(t.get("amount") or t.get("quantity") or 0)
            
            if amount == 0: continue # Skip invalid sync
            
            revenue = price * amount
            
            # For Sells, we calculate PnL estimate
            # For Buys, we just show the purchase
            new_record = {
                "coin": coin,
                "action": direction, # BUY or SELL
                "amount": amount,
                "price": price,
                "time": t.get("createdAt", time.strftime("%Y-%m-%d %H:%M")),
                "reason": "API_SYNC",
                "orderId": tid,
                "revenue": revenue if direction == "SELL" else 0,
                "cost": revenue if direction == "BUY" else (revenue / 1.05),
                "net_pnl": 0
            }
            
            if direction == "SELL":
                cost_est = revenue / 1.05
                new_record["net_pnl"] = revenue - cost_est - (revenue * 0.0028)
                new_record["buy_price"] = cost_est / amount if amount > 0 else 0
                new_record["sell_price"] = price
            else:
                new_record["buy_price"] = price
                new_record["sell_price"] = 0

            history.append(new_record)
            updates = True
            log_message(f"🔄 Geçmiş Eşitleme: {coin} {direction} eklendi.")

        if updates:
            save_history(history)
            BOT_STATE["trade_history"] = history
            log_message("✅ Geçmiş işlemler senkronize edildi.")
            
    except Exception as e:
        log_message(f"History Sync Error: {e}")

def get_real_cost_from_api(coin):
    """
    Helper to fetch last buy price from Paribu History
    """
    try:
        temp_client = ParibuClient()
        price, amount = temp_client.get_last_buy_price(coin)
        return price
    except:
        return 0

def sync_wallet_to_active_trades(wallet_data, market_prices):
    """
    CRITICAL FIX: Checks if we have coins in wallet that are NOT in active_trades.
    If found, adds them to tracking with current price as entry (Best Effort).
    """
    if not wallet_data: return
    
    updates = False
    for coin, data in wallet_data.items():
        if coin == "TL": continue
        
        coin = coin.upper()
        # Check if we have significant balance (> 30 TL worth)
        # We need price to check value.
        pair_key = f"{coin}_TL"
        
        current_price = 0
        if market_prices and pair_key in market_prices:
             current_price = float(market_prices[pair_key].get('last', 0))
             
        available = float(data.get('available', 0))
        # Total Value
        value_tl = available * current_price
        
        # If valuable and NOT tracked
        if value_tl > 30 and coin not in BOT_STATE["active_trades"]:
            # CHECK BLACKLIST
            if coin in BOT_STATE["blacklist"]:
                continue
                
            # TRY TO RECOVER REAL COST
            real_buy_price = get_real_cost_from_api(coin)
            if real_buy_price > 0:
                cost_basis = real_buy_price
                origin = "API_HISTORY"
            else:
                cost_basis = current_price # Fallback
                origin = "MARKET_PRICE"
                
            log_message(f"🔍 Cüzdan Senkronizasyonu: {coin} sisteme dahil edildi. (Maliyet: {cost_basis} TL - Kaynak: {origin})")
            # Calculate Target Price (Entry + Profit Margin)
            tp_pct = float(BOT_STATE.get("take_profit_percent", 5.0))
            target_price = cost_basis * (1 + (tp_pct / 100))
            
            BOT_STATE["active_trades"][coin] = {
                "price": cost_basis,
                "target_price": target_price, # NEW: Explicit Target
                "cost": value_tl,
                "amount": available,
                "highest_price": current_price,
                "time": time.strftime("%H:%M")
            }
            updates = True

    # ONE-TIME HISTORY SYNC (If empty)
    if not BOT_STATE["trade_history"]:
         sync_past_trades()

    # 2. CLEANUP: Remove trades that are no longer in wallet (Sold externaly or Dust)
    coins_to_remove = []
    for coin in BOT_STATE["active_trades"]:
        # If coin not in wallet at all, OR balance is very low (Dust)
        if coin not in wallet_data:
             coins_to_remove.append(coin)
             continue
             
        # Check Dust (Value < 30 TL)
        avail = float(wallet_data[coin].get("available", 0))
        # Use active trade price or 0
        pr = float(BOT_STATE["active_trades"][coin].get("price", 0))
        wallet_val = avail * pr
        
        if wallet_val < 30:
            coins_to_remove.append(coin)

    for coin in coins_to_remove:
        log_message(f"🧹 Temizlik: {coin} bakiyesi yetersiz (<30 TL), takip listesinden çıkarılıyor.")
        del BOT_STATE["active_trades"][coin]
        updates = True
            
    if updates:
        save_trades(BOT_STATE["active_trades"])

# --- BACKGROUND BOT LOOP ---
BOT_STATE = {
    "running": False,
    "logs": [],
    "market_data": [],
    "wallet": {},
    "active_trades": load_trades(),
    "trade_history": repair_history(load_history()),
    "whitelist": "",
    "interval": 2,
    "threshold": 0.3, # Scalping: Follow smaller moves
    "sell_threshold": -2.0,
    "trade_percent": 100,
    "take_profit_percent": 1.5, # Scalping: Quick small profits
    "ai_mode": True,
    "selected_coins": [],
    "all_coins": [],
    "recommendations": [],
    "blacklist": load_blacklist(), # Load from file
    "fomo_mode": False
}

# --- LOGGING HELPER ---
def log_message(msg):
    print(msg) 
    with STATE_LOCK:
        BOT_STATE["logs"].insert(0, f"{time.strftime('%H:%M:%S')} - {msg}")
        if len(BOT_STATE["logs"]) > 100:
            BOT_STATE["logs"].pop()

def calculate_pnl(sell_total, buy_total):
    """
    Calculate Net PnL after Paribu Commissions (0.28% Buy + 0.28% Sell = 0.56%)
    Returns: (Net Profit/Loss, Total Commission Amount)
    """
    if buy_total == 0: return 0, 0
    
    # Commission Rates
    buy_comm = buy_total * 0.0028
    sell_comm = sell_total * 0.0028
    total_comm = buy_comm + sell_comm
    
    # Net Result
    # Gross Profit = Sell - Buy
    # Net Profit = Gross Profit - Total Comm
    net_pnl = (sell_total - buy_total) - total_comm
    
    return net_pnl, total_comm



# --- BACKGROUND BOT LOOP ---
def bot_loop():
    log_message("==========================================")
    log_message("   PARIBU PROBOT V3.0 - INTELLIGENCE ENGINE")
    log_message("==========================================")
    log_message("Starting Intelligence Engine...")
    binance = BinanceClient()
    paribu = ParibuClient()
    strategy = TradingStrategy(paribu, binance)
    
    # Cache for strategy analysis (Performance)
    all_analysis = {} 
    
    while True:
        if BOT_STATE["running"]:
            active_coins = BOT_STATE.get("selected_coins", [])
            interval = int(BOT_STATE.get("interval", 5)) # Dynamic interval
            
            # 1. Fetch Wallet (Occasionally, e.g., every 10 loops)
            # For MVP, fetch every loop or use a counter. Let's just try fetch.
            balances = paribu.get_balances() 
            if balances: BOT_STATE["wallet"] = balances
            
            # --- SYNC WALLET (Memory Recovery) ---
            # Try to sync providing we have some market data (re-using old dict if needed or fetching fresh inside helper requires rewrite)
            # Better to pass the tickers we fetch below.
            # Postpone sync call until we have tickers.
            
            # --- BATCH FETCH ---
            try:
                log_message("Fetching market data...")
                binance_prices = binance.get_all_prices()
                paribu_tickers = paribu.get_tickers()
                
                # --- EXECUTE SYNC NOW ---
                if balances and paribu_tickers:
                     sync_wallet_to_active_trades(balances, paribu_tickers)
                
                if not paribu_tickers:
                    log_message("⚠️ Paribu Data Failed! (Empty Ticker)")
                
                if paribu_tickers:
                     # --- WALLET ENRICHMENT (Add Approx TL Value) ---
                     if BOT_STATE["wallet"]:
                        for w_coin, w_data in BOT_STATE["wallet"].items():
                            if w_coin != 'TL' and isinstance(w_data, dict):
                                w_pair = f"{w_coin}_TL"
                                if w_pair in paribu_tickers:
                                    try:
                                        last_price_str = paribu_tickers[w_pair].get('last')
                                        if last_price_str:
                                            w_price = float(last_price_str)
                                            w_total = float(w_data.get('total', 0))
                                            w_data['est_tl'] = w_total * w_price
                                    except:
                                        pass # Keep old value or skip

                     # DYNAMIC COIN DISCOVERY
                     # Paribu format: "BTC_TL", "ETH_TL". We extract "BTC", "ETH".
                     detected_coins = [pair.split("_")[0] for pair in paribu_tickers.keys() if "_TL" in pair]
                     
                     # Filter coins that also exist on Binance to ensure we can compare
                     valid_coins = []
                     for coin in detected_coins:
                         if f"{coin}USDT" in binance_prices:
                             valid_coins.append(coin)
                             
                     # Update BOT_STATE["all_coins"] for UI selection
                     BOT_STATE["all_coins"] = sorted(valid_coins)
                     
                     # If user hasn't manually selected, default to top coins or all? 
                     # Let's keep manual selection effectively.
                     # But for the requested "All coins" experience, we should auto-add new ones if "selected_coins" is empty or force it.
                     # Better approach: Iterate over active_coins. BUT user wants ALL.
                     # Let's update active_coins to be valid_coins if the user selected "ALL" (we add a special flag later).
                     # For now, let's just make sure list is up to date.
                
                table_data = [] # Prepare data for UI
                
                # Use valid_coins if available (dynamic), otherwise fallback to active_coins
                # Logic: We only process coins that are IN active_coins list.
                # To show ALL, user must check all boxes. 
                # OR we change logic: Show ALL in table, but only TRADE selected.
                # User asked: "Coinlerin tamami yok". So table should show ALL.
                
                # AI MODE LOGIC
                if BOT_STATE["ai_mode"]:
                    # AI Mode: SCAN & TRADE ALL VALID COINS (Ignore Whitelist)
                    display_coins = BOT_STATE["all_coins"] if BOT_STATE["all_coins"] else active_coins
                    active_coins = display_coins # Enabling trading for ALL displayed coins
                else:
                    # MANUAL MODE: Use Whitelist
                    if BOT_STATE["whitelist"] and len(BOT_STATE["whitelist"].strip()) > 0:
                        desired_coins = [c.strip().upper() for c in BOT_STATE["whitelist"].split(',') if c.strip()]
                        display_coins = [c for c in valid_coins if c in desired_coins]
                        if not display_coins: display_coins = []
                    else:
                        display_coins = BOT_STATE["all_coins"] if BOT_STATE["all_coins"] else active_coins
                        # In manual mode without whitelist, we show all but maybe only trade selected?
                        # For now, let's assume manual mode = trade whatever is in "active_coins" (which is empty by default unless logic elsewhere)
                        # Actually, looking at original code, "active_coins" was "selected_coins".
                        
                # Ensure we have a valid list
                if not display_coins: display_coins = []
                
                # --- BATCH OPTIMIZATION ---
                # Analyzing 183 coins takes too long.
                # Solution: Always analyze Active Trades + Random Sample of others.
                # Full rotation happens naturally over time.
                BATCH_SIZE = 30 # Increased from 15 for faster discovery
                
                # 1. Always analyze active positions
                priority_coins = [c for c in active_coins if c in BOT_STATE["active_trades"]]
                
                # 2. Randomly sample others
                other_coins = [c for c in display_coins if c not in priority_coins]
                random.shuffle(other_coins)
                batch_coins = priority_coins + other_coins[:BATCH_SIZE]
                
                # Show scan progress
                tl_avail_log = 0.0
                if isinstance(BOT_STATE["wallet"].get("TL"), dict):
                    tl_avail_log = float(BOT_STATE["wallet"]["TL"].get("available", 0.0))
                
                log_message(f"🔄 Tarama: {len(batch_coins)} coin analiz ediliyor... (Bakiye: {tl_avail_log:.2f} TL)")

                for coin in display_coins:
                    paribu_pair = f"{coin}_TL"
                    binance_pair = f"{coin}USDT"
                    
                    b_price = binance_prices.get(binance_pair)
                    p_ticker = paribu_tickers.get(paribu_pair)
                    
                    if b_price and p_ticker:
                        p_last = p_ticker.get('last')
                        
                        # LOGIC: Only run heavy strategy if in batch OR active trade
                        should_analyze = (coin in batch_coins)
                        
                        # --- CHECK TAKE PROFIT ON TRACKED TRADES (Always) ---
                        if coin in BOT_STATE["active_trades"]:
                            # SKIP IF BLACKLISTED
                            if coin in BOT_STATE["blacklist"]:
                                continue

                            try:
                                # Handle dict vs float (migration)
                                trade_data = BOT_STATE["active_trades"][coin]
                                entry_price = float(trade_data) if not isinstance(trade_data, dict) else float(trade_data["price"])
                                buy_cost = 0
                                if isinstance(trade_data, dict): buy_cost = float(trade_data.get("cost", 0))

                                highest_price = float(trade_data.get("highest_price", entry_price))
                                
                                # Update Highest Price (Trailing Logic)
                                current_price = float(p_last)
                                if current_price > highest_price:
                                    highest_price = current_price
                                    # Update state with new high
                                    BOT_STATE["active_trades"][coin]["highest_price"] = highest_price
                                    save_trades(BOT_STATE["active_trades"])

                                pct_diff = ((current_price - entry_price) / entry_price) * 100
                                tp_limit = float(BOT_STATE.get("take_profit_percent", 5.0))
                                
                                # Trailing Calculations
                                highest_price = float(trade_data.get("highest_price", entry_price)) # Ensure we use the updated highest
                                trailing_pullback = 0.0
                                if highest_price > 0:
                                    trailing_pullback = ((highest_price - current_price) / highest_price) * 100
                                
                                # BLACKLIST CHECK FOR SELLING
                                if coin in BOT_STATE["blacklist"]:
                                     continue # Skip logic for blacklisted coins completely (HOLD)

                                # --- WORLD CLASS SMART EXIT ---
                                # Check if we should Sell or Hold
                                should_sell_smart, smart_reason = strategy.should_take_profit(coin, current_price, entry_price, tp_limit)
                                
                                # Override for Trailing Stop hard trigger
                                atr_stop_pct = 3.0
                                if pct_diff > 2.0:
                                    atr_stop_pct = strategy.get_atr_stop(coin, current_price)
                                    
                                is_classic_trailing = (pct_diff > atr_stop_pct) and (trailing_pullback >= 0.5)

                                # LOGGING FOR DEBUG (WHY NOT SELLING?)
                                if pct_diff > 1.0: # Only log if we are somewhat profitable
                                     log_message(f"🔍 SATIŞ KONTROL ({coin}): Kar: %{pct_diff:.2f} | SmartSell: {should_sell_smart} ({smart_reason}) | Trailing: {is_classic_trailing} (Pullback: {trailing_pullback:.2f}%, Stop: {atr_stop_pct:.2f}%)")
                                
                                should_sell = False
                                reason = ""
                                
                                # --- TARGET PRICE CHECK (TRANSPARENCY UPDATE) ---
                                # Check if we hit the explicit target price
                                target_price = float(trade_data.get("target_price", entry_price * (1 + (tp_limit/100))))
                                if current_price >= target_price:
                                    should_sell = True
                                    reason = f"🎯 HEDEF FİYAT GELDİ ({current_price:.2f} >= {target_price:.2f})"
                                    # Override Smart Wait if user wants strict sells?
                                    # For now, let's allow Smart Exit to HOLD if momentum is super strong, 
                                    # BUT if Smart Exit says "SELL" or "Neutral", we sell.
                                    if not should_sell_smart and "BEKLE" in smart_reason:
                                        should_sell = False # Respect the "Hold for more profit" AI decision
                                        reason = f"Hedef Geldi ({current_price:.2f}) ama AI Bekletiyor: {smart_reason}"
                                        log_message(f"⏳ {reason}")
                                elif should_sell_smart:
                                    should_sell = True
                                    reason = smart_reason
                                elif is_classic_trailing:
                                    should_sell = True
                                    reason = f"Trailing Stop: Zirveden %{trailing_pullback:.2f} düştü"

                                if should_sell:
                                    is_trailing = is_classic_trailing # Keep legacy flag for logging if needed
                                    
                                    # Trigger Sell Amount
                                    if BOT_STATE["wallet"] and coin in BOT_STATE["wallet"]:
                                        c_bal = float(BOT_STATE["wallet"][coin].get("available", 0))
                                        
                                        # MINIMUM VALUE CHECK (12 TL Buffer)
                                        estimated_value = c_bal * current_price
                                        if estimated_value < 12:
                                            log_message(f"⚠️ Satış İptal (Limit Altı): {estimated_value:.2f} TL (Min 10 TL)")
                                            continue

                                        if c_bal > 0:
                                            resp = paribu.place_order(paribu_pair, c_bal, "sell")
                                            
                                            # Validations
                                            is_success = False
                                            if isinstance(resp, dict):
                                                if resp.get("status") == "ok": is_success = True
                                                elif "data" in resp and resp.get("data", {}).get("id"): is_success = True
                                                elif "id" in resp: is_success = True
                                            
                                            if is_success:
                                                try:
                                                    log_message(f"✅ Kar Al Satışı Başarılı: {resp}")

                                                    # CALCULATE PNL
                                                    sell_total = c_bal * current_price
                                                    if buy_cost == 0: buy_cost = c_bal * entry_price # Estimate
                                                    net_pnl, comm = calculate_pnl(sell_total, buy_cost)
                                                    
                                                    # SAVE TO HISTORY
                                                    trade_record = {
                                                        "coin": coin,
                                                        "action": "TAKE_PROFIT",
                                                        "reason": reason,
                                                        "buy_price": entry_price,
                                                        "sell_price": current_price,
                                                        "cost": buy_cost,
                                                        "revenue": sell_total,
                                                        "net_pnl": net_pnl,
                                                        "commission": comm,
                                                        "time": time.strftime("%Y-%m-%d %H:%M")
                                                    }
                                                    BOT_STATE["trade_history"].append(trade_record)
                                                    save_history(BOT_STATE["trade_history"])
                                                    log_message(f"💵 HESAPLAMA: {sell_total:.2f} - {buy_cost:.2f} = {net_pnl:.2f} TL Kâr")

                                                    # Track Performance (Self-Improvement)
                                                    strat_name = trade_data.get("strategy", "MANUAL")
                                                    pnl_pct = (net_pnl / buy_cost) * 100 if buy_cost > 0 else 0
                                                    tracker.log_trade(coin, strat_name, pnl_pct)

                                                    # Remove from Tracker
                                                    del BOT_STATE["active_trades"][coin]
                                                    save_trades(BOT_STATE["active_trades"])
                                                except Exception as e:
                                                    log_message(f"❌ HISTORY KAYIT HATASI: {e}")
                                                    traceback.print_exc()
                                            else:
                                                 log_message(f"❌ SATIŞ EMRİ BAŞARISIZ: {resp}")
                            except Exception as e:
                                log_message(f"TP Error: {e}")

                        # --- ORDERBOOK FETCH SKIPPED FOR SPEED ---
                        p_bid = p_last 
                        p_ask = p_last

                        # --- SMART STRATEGY (BATCHED) ---
                        if should_analyze:
                            analysis = strategy.check_opportunity(
                                coin, 
                                b_price, 
                                p_last, 
                                threshold=BOT_STATE["threshold"],
                                sell_threshold=BOT_STATE.get("sell_threshold", -2.0),
                                fomo_enabled=BOT_STATE.get("fomo_mode", False)
                            )
                        else:
                            # LIGHT MODE: Dummy Analysis
                            last_an = all_analysis.get(coin, {})
                            analysis = {
                                "signal": None,
                                "momentum": last_an.get("momentum", 0) if last_an else 0,
                                "sentiment": last_an.get("sentiment", "SIRA BEKLEMEDE") if last_an else "SIRA BEKLEMEDE",
                                "ta_info": {"desc": "Analiz Bekleniyor...", "confidence": 0, "rsi": 50}
                            }
                        
                        if analysis:
                            if should_analyze: all_analysis[coin] = analysis # Cache result
                            
                            # Add to Table Data
                            sent = analysis["sentiment"]
                            desc = ""
                            rsi = 50
                            if "ta_info" in analysis:
                                desc = analysis["ta_info"].get("desc", "")
                                rsi = analysis["ta_info"].get("rsi", 50)

                            # Get extra data
                            p_ticker = paribu_tickers.get(f"{coin}_TL".upper(), {})
                            p_vol = p_ticker.get("vol", 0)
                            p_change = p_ticker.get("change", 0)
                            p_ask = float(p_ticker.get("lowestAsk", 0))
                            p_bid = float(p_ticker.get("highestBid", 0))
                            spread = 0
                            if p_bid > 0: 
                                spread = ((p_ask - p_bid) / p_bid) * 100
                            
                            # DEBUG SPREAD (Only for BTC to avoid spam)
                            if coin == "BTC":
                                log_message(f"🔍 DEBUG SPREAD: Bid={p_bid} Ask={p_ask} Spread={spread:.2f}%")

                            table_data.append({
                                "coin": coin,
                                "binance": b_price,
                                "paribu": p_last, 
                                "bid": p_bid,
                                "ask": p_ask,
                                "volume": p_vol,
                                "change": p_change,
                                "spread": spread,
                                "momentum": analysis["momentum"],
                                "sentiment": sent,
                                "desc": desc, 
                                "rsi": int(rsi), 
                                "ta_info": analysis.get("ta_info", {}),
                                "macd": analysis.get("ta_info", {}).get("macd_line", 0) # Trackers for UI
                            })
                            
                            # Execute Trade if Signal AND Coin is in Selected List
                            if coin in active_coins and analysis["signal"]:
                                action = analysis["signal"]["action"]
                                log_message(f"⚡ SİNYAL YAKALANDI ({coin}): {action} | Sebep: {analysis['signal']['reason']}")
                                
                                if action == "AL":
                                    # Calculate Amount based on % of TL Balance (AVAILABLE ONLY)
                                    try:
                                        # Use 'available' instead of 'total' to avoid spending locked funds
                                        tl_avail = 0.0
                                        if isinstance(BOT_STATE["wallet"]["TL"], dict):
                                             tl_avail = float(BOT_STATE["wallet"]["TL"].get("available", 0.0))
                                        else:
                                             # Fallback if wallet is weird structure (e.g. 0)
                                             tl_avail = 0.0

                                        percent = float(BOT_STATE.get("trade_percent", 100))
                                        # Safety: Use 99% max to avoid rounding errors
                                        if percent >= 100: percent = 99.0
                                        
                                        raw_amt = (tl_avail * percent) / 100
                                        trade_amt = float(f"{raw_amt:.2f}") # Round down to 2 decimals
                                        
                                        log_message(f"💰 Bakiye: {tl_avail} TL | Kullanılacak: {trade_amt:.2f} TL (%{percent})")

                                        # --- 1. BAKİYE KONTROLÜ (> 105 TL) ---
                                        if tl_avail < 105.0:
                                            log_message(f"⚠️ Yetersiz Bakiye: {tl_avail:.2f} TL (Minimum alım için ~100 TL gerekir). Alım pas geçildi.")
                                            continue

                                        # --- 1b. SPREAD & COST CHECK (Scalping Guard) ---
                                        p_ticker = paribu_tickers.get(paribu_pair, {})
                                        p_ask = float(p_ticker.get("lowestAsk", 0))
                                        p_bid = float(p_ticker.get("highestBid", 0))
                                        spread = 0
                                        if p_bid > 0: 
                                            spread = ((p_ask - p_bid) / p_bid) * 100
                                        
                                        target_profit = float(BOT_STATE.get("take_profit_percent", 1.5))
                                        # Commission is 0.56% total (Buy+Sell)
                                        costs = spread + 0.56
                                        
                                        if costs >= target_profit:
                                            log_message(f"⚠️ Limit İptal (Verimsiz): {coin} Makas+Komisyon (%{costs:.2f}) Hedef Kârı (%{target_profit:.2f}) aşıyor.")
                                            continue

                                        # --- 2. ÜCRET HESAPLAMA (PRECISION FIX) ---
                                        amount = trade_amt / float(p_last)
                                        
                                        # EĞER ADET > 1 İSE TAM SAYI YAP (Küsüratla uğraşma)
                                        # EĞER ADET < 1 İSE (BTC GİBİ) KÜSÜRATLI KALSIN (Max 6 basamak)
                                        if amount > 1.0:
                                            amount = int(amount)
                                            # Tekrar TL maliyetini hesapla (Tam sayıya göre)
                                            trade_amt = float(f"{amount * float(p_last):.2f}")
                                        else:
                                            amount = float(f"{amount:.6f}") # Limit precision
                                            trade_amt = float(f"{amount * float(p_last):.2f}")
                                        
                                        # Min trade amount check (Paribu usually 100 TL for many pairs)
                                        if trade_amt >= 100:
                                            log_message(f"🚀 AL EMRİ GİDİYOR: {paribu_pair} Tutar: {trade_amt:.2f} TL ({amount} adet)")
                                            resp = paribu.place_order(paribu_pair, trade_amt, "buy")
                                            log_message(f"📡 Emir Sonucu: {resp}")
                                            
                                            # Validate Order Success
                                            is_success = False
                                            if isinstance(resp, dict):
                                                if resp.get("status") == "ok": is_success = True
                                                elif "data" in resp and resp.get("data", {}).get("id"): is_success = True
                                                # Some APIs return just {id: ...}
                                                elif "id" in resp: is_success = True
                                            
                                            if is_success:
                                                log_message(f"✅ Emir İletildi, Takip Başlıyor...")
                                                # TRACK TRADE WITH COST BASIS
                                                strat_trigger = analysis.get("trigger", "MANUAL")
                                                # if fomo_protection: strat_trigger = "FOMO_PANIC"
                                                update_active_trade_buy(coin, p_last, trade_amt, strat_trigger)
                                            else:
                                                log_message(f"❌ Emir Başarısız (Takip Edilmeyecek): {resp}")
                                        else:
                                            log_message(f"⚠️ Limit Altı Tutar: {trade_amt:.2f} TL (Paribu Min: 100 TL). Lütfen Bakiyenizi veya Bütçe(%) ayarınızı kontrol edin.")
                                    except Exception as e:
                                        log_message(f"Hata (Buy Flow): {e}")

                                # --- SELL LOGIC (SAT) ---
                                elif action == "SAT":
                                    # Fix: Ensure logic uses UPPERCASE keys consistently
                                    u_coin = coin.upper()
                                    
                                    # Check if we actually have this coin in Wallet
                                    if BOT_STATE["wallet"] and u_coin in BOT_STATE["wallet"]:
                                        c_bal = float(BOT_STATE["wallet"][u_coin].get("available", 0))
                                        if c_bal > 0:
                                            # Prepare Data for PnL
                                            # Check saved trade data (try both original and upper key)
                                            trade_data = BOT_STATE["active_trades"].get(coin, BOT_STATE["active_trades"].get(u_coin, float(p_last)))
                                            
                                            entry_price = float(trade_data) if not isinstance(trade_data, dict) else float(trade_data["price"])
                                            buy_cost = 0
                                            if isinstance(trade_data, dict): buy_cost = float(trade_data.get("cost", 0))

                                            # Calculate PnL
                                            # Sell Total = Balance * Current Price
                                            sell_total = c_bal * float(p_last)
                                            
                                            # MINIMUM VALUE CHECK (12 TL Buffer)
                                            if sell_total < 12:
                                                log_message(f"⚠️ Sinyal Satışı İptal (Limit Altı): {sell_total:.2f} TL (Min 10 TL)")
                                                continue
                                            
                                            # If buy_cost is missing (old data), estimate it
                                            if buy_cost == 0: buy_cost = c_bal * entry_price

                                            net_pnl, comm = calculate_pnl(sell_total, buy_cost)
                                            
                                            # --- PROFIT PROTECTION CHECK ---
                                            # 1. Is it a tracked trade?
                                            is_tracked = (coin in BOT_STATE["active_trades"]) or (u_coin in BOT_STATE["active_trades"])
                                            
                                            # 2. Stop Loss Check
                                            is_stop_loss = "STOP" in str(analysis.get('signal', {}).get('reason', '')).upper()
                                            
                                            # 3. Decision Logic
                                            if is_tracked and not is_stop_loss and net_pnl <= 0:
                                                log_message(f"✋ Satış Ertelendi: Henüz Net Kar Yok ({net_pnl:.2f} TL). Bekleniyor...")
                                                continue
                                            
                                            if not is_tracked:
                                                log_message(f"ℹ️ Takip Edilmeyen Coin: Kar kontrolü pas geçildi. (Maliyet Bilinmiyor)")

                                            log_message(f"🔻 SATIŞ YAPILIYOR: {coin} | Tahmini Tutar: {sell_total:.2f} TL | Net Kar: {net_pnl:.2f} TL")
                                            resp = paribu.place_order(paribu_pair, c_bal, "sell")
                                            
                                            # Validate Order Success
                                            is_success = False
                                            if isinstance(resp, dict):
                                                if resp.get("status") == "ok": is_success = True
                                                elif "data" in resp and resp.get("data", {}).get("id"): is_success = True
                                                # Some APIs return just {id: ...}
                                                elif "id" in resp: is_success = True
                                            
                                            if is_success:
                                                log_message(f"✅ Satış Başarılı: {resp}")
                                                
                                                # SAVE HISTORY
                                                trade_record = {
                                                    "coin": coin,
                                                    "action": "SELL",
                                                    "reason": analysis['signal']['reason'],
                                                    "buy_price": entry_price,
                                                    "sell_price": float(p_last),
                                                    "cost": buy_cost,
                                                    "revenue": sell_total,
                                                    "net_pnl": net_pnl,
                                                    "commission": comm,
                                                    "time": time.strftime("%Y-%m-%d %H:%M")
                                                }
                                                BOT_STATE["trade_history"].append(trade_record)
                                                save_history(BOT_STATE["trade_history"])
                                                
                                                log_message(f"💵 NET KAR/ZARAR: {net_pnl:.2f} TL (Komisyon: {comm:.2f} TL)")

                                                # Remove from Tracker
                                                if coin in BOT_STATE["active_trades"]:
                                                    del BOT_STATE["active_trades"][coin]
                                                    save_trades(BOT_STATE["active_trades"])
                                            else:
                                                log_message(f"❌ Satış Başarısız (Emir İletilemedi): {resp}")
                        
                        
                # --- AI RECOMMENDATIONS AGGREGATION ---
                # Sort by confidence
                recs = []
                for item in table_data:
                    conf = 50
                    if "ta_info" in item and isinstance(item["ta_info"], dict):
                        conf = item.get("ta_info", {}).get("confidence", 50)
                    
                    # Only recommend Strong Buy or Buy with high confidence
                    if conf >= 80 and "AL" in str(item.get("sentiment", "")):
                        recs.append(item)
                
                recs.sort(key=lambda x: x.get("ta_info", {}).get("confidence", 0), reverse=True)
                BOT_STATE["recommendations"] = recs[:5] # Top 5
                
                BOT_STATE["market_data"] = table_data # Update UI
                        
            except Exception as e:
                 log_message(f"Engine Error: {str(e)}")
                 traceback.print_exc()
            
            time.sleep(interval)
        else:
            time.sleep(1)

def update_active_trade_buy(coin, price, cost_tl, strategy="MANUAL"):
    """ Helper to update active trades with DCA (Weighted Average) Logic """
    # Enforce Uppercase Key
    coin = coin.upper()
    
    current_trade = BOT_STATE["active_trades"].get(coin)
    
    new_price = float(price)
    new_cost = float(cost_tl)
    new_amount = new_cost / new_price if new_price > 0 else 0
    
    if current_trade:
        # DCA LOGIC: Calculate Weighted Average
        old_cost = float(current_trade.get("cost", 0))
        old_amount = float(current_trade.get("amount", 0))
        # If amount missing, estimate from price
        if old_amount == 0 and float(current_trade.get("price", 1)) > 0:
             old_amount = old_cost / float(current_trade["price"])
             
        total_cost = old_cost + new_cost
        total_amount = old_amount + new_amount
        
        avg_price = total_cost / total_amount if total_amount > 0 else new_price
        
        # Recalculate Target for DCA
        tp_pct = float(BOT_STATE.get("take_profit_percent", 5.0))
        target_price = avg_price * (1 + (tp_pct / 100))

        BOT_STATE["active_trades"][coin] = {
            "price": avg_price,
            "target_price": target_price,
            "cost": total_cost,
            "amount": total_amount,
            "highest_price": avg_price, # Reset high to Avg
            "time": time.strftime("%H:%M"),
            "strategy": strategy
        }
        log_message(f"➕ POZİSYON EKLENDİ (DCA): {coin} Yeni Ort: {avg_price:.2f} TL | Hedef: {target_price:.2f} TL")
    else:
        # NEW TRADE
        tp_pct = float(BOT_STATE.get("take_profit_percent", 5.0))
        target_price = new_price * (1 + (tp_pct / 100))
        
        BOT_STATE["active_trades"][coin] = {
            "price": new_price,
            "target_price": target_price,
            "cost": new_cost,
            "amount": new_amount,
            "highest_price": new_price, 
            "time": time.strftime("%H:%M"),
            "strategy": strategy
        }
        log_message(f"📝 Takip Başlatıldı (Kayıt): {coin} @ {new_price} TL")
        
    save_trades(BOT_STATE["active_trades"])

# --- FLASK ROUTES ---
@app.route('/')
@requires_auth
def index():
    return render_template('index.html', 
                           running=BOT_STATE["running"],
                           logs=list(BOT_STATE["logs"]),
                           market_data=BOT_STATE["market_data"],
                           wallet=BOT_STATE["wallet"],
                           threshold=BOT_STATE["threshold"],
                           sell_threshold=BOT_STATE.get("sell_threshold", -2.0),
                           trade_percent=BOT_STATE.get("trade_percent", 100),
                           take_profit_percent=BOT_STATE.get("take_profit_percent", 5.0),
                           ai_mode=BOT_STATE.get("ai_mode", False),
                           whitelist=BOT_STATE["whitelist"],
                           interval=BOT_STATE["interval"])
@app.route('/api/data')
@requires_auth
def api_data():
    """
    Returns dynamic data for AJAX updates (No Page Refresh)
    """
    with STATE_LOCK:
        payload = {
            "market_data": list(BOT_STATE["market_data"]),
            "wallet": dict(BOT_STATE["wallet"]),
            "active_trades": dict(BOT_STATE["active_trades"]),
            "trade_history": list(BOT_STATE["trade_history"]),
            "recommendations": list(BOT_STATE.get("recommendations", [])),
            "blacklist": list(BOT_STATE["blacklist"]),
            "logs": list(BOT_STATE["logs"]),
            "running": BOT_STATE["running"],
            "fomo_mode": BOT_STATE.get("fomo_mode", False)
        }
    return jsonify(payload)

@app.route('/api/delete_trade/<coin>', methods=['POST'])
@requires_auth
def delete_trade(coin):
    if coin in BOT_STATE["active_trades"]:
        with STATE_LOCK:
            del BOT_STATE["active_trades"][coin]
            save_trades(BOT_STATE["active_trades"])
        log_message(f"⚠️ Manuel Silme: {coin} açık pozisyonlardan silindi.")
    return jsonify({"status": "ok"})

@app.route('/api/clear_history', methods=['POST'])
@requires_auth
def clear_history():
    try:
        with STATE_LOCK:
            BOT_STATE["trade_history"] = []
            save_history([])
        log_message("🧹 Sistem Sıfırlandı: Tüm işlem geçmişi silindi.")
        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/api/delete_history/<int:index>', methods=['POST'])
@requires_auth
def delete_history(index):
    try:
        with STATE_LOCK:
            if index < 0 or index >= len(BOT_STATE["trade_history"]):
                return jsonify({"status": "error", "message": "Kayit bulunamadi"}), 404
            deleted = BOT_STATE["trade_history"].pop(index)
            save_history(BOT_STATE["trade_history"])
        log_message(f"History entry deleted: {deleted.get('coin', 'UNKNOWN')}")
        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/api/manual_sell/<coin>', methods=['POST'])
@requires_auth
def manual_sell(coin):
    coin = coin.upper()
    # Instantiate client locally for the route
    paribu = ParibuClient()
    try:
        if BOT_STATE["wallet"] and coin in BOT_STATE["wallet"]:
            c_bal = float(BOT_STATE["wallet"][coin].get("available", 0))
            if c_bal > 0:
                paribu_pair = f"{coin}_TL"
                log_message(f"🚨 MANUEL SATIŞ EMRİ: {coin} Tutar: {c_bal}")
                resp = paribu.place_order(paribu_pair, c_bal, "sell")
                
                # Check response (Handle multiple Paribu success formats)
                is_success = False
                if isinstance(resp, dict):
                    if resp.get("status") in ["ok", "close"]: is_success = True
                    elif "id" in resp or "data" in resp or "uid" in resp: is_success = True
                
                if is_success:
                    log_message(f"✅ Manuel Satış Başarılı: {resp}")
                    
                    # RECORD TO HISTORY
                    try:
                        entry_price = 0
                        buy_cost = 0
                        trade_data = BOT_STATE["active_trades"].get(coin)
                        if trade_data:
                            entry_price = float(trade_data.get("price", 0))
                            buy_cost = float(trade_data.get("cost", 0))
                        
                        # Get price from response (market order averages)
                        sell_price = 0
                        if isinstance(resp, dict):
                            sell_price = float(resp.get("price") or resp.get("average") or 0)
                        
                        sell_total = c_bal * sell_price
                        net_pnl, comm = 0, 0
                        if buy_cost > 0 and sell_total > 1:
                            net_pnl, comm = calculate_pnl(sell_total, buy_cost)

                        trade_record = {
                            "coin": coin,
                            "action": "MANUAL_SELL",
                            "amount": c_bal,
                            "buy_price": entry_price,
                            "sell_price": sell_price,
                            "cost": buy_cost,
                            "revenue": sell_total,
                            "net_pnl": net_pnl,
                            "time": time.strftime("%Y-%m-%d %H:%M:%S")
                        }
                        BOT_STATE["trade_history"].append(trade_record)
                        save_history(BOT_STATE["trade_history"])
                    except Exception as e:
                        log_message(f"Manual History Record Err: {e}")

                    # Remove from active trades if exists
                    if coin in BOT_STATE["active_trades"]:
                        del BOT_STATE["active_trades"][coin]
                        save_trades(BOT_STATE["active_trades"])
                    return jsonify({"status": "ok", "message": "Emir İletildi"})
                else:
                    log_message(f"❌ Manuel Satış Hatası: {resp}")
                    return jsonify({"status": "error", "message": str(resp)})
            else:
                return jsonify({"status": "error", "message": "Bakiye Yetersiz"})
        else:
            return jsonify({"status": "error", "message": "Cüzdanda bulunamadı"})
    except Exception as e:
        log_message(f"Manuel Satış Exception: {e}")
        return jsonify({"status": "error", "message": str(e)})

@app.route('/api/update_cost/<coin>', methods=['POST'])
@requires_auth
def update_cost(coin):
    """
    Manually update the cost/entry price of a trade.
    Useful if the bot loses memory and resets price to current market price.
    """
    coin = coin.upper()
    try:
        data = request.json
        new_price = float(data.get("price", 0))
        
        if new_price <= 0:
            return jsonify({"status": "error", "message": "Geçersiz Fiyat"})
            
        if coin in BOT_STATE["active_trades"]:
            trade = BOT_STATE["active_trades"][coin]
            
            # Update Price
            trade["price"] = new_price
            
            # Update Cost (Total invested) based on amount
            amount = float(trade.get("amount", 0))
            if amount > 0:
                trade["cost"] = amount * new_price
            
            # Recalculate Target based on NEW Entry Price
            tp_pct = float(BOT_STATE.get("take_profit_percent", 5.0))
            trade["target_price"] = new_price * (1 + (tp_pct / 100))
            
            save_trades(BOT_STATE["active_trades"])
            log_message(f"✏️ MANUEL DÜZELTME: {coin} Maliyet: {new_price} TL olarak güncellendi.")
            
            return jsonify({"status": "ok", "message": "Maliyet Güncellendi"})
        else:
            return jsonify({"status": "error", "message": "Coin takipte değil."})
            
    except Exception as e:
        log_message(f"Cost Update Error: {e}")
        return jsonify({"status": "error", "message": str(e)})
    except Exception as e:
        log_message(f"Manuel Satış Exception: {e}")
        return jsonify({"status": "error", "message": str(e)})

@app.route('/api/toggle_blacklist/<coin>', methods=['POST'])
@requires_auth
def toggle_blacklist(coin):
    coin = coin.upper()
    if coin in BOT_STATE["blacklist"]:
        BOT_STATE["blacklist"].remove(coin)
    else:
        BOT_STATE["blacklist"].append(coin)
        # If we blacklist a coin, remove it from active trades so it disappears from UI
        if coin in BOT_STATE["active_trades"]:
            del BOT_STATE["active_trades"][coin]
            save_trades(BOT_STATE["active_trades"])
        
    save_blacklist(BOT_STATE["blacklist"]) # PERSIST CHANGE
    return jsonify({"status": "ok", "blacklisted": coin in BOT_STATE["blacklist"]})

@app.route('/api/toggle_fomo', methods=['POST'])
@requires_auth
def toggle_fomo():
    BOT_STATE["fomo_mode"] = not BOT_STATE.get("fomo_mode", False)
    return jsonify({"status": "ok", "fomo_mode": BOT_STATE["fomo_mode"]})

@app.route('/update_settings', methods=['POST'])
@requires_auth
def update_settings():
    BOT_STATE["interval"] = int(request.form.get('interval', 5))
    BOT_STATE["threshold"] = float(request.form.get('threshold', 0.5))
    BOT_STATE["sell_threshold"] = float(request.form.get('sell_threshold', -2.0))
    BOT_STATE["trade_percent"] = float(request.form.get('trade_percent', 100))
    BOT_STATE["take_profit_percent"] = float(request.form.get('take_profit_percent', 5.0))
    BOT_STATE["whitelist"] = request.form.get('whitelist', '').strip().upper()
    BOT_STATE["ai_mode"] = True 
    log_message(f"AI Guncellendi: Al=%{BOT_STATE['threshold']} Sat=%{BOT_STATE['sell_threshold']} Kar=%{BOT_STATE['take_profit_percent']}")
    
    # 1. Update Targets for EXISTING Trades
    new_tp_pct = BOT_STATE["take_profit_percent"]
    for coin, trade in BOT_STATE["active_trades"].items():
        entry = float(trade.get("price", 0))
        if entry > 0:
            new_target = entry * (1 + (new_tp_pct / 100))
            trade["target_price"] = new_target
            
    save_trades(BOT_STATE["active_trades"])

    # 2. Safety: Stop bot to allow user to review before starting
    if BOT_STATE["running"]:
        BOT_STATE["running"] = False
        log_message("⚠️ Ayarlar değiştiği için güvenlik amacıyla sistem DURAKLATILDI. Lütfen tekrar başlatın.")
    else:
        log_message("✅ Ayarlar kaydedildi. Başlatmak için butona basın.")
        # Start thread if not alive? No, thread is always alive loop checks flag.
    return redirect(url_for('index'))

@app.route('/toggle_bot', methods=['POST'])
@requires_auth
def toggle_bot():
    """ Toggles the running state of the bot """
    current = BOT_STATE["running"]
    BOT_STATE["running"] = not current
    status = "BAŞLATILDI" if BOT_STATE["running"] else "DURDURULDU"
    log_message(f"⚠️ Sistem kullanıcı tarafından {status}")
    return jsonify({"running": BOT_STATE["running"], "status": status})

@app.route('/debug')
@requires_auth
def debug_page():
    """
    Diagnostic page to test connectivity.
    """
    results = []
    results.append("<h3>Connectivity Test</h3>")
    
    # 1. Test Google (Internet)
    try:
        r = requests.get("https://www.google.com", timeout=5)
        results.append(f"<p style='color:green'>✅ Internet Check (Google): {r.status_code}</p>")
    except Exception as e:
        results.append(f"<p style='color:red'>❌ Internet Check Failed: {e}</p>")

    # 2. Test Paribu Public Ticker
    try:
        url = "https://www.paribu.com/ticker"
        headers = {'User-Agent': 'Mozilla/5.0'}
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code == 200:
             data = r.json()
             sample = list(data.keys())[:3] if data else "Empty"
             results.append(f"<p style='color:green'>✅ Paribu Ticker: {r.status_code} (Sample: {sample})</p>")
        else:
             results.append(f"<p style='color:red'>❌ Paribu Ticker Error: {r.status_code} - {r.text[:100]}</p>")
    except Exception as e:
        results.append(f"<p style='color:red'>❌ Paribu Ticker Exception: {e}</p>")

    # 3. Test Binance
    try:
        r = requests.get("https://api.binance.com/api/v3/ping", timeout=5)
        results.append(f"<p style='color:green'>✅ Binance Ping: {r.status_code}</p>")
    except Exception as e:
        results.append(f"<p style='color:red'>❌ Binance Ping Failed: {e}</p>")

    # 4. Test Wallet (Private API)
    results.append("<h4>Wallet/Auth Test</h4>")
    try:
        # Try importing the client to use its signing logic
        from paribu_client import ParibuClient
        client = ParibuClient()
        
        # Test 1: api.paribu.com (Current Config)
        results.append(f"<p>Testing Configured URL: {client.base_url} ...</p>")
        headers = client._get_headers()
        # Try a few endpoints
        for ep in ["/users/balances", "/balances", "/wallet"]:
            try:
                url = f"{client.base_url}{ep}"
                r = requests.get(url, headers=headers, timeout=5)
                if r.status_code == 200:
                    results.append(f"<p style='color:green'>✅ FOUND Balance at {ep}: {r.text[:50]}...</p>")
                else:
                    results.append(f"<p style='color:orange'>⚠️ {ep} -> {r.status_code}</p>")
            except:
                pass
                
        # Test 2: www.paribu.com/app/v1 (Legacy/Alternate)
        alt_url = "https://www.paribu.com/app/v1"
        results.append(f"<p>Testing Alternate URL: {alt_url} ...</p>")
        # Need new headers since timestamp changes
        headers = client._get_headers() 
        try:
            url = f"{alt_url}/users/balances"
            r = requests.get(url, headers=headers, timeout=5)
            if r.status_code == 200:
                 results.append(f"<p style='color:green'>✅ FOUND Balance at Alternate: {r.text[:50]}...</p>")
            elif r.status_code == 401:
                 results.append(f"<p style='color:red'>❌ Auth Failed (401) at Alternate. Keys might be wrong or Sig invalid.</p>")
            else:
                 results.append(f"<p style='color:orange'>⚠️ Alternate -> {r.status_code}</p>")
        except Exception as e:
            results.append(f"<p style='color:red'>Mean Alternate Error: {e}</p>")

    except Exception as e:
        results.append(f"<p style='color:red'>❌ Wallet Test Exception: {e}</p>")

    return "".join(results)

if __name__ == "__main__":
    # Start Bot Thread
    t = threading.Thread(target=bot_loop, daemon=True)
    t.start()
    
    # Start Flask Server
    print("Starting Web Server on Port 5000...")
    app.run(host='0.0.0.0', port=5000, debug=app.config['DEBUG'])
