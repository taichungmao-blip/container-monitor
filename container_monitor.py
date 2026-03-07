import os
import requests
import pandas as pd
import yfinance as yf
import akshare as ak
import matplotlib.pyplot as plt
from datetime import datetime, timedelta

# 環境變數
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK")
FINMIND_TOKEN = os.getenv("FINMIND_TOKEN")
STOCKS = {"2603": "長榮", "2609": "陽明", "2615": "萬海"}

def get_institutional_data(stock_id):
    url = "https://api.finmindtrade.com/api/v4/data"
    start_date = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    parameter = {
        "dataset": "TaiwanStockInstitutionalInvestorsBuySell",
        "data_id": stock_id,
        "start_date": start_date,
        "token": FINMIND_TOKEN,
    }
    try:
        resp = requests.get(url, params=parameter).json()
        df = pd.DataFrame(resp["data"])
        if df.empty: return "🔴 查無籌碼"
        latest_date = df['date'].max()
        today_df = df[df['date'] == latest_date]
        net_buy_sum = (today_df['buy'].sum() - today_df['sell'].sum()) / 1000
        status_icon = "🟢" if net_buy_sum > 0 else "🔴"
        return f"{status_icon} 法人: {int(net_buy_sum):+} 張"
    except:
        return "⚠️ 籌碼抓取失敗"

def get_ec_futures_data():
    """透過 akshare 抓取集運指數期貨，並轉換格式"""
    try:
        df = ak.futures_zh_daily_sina(symbol="ec0")
        if df.empty: return pd.DataFrame()
        
        df['date'] = pd.to_datetime(df['date'])
        df.set_index('date', inplace=True)
        
        # 抓取最後 120 筆 (約半年交易日) 以配合圖表顯示
        df = df.tail(120).copy()
        # 統一欄位名稱以配合後續運算邏輯
        df.rename(columns={'close': 'Close', 'volume': 'Volume'}, inplace=True)
        return df
    except Exception as e:
        print(f"期貨數據抓取失敗: {e}")
        return pd.DataFrame()

def run_strategy():
    print("正在抓取 集運指數(歐線)期貨 (EC0)...")
    ec_data = get_ec_futures_data()
    
    if ec_data.empty:
        print("集運指數期貨數據抓取失敗，程式終止。")
        return

    last_ec = ec_data['Close'].iloc[-1]
    ma20_ec = ec_data['Close'].rolling(window=20).mean().iloc[-1]
    change_ec = ec_data['Close'].pct_change().iloc[-1] * 100

    msg = f"🚢 **貨櫃三雄監控報表** ({datetime.now().strftime('%Y-%m-%d %H:%M')})\n"
    msg += f"📊 歐線期貨(EC0): {last_ec:.2f} ({change_ec:+.2f}%)\n"
    msg += f"📈 運價趨勢: {'🔥 多頭 (20MA上)' if last_ec > ma20_ec else '❄️ 弱勢 (20MA下)'}\n"
    msg += "---"

    chart_data = {"EC0": ec_data}

    for sid, name in STOCKS.items():
        stock = yf.Ticker(f"{sid}.TW").history(period="6mo")
        if stock.empty: continue
        
        chart_data[sid] = stock
        
        price = stock['Close'].iloc[-1]
        prev_price = stock['Close'].iloc[-2]
        daily_change = ((price - prev_price) / prev_price) * 100
        
        vol_today = stock['Volume'].iloc[-1]
        vol_ma5 = stock['Volume'].rolling(window=5).mean().iloc[-1]
        vol_ratio = vol_today / vol_ma5
        
        ma20_stock = stock['Close'].rolling(window=20).mean().iloc[-1]
        bias_20 = ((price - ma20_stock) / ma20_stock) * 100
        
        chip_info = get_institutional_data(sid)
        is_chip_positive = "🟢" in chip_info

        msg += f"\n📌 **{name} ({sid})**"
        msg += f"\n   報價: {price:.1f} ({daily_change:+.1f}%) | 乖離: {bias_20:+.1f}%"
        msg += f"\n   成交: {int(vol_today/1000):,} 張 (量比: {vol_ratio:.2f}x)"
        msg += f"\n   籌碼: {chip_info}"

        # --- 核心策略判斷 (結合歐線期貨與法人籌碼) ---
        strategy_label = ""
        
        if last_ec > ma20_ec and is_chip_positive:
            if bias_20 > 10:
                strategy_label = "✋ [策略: 運價強勢但個股過熱，不追高]"
            elif vol_ratio > 1.2:
                strategy_label = "🚀 [策略: 運價籌碼雙多 + 量增攻擊]"
            else:
                strategy_label = "🚀 [策略: 運價籌碼雙多]"
        
        elif last_ec < ma20_ec and is_chip_positive:
            if bias_20 < -8:
                strategy_label = "💎 [策略: 嚴重超跌 + 法人抄底]"
            else:
                strategy_label = "💎 [策略: 運價偏弱，法人逆勢抄底]"
                
        elif daily_change > 1.5 and vol_ratio < 0.7:
             strategy_label = "⚠️ [策略: 價漲量縮，動能疑慮]"
        
        else:
            if not is_chip_positive and last_ec < ma20_ec:
                strategy_label = "⏳ [策略: 運價與籌碼雙弱，建議觀望]"
            else:
                strategy_label = "📊 [策略: 區間盤整，暫無明顯訊號]"

        msg += f"\n   💡 {strategy_label}\n"

    print(msg) 

    # === 產生 4 張獨立圖表 ===
    chart_filenames = []
    for key, df in chart_data.items():
        if not df.empty:
            plt.figure(figsize=(6, 4))
            
            close_prices = df['Close']
            label_name = "EC Futures (Freight)" if key == "EC0" else f"Stock {key}"
            
            plt.plot(df.index, close_prices, color='tab:blue', linewidth=1.5)
            
            plt.title(f'6-Month Trend: {label_name}')
            plt.xlabel('Date')
            plt.ylabel('Price/Index')
            plt.grid(True, linestyle='--', alpha=0.7)
            plt.tight_layout()
            
            filename = f"trend_chart_container_{key}.png"
            plt.savefig(filename)
            plt.close()
            chart_filenames.append(filename)

    # === 透過 Discord Webhook 傳送 ===
    if DISCORD_WEBHOOK_URL and chart_filenames:
        payload = {"content": msg}
        files = {}
        file_handles = []
        
        for i, filename in enumerate(chart_filenames):
            f = open(filename, "rb")
            file_handles.append(f)
            files[f"file{i}"] = (filename, f, "image/png")
            
        requests.post(DISCORD_WEBHOOK_URL, data=payload, files=files)
        
        for f in file_handles:
            f.close()

if __name__ == "__main__":
    run_strategy()
