import requests
import csv
import os
from datetime import datetime

def get_okx_1min_candle_data():
    """
    Fetch BTC-USDT 1-minute candlestick data from OKX API and save to CSV
    Supports proxy via environment variables (HTTP_PROXY, HTTPS_PROXY)
    API Doc: https://www.okx.com/docs-v5/en/#rest-api-market-data-get-candlesticks
    """
    url = "https://www.okx.com/api/v5/market/candles"
    params = {
        "instId": "BTC-USDT",
        "bar": "1m"
    }

    # Get proxy settings from environment variables
    proxies = {
        "http": os.getenv("HTTP_PROXY"),
        "https": os.getenv("HTTPS_PROXY")
    }

    try:
        # Send request with proxy support
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

        # CSV headers as required
        headers = ['Time', 'Open', 'High', 'Low', 'Close', 'Volume']

        # Generate filename with timestamp
        file_name = f"BTC-USDT_1m_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

        with open(file_name, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(headers)

            # Write only first 6 columns: time, open, high, low, close, volume
            for row in candle_data:
                writer.writerow(row[:6])

        print(f"✅ Data saved successfully: {file_name}")
        print(f"📊 Total records saved: {len(candle_data)}")

    except requests.exceptions.RequestException as e:
        print(f"❌ Network error: {str(e)}")
    except Exception as e:
        print(f"❌ Unexpected error: {str(e)}")

if __name__ == "__main__":
    get_okx_1min_candle_data()
