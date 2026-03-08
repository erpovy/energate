import time

class TradingStrategy:
    def __init__(self, paribu_client, binance_client):
        self.paribu = paribu_client
        self.binance = binance_client
        self.binance = binance_client
        self.rsi_period = 14
        from tracking import tracker
        self.tracker = tracker
        # History to calculate momentum: {'BTC': [price_t-2, price_t-1, price_t0]}
        self.price_history = {} # For Binance Momentum
        self.p_history = {} # For Paribu Momentum (FOMO)
        self.MAX_HISTORY = 50 # Keep ~2 hours of data points

    # --- TECHNICAL INDICATORS (Pure Python) ---
    def calculate_rsi(self, prices, period=14):
        if len(prices) < period + 1: return 50
        
        gains = []
        losses = []
        for i in range(1, len(prices)):
            delta = prices[i] - prices[i-1]
            if delta > 0:
                gains.append(delta)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(delta))
        
        # Simple Average roughly match SMA RSI
        avg_gain = sum(gains[-period:]) / period
        avg_loss = sum(losses[-period:]) / period
        
        if avg_loss == 0: return 100
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        return rsi

    def calculate_macd(self, prices, fast=12, slow=26, signal=9):
        # Very simplified EMA (for speed) purely on recent window
        # Real MACD needs pandas for accuracy, this is an approximation for trend
        if len(prices) < slow: return 0, 0
        
        # Simple Moving Averages for now to avoid complexity without numpy
        fast_ma = sum(prices[-fast:]) / fast
        slow_ma = sum(prices[-slow:]) / slow
        macd_line = fast_ma - slow_ma
        return macd_line

    def calculate_atr(self, candles, period=14):
        if not candles or len(candles) < period + 1: return 0.0
        
        tr_list = []
        for i in range(1, len(candles)):
            current = candles[i]
            prev = candles[i-1]
            
            # TR = Max(H-L, |H-Cp|, |L-Cp|)
            hl = current['h'] - current['l']
            h_cp = abs(current['h'] - prev['c'])
            l_cp = abs(current['l'] - prev['c'])
            
            tr = max(hl, h_cp, l_cp)
            tr_list.append(tr)
            
        if not tr_list: return 0.0
        
        # Simple Average calc for ATR
        atr = sum(tr_list[-period:]) / period
        return atr

    def get_atr_stop(self, coin, price):
        """
        Returns dynamic stop percentage based on ATR.
        """
        symbol = f"{coin}USDT"
        candles = self.binance.get_klines(symbol, "15m", 20)
        if not candles: return 3.0 # Fallback
        
        atr = self.calculate_atr(candles)
        if atr == 0: return 3.0
        
        # Stop Distance = 2 * ATR
        # Convert to percentage
        stop_dist = (atr * 2.0)
        stop_pct = (stop_dist / price) * 100
        
        # Safety Clamps (Min 2%, Max 6%)
        if stop_pct < 2.0: stop_pct = 2.0
        if stop_pct > 6.0: stop_pct = 6.0
        
        return stop_pct

    def calculate_sma(self, prices, period=50):
        if len(prices) < period: return 0
        return sum(prices[-period:]) / period

    def calculate_ema(self, prices, period=200):
        if len(prices) < period: return 0
        
        # Start with SMA
        ema = sum(prices[:period]) / period
        multiplier = 2 / (period + 1)
        
        for price in prices[period:]:
            ema = (price - ema) * multiplier + ema
            
        return ema

    def calculate_bollinger_bands(self, prices, period=20, std_dev=2):
        if len(prices) < period: return 0, 0, 0
        
        sma = self.calculate_sma(prices, period)
        
        # Calculate Standard Deviation
        variance = sum([((x - sma) ** 2) for x in prices[-period:]]) / period
        std = variance ** 0.5
        
        upper = sma + (std * std_dev)
        lower = sma - (std * std_dev)
        
        return upper, lower, sma

    def analyze_technical(self, coin, b_price):
        """
        Fetches candles and performs TA.
        Returns: { "signal": "BUY/SELL/NEUTRAL", "rsi": 50, "desc": "RSI Oversold" }
        """
        symbol = f"{coin}USDT"
        pk_data = self.binance.get_klines(symbol, "15m", 50)
        
        if not pk_data or len(pk_data) < 30:
            return {"signal": "NEUTRAL", "rsi": 50, "desc": "Yetersiz Veri", "score": 0, "confidence": 0}
            
        # Extract Closes for RSI/MACD
        pk = [k['c'] for k in pk_data]
        # Extract Volumes
        vols = [k['v'] for k in pk_data]
        
        rsi = self.calculate_rsi(pk)
        macd = self.calculate_macd(pk)
        
        # LOGIC
        signal = "DURGUN"
        desc = []
        score = 0
        weights = self.tracker.get_weights()
        triggers = {} # To track which signal contributed most
        
        # Volume Check (Pro Layer)
        # Compare last volume with 20-period Moving Average
        if len(vols) >= 20:
            avg_vol = sum(vols[-21:-1]) / 20 # Previous 20 candles
            curr_vol = vols[-1]
            
            if avg_vol > 0:
                if curr_vol > (avg_vol * 1.5):
                    w = weights.get("VOLUME", 1.0)
                    score += 1 * w
                    triggers["VOLUME"] = triggers.get("VOLUME", 0) + (1 * w)
                    desc.append("Hacimli Yükseliş 📊")
                elif curr_vol < (avg_vol * 0.5):
                    score -= 1 # Penalize weak moves
                    desc.append("Hacimsiz (Zayıf)")
        
        # RSI Check (Adaptive)
        w_rsi = weights.get("RSI", 1.0)
        # Entry thresholds change based on trend
        rsi_bottom = 30
        rsi_mid = 40
        
        # If we are in uptrend (score starts positive or ema_ok will be checked later), increase floor
        # Wait, ema_ok is checked later, but we can check it here if we pass trend info
        # For now, let's use the standard RSI logic but make it more sensitive
        if rsi < 30:
            score += 2 * w_rsi
            triggers["RSI"] = triggers.get("RSI", 0) + (2 * w_rsi)
            desc.append(f"RSI Dipte ({int(rsi)})")
        elif rsi < 45: # Increased from 40 for more sensitivity
            score += 1 * w_rsi
            triggers["RSI"] = triggers.get("RSI", 0) + (1 * w_rsi)
            desc.append(f"RSI Ucuz ({int(rsi)})")
        elif rsi > 75: # Increased from 70
            score -= 2 * w_rsi
            desc.append(f"RSI Tepede ({int(rsi)})")
        elif rsi > 65: # Increased from 60
            score -= 1 * w_rsi
        
        # MACD Check (NEW)
        w_macd = weights.get("MACD", 1.0)
        if macd > 0:
            score += 1 * w_macd
            triggers["MACD"] = triggers.get("MACD", 0) + (1 * w_macd)
            desc.append("MACD Pozitif 📈")
        elif macd < 0:
            score -= 1 * w_macd
            desc.append("MACD Negatif 📉")
        
        # Momentum Check (Short term)
        last_price = pk[-1]
        prev_price = pk[-4] # 1 hour ago
        change = ((last_price - prev_price) / prev_price) * 100
        
        if change > 1.0:
            score += 1
            desc.append("Yükseliş Trendi")
        elif change < -1.0:
            score -= 1
            desc.append("Düşüş Trendi")

        # Confidence Calculation (0-100)
        # Base confidence from score
        confidence = 50
        if score >= 2: confidence = 90
        elif score == 1: confidence = 70
        elif score == -1: confidence = 30
        elif score <= -2: confidence = 10
        
        # Adjust based on RSI Extremes
        if rsi < 25: confidence += 5
        if rsi > 75: confidence -= 5
        
        # Result
        if score >= 2:
            signal = "GÜÇLÜ AL"
        elif score == 1:
            signal = "AL"
        elif score <= -2:
            signal = "GÜÇLÜ SAT"
        elif score == -1:
            signal = "SAT"
            
        # Determine Trigger
        best_trigger = "MANUAL"
        if triggers:
            best_trigger = max(triggers, key=triggers.get)
            
        final_desc = ", ".join(desc) if desc else "Yatay Seyir"
        return {"signal": signal, "rsi": rsi, "macd_line": macd, "desc": final_desc, "score": score, "confidence": confidence, "ema_ok": True, "breakout": False, "trigger": best_trigger}

    def check_opportunity(self, coin, b_price, p_price, threshold=1.0, sell_threshold=-2.0, fomo_enabled=False):
        t_now = time.time()

        # 1. Update History (Binance)
        if coin not in self.price_history: self.price_history[coin] = []
        history = self.price_history[coin]
        history.append({'t': t_now, 'price': b_price})
        if len(history) > self.MAX_HISTORY: history.pop(0)

        # 1b. Update History (Paribu) - FOR FOMO
        if coin not in self.p_history: self.p_history[coin] = []
        p_hist = self.p_history[coin]
        p_hist.append({'t': t_now, 'price': float(p_price)})
        if len(p_hist) > self.MAX_HISTORY: p_hist.pop(0)

        response = {
            "signal": None,
            "momentum": 0.0,
            "sentiment": "DURGUN",
            "ta_info": {"signal": "DURGUN", "rsi": 50, "desc": "", "score": 0} # Default
        }

        # Need at least 2 data points for momentum
        if len(history) < 2: return response

        # 2. Calculate Momentum (Binance)
        oldest = history[0]
        mom = ((b_price - oldest['price']) / oldest['price']) * 100
        response["momentum"] = mom

        # 2b. Calculate Momentum (Paribu)
        p_mom = 0.0
        if len(p_hist) > 10: # Need some history
             p_old = p_hist[0] # Approx 15-20 mins ago
             p_mom = ((float(p_price) - p_old['price']) / p_old['price']) * 100

        # 3. FAST PATH: Only run expensive TA if momentum is interesting
        # If price hasn't moved 0.5% in either direction, don't waste time fetching candles
        if abs(mom) < 0.5 and abs(p_mom) < 2.0: # Check Paribu too
            return response
            
        # 4. Deep Analysis (TA) - Only for movers
        ta = self.analyze_technical(coin, b_price)
        
        # --- TREND FILTER (EMA 200) ---
        # Fetch long history for EMA 200
        # We need at least 200 candles. 1h timeframe is good for major trend.
        try:
            # Optimize: Check 4h trend for 'Big Picture'
            # If we are effectively day trading, 1h EMA 200 is solid support/resistance
            klines_1h = self.binance.get_klines(f"{coin}USDT", "1h", 210)
            if klines_1h and len(klines_1h) >= 200:
                closes_1h = [k['c'] for k in klines_1h]
                ema_200 = self.calculate_ema(closes_1h, 200)
                current_1h = closes_1h[-1]
                
                if current_1h < ema_200:
                    # DOWNTREND DETECTED
                    ta["ema_ok"] = False
                    ta["desc"] += " | ⚠️ Trend Düşüş (EMA 200 Altı)"
                    # Reduce Score significantly to prevent buys
                    w_ema = weights.get("EMA_TREND", 1.0)
                    ta["score"] -= 5 * w_ema
                    ta["confidence"] = 5
        except Exception as e:
            # print(f"EMA Check Error: {e}")
            pass

        # --- BOLLINGER BREAKOUT STRATEGY ---
        try:
             # Use 15m candles for entry
             klines_15m = self.binance.get_klines(f"{coin}USDT", "15m", 30)
             if klines_15m and len(klines_15m) >= 20:
                 closes_15m = [k['c'] for k in klines_15m]
                 vols_15m = [k['v'] for k in klines_15m]
                 
                 upper, lower, sma = self.calculate_bollinger_bands(closes_15m, 20, 2)
                 
                 # 1. SQUEEZE DETECTED? (Bandwidth < 5%)
                 bandwidth = ((upper - lower) / sma) * 100
                 
                 current_price = closes_15m[-1]
                 
                 # 2. BREAKOUT DETECTED?
                 # Price breaks Upper Band AND Volume Spike
                 if current_price > upper:
                      # Vol check
                      avg_vol = sum(vols_15m[-21:-1]) / 20
                      curr_vol = vols_15m[-1]
                      
                      if curr_vol > (avg_vol * 1.5): # 50% more volume
                           if bandwidth < 10.0: # Breakout from tight range is better
                               ta["breakout"] = True
                               ta["score"] += 5 * weights.get("BOLLINGER", 1.0) # HUGE SIGNAL
                               ta["desc"] += f" | 🚀 BOLLINGER KIRILIMI (Hacim: x{curr_vol/avg_vol:.1f})"
                               ta["trigger"] = "BOLLINGER"
        except Exception as e:
             # print(f"Bollinger Check Error: {e}")
             pass
        
        # --- FOMO OVERRIDE ---
        is_fomo = False
        if fomo_enabled and p_mom > 2.0:
            # Paribu is PUMPING (>2% in short time)
            # Override RSI penalty (e.g. if Score is -1 because of RSI 75)
            # Add +4 Score to force Buy
            ta["score"] += 4 
            ta["desc"] += f" | 🚀 FOMO AKTİF (Paribu: %{p_mom:.2f})"
            ta["confidence"] = 95 # MAX CONFIDENCE
            is_fomo = True
        # ---------------------
        
        response["sentiment"] = ta["signal"]
        
        # RE-EVALUATE SIGNAL AFTER STRATEGY UPDATES
        if ta["score"] >= 2:
             ta["signal"] = "GÜÇLÜ AL"
        elif ta["score"] >= 1:
             ta["signal"] = "AL"
        elif ta["score"] <= -2:
             ta["signal"] = "GÜÇLÜ SAT"
             
        response["ta_info"] = ta

        # 5. Combine Signals (Scalping Friendly)
        # We lower the requirements slightly if trend is good
        if ta["breakout"]:
            response["signal"] = {"action": "AL", "reason": f"BREAKOUT: {ta['desc']}"}
        elif ta["score"] >= 1.5 and (mom > 0.3 or is_fomo): # Lowered from 2 and 0.5
             response["signal"] = {"action": "AL", "reason": f"Scalp Entry (Score+Mom): {ta['desc']}"}
        elif ta["score"] >= 1 and mom > threshold: 
             response["signal"] = {"action": "AL", "reason": f"Momentum Play: {ta['desc']}"}
             
        # Reject if EMA Bad (Override everything except extreme FOMO)
        if not ta.get("ema_ok", True) and not is_fomo and not ta.get("breakout", False):
             response["signal"] = None # KILL SIGNAL
             response["sentiment"] = "DÜŞÜŞ TRENDİ"
             response["ta_info"]["desc"] += " (İşlem İptal: Trend Düşüş)"

        if ta["score"] <= -1 and mom < sell_threshold:
             response["signal"] = {"action": "SAT", "reason": f"TA Sell: {ta['desc']}"}

        return response

    def should_take_profit(self, coin, current_price, entry_price, target_percent=5.0):
        """
        SMART EXIT STRATEGY (World Class)
        Decides if we should sell NOW or HOLD for more profit.
        Returns: (bool, str) -> (Should Sell?, Reason)
        """
        # Calculate raw profit
        profit_pct = ((current_price - entry_price) / entry_price) * 100
        
        # 1. Base Case: If we haven't reached target, don't even check
        # For Scalping, we allow tighter exits if price stalls
        if profit_pct < (target_percent * 0.8): # Allow exit at 80% of target if momentum dies
            return False, "Target not reached"

        # 2. Get Momentum & TA
        # We need fresh data for this specific check
        symbol = f"{coin}USDT"
        klines = self.binance.get_klines(symbol, "15m", 20)
        
        if not klines or len(klines) < 15:
            # No data? Take profit to be safe
            return True, f"Veri Yok - Güvenli Çıkış (%{profit_pct:.2f})"

        # Calculate Momentum (Last 3 candles)
        closes = [float(k['c']) for k in klines]
        mom_short = ((closes[-1] - closes[-3]) / closes[-3]) * 100
        
        # Calculate RSI (Quick approx)
        rsi = self.calculate_rsi(closes, 14)

        # 3. DECISION LOGIC
        
        # SCENARIO A: SUPER PUMP (Riding the wave)
        # If momentum is very strong (>1.0% in 30 mins), HOLD even if profit > target
        if mom_short > 1.0 and rsi < 85: # Slightly more aggressive hold
             return False, f"⏳ TRENDİ SÜR: Güçlü Alıcı Var (+%{mom_short:.2f}), RSI {int(rsi)}"

        # SCENARIO B: EXHAUSTION (RSI Divergence or Overbought)
        # If RSI is screaming overbought (>80) and momentum slows down
        if rsi > 80 and mom_short < 0.2:
             return True, f"🔥 ZİRVEDE SAT: RSI Yoruldu ({int(rsi)}) (Smart Exit)"

        # SCENARIO C: TREND BREAK
        # If price starts dropping from recent high (handled by Trailing Stop usually, but here as backup)
        # We assume standard Trailing Stop handles the drop. This function handles the "Don't Sell Yet" part.
        
        # Default: If we are above target and no strong reason to hold -> SELL
        return True, f"✅ Kar Al: Hedef Aşıldı (%{profit_pct:.2f})"
