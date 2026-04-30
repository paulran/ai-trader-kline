import csv
import os
import time
import requests
import pandas as pd
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from config import Config
from stock_trader import StockTrader
from feishu_notifier import FeishuNotifier, get_notifier
from logger import logger
from sqlite_store import SQLiteKlineStore


OKX_DELAY_SECONDS = 10


def parse_okx_candle_row(row: List, inst_type: str) -> List:
    """
    解析OKX K线数据行，根据交易类型提取正确的Volume和Amount
    
    OKX返回格式: [ts, o, h, l, c, vol, volCcy, volCcyQuote, confirm]
    - SPOT(币币/币币杠杆): Volume=vol(基础货币数量), Amount=volCcyQuote(计价货币成交额)
    - PERP(衍生品合约): Volume=volCcy(币的数量, 因为vol是合约张数), Amount=volCcyQuote(计价货币成交额)
    
    注意：OKX返回的ts是毫秒时间戳，这里会转换为秒数格式
    
    Args:
        row: OKX返回的原始K线数据行
        inst_type: 交易类型，"SPOT" 或 "PERP"
    
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
    
    if inst_type.upper() == "PERP":
        volume = vol_ccy
    else:
        volume = vol
    
    amount = vol_ccy_quote
    
    return [ts_s, o, h, l, c, volume, amount]


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
        logger.info(f"等待到下一个对齐时间点: {target_time.strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info(f"还需等待 {wait_seconds:.1f} 秒...")
        time.sleep(wait_seconds)


class OKXKlineFetcher:
    def __init__(self, config: Config = None):
        self.config = config or Config()
        self.inst_type = self.config.OKX_INST_TYPE
        self.proxies = {
            "http": os.getenv("HTTP_PROXY"),
            "https": os.getenv("HTTPS_PROXY")
        }
        self.sqlite_store = SQLiteKlineStore(self.config)
        self.exchange = self.config.EXCHANGE
    
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
                logger.error(f"API请求失败 | code: {data.get('code')}, msg: {data.get('msg')}")
                return None
            
            candle_data = data.get("data", [])
            if not candle_data:
                logger.warning("未获取到K线数据")
                return None
            
            if remove_last and len(candle_data) > 1:
                candle_data = candle_data[1:]
                logger.info(f"已移除最后一条可能不完整的数据，剩余 {len(candle_data)} 条")
            
            return candle_data
            
        except requests.exceptions.RequestException as e:
            logger.error(f"网络错误: {str(e)}")
            return None
        except Exception as e:
            logger.error(f"意外错误: {str(e)}")
            return None
    
    def save_to_csv(self, candle_data: List[List], bar: str) -> str:
        headers = ['Time', 'Open', 'High', 'Low', 'Close', 'Volume', 'Amount']
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        file_name = f"{self.config.OKX_INST_ID}_{bar}_{timestamp}.csv"
        file_path = os.path.join(self.config.DATA_PATH, file_name)
        
        with open(file_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(headers)
            
            for row in candle_data:
                parsed_row = parse_okx_candle_row(row, self.inst_type)
                writer.writerow(parsed_row)
        
        logger.info(f"数据已保存到CSV: {file_path}")
        return file_path
    
    def save_to_sqlite(self, candle_data: List[List], bar: str) -> int:
        klines = []
        for row in candle_data:
            parsed_row = parse_okx_candle_row(row, self.inst_type)
            time = int(parsed_row[0])
            open_price = float(parsed_row[1])
            high = float(parsed_row[2])
            low = float(parsed_row[3])
            close = float(parsed_row[4])
            volume = float(parsed_row[5])
            amount = float(parsed_row[6])
            klines.append((time, open_price, high, low, close, volume, amount))
        
        count = self.sqlite_store.insert_klines_batch(
            exchange=self.exchange,
            inst_type=self.inst_type,
            symbol=self.config.OKX_INST_ID,
            bar=bar,
            klines=klines
        )
        
        logger.info(f"数据已保存到SQLite: {count} 条记录")
        return count
    
    def to_dataframe(self, candle_data: List[List]) -> pd.DataFrame:
        rows = []
        for row in candle_data:
            parsed_row = parse_okx_candle_row(row, self.inst_type)
            rows.append({
                'Time': int(parsed_row[0]),
                'Open': float(parsed_row[1]),
                'High': float(parsed_row[2]),
                'Low': float(parsed_row[3]),
                'Close': float(parsed_row[4]),
                'Volume': float(parsed_row[5]),
                'Amount': float(parsed_row[6])
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
        self.last_final_decision: Optional[str] = None
        self.feishu_notifier: Optional[FeishuNotifier] = None
        
        self.fetcher = OKXKlineFetcher(self.config)
        self._init_feishu_notifier()
    
    def _init_feishu_notifier(self):
        if self.feishu_notifier is None:
            self.feishu_notifier = get_notifier()
    
    def _should_send_notification(self, current_decision: str) -> bool:
        if self.last_final_decision is None:
            return False
        
        if self.last_final_decision == current_decision:
            return False
        
        if current_decision == "Buy":
            return self.last_final_decision in ["Hold", "Sell"]
        elif current_decision == "Sell":
            return self.last_final_decision in ["Hold", "Buy"]
        
        return False
    
    def _format_result_for_feishu(self, result: Dict) -> str:
        lines = []
        
        lines.append("【交易信号 - 决策变化通知】")
        lines.append("-" * 40)
        
        kline_info = result.get('kline_info', {})
        if kline_info:
            lines.append(f"时间: {kline_info.get('time', 'N/A')}")
            lines.append(f"交易对: {self.config.OKX_INST_ID}")
            lines.append(f"交易类型: {self.config.OKX_INST_TYPE}")
            lines.append(f"K线周期: {self.bar}")
            lines.append(f"开盘: {kline_info.get('open', 0):.2f}")
            lines.append(f"最高: {kline_info.get('high', 0):.2f}")
            lines.append(f"最低: {kline_info.get('low', 0):.2f}")
            lines.append(f"收盘: {kline_info.get('close', 0):.2f}")
            lines.append(f"成交量: {kline_info.get('volume', 0):,}")
            amount = kline_info.get('amount')
            if amount is not None:
                lines.append(f"成交额: {amount:,.2f}")
        
        lines.append("-" * 40)
        
        rl_pred = result.get('rl_prediction')
        if rl_pred:
            lines.append(f"强化学习推荐: {rl_pred.get('action', 'N/A')}")
            q_values = rl_pred.get('q_values', [])
            if q_values:
                lines.append(f"  Q值: {[f'{q:.4f}' for q in q_values]}")
        
        llm_analysis = result.get('llm_analysis')
        if llm_analysis:
            lines.append(f"LLM推荐: {llm_analysis.get('recommended_action', 'N/A')}")
            lines.append(f"  置信度: {llm_analysis.get('confidence', 0):.2f}")
            analysis = llm_analysis.get('analysis', '')
            if analysis and len(analysis) > 100:
                analysis = analysis[:100] + "..."
            if analysis:
                lines.append(f"  分析: {analysis}")
        
        lines.append("-" * 40)
        
        final_decision = result.get('final_decision', {})
        if final_decision:
            action = final_decision.get('action', 'N/A')
            lines.append(f"【最终决策】: {action}")
            lines.append(f"前一次决策: {self.last_final_decision or '无'}")
            
            combination_info = final_decision.get('combination_info', {})
            if combination_info:
                combination_reason = combination_info.get('combination_reason', '')
                if combination_reason:
                    lines.append(f"决策原因: {combination_reason}")
        
        lines.append("-" * 40)
        lines.append(f"通知时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        return "\n".join(lines)
    
    def _send_feishu_notification(self, result: Dict) -> bool:
        if self.feishu_notifier is None:
            return False
        
        if not self.feishu_notifier.enabled:
            return False
        
        try:
            message = self._format_result_for_feishu(result)
            send_result = self.feishu_notifier.send(message)
            
            if send_result.get('success'):
                logger.info("飞书通知发送成功")
                return True
            else:
                logger.error(f"飞书通知发送失败: {send_result.get('error', '未知错误')}")
                return False
                
        except Exception as e:
            logger.error(f"发送飞书通知时发生错误: {str(e)}")
            return False
    
    def initialize_trader(self, model_path: str = None, use_llm: bool = True):
        logger.info("="*60)
        logger.info("初始化 AI Trader...")
        logger.info("="*60)
        
        self.trader = StockTrader(self.config)
        
        model_loaded = False
        if model_path:
            try:
                self.trader.load_trained_model(model_path)
                model_loaded = True
            except Exception as e:
                logger.warning(f"警告: 加载指定模型失败: {e}")
                logger.warning("将尝试使用默认模型路径，或仅使用LLM分析")
        elif os.path.exists(self.config.BEST_MODEL_PATH):
            try:
                self.trader.load_trained_model(self.config.BEST_MODEL_PATH)
                model_loaded = True
            except Exception as e:
                logger.warning(f"警告: 加载默认模型失败: {e}")
        else:
            logger.info("提示: 未找到预训练模型，将仅使用LLM分析和规则分析")
        
        if not model_loaded:
            logger.info("\n建议:")
            logger.info("  1. 如需使用强化学习模型，请先运行: python main.py --mode train")
            logger.info("  2. 当前将使用LLM分析和规则分析进行预测\n")
        
        if use_llm:
            self.trader.initialize_analyzer()
        
        logger.info("AI Trader 初始化完成")
        logger.info("="*60)
    
    def analyze_candles(self, candle_data: List[List], use_llm: bool = True) -> Optional[Dict]:
        if self.trader is None:
            logger.error("错误: Trader未初始化")
            return None
        
        df = self.fetcher.to_dataframe(candle_data)
        
        latest = df.iloc[-1]
        current_kline_time = int(latest['Time'])
        
        if self.last_kline_time is not None and current_kline_time == self.last_kline_time:
            logger.info("K线数据未更新，跳过分析")
            return None
        
        self.last_kline_time = current_kline_time
        
        if self.trader.historical_klines.empty:
            self.trader.load_historical_data(df)
        
        latest_row = df.iloc[-1]
        time_s = int(latest_row['Time'])
        time_str = datetime.fromtimestamp(time_s).strftime('%Y-%m-%d %H:%M:%S')
        
        amount = latest_row.get('Amount', None)
        
        result = self.trader.predict_single_kline(
            time=time_str,
            open=latest_row['Open'],
            high=latest_row['High'],
            low=latest_row['Low'],
            close=latest_row['Close'],
            volume=latest_row['Volume'],
            amount=amount,
            use_llm=use_llm
        )
        
        return result
    
    def print_result(self, result: Dict, simulate_trade: bool = False):
        if not result:
            return
        
        logger.info("\n" + "="*60)
        logger.info(f"分析结果 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info("="*60)
        
        kline_info = result.get('kline_info', {})
        logger.info(f"\nK线信息:")
        logger.info(f"  时间: {kline_info.get('time', 'N/A')}")
        logger.info(f"  开盘: {kline_info.get('open', 0):.2f}")
        logger.info(f"  最高: {kline_info.get('high', 0):.2f}")
        logger.info(f"  最低: {kline_info.get('low', 0):.2f}")
        logger.info(f"  收盘: {kline_info.get('close', 0):.2f}")
        logger.info(f"  成交量: {kline_info.get('volume', 0):,}")
        amount = kline_info.get('amount')
        if amount is not None:
            logger.info(f"  成交额: {amount:,.2f}")
        
        rl_pred = result.get('rl_prediction')
        if rl_pred:
            logger.info(f"\n强化学习预测:")
            logger.info(f"  推荐操作: {rl_pred['action']}")
            logger.info(f"  Q值: {[f'{q:.4f}' for q in rl_pred['q_values']]}")
        
        llm_analysis = result.get('llm_analysis')
        if llm_analysis:
            logger.info(f"\nLLM分析结果:")
            logger.info(f"  技术分析: {llm_analysis.get('analysis', 'N/A')}")
            logger.info(f"  风险评估: {llm_analysis.get('risk_assessment', 'N/A')}")
            logger.info(f"  推荐操作: {llm_analysis.get('recommended_action', 'N/A')}")
            logger.info(f"  置信度: {llm_analysis.get('confidence', 0):.2f}")
        
        final_decision = result.get('final_decision')
        if final_decision:
            logger.info(f"\n{'='*60}")
            logger.info(f"最终决策: {final_decision['action']}")
            logger.info(f"{'='*60}")
            
            if 'combination_info' in final_decision:
                logger.info(final_decision['combination_info']['combination_reason'])
            
            if simulate_trade and self.trader:
                close_price = kline_info.get('close', 0)
                if close_price > 0:
                    self.trader.simulate_trade(final_decision['action'], close_price)
        
        logger.info("="*60 + "\n")
    
    def run_once(self, use_llm: bool = True, save_data: bool = True, 
                  simulate_trade: bool = False, use_aligned_time: bool = True):
        if use_aligned_time:
            wait_for_aligned_time(self.bar_type)
        
        logger.info(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 开始获取 {self.bar} K线数据...")
        
        candle_data = self.fetcher.fetch_candles(self.bar, remove_last=True)
        if not candle_data:
            logger.warning("获取K线数据失败")
            return
        
        logger.info(f"成功获取 {len(candle_data)} 根K线数据")
        
        if save_data:
            self.fetcher.save_to_sqlite(candle_data, self.bar)
        
        result = self.analyze_candles(candle_data, use_llm)
        if result:
            self.print_result(result, simulate_trade)
            
            final_decision = result.get('final_decision')
            if final_decision:
                current_action = final_decision.get('action')
                if current_action:
                    if self._should_send_notification(current_action):
                        logger.info(f"\n检测到决策变化: {self.last_final_decision} -> {current_action}")
                        logger.info("准备发送飞书通知...")
                        self._send_feishu_notification(result)
                    
                    self.last_final_decision = current_action
        
        return result
    
    def start(self, use_llm: bool = True, save_data: bool = True, 
               simulate_trade: bool = False, use_aligned_time: bool = True):
        logger.info("="*60)
        logger.info(f"实时K线分析器启动")
        logger.info(f"交易对: {self.config.OKX_INST_ID}")
        logger.info(f"交易类型: {self.config.OKX_INST_TYPE}")
        logger.info(f"K线周期: {self.bar}")
        logger.info(f"时间对齐: {'是 (延后10秒)' if use_aligned_time else '否'}")
        logger.info(f"刷新间隔: {self.interval} 秒")
        logger.info(f"使用LLM: {'是' if use_llm else '否'}")
        logger.info(f"保存数据: {'是' if save_data else '否'}")
        logger.info(f"模拟交易: {'是' if simulate_trade else '否'}")
        logger.info("="*60)
        logger.info("按 Ctrl+C 停止\n")
        
        self.running = True
        
        while self.running:
            try:
                self.run_once(use_llm, save_data, simulate_trade, use_aligned_time)
                
                logger.info(f"等待 {self.interval} 秒后进行下次分析...")
                time.sleep(self.interval)
                
            except KeyboardInterrupt:
                logger.info("\n\n收到停止信号，正在退出...")
                self.running = False
            except Exception as e:
                logger.error(f"运行时错误: {e}")
                logger.info(f"等待 {self.interval} 秒后重试...")
                time.sleep(self.interval)
        
        logger.info("实时K线分析器已停止")
