import requests
import csv
import os
from datetime import datetime
from typing import List


def parse_okx_candle_row(row: List, inst_type: str) -> List:
    """
    解析OKX K线数据行，根据交易类型提取正确的Volume和Amount
    
    OKX返回格式: [ts, o, h, l, c, vol, volCcy, volCcyQuote, confirm]
    - SPOT(币币/币币杠杆): Volume=vol(基础货币数量), Amount=volCcyQuote(计价货币成交额)
    - SWAP(衍生品合约): Volume=volCcy(币的数量, 因为vol是合约张数), Amount=volCcyQuote(计价货币成交额)
    
    注意：OKX返回的ts是毫秒时间戳，这里会转换为秒数格式
    
    Args:
        row: OKX返回的原始K线数据行
        inst_type: 交易类型，"SPOT" 或 "SWAP"
    
    Returns:
        处理后的数据行: [time(秒数), open, high, low, close, volume, amount]
    """
    ts_ms = row[0]
    ts_s = str(int(int(ts_ms) / 1000))
    o = row[1]
    h = row[2]
    l = row[3]
    c = row[4]
    vol = row[5]
    vol_ccy = row[6] if len(row) > 6 else "0"
    vol_ccy_quote = row[7] if len(row) > 7 else "0"
    
    if inst_type.upper() == "SWAP":
        volume = vol_ccy
    else:
        volume = vol
    
    amount = vol_ccy_quote
    
    return [ts_s, o, h, l, c, volume, amount]


def get_okx_1min_candle_data(inst_id: str = "BTC-USDT", inst_type: str = "SPOT"):
    """
    Fetch BTC-USDT 1-minute candlestick data from OKX API and save to CSV
    Supports proxy via environment variables (HTTP_PROXY, HTTPS_PROXY)
    API Doc: https://www.okx.com/docs-v5/en/#rest-api-market-data-get-candlesticks
    
    Args:
        inst_id: 交易对ID，如 "BTC-USDT" 或 "BTC-USDT-SWAP"
        inst_type: 交易类型，"SPOT" (币币/币币杠杆) 或 "SWAP" (衍生品合约)
    """
    url = "https://www.okx.com/api/v5/market/candles"
    params = {
        "instId": inst_id,
        "bar": "1m"
    }

    proxies = {
        "http": os.getenv("HTTP_PROXY"),
        "https": os.getenv("HTTPS_PROXY")
    }

    try:
        response = requests.get(url, params=params, timeout=20, proxies=proxies)
        response.raise_for_status()
        data = response.json()

        if data.get("code") != "0":
            print(f"API request failed | code: {data.get('code')}, msg: {data.get('msg')}")
            return

        candle_data = data.get("data", [])
        if not candle_data:
            print("No candlestick data received.")
            return

        headers = ['Time', 'Open', 'High', 'Low', 'Close', 'Volume', 'Amount']

        file_name = f"{inst_id}_1m_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

        with open(file_name, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(headers)

            for row in candle_data:
                parsed_row = parse_okx_candle_row(row, inst_type)
                writer.writerow(parsed_row)

        print(f"✅ Data saved successfully: {file_name}")
        print(f"📊 Total records saved: {len(candle_data)}")
        print(f"💱 Instrument Type: {inst_type}")

    except requests.exceptions.RequestException as e:
        print(f"❌ Network error: {str(e)}")
    except Exception as e:
        print(f"❌ Unexpected error: {str(e)}")

if __name__ == "__main__":
    get_okx_1min_candle_data()
