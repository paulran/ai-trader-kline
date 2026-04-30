import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, render_template, request, jsonify
from datetime import datetime
from sqlite_store import SQLiteKlineStore, SignalStore
from config import Config
import pandas as pd
import numpy as np
import traceback

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
    
    df['EMA_12'] = ema_12
    df['EMA_26'] = ema_26
    
    return df


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/klines')
def get_klines():
    try:
        exchange = request.args.get('exchange', 'OKX')
        inst_type = request.args.get('type', 'SPOT')
        symbol = request.args.get('symbol', 'BTC-USDT')
        period = request.args.get('period', '1m')
        start_time = request.args.get('start_time', None)
        end_time = request.args.get('end_time', None)
        
        print(f"API请求: exchange={exchange}, type={inst_type}, symbol={symbol}, period={period}")
        
        start_ts = None
        end_ts = None
        
        if start_time:
            try:
                if start_time.isdigit():
                    start_ts = int(start_time)
                else:
                    start_ts = int(datetime.strptime(start_time, '%Y-%m-%d').timestamp())
            except Exception as e:
                print(f"开始时间解析错误: {e}")
        
        if end_time:
            try:
                if end_time.isdigit():
                    end_ts = int(end_time)
                else:
                    end_ts = int(datetime.strptime(end_time, '%Y-%m-%d').timestamp())
            except Exception as e:
                print(f"结束时间解析错误: {e}")
        
        df = kline_store.load_klines(
            exchange=exchange,
            inst_type=inst_type,
            symbol=symbol,
            bar=period,
            start_time=start_ts,
            end_time=end_ts
        )
        
        print(f"加载K线数据: {len(df)} 条")
        
        if df.empty:
            print("没有找到K线数据")
            return jsonify({
                'success': False,
                'message': f'No data found for {exchange} {inst_type} {symbol} {period}',
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
        
        print(f"加载信号数据: {len(signals_df)} 条")
        
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
        
        def get_indicator_list(col_name):
            result = []
            for val in df[col_name].values:
                if pd.isna(val):
                    result.append(None)
                else:
                    result.append(float(val))
            return result
        
        indicators = {
            'SMA_5': get_indicator_list('SMA_5'),
            'SMA_10': get_indicator_list('SMA_10'),
            'SMA_20': get_indicator_list('SMA_20'),
            'SMA_60': get_indicator_list('SMA_60'),
            'EMA_12': get_indicator_list('EMA_12'),
            'EMA_26': get_indicator_list('EMA_26'),
            'RSI': get_indicator_list('RSI'),
            'MACD': get_indicator_list('MACD'),
            'MACD_signal': get_indicator_list('MACD_signal'),
            'MACD_hist': get_indicator_list('MACD_hist'),
            'BB_upper': get_indicator_list('BB_upper'),
            'BB_middle': get_indicator_list('BB_middle'),
            'BB_lower': get_indicator_list('BB_lower')
        }
        
        result = {
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
        }
        
        print(f"返回数据: {len(klines_data)} 条K线, {len(signals_data)} 个信号")
        
        return jsonify(result)
        
    except Exception as e:
        print(f"API错误: {e}")
        traceback.print_exc()
        return jsonify({
            'success': False,
            'message': str(e),
            'data': [],
            'signals': [],
            'indicators': {}
        })


if __name__ == '__main__':
    print("启动K线图表服务器...")
    print("访问地址: http://localhost:5000")
    app.run(debug=True, host='0.0.0.0', port=5000)
