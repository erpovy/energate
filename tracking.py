import json
import os
import time

WEIGHTS_FILE = "adaptive_weights.json"
HISTORY_FILE = "strategy_performance.json"

class PerformanceTracker:
    def __init__(self):
        self.weights = self.load_weights()
        self.history = self.load_history()

    def load_weights(self):
        if os.path.exists(WEIGHTS_FILE):
             try:
                 with open(WEIGHTS_FILE, 'r') as f:
                     return json.load(f)
             except:
                 pass
        # Defaults
        return {
            "RSI": 1.0,
            "MACD": 1.0,
            "BOLLINGER": 1.0,
            "EMA_TREND": 1.0,
            "FOMO": 1.0
        }

    def save_weights(self):
        with open(WEIGHTS_FILE, 'w') as f:
            json.dump(self.weights, f, indent=4)

    def load_history(self):
        if os.path.exists(HISTORY_FILE):
             try:
                 with open(HISTORY_FILE, 'r') as f:
                     return json.load(f)
             except:
                 return []
        return []

    def log_trade(self, coin, strategy, pnl_percent):
        """
        Geri bildirim döngüsü.
        Eğer kar ettiysek (+), strateji puanı artar.
        Zarar ettiysek (-), strateji puanı düşer.
        """
        if not strategy: return
        
        # Kayıt
        record = {
            "time": time.time(),
            "coin": coin,
            "strategy": strategy,
            "pnl": pnl_percent
        }
        self.history.append(record)
        
        # Dosyayı çok şişirmemek için son 100 işlem
        if len(self.history) > 100:
            self.history = self.history[-100:]
            
        with open(HISTORY_FILE, 'w') as f:
             json.dump(self.history, f, indent=4)

        # Ağırlık Güncelleme (Feedback Loop)
        self.update_weight(strategy, pnl_percent)

    def update_weight(self, strategy, pnl):
        if strategy not in self.weights:
            self.weights[strategy] = 1.0
            
        current = self.weights[strategy]
        
        # Basit Reinforcement Learning
        # PnL pozitifse ağırlığı %5 artır, negatifse %5 azalt
        if pnl > 0:
            current *= 1.05
        else:
            current *= 0.95
            
        # Limitler (0.1 ile 5.0 arası)
        current = max(0.1, min(current, 5.0))
        
        self.weights[strategy] = current
        self.save_weights()
        print(f"🧬 SELF-IMPROVEMENT: '{strategy}' ağırlığı güncellendi: {current:.2f} (PnL: {pnl}%)")

    def get_weights(self):
        return self.weights

# Global Instance
tracker = PerformanceTracker()
