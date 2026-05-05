import csv
import os
import time
import requests
import pandas as pd
import numpy as np
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from config import Config
from stock_trader import StockTrader
from feishu_notifier import FeishuNotifier, get_notifier
from logger import logger
from sqlite_store import SQLiteKlineStore, SignalStore


OKX_DELAY_SECONDS = 10


def parse_okx_candle_row(row: List, inst_type: str) -> List:
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
        raise ValueError(f"Unsupported K-line period: {bar_type}")

    return target_time


def wait_for_aligned_time(bar_type: str) -> None:
    target_time = get_next_aligned_time(bar_type)
    now = datetime.now()

    if target_time <= now:
        return

    wait_seconds = (target_time - now).total_seconds()

    if wait_seconds > 0:
        logger.info(f"Waiting for aligned time: {target_time.strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info(f"Wait time: {wait_seconds:.1f} seconds...")
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
                logger.error(f"API request failed | code: {data.get('code')}, msg: {data.get('msg')}")
                return None

            candle_data = data.get("data", [])
            if not candle_data:
                logger.warning("No K-line data received")
                return None

            if remove_last and len(candle_data) > 1:
                candle_data = candle_data[1:]
                logger.info(f"Removed last incomplete data, remaining {len(candle_data)} items")

            return candle_data

        except requests.exceptions.RequestException as e:
            logger.error(f"Network error: {str(e)}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error: {str(e)}")
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

        logger.info(f"Data saved to CSV: {file_path}")
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

        logger.info(f"Data saved to SQLite: {count} records")
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
            raise ValueError(f"Unsupported K-line period: {bar_type}, supported: 1m and 15m")

        self.trader: Optional[StockTrader] = None
        self.running = False
        self.last_kline_time: Optional[int] = None
        self.last_final_decision: Optional[str] = None
        self.feishu_notifier: Optional[FeishuNotifier] = None

        self.fetcher = OKXKlineFetcher(self.config)
        self.signal_store = SignalStore(self.config)
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

        lines.append("【Trading Signal - Decision Change Notification】")
        lines.append("-" * 40)

        kline_info = result.get('kline_info', {})
        if kline_info:
            lines.append(f"Time: {kline_info.get('time', 'N/A')}")
            lines.append(f"Trading Pair: {self.config.OKX_INST_ID}")
            lines.append(f"Trading Type: {self.config.OKX_INST_TYPE}")
            lines.append(f"K-line Period: {self.bar}")
            lines.append(f"Open: {kline_info.get('open', 0):.2f}")
            lines.append(f"High: {kline_info.get('high', 0):.2f}")
            lines.append(f"Low: {kline_info.get('low', 0):.2f}")
            lines.append(f"Close: {kline_info.get('close', 0):.2f}")
            lines.append(f"Volume: {kline_info.get('volume', 0):,}")
            amount = kline_info.get('amount')
            if amount is not None:
                lines.append(f"Amount: {amount:,.2f}")

        lines.append("-" * 40)

        rl_pred = result.get('rl_prediction')
        if rl_pred:
            lines.append(f"RL Recommendation: {rl_pred.get('action', 'N/A')}")
            q_values = rl_pred.get('q_values', [])
            if q_values:
                lines.append(f"  Q-values: {[f'{q:.4f}' for q in q_values]}")

        llm_analysis = result.get('llm_analysis')
        if llm_analysis:
            lines.append(f"LLM Recommendation: {llm_analysis.get('recommended_action', 'N/A')}")
            lines.append(f"  Confidence: {llm_analysis.get('confidence', 0):.2f}")
            analysis = llm_analysis.get('analysis', '')
            if analysis and len(analysis) > 500:
                analysis = analysis[:500] + "..."
            if analysis:
                lines.append(f"  Analysis: {analysis}")

        lines.append("-" * 40)

        final_decision = result.get('final_decision', {})
        if final_decision:
            action = final_decision.get('action', 'N/A')
            lines.append(f"【Final Decision】: {action}")
            lines.append(f"Previous Decision: {self.last_final_decision or 'None'}")

            combination_info = final_decision.get('combination_info', {})
            if combination_info:
                combination_reason = combination_info.get('combination_reason', '')
                if combination_reason:
                    lines.append(f"Decision Reason: {combination_reason}")

        lines.append("-" * 40)
        lines.append(f"Notification Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

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
                logger.info("Feishu notification sent successfully")
                return True
            else:
                logger.error(f"Feishu notification failed: {send_result.get('error', 'Unknown error')}")
                return False

        except Exception as e:
            logger.error(f"Error sending Feishu notification: {str(e)}")
            return False

    def initialize_trader(self, model_path: str = None, use_llm: bool = True, use_rl: bool = True):
        logger.info("=" * 60)
        logger.info("Initializing AI Trader...")
        logger.info("=" * 60)

        self.trader = StockTrader(self.config)

        if use_rl:
            model_loaded = False
            if model_path:
                try:
                    self.trader.load_trained_model(model_path)
                    model_loaded = True
                except Exception as e:
                    logger.warning(f"Warning: Failed to load specified model: {e}")
                    logger.warning("Will try default model path, or use LLM analysis only")
            elif os.path.exists(self.config.BEST_MODEL_PATH):
                try:
                    self.trader.load_trained_model(self.config.BEST_MODEL_PATH)
                    model_loaded = True
                except Exception as e:
                    logger.warning(f"Warning: Failed to load default model: {e}")
            else:
                logger.info("Hint: No pretrained model found, will use LLM analysis and rule-based analysis only")

            if not model_loaded:
                logger.info("\nSuggestions:")
                logger.info("  1. To use RL model, run: python main.py --mode train")
                logger.info("  2. Currently will use LLM analysis and rule-based analysis\n")
        else:
            logger.info("RL model disabled, using LLM analysis and rule-based analysis only")

        if use_llm:
            self.trader.initialize_analyzer()

        logger.info("AI Trader initialization complete")
        logger.info("=" * 60)

    def analyze_candles(self, candle_data: List[List], use_llm: bool = True) -> Optional[Dict]:
        if self.trader is None:
            logger.error("Error: Trader not initialized")
            return None

        df = self.fetcher.to_dataframe(candle_data)

        latest = df.iloc[-1]
        current_kline_time = int(latest['Time'])

        if self.last_kline_time is not None and current_kline_time == self.last_kline_time:
            logger.info("K-line data not updated, skipping analysis")
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

        logger.info("\n" + "=" * 60)
        logger.info(f"Analysis Result - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info("=" * 60)

        kline_info = result.get('kline_info', {})
        logger.info(f"\nK-line Info:")
        logger.info(f"  Time: {kline_info.get('time', 'N/A')}")
        logger.info(f"  Open: {kline_info.get('open', 0):.2f}")
        logger.info(f"  High: {kline_info.get('high', 0):.2f}")
        logger.info(f"  Low: {kline_info.get('low', 0):.2f}")
        logger.info(f"  Close: {kline_info.get('close', 0):.2f}")
        logger.info(f"  Volume: {kline_info.get('volume', 0):,}")
        amount = kline_info.get('amount')
        if amount is not None:
            logger.info(f"  Amount: {amount:,.2f}")

        rl_pred = result.get('rl_prediction')
        if rl_pred:
            logger.info(f"\nRL Prediction:")
            logger.info(f"  Recommended Action: {rl_pred['action']}")
            logger.info(f"  Q-values: {[f'{q:.4f}' for q in rl_pred['q_values']]}")

        llm_analysis = result.get('llm_analysis')
        if llm_analysis:
            logger.info(f"\nLLM Analysis Result:")
            logger.info(f"  Technical Analysis: {llm_analysis.get('analysis', 'N/A')}")
            logger.info(f"  Risk Assessment: {llm_analysis.get('risk_assessment', 'N/A')}")
            logger.info(f"  Recommended Action: {llm_analysis.get('recommended_action', 'N/A')}")
            logger.info(f"  Confidence: {llm_analysis.get('confidence', 0):.2f}")

        final_decision = result.get('final_decision')
        if final_decision:
            logger.info(f"\n{'=' * 60}")
            logger.info(f"Final Decision: {final_decision['action']}")
            logger.info(f"{'=' * 60}")

            if 'combination_info' in final_decision:
                logger.info(final_decision['combination_info']['combination_reason'])

            if simulate_trade and self.trader:
                close_price = kline_info.get('close', 0)
                if close_price > 0:
                    self.trader.simulate_trade(final_decision['action'], close_price)

        logger.info("=" * 60 + "\n")

    def run_once(self, use_llm: bool = True, save_data: bool = True,
                 simulate_trade: bool = False, use_aligned_time: bool = True, use_rl: bool = True):
        if use_aligned_time:
            wait_for_aligned_time(self.bar_type)

        logger.info(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Fetching {self.bar} K-line data...")

        candle_data = self.fetcher.fetch_candles(self.bar, remove_last=True)
        if not candle_data:
            logger.warning("Failed to fetch K-line data")
            return

        logger.info(f"Successfully fetched {len(candle_data)} K-line items")

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
                        logger.info(f"\nDecision change detected: {self.last_final_decision} -> {current_action}")
                        logger.info("Preparing to send Feishu notification...")
                        self._send_feishu_notification(result)

                    self._save_signal_if_needed(result, current_action)

                    self.last_final_decision = current_action

        return result

    def _save_signal_if_needed(self, result: Dict, current_action: str) -> None:
        if current_action not in ["Buy", "Sell"]:
            return

        kline_info = result.get('kline_info', {})
        if not kline_info:
            return

        time_str = kline_info.get('time')
        if not time_str:
            return

        try:
            dt = datetime.strptime(time_str, '%Y-%m-%d %H:%M:%S')
            kline_time = int(dt.timestamp())
        except ValueError:
            try:
                dt = datetime.strptime(time_str, '%Y-%m-%d %H:%M')
                kline_time = int(dt.timestamp())
            except ValueError:
                logger.warning(f"Cannot parse time format: {time_str}")
                return

        final_decision = result.get('final_decision', {})
        combination_info = final_decision.get('combination_info')

        confidence = 0.5
        if combination_info and 'vote_weights' in combination_info:
            vote_weights = combination_info['vote_weights']
            confidence = vote_weights.get(current_action, 0.5)
        else:
            llm_analysis = result.get('llm_analysis')
            if llm_analysis:
                confidence = llm_analysis.get('confidence', 0.5)
            else:
                rl_prediction = result.get('rl_prediction')
                if rl_prediction:
                    q_values = rl_prediction.get('q_values', [])
                    if q_values and len(q_values) == 3:
                        action_int = {'Buy': 0, 'Hold': 1, 'Sell': 2}.get(current_action, 1)
                        if 0 <= action_int < len(q_values):
                            q_total = sum(abs(q) for q in q_values)
                            if q_total > 0:
                                confidence = abs(q_values[action_int]) / q_total

        remark_parts = []

        rl_prediction = result.get('rl_prediction')
        if rl_prediction:
            rl_action = rl_prediction.get('action')
            rl_q_values = rl_prediction.get('q_values', [])
            remark_parts.append(f"[RL] action={rl_action}, q_values={rl_q_values}")

        llm_analysis = result.get('llm_analysis')
        if llm_analysis:
            llm_action = llm_analysis.get('recommended_action')
            llm_conf = llm_analysis.get('confidence', 0.5)
            llm_analysis_text = llm_analysis.get('analysis', '')
            llm_reason = llm_analysis.get('reason', '')
            remark_parts.append(f"[LLM] action={llm_action}, confidence={llm_conf:.2f}")
            if llm_analysis_text:
                remark_parts.append(f"[LLM Analysis] {llm_analysis_text}")
            if llm_reason:
                remark_parts.append(f"[LLM Reason] {llm_reason}")

        if combination_info:
            vote_weights = combination_info.get('vote_weights', {})
            combination_reason = combination_info.get('combination_reason', '')
            remark_parts.append(f"[Vote] Buy={vote_weights.get('Buy', 0):.2f}, Hold={vote_weights.get('Hold', 0):.2f}, Sell={vote_weights.get('Sell', 0):.2f}")
            if combination_reason:
                remark_parts.append(f"[Combination] {combination_reason.strip()}")

        if self.last_final_decision:
            remark_parts.append(f"[Previous] {self.last_final_decision}")

        remark = "\n".join(remark_parts)

        action_int = 0 if current_action == "Buy" else 2

        self.signal_store.insert_signal(
            exchange=self.config.EXCHANGE,
            inst_type=self.config.OKX_INST_TYPE,
            symbol=self.config.OKX_INST_ID,
            bar=self.bar,
            kline_time=kline_time,
            action=action_int,
            confidence=confidence,
            remark=remark
        )

    def start(self, use_llm: bool = True, save_data: bool = True,
              simulate_trade: bool = False, use_aligned_time: bool = True, use_rl: bool = True):
        logger.info("=" * 60)
        logger.info(f"Realtime K-line Analyzer Started")
        logger.info(f"Trading Pair: {self.config.OKX_INST_ID}")
        logger.info(f"Trading Type: {self.config.OKX_INST_TYPE}")
        logger.info(f"K-line Period: {self.bar}")
        logger.info(f"Time Alignment: {'Yes (10 seconds delay)' if use_aligned_time else 'No'}")
        logger.info(f"Refresh Interval: {self.interval} seconds")
        logger.info(f"Use LLM: {'Yes' if use_llm else 'No'}")
        logger.info(f"Use RL: {'Yes' if use_rl else 'No'}")
        logger.info(f"Save Data: {'Yes' if save_data else 'No'}")
        logger.info(f"Simulate Trade: {'Yes' if simulate_trade else 'No'}")
        logger.info("=" * 60)
        logger.info("Press Ctrl+C to stop\n")

        self.running = True

        while self.running:
            try:
                self.run_once(use_llm, save_data, simulate_trade, use_aligned_time, use_rl)

                logger.info(f"Waiting {self.interval} seconds for next analysis...")
                time.sleep(self.interval)

            except KeyboardInterrupt:
                logger.info("\n\nReceived stop signal, exiting...")
                self.running = False
            except Exception as e:
                logger.error(f"Runtime error: {e}")
                logger.info(f"Waiting {self.interval} seconds to retry...")
                time.sleep(self.interval)

        logger.info("Realtime K-line Analyzer stopped")


class MultiTimeframeAnalyzer:
    def __init__(self, config: Config = None):
        self.config = config or Config()
        self.config.create_directories()

        self.interval = self.config.REALTIME_INTERVAL_1M
        self.bars = ["1m", "15m"]

        self.trader: Optional[StockTrader] = None
        self.running = False
        self.last_kline_time_1m: Optional[int] = None
        self.last_kline_time_15m: Optional[int] = None
        self.last_final_decision: Optional[str] = None
        self.feishu_notifier: Optional[FeishuNotifier] = None

        self.fetcher_1m = OKXKlineFetcher(self.config)
        self.fetcher_15m = OKXKlineFetcher(self.config)
        self.signal_store = SignalStore(self.config)
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

        lines.append("【Trading Signal - Decision Change Notification】")
        lines.append("-" * 40)

        kline_info = result.get('kline_info', {})
        if kline_info:
            lines.append(f"Time: {kline_info.get('time', 'N/A')}")
            lines.append(f"Trading Pair: {self.config.OKX_INST_ID}")
            lines.append(f"Trading Type: {self.config.OKX_INST_TYPE}")
            lines.append(f"K-line Period: 1min + 15min")
            lines.append(f"Open: {kline_info.get('open', 0):.2f}")
            lines.append(f"High: {kline_info.get('high', 0):.2f}")
            lines.append(f"Low: {kline_info.get('low', 0):.2f}")
            lines.append(f"Close: {kline_info.get('close', 0):.2f}")
            lines.append(f"Volume: {kline_info.get('volume', 0):,}")
            amount = kline_info.get('amount')
            if amount is not None:
                lines.append(f"Amount: {amount:,.2f}")

        lines.append("-" * 40)

        rl_pred = result.get('rl_prediction')
        if rl_pred:
            lines.append(f"RL Recommendation: {rl_pred.get('action', 'N/A')}")
            q_values = rl_pred.get('q_values', [])
            if q_values:
                lines.append(f"  Q-values: {[f'{q:.4f}' for q in q_values]}")

        llm_analysis = result.get('llm_analysis')
        if llm_analysis:
            lines.append(f"LLM Recommendation: {llm_analysis.get('recommended_action', 'N/A')}")
            lines.append(f"  Confidence: {llm_analysis.get('confidence', 0):.2f}")
            analysis = llm_analysis.get('analysis', '')
            if analysis and len(analysis) > 500:
                analysis = analysis[:500] + "..."
            if analysis:
                lines.append(f"  Analysis: {analysis}")

        lines.append("-" * 40)

        final_decision = result.get('final_decision', {})
        if final_decision:
            action = final_decision.get('action', 'N/A')
            lines.append(f"【Final Decision】: {action}")
            lines.append(f"Previous Decision: {self.last_final_decision or 'None'}")

            combination_info = final_decision.get('combination_info', {})
            if combination_info:
                combination_reason = combination_info.get('combination_reason', '')
                if combination_reason:
                    lines.append(f"Decision Reason: {combination_reason}")

        lines.append("-" * 40)
        lines.append(f"Notification Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

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
                logger.info("Feishu notification sent successfully")
                return True
            else:
                logger.error(f"Feishu notification failed: {send_result.get('error', 'Unknown error')}")
                return False

        except Exception as e:
            logger.error(f"Error sending Feishu notification: {str(e)}")
            return False

    def initialize_trader(self, model_path: str = None, use_llm: bool = True, use_rl: bool = True):
        logger.info("=" * 60)
        logger.info("Initializing AI Trader (Multi-Timeframe Mode)...")
        logger.info("=" * 60)

        self.trader = StockTrader(self.config)

        if use_rl:
            model_loaded = False
            if model_path:
                try:
                    self.trader.load_trained_model(model_path)
                    model_loaded = True
                except Exception as e:
                    logger.warning(f"Warning: Failed to load specified model: {e}")
                    logger.warning("Will try default model path, or use LLM analysis only")
            elif os.path.exists(self.config.BEST_MODEL_PATH):
                try:
                    self.trader.load_trained_model(self.config.BEST_MODEL_PATH)
                    model_loaded = True
                except Exception as e:
                    logger.warning(f"Warning: Failed to load default model: {e}")
            else:
                logger.info("Hint: No pretrained model found, will use LLM analysis and rule-based analysis only")

            if not model_loaded:
                logger.info("\nSuggestions:")
                logger.info("  1. To use RL model, run: python main.py --mode train")
                logger.info("  2. Currently will use LLM analysis and rule-based analysis\n")
        else:
            logger.info("RL model disabled, using LLM analysis and rule-based analysis only")

        if use_llm:
            self.trader.initialize_analyzer()

        logger.info("AI Trader initialization complete")
        logger.info("=" * 60)

    def analyze_multi_timeframe(self, candle_data_1m: List[List], candle_data_15m: List[List], use_llm: bool = True) -> Optional[Dict]:
        if self.trader is None:
            logger.error("Error: Trader not initialized")
            return None

        df_1m = self.fetcher_1m.to_dataframe(candle_data_1m)
        df_15m = self.fetcher_15m.to_dataframe(candle_data_15m)

        latest_1m = df_1m.iloc[-1]
        current_kline_time_1m = int(latest_1m['Time'])

        latest_15m = df_15m.iloc[-1]
        current_kline_time_15m = int(latest_15m['Time'])

        if self.last_kline_time_1m is not None and current_kline_time_1m == self.last_kline_time_1m:
            logger.info("1min K-line data not updated, skipping analysis")
            return None

        self.last_kline_time_1m = current_kline_time_1m
        self.last_kline_time_15m = current_kline_time_15m

        if self.trader.historical_klines.empty:
            self.trader.load_historical_data(df_1m)
        else:
            self.trader.historical_klines = pd.concat([self.trader.historical_klines, df_1m.iloc[-1:]], ignore_index=True)

        if len(self.trader.historical_klines) >= 5:
            self.trader.historical_klines = self.trader.data_loader._add_technical_indicators(self.trader.historical_klines)

        latest_row = df_1m.iloc[-1]
        time_s = int(latest_row['Time'])
        time_str = datetime.fromtimestamp(time_s).strftime('%Y-%m-%d %H:%M:%S')

        amount = latest_row.get('Amount', None)

        kline_info = {
            'time': time_str,
            'open': latest_row['Open'],
            'high': latest_row['High'],
            'low': latest_row['Low'],
            'close': latest_row['Close'],
            'volume': latest_row['Volume']
        }
        if amount is not None:
            kline_info['amount'] = amount

        result = {
            'kline_info': kline_info,
            'kline_info_15m': {
                'time': datetime.fromtimestamp(int(df_15m.iloc[-1]['Time'])).strftime('%Y-%m-%d %H:%M:%S'),
                'open': df_15m.iloc[-1]['Open'],
                'high': df_15m.iloc[-1]['High'],
                'low': df_15m.iloc[-1]['Low'],
                'close': df_15m.iloc[-1]['Close'],
                'volume': df_15m.iloc[-1]['Volume']
            },
            'rl_prediction': None,
            'llm_analysis': None,
            'final_decision': None
        }

        if self.trader.agent is not None and len(self.trader.historical_klines) >= self.config.WINDOW_SIZE:
            current_idx = len(self.trader.historical_klines) - 1
            state = self.trader.data_loader.prepare_state_features(
                self.trader.historical_klines,
                current_idx,
                self.config.WINDOW_SIZE
            )

            portfolio_state = np.array([
                self.trader.portfolio_info['balance'] / self.config.INITIAL_BALANCE,
                self.trader.portfolio_info['shares_held'] / self.config.MAX_SHARES,
                (self.trader.portfolio_info['avg_cost'] / latest_row['Close']) - 1
                    if self.trader.portfolio_info['shares_held'] > 0 and latest_row['Close'] > 0 else 0.0
            ])
            portfolio_state = np.tile(portfolio_state, (self.config.WINDOW_SIZE, 1))

            full_state = np.concatenate([state, portfolio_state], axis=1).astype(np.float32)

            rl_action_int, rl_q_values = self.trader.agent.predict_action(full_state)
            rl_action_name = self.config.INT_TO_ACTION[rl_action_int]

            result['rl_prediction'] = {
                'action': rl_action_name,
                'action_int': rl_action_int,
                'q_values': rl_q_values
            }

        if use_llm:
            if self.trader.analyzer is None:
                self.trader.initialize_analyzer()

            llm_analysis = self.trader.analyzer.analyze_kline_multi_timeframe(
                self.trader.historical_klines,
                df_15m,
                self.trader.recent_actions,
                self.trader.portfolio_info
            )
            result['llm_analysis'] = llm_analysis

        if result['rl_prediction'] is not None and result['llm_analysis'] is not None:
            if self.trader.analyzer is None:
                self.trader.initialize_analyzer()

            final_action_int, final_action_name, combination_info = self.trader.analyzer.combine_signals(
                result['rl_prediction']['action_int'],
                result['llm_analysis'],
                result['rl_prediction']['q_values']
            )

            result['final_decision'] = {
                'action': final_action_name,
                'action_int': final_action_int,
                'combination_info': combination_info
            }

        elif result['rl_prediction'] is not None:
            result['final_decision'] = {
                'action': result['rl_prediction']['action'],
                'action_int': result['rl_prediction']['action_int'],
                'source': 'rl_only'
            }

        elif result['llm_analysis'] is not None:
            llm_action = result['llm_analysis']['recommended_action']
            llm_action_int = self.config.ACTION_TO_INT[llm_action]

            result['final_decision'] = {
                'action': llm_action,
                'action_int': llm_action_int,
                'source': 'llm_only'
            }

        if result['final_decision']:
            self.trader.recent_actions.append(result['final_decision']['action'])
            if len(self.trader.recent_actions) > 50:
                self.trader.recent_actions = self.trader.recent_actions[-50:]

        return result

    def print_result(self, result: Dict, simulate_trade: bool = False):
        if not result:
            return

        logger.info("\n" + "=" * 60)
        logger.info(f"Multi-Timeframe Analysis Result - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info("=" * 60)

        kline_info = result.get('kline_info', {})
        logger.info(f"\n1min K-line Info:")
        logger.info(f"  Time: {kline_info.get('time', 'N/A')}")
        logger.info(f"  Open: {kline_info.get('open', 0):.2f}")
        logger.info(f"  High: {kline_info.get('high', 0):.2f}")
        logger.info(f"  Low: {kline_info.get('low', 0):.2f}")
        logger.info(f"  Close: {kline_info.get('close', 0):.2f}")
        logger.info(f"  Volume: {kline_info.get('volume', 0):,}")
        amount = kline_info.get('amount')
        if amount is not None:
            logger.info(f"  Amount: {amount:,.2f}")

        kline_info_15m = result.get('kline_info_15m', {})
        logger.info(f"\n15min K-line Info:")
        logger.info(f"  Time: {kline_info_15m.get('time', 'N/A')}")
        logger.info(f"  Open: {kline_info_15m.get('open', 0):.2f}")
        logger.info(f"  High: {kline_info_15m.get('high', 0):.2f}")
        logger.info(f"  Low: {kline_info_15m.get('low', 0):.2f}")
        logger.info(f"  Close: {kline_info_15m.get('close', 0):.2f}")
        logger.info(f"  Volume: {kline_info_15m.get('volume', 0):,}")

        rl_pred = result.get('rl_prediction')
        if rl_pred:
            logger.info(f"\nRL Prediction:")
            logger.info(f"  Recommended Action: {rl_pred['action']}")
            logger.info(f"  Q-values: {[f'{q:.4f}' for q in rl_pred['q_values']]}")

        llm_analysis = result.get('llm_analysis')
        if llm_analysis:
            logger.info(f"\nLLM Analysis Result:")
            logger.info(f"  Technical Analysis: {llm_analysis.get('analysis', 'N/A')}")
            logger.info(f"  Risk Assessment: {llm_analysis.get('risk_assessment', 'N/A')}")
            logger.info(f"  Recommended Action: {llm_analysis.get('recommended_action', 'N/A')}")
            logger.info(f"  Confidence: {llm_analysis.get('confidence', 0):.2f}")

        final_decision = result.get('final_decision')
        if final_decision:
            logger.info(f"\n{'=' * 60}")
            logger.info(f"Final Decision: {final_decision['action']}")
            logger.info(f"{'=' * 60}")

            if 'combination_info' in final_decision:
                logger.info(final_decision['combination_info']['combination_reason'])

            if simulate_trade and self.trader:
                close_price = kline_info.get('close', 0)
                if close_price > 0:
                    self.trader.simulate_trade(final_decision['action'], close_price)

        logger.info("=" * 60 + "\n")

    def run_once(self, use_llm: bool = True, save_data: bool = True,
                 simulate_trade: bool = False, use_aligned_time: bool = True):
        if use_aligned_time:
            wait_for_aligned_time("1m")

        logger.info(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Fetching multi-timeframe K-line data...")

        candle_data_1m = self.fetcher_1m.fetch_candles("1m", remove_last=True)
        candle_data_15m = self.fetcher_15m.fetch_candles("15m", remove_last=False)

        if not candle_data_1m:
            logger.warning("Failed to fetch 1min K-line data")
            return

        if not candle_data_15m:
            logger.warning("Failed to fetch 15min K-line data")
            return

        logger.info(f"Successfully fetched 1min: {len(candle_data_1m)} items, 15min: {len(candle_data_15m)} items")

        if save_data:
            self.fetcher_1m.save_to_sqlite(candle_data_1m, "1m")
            self.fetcher_15m.save_to_sqlite(candle_data_15m, "15m")

        result = self.analyze_multi_timeframe(candle_data_1m, candle_data_15m, use_llm)
        if result:
            self.print_result(result, simulate_trade)

            final_decision = result.get('final_decision')
            if final_decision:
                current_action = final_decision.get('action')
                if current_action:
                    if self._should_send_notification(current_action):
                        logger.info(f"\nDecision change detected: {self.last_final_decision} -> {current_action}")
                        logger.info("Preparing to send Feishu notification...")
                        self._send_feishu_notification(result)

                    self._save_signal_if_needed(result, current_action)

                    self.last_final_decision = current_action

        return result

    def _save_signal_if_needed(self, result: Dict, current_action: str) -> None:
        if current_action not in ["Buy", "Sell"]:
            return

        kline_info = result.get('kline_info', {})
        if not kline_info:
            return

        time_str = kline_info.get('time')
        if not time_str:
            return

        try:
            dt = datetime.strptime(time_str, '%Y-%m-%d %H:%M:%S')
            kline_time = int(dt.timestamp())
        except ValueError:
            try:
                dt = datetime.strptime(time_str, '%Y-%m-%d %H:%M')
                kline_time = int(dt.timestamp())
            except ValueError:
                logger.warning(f"Cannot parse time format: {time_str}")
                return

        final_decision = result.get('final_decision', {})
        combination_info = final_decision.get('combination_info')

        confidence = 0.5
        if combination_info and 'vote_weights' in combination_info:
            vote_weights = combination_info['vote_weights']
            confidence = vote_weights.get(current_action, 0.5)
        else:
            llm_analysis = result.get('llm_analysis')
            if llm_analysis:
                confidence = llm_analysis.get('confidence', 0.5)
            else:
                rl_prediction = result.get('rl_prediction')
                if rl_prediction:
                    q_values = rl_prediction.get('q_values', [])
                    if q_values and len(q_values) == 3:
                        action_int = {'Buy': 0, 'Hold': 1, 'Sell': 2}.get(current_action, 1)
                        if 0 <= action_int < len(q_values):
                            q_total = sum(abs(q) for q in q_values)
                            if q_total > 0:
                                confidence = abs(q_values[action_int]) / q_total

        remark_parts = []

        rl_prediction = result.get('rl_prediction')
        if rl_prediction:
            rl_action = rl_prediction.get('action')
            rl_q_values = rl_prediction.get('q_values', [])
            remark_parts.append(f"[RL] action={rl_action}, q_values={rl_q_values}")

        llm_analysis = result.get('llm_analysis')
        if llm_analysis:
            llm_action = llm_analysis.get('recommended_action')
            llm_conf = llm_analysis.get('confidence', 0.5)
            llm_analysis_text = llm_analysis.get('analysis', '')
            llm_reason = llm_analysis.get('reason', '')
            remark_parts.append(f"[LLM] action={llm_action}, confidence={llm_conf:.2f}")
            if llm_analysis_text:
                remark_parts.append(f"[LLM Analysis] {llm_analysis_text}")
            if llm_reason:
                remark_parts.append(f"[LLM Reason] {llm_reason}")

        if combination_info:
            vote_weights = combination_info.get('vote_weights', {})
            combination_reason = combination_info.get('combination_reason', '')
            remark_parts.append(f"[Vote] Buy={vote_weights.get('Buy', 0):.2f}, Hold={vote_weights.get('Hold', 0):.2f}, Sell={vote_weights.get('Sell', 0):.2f}")
            if combination_reason:
                remark_parts.append(f"[Combination] {combination_reason.strip()}")

        if self.last_final_decision:
            remark_parts.append(f"[Previous] {self.last_final_decision}")

        remark = "\n".join(remark_parts)

        action_int = 0 if current_action == "Buy" else 2

        self.signal_store.insert_signal(
            exchange=self.config.EXCHANGE,
            inst_type=self.config.OKX_INST_TYPE,
            symbol=self.config.OKX_INST_ID,
            bar="1m+15m",
            kline_time=kline_time,
            action=action_int,
            confidence=confidence,
            remark=remark
        )

    def start(self, use_llm: bool = True, save_data: bool = True,
              simulate_trade: bool = False, use_aligned_time: bool = True):
        logger.info("=" * 60)
        logger.info(f"Multi-Timeframe K-line Analyzer Started")
        logger.info(f"Trading Pair: {self.config.OKX_INST_ID}")
        logger.info(f"Trading Type: {self.config.OKX_INST_TYPE}")
        logger.info(f"K-line Period: 1min + 15min")
        logger.info(f"Time Alignment: {'Yes (10 seconds delay)' if use_aligned_time else 'No'}")
        logger.info(f"Refresh Interval: {self.interval} seconds")
        logger.info(f"Use LLM: {'Yes' if use_llm else 'No'}")
        logger.info(f"Save Data: {'Yes' if save_data else 'No'}")
        logger.info(f"Simulate Trade: {'Yes' if simulate_trade else 'No'}")
        logger.info("=" * 60)
        logger.info("Press Ctrl+C to stop\n")

        self.running = True

        while self.running:
            try:
                self.run_once(use_llm, save_data, simulate_trade, use_aligned_time)

                logger.info(f"Waiting {self.interval} seconds for next analysis...")
                time.sleep(self.interval)

            except KeyboardInterrupt:
                logger.info("\n\nReceived stop signal, exiting...")
                self.running = False
            except Exception as e:
                logger.error(f"Runtime error: {e}")
                logger.info(f"Waiting {self.interval} seconds to retry...")
                time.sleep(self.interval)

        logger.info("Multi-Timeframe K-line Analyzer stopped")
