import csv
import os
import time
import requests
import pandas as pd
from datetime import datetime
from typing import Dict, List, Optional
from config import Config
from stock_trader import StockTrader


OKX_DELAY_SECONDS = 10


def get_next_aligned_time(bar_type: str) -> datetime:
    now = datetime.now()
    
    if bar_type == "1m":
        next_minute = now.replace(second=0, microsecond=0)
        if now.second >= OKX_DELAY_SECONDS:
            from datetime import timedelta
            next_minute += timedelta(minutes=1)
        target_time = next_minute.replace(second=OKX_DELAY_SECONDS)
    
    elif bar_type == "15m":
        current_minute = now.minute
        minutes_to_add = (15 - (current_minute % 15)) % 15
        if minutes_to_add == 0 and now.second >= OKX_DELAY_SECONDS:
            minutes_to_add = 15
        
        from datetime import timedelta
        target_time = now.replace(second=OKX_DELAY_SECONDS, microsecond=0)
        if minutes_to_add > 0:
            target_time += timedelta(minutes=minutes_to_add)
            target_time = target_time.replace(second=OKX_DELAY_SECONDS, microsecond=0)
    
    else:
        raise ValueError(f"不支持的K线周期: {bar_type}")
    
    return target_time


def wait_for_aligned_time(bar_type: str) -> None:
    target_time = get_next_aligned_time(bar_type)
    now = datetime.now()
    
    if target_time <= now:
        return
    
    wait_seconds = (target_time - now).total_seconds()
    
    if wait_seconds > 0:
        print(f"等待到下一个对齐时间点: {target_time.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"还需等待 {wait_seconds:.1f} 秒...")
        time.sleep(wait_seconds)


class OKXKlineFetcher:
    def __init__(self, config: Config = None):
        self.config = config or Config()
        self.proxies = {
            "http": os.getenv("HTTP_PROXY"),
            "https": os.getenv("HTTPS_PROXY")
        }
    
    def fetch_candles(self, bar: str, remove_last: bool = True) -> Optional[List[List]]:
        params = {
            "instId": self.config.OKX_INST_ID,
            "bar": bar
        }
        
        try:
            response = requests.get(
                self.config.OKX_API_URL,
                params=params,
                timeout=self.config.OKX_TIMEOUT,
                proxies=self.proxies
            )
            response.raise_for_status()
            data = response.json()
            
            if data.get("code") != "0":
                print(f"API请求失败 | code: {data.get('code')}, msg: {data.get('msg')}")
                return None
            
            candle_data = data.get("data", [])
            if not candle_data:
                print("未获取到K线数据")
                return None
            
            if remove_last and len(candle_data) > 1:
                candle_data = candle_data[1:]
                print(f"已移除最后一条可能不完整的数据，剩余 {len(candle_data)} 条")
            
            return candle_data
            
        except requests.exceptions.RequestException as e:
            print(f"网络错误: {str(e)}")
            return None
        except Exception as e:
            print(f"意外错误: {str(e)}")
            return None
    
    def save_to_csv(self, candle_data: List[List], bar: str) -> str:
        headers = ['Time', 'Open', 'High', 'Low', 'Close', 'Volume']
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        file_name = f"{self.config.OKX_INST_ID}_{bar}_{timestamp}.csv"
        file_path = os.path.join(self.config.REALTIME_DATA_PATH, file_name)
        
        with open(file_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(headers)
            
            for row in candle_data:
                writer.writerow(row[:6])
        
        print(f"数据已保存: {file_path}")
        return file_path
    
    def to_dataframe(self, candle_data: List[List]) -> pd.DataFrame:
        rows = []
        for row in candle_data:
            rows.append({
                'Time': int(row[0]),
                'Open': float(row[1]),
                'High': float(row[2]),
                'Low': float(row[3]),
                'Close': float(row[4]),
                'Volume': float(row[5])
            })
        
        df = pd.DataFrame(rows)
        df = df.sort_values('Time').reset_index(drop=True)
        return df


class RealtimeAnalyzer:
    def __init__(self, config: Config = None, bar_type: str = "1m", interval: int = None):
        self.config = config or Config()
        self.config.create_directories()
        
        self.bar_type = bar_type
        if bar_type == "1m":
            self.interval = interval or self.config.REALTIME_INTERVAL_1M
            self.bar = self.config.OKX_BAR_1M
        elif bar_type == "15m":
            self.interval = interval or self.config.REALTIME_INTERVAL_15M
            self.bar = self.config.OKX_BAR_15M
        else:
            raise ValueError(f"不支持的K线周期: {bar_type}，支持 1m 和 15m")
        
        self.trader: Optional[StockTrader] = None
        self.running = False
        self.last_kline_time: Optional[int] = None
        
        self.fetcher = OKXKlineFetcher(self.config)
    
    def initialize_trader(self, model_path: str = None, use_llm: bool = True):
        print("="*60)
        print("初始化 AI Trader...")
        print("="*60)
        
        self.trader = StockTrader(self.config)
        
        model_loaded = False
        if model_path:
            try:
                self.trader.load_trained_model(model_path)
                model_loaded = True
            except Exception as e:
                print(f"警告: 加载指定模型失败: {e}")
                print("将尝试使用默认模型路径，或仅使用LLM分析")
        elif os.path.exists(self.config.BEST_MODEL_PATH):
            try:
                self.trader.load_trained_model(self.config.BEST_MODEL_PATH)
                model_loaded = True
            except Exception as e:
                print(f"警告: 加载默认模型失败: {e}")
        else:
            print("提示: 未找到预训练模型，将仅使用LLM分析和规则分析")
        
        if not model_loaded:
            print("\n建议:")
            print("  1. 如需使用强化学习模型，请先运行: python main.py --mode train")
            print("  2. 当前将使用LLM分析和规则分析进行预测\n")
        
        if use_llm:
            self.trader.initialize_analyzer()
        
        print("AI Trader 初始化完成")
        print("="*60)
    
    def analyze_candles(self, candle_data: List[List], use_llm: bool = True) -> Optional[Dict]:
        if self.trader is None:
            print("错误: Trader未初始化")
            return None
        
        df = self.fetcher.to_dataframe(candle_data)
        
        latest = df.iloc[-1]
        current_kline_time = int(latest['Time'])
        
        if self.last_kline_time is not None and current_kline_time == self.last_kline_time:
            print("K线数据未更新，跳过分析")
            return None
        
        self.last_kline_time = current_kline_time
        
        if self.trader.historical_klines.empty:
            self.trader.load_historical_data(df)
        
        latest_row = df.iloc[-1]
        time_ms = int(latest_row['Time'])
        time_str = datetime.fromtimestamp(time_ms / 1000).strftime('%Y-%m-%d %H:%M:%S')
        
        result = self.trader.predict_single_kline(
            time=time_str,
            open=latest_row['Open'],
            high=latest_row['High'],
            low=latest_row['Low'],
            close=latest_row['Close'],
            volume=latest_row['Volume'],
            use_llm=use_llm
        )
        
        return result
    
    def print_result(self, result: Dict, simulate_trade: bool = False):
        if not result:
            return
        
        print("\n" + "="*60)
        print(f"分析结果 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("="*60)
        
        kline_info = result.get('kline_info', {})
        print(f"\nK线信息:")
        print(f"  时间: {kline_info.get('time', 'N/A')}")
        print(f"  开盘: {kline_info.get('open', 0):.2f}")
        print(f"  最高: {kline_info.get('high', 0):.2f}")
        print(f"  最低: {kline_info.get('low', 0):.2f}")
        print(f"  收盘: {kline_info.get('close', 0):.2f}")
        print(f"  成交量: {kline_info.get('volume', 0):,}")
        
        rl_pred = result.get('rl_prediction')
        if rl_pred:
            print(f"\n强化学习预测:")
            print(f"  推荐操作: {rl_pred['action']}")
            print(f"  Q值: {[f'{q:.4f}' for q in rl_pred['q_values']]}")
        
        llm_analysis = result.get('llm_analysis')
        if llm_analysis:
            print(f"\nLLM分析结果:")
            print(f"  技术分析: {llm_analysis.get('analysis', 'N/A')}")
            print(f"  风险评估: {llm_analysis.get('risk_assessment', 'N/A')}")
            print(f"  推荐操作: {llm_analysis.get('recommended_action', 'N/A')}")
            print(f"  置信度: {llm_analysis.get('confidence', 0):.2f}")
        
        final_decision = result.get('final_decision')
        if final_decision:
            print(f"\n{'='*60}")
            print(f"最终决策: {final_decision['action']}")
            print(f"{'='*60}")
            
            if 'combination_info' in final_decision:
                print(final_decision['combination_info']['combination_reason'])
            
            if simulate_trade and self.trader:
                close_price = kline_info.get('close', 0)
                if close_price > 0:
                    self.trader.simulate_trade(final_decision['action'], close_price)
        
        print("="*60 + "\n")
    
    def run_once(self, use_llm: bool = True, save_data: bool = True, 
                  simulate_trade: bool = False, use_aligned_time: bool = True):
        if use_aligned_time:
            wait_for_aligned_time(self.bar_type)
        
        print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 开始获取 {self.bar} K线数据...")
        
        candle_data = self.fetcher.fetch_candles(self.bar, remove_last=True)
        if not candle_data:
            print("获取K线数据失败")
            return
        
        print(f"成功获取 {len(candle_data)} 根K线数据")
        
        if save_data:
            self.fetcher.save_to_csv(candle_data, self.bar)
        
        result = self.analyze_candles(candle_data, use_llm)
        if result:
            self.print_result(result, simulate_trade)
        
        return result
    
    def start(self, use_llm: bool = True, save_data: bool = True, 
               simulate_trade: bool = False, use_aligned_time: bool = True):
        print("="*60)
        print(f"实时K线分析器启动")
        print(f"交易对: {self.config.OKX_INST_ID}")
        print(f"K线周期: {self.bar}")
        print(f"时间对齐: {'是 (延后10秒)' if use_aligned_time else '否'}")
        print(f"刷新间隔: {self.interval} 秒")
        print(f"使用LLM: {'是' if use_llm else '否'}")
        print(f"保存数据: {'是' if save_data else '否'}")
        print(f"模拟交易: {'是' if simulate_trade else '否'}")
        print("="*60)
        print("按 Ctrl+C 停止\n")
        
        self.running = True
        
        while self.running:
            try:
                self.run_once(use_llm, save_data, simulate_trade, use_aligned_time)
                
                print(f"等待 {self.interval} 秒后进行下次分析...")
                time.sleep(self.interval)
                
            except KeyboardInterrupt:
                print("\n\n收到停止信号，正在退出...")
                self.running = False
            except Exception as e:
                print(f"运行时错误: {e}")
                print(f"等待 {self.interval} 秒后重试...")
                time.sleep(self.interval)
        
        print("实时K线分析器已停止")
