import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, render_template, request, jsonify
from datetime import datetime
from sqlite_store import SQLiteKlineStore, SignalStore
from config import Config
import pandas as pd
import numpy as np

app = Flask(__name__)
config = Config()
kline_store = SQLiteKlineStore(config)
signal_store = SignalStore(config)


def calculate_technical_indicators(df):
    df = df.copy()
    
    df['SMA_5'] = df['Close'].rolling(window=5).mean()
    df['SMA_10'] = df['Close'].rolling(window=10).mean()
    df['SMA_20'] = df['Close'].rolling(window=20).mean()
    df['SMA_60'] = df['Close'].rolling(window=60).mean()
    
    delta = df['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))
    
    ema_12 = df['Close'].ewm(span=12, adjust=False).mean()
    ema_26 = df['Close'].ewm(span=26, adjust=False).mean()
    df['MACD'] = ema_12 - ema_26
    df['MACD_signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
    df['MACD_hist'] = df['MACD'] - df['MACD_signal']
    
    df['BB_upper'] = df['SMA_20'] + 2 * df['Close'].rolling(window=20).std()
    df['BB_lower'] = df['SMA_20'] - 2 * df['Close'].rolling(window=20).std()
    df['BB_middle'] = df['SMA_20']
    
    ema_12 = df['Close'].ewm(span=12, adjust=False).mean()
    ema_26 = df['Close'].ewm(span=26, adjust=False).mean()
    df['EMA_12'] = ema_12
    df['EMA_26'] = ema_26
    
    return df


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/klines')
def get_klines():
    exchange = request.args.get('exchange', 'OKX')
    inst_type = request.args.get('type', 'SPOT')
    symbol = request.args.get('symbol', 'BTC-USDT')
    period = request.args.get('period', '1m')
    start_time = request.args.get('start_time', None)
    end_time = request.args.get('end_time', None)
    
    start_ts = None
    end_ts = None
    
    if start_time:
        try:
            if start_time.isdigit():
                start_ts = int(start_time)
            else:
                start_ts = int(datetime.strptime(start_time, '%Y-%m-%d').timestamp())
        except:
            pass
    
    if end_time:
        try:
            if end_time.isdigit():
                end_ts = int(end_time)
            else:
                end_ts = int(datetime.strptime(end_time, '%Y-%m-%d').timestamp())
        except:
            pass
    
    df = kline_store.load_klines(
        exchange=exchange,
        inst_type=inst_type,
        symbol=symbol,
        bar=period,
        start_time=start_ts,
        end_time=end_ts
    )
    
    if df.empty:
        return jsonify({
            'success': False,
            'message': 'No data found',
            'data': [],
            'signals': [],
            'indicators': {}
        })
    
    df = calculate_technical_indicators(df)
    
    klines_data = []
    for idx, row in df.iterrows():
        klines_data.append({
            'time': int(row['Time']),
            'open': float(row['Open']),
            'high': float(row['High']),
            'low': float(row['Low']),
            'close': float(row['Close']),
            'volume': float(row['Volume'])
        })
    
    signals_df = signal_store.load_signals(
        exchange=exchange,
        inst_type=inst_type,
        symbol=symbol,
        bar=period,
        start_time=start_ts,
        end_time=end_ts
    )
    
    signals_data = []
    if not signals_df.empty:
        for idx, row in signals_df.iterrows():
            action_name = signal_store.INT_TO_ACTION.get(int(row['action']), 'Unknown')
            signals_data.append({
                'time': int(row['kline_time']),
                'action': int(row['action']),
                'action_name': action_name,
                'confidence': float(row['confidence']),
                'remark': row['remark'] if pd.notna(row['remark']) else ''
            })
    
    indicators = {
        'SMA_5': df['SMA_5'].dropna().reset_index(drop=True).to_dict(),
        'SMA_10': df['SMA_10'].dropna().reset_index(drop=True).to_dict(),
        'SMA_20': df['SMA_20'].dropna().reset_index(drop=True).to_dict(),
        'SMA_60': df['SMA_60'].dropna().reset_index(drop=True).to_dict(),
        'EMA_12': df['EMA_12'].dropna().reset_index(drop=True).to_dict(),
        'EMA_26': df['EMA_26'].dropna().reset_index(drop=True).to_dict(),
        'RSI': df['RSI'].dropna().reset_index(drop=True).to_dict(),
        'MACD': df['MACD'].dropna().reset_index(drop=True).to_dict(),
        'MACD_signal': df['MACD_signal'].dropna().reset_index(drop=True).to_dict(),
        'MACD_hist': df['MACD_hist'].dropna().reset_index(drop=True).to_dict(),
        'BB_upper': df['BB_upper'].dropna().reset_index(drop=True).to_dict(),
        'BB_middle': df['BB_middle'].dropna().reset_index(drop=True).to_dict(),
        'BB_lower': df['BB_lower'].dropna().reset_index(drop=True).to_dict()
    }
    
    return jsonify({
        'success': True,
        'data': klines_data,
        'signals': signals_data,
        'indicators': indicators,
        'metadata': {
            'exchange': exchange,
            'type': inst_type,
            'symbol': symbol,
            'period': period,
            'count': len(klines_data)
        }
    })


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
