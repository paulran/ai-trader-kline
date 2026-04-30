import sqlite3
import os
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple
import pandas as pd
from config import Config
from logger import logger


class SQLiteKlineStore:
    def __init__(self, config: Config = None):
        self.config = config or Config()
        self.config.create_directories()
    
    def _get_db_path(self, exchange: str, inst_type: str, symbol: str, 
                     bar: str, year_month: str) -> str:
        db_name = f"{exchange}_{inst_type}_{symbol}_{bar}_{year_month}.db"
        return os.path.join(self.config.DATA_PATH, db_name)
    
    def _get_year_month_from_timestamp(self, timestamp: int) -> str:
        dt = datetime.fromtimestamp(timestamp)
        return dt.strftime('%Y%m')
    
    def _init_database(self, db_path: str) -> None:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS klines (
                Time INTEGER PRIMARY KEY,
                Open REAL NOT NULL,
                High REAL NOT NULL,
                Low REAL NOT NULL,
                Close REAL NOT NULL,
                Volume REAL NOT NULL,
                Amount REAL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_time ON klines(Time)
        ''')
        
        conn.commit()
        conn.close()
    
    def insert_kline(self, exchange: str, inst_type: str, symbol: str, bar: str,
                      time: int, open: float, high: float, low: float, 
                      close: float, volume: float, amount: float = 0) -> bool:
        year_month = self._get_year_month_from_timestamp(time)
        db_path = self._get_db_path(exchange, inst_type, symbol, bar, year_month)
        
        self._init_database(db_path)
        
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT INTO klines (Time, Open, High, Low, Close, Volume, Amount, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(Time) DO UPDATE SET
                    Open = excluded.Open,
                    High = excluded.High,
                    Low = excluded.Low,
                    Close = excluded.Close,
                    Volume = excluded.Volume,
                    Amount = excluded.Amount,
                    updated_at = CURRENT_TIMESTAMP
            ''', (time, open, high, low, close, volume, amount))
            
            conn.commit()
            conn.close()
            
            logger.debug(f"已插入/更新K线数据: time={time}, symbol={symbol}")
            return True
            
        except Exception as e:
            logger.error(f"插入K线数据失败: {e}")
            return False
    
    def insert_klines_batch(self, exchange: str, inst_type: str, symbol: str, bar: str,
                              klines: List[Tuple[int, float, float, float, float, float, float]]) -> int:
        if not klines:
            return 0
        
        grouped = {}
        for kline in klines:
            time = kline[0]
            year_month = self._get_year_month_from_timestamp(time)
            if year_month not in grouped:
                grouped[year_month] = []
            grouped[year_month].append(kline)
        
        total_inserted = 0
        
        for year_month, month_klines in grouped.items():
            db_path = self._get_db_path(exchange, inst_type, symbol, bar, year_month)
            self._init_database(db_path)
            
            try:
                conn = sqlite3.connect(db_path)
                cursor = conn.cursor()
                
                for kline in month_klines:
                    time, open, high, low, close, volume, amount = kline
                    cursor.execute('''
                        INSERT INTO klines (Time, Open, High, Low, Close, Volume, Amount, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                        ON CONFLICT(Time) DO UPDATE SET
                            Open = excluded.Open,
                            High = excluded.High,
                            Low = excluded.Low,
                            Close = excluded.Close,
                            Volume = excluded.Volume,
                            Amount = excluded.Amount,
                            updated_at = CURRENT_TIMESTAMP
                    ''', (time, open, high, low, close, volume, amount))
                
                conn.commit()
                conn.close()
                
                total_inserted += len(month_klines)
                logger.debug(f"已批量插入 {len(month_klines)} 条K线数据到 {year_month}")
                
            except Exception as e:
                logger.error(f"批量插入K线数据失败 ({year_month}): {e}")
        
        return total_inserted
    
    def load_klines(self, exchange: str, inst_type: str, symbol: str, bar: str,
                    start_time: int = None, end_time: int = None,
                    year_months: List[str] = None) -> pd.DataFrame:
        if year_months is None:
            if start_time is not None and end_time is not None:
                start_ym = self._get_year_month_from_timestamp(start_time)
                end_ym = self._get_year_month_from_timestamp(end_time)
                year_months = self._get_year_months_between(start_ym, end_ym)
            else:
                year_months = self._get_all_available_year_months(exchange, inst_type, symbol, bar)
        
        all_data = []
        
        for year_month in year_months:
            db_path = self._get_db_path(exchange, inst_type, symbol, bar, year_month)
            
            if not os.path.exists(db_path):
                continue
            
            try:
                conn = sqlite3.connect(db_path)
                
                query = "SELECT Time, Open, High, Low, Close, Volume, Amount FROM klines"
                conditions = []
                params = []
                
                if start_time is not None:
                    conditions.append("Time >= ?")
                    params.append(start_time)
                if end_time is not None:
                    conditions.append("Time <= ?")
                    params.append(end_time)
                
                if conditions:
                    query += " WHERE " + " AND ".join(conditions)
                
                query += " ORDER BY Time ASC"
                
                df = pd.read_sql_query(query, conn, params=params)
                conn.close()
                
                all_data.append(df)
                
            except Exception as e:
                logger.error(f"加载K线数据失败 ({year_month}): {e}")
        
        if all_data:
            result = pd.concat(all_data, ignore_index=True)
            result = result.sort_values('Time').reset_index(drop=True)
            return result
        
        return pd.DataFrame()
    
    def _get_year_months_between(self, start_ym: str, end_ym: str) -> List[str]:
        months = []
        start = datetime.strptime(start_ym, '%Y%m')
        end = datetime.strptime(end_ym, '%Y%m')
        
        current = start
        while current <= end:
            months.append(current.strftime('%Y%m'))
            if current.month == 12:
                current = current.replace(year=current.year + 1, month=1)
            else:
                current = current.replace(month=current.month + 1)
        
        return months
    
    def _get_all_available_year_months(self, exchange: str, inst_type: str, 
                                          symbol: str, bar: str) -> List[str]:
        data_path = Path(self.config.DATA_PATH)
        prefix = f"{exchange}_{inst_type}_{symbol}_{bar}_"
        
        months = []
        for file_path in data_path.glob(f"{prefix}*.db"):
            filename = file_path.stem
            ym_part = filename[len(prefix):]
            if len(ym_part) == 6 and ym_part.isdigit():
                months.append(ym_part)
        
        return sorted(months)
    
    def get_latest_kline_time(self, exchange: str, inst_type: str, symbol: str, bar: str) -> Optional[int]:
        year_months = self._get_all_available_year_months(exchange, inst_type, symbol, bar)
        
        if not year_months:
            return None
        
        latest_time = None
        
        for year_month in reversed(year_months):
            db_path = self._get_db_path(exchange, inst_type, symbol, bar, year_month)
            
            if not os.path.exists(db_path):
                continue
            
            try:
                conn = sqlite3.connect(db_path)
                cursor = conn.cursor()
                
                cursor.execute("SELECT MAX(Time) FROM klines")
                result = cursor.fetchone()[0]
                conn.close()
                
                if result is not None:
                    if latest_time is None or result > latest_time:
                        latest_time = result
                        
            except Exception as e:
                logger.error(f"获取最新K线时间失败 ({year_month}): {e}")
        
        return latest_time
    
    def get_kline_count(self, exchange: str, inst_type: str, symbol: str, bar: str,
                         start_time: int = None, end_time: int = None) -> int:
        df = self.load_klines(exchange, inst_type, symbol, bar, start_time, end_time)
        return len(df)
    
    def delete_old_data(self, exchange: str, inst_type: str, symbol: str, bar: str,
                         before_time: int = None) -> int:
        if before_time is None:
            return 0
        
        year_months = self._get_all_available_year_months(exchange, inst_type, symbol, bar)
        deleted_count = 0
        
        for year_month in year_months:
            db_path = self._get_db_path(exchange, inst_type, symbol, bar, year_month)
            
            if not os.path.exists(db_path):
                continue
            
            try:
                conn = sqlite3.connect(db_path)
                cursor = conn.cursor()
                
                cursor.execute("DELETE FROM klines WHERE Time < ?", (before_time,))
                count = cursor.rowcount
                conn.commit()
                conn.close()
                
                deleted_count += count
                logger.debug(f"已删除 {count} 条旧数据 ({year_month})")
                
            except Exception as e:
                logger.error(f"删除旧数据失败 ({year_month}): {e}")
        
        return deleted_count


class SignalStore:
    def __init__(self, config: Config = None):
        self.config = config or Config()
        self.config.create_directories()
    
    def _get_db_path(self, exchange: str, inst_type: str, symbol: str, 
                     bar: str, year_month: str) -> str:
        db_name = f"{exchange}_{inst_type}_{symbol}_{bar}_{year_month}_signals.db"
        return os.path.join(self.config.DATA_PATH, db_name)
    
    def _get_year_month_from_timestamp(self, timestamp: int) -> str:
        dt = datetime.fromtimestamp(timestamp)
        return dt.strftime('%Y%m')
    
    def _init_database(self, db_path: str) -> None:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kline_time INTEGER NOT NULL,
                action TEXT NOT NULL,
                open_price REAL NOT NULL,
                high_price REAL NOT NULL,
                low_price REAL NOT NULL,
                close_price REAL NOT NULL,
                volume REAL NOT NULL,
                amount REAL DEFAULT 0,
                rl_action TEXT,
                rl_q_values TEXT,
                llm_action TEXT,
                llm_confidence REAL,
                llm_analysis TEXT,
                llm_risk_assessment TEXT,
                llm_reason TEXT,
                combination_reason TEXT,
                previous_action TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_kline_time ON signals(kline_time)
        ''')
        
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_action ON signals(action)
        ''')
        
        conn.commit()
        conn.close()
    
    def insert_signal(self, exchange: str, inst_type: str, symbol: str, bar: str,
                      kline_time: int, action: str,
                      open_price: float, high_price: float, low_price: float, 
                      close_price: float, volume: float, amount: float = 0,
                      rl_action: str = None, rl_q_values: List[float] = None,
                      llm_action: str = None, llm_confidence: float = None,
                      llm_analysis: str = None, llm_risk_assessment: str = None,
                      llm_reason: str = None, combination_reason: str = None,
                      previous_action: str = None) -> bool:
        if action not in ["Buy", "Sell"]:
            return False
        
        year_month = self._get_year_month_from_timestamp(kline_time)
        db_path = self._get_db_path(exchange, inst_type, symbol, bar, year_month)
        
        self._init_database(db_path)
        
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            
            rl_q_values_str = str(rl_q_values) if rl_q_values else None
            
            cursor.execute('''
                INSERT INTO signals (
                    kline_time, action, 
                    open_price, high_price, low_price, close_price, volume, amount,
                    rl_action, rl_q_values,
                    llm_action, llm_confidence, llm_analysis, llm_risk_assessment, llm_reason,
                    combination_reason, previous_action
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                kline_time, action,
                open_price, high_price, low_price, close_price, volume, amount,
                rl_action, rl_q_values_str,
                llm_action, llm_confidence, llm_analysis, llm_risk_assessment, llm_reason,
                combination_reason, previous_action
            ))
            
            conn.commit()
            conn.close()
            
            logger.info(f"已保存交易信号: {action} @ {datetime.fromtimestamp(kline_time).strftime('%Y-%m-%d %H:%M:%S')}")
            return True
            
        except Exception as e:
            logger.error(f"保存交易信号失败: {e}")
            return False
    
    def load_signals(self, exchange: str, inst_type: str, symbol: str, bar: str,
                     start_time: int = None, end_time: int = None,
                     action: str = None,
                     year_months: List[str] = None) -> pd.DataFrame:
        if year_months is None:
            if start_time is not None and end_time is not None:
                start_ym = self._get_year_month_from_timestamp(start_time)
                end_ym = self._get_year_month_from_timestamp(end_time)
                year_months = self._get_year_months_between(start_ym, end_ym)
            else:
                year_months = self._get_all_available_year_months(exchange, inst_type, symbol, bar)
        
        all_data = []
        
        for year_month in year_months:
            db_path = self._get_db_path(exchange, inst_type, symbol, bar, year_month)
            
            if not os.path.exists(db_path):
                continue
            
            try:
                conn = sqlite3.connect(db_path)
                
                query = """
                    SELECT id, kline_time, action, 
                           open_price, high_price, low_price, close_price, volume, amount,
                           rl_action, rl_q_values,
                           llm_action, llm_confidence, llm_analysis, llm_risk_assessment, llm_reason,
                           combination_reason, previous_action, created_at
                    FROM signals
                """
                conditions = []
                params = []
                
                if start_time is not None:
                    conditions.append("kline_time >= ?")
                    params.append(start_time)
                if end_time is not None:
                    conditions.append("kline_time <= ?")
                    params.append(end_time)
                if action is not None:
                    conditions.append("action = ?")
                    params.append(action)
                
                if conditions:
                    query += " WHERE " + " AND ".join(conditions)
                
                query += " ORDER BY kline_time ASC"
                
                df = pd.read_sql_query(query, conn, params=params)
                conn.close()
                
                all_data.append(df)
                
            except Exception as e:
                logger.error(f"加载交易信号失败 ({year_month}): {e}")
        
        if all_data:
            result = pd.concat(all_data, ignore_index=True)
            result = result.sort_values('kline_time').reset_index(drop=True)
            return result
        
        return pd.DataFrame()
    
    def _get_year_months_between(self, start_ym: str, end_ym: str) -> List[str]:
        months = []
        start = datetime.strptime(start_ym, '%Y%m')
        end = datetime.strptime(end_ym, '%Y%m')
        
        current = start
        while current <= end:
            months.append(current.strftime('%Y%m'))
            if current.month == 12:
                current = current.replace(year=current.year + 1, month=1)
            else:
                current = current.replace(month=current.month + 1)
        
        return months
    
    def _get_all_available_year_months(self, exchange: str, inst_type: str, 
                                          symbol: str, bar: str) -> List[str]:
        data_path = Path(self.config.DATA_PATH)
        prefix = f"{exchange}_{inst_type}_{symbol}_{bar}_"
        suffix = "_signals.db"
        
        months = []
        for file_path in data_path.glob(f"{prefix}*_signals.db"):
            filename = file_path.stem
            ym_part = filename[len(prefix):-len("_signals")]
            if len(ym_part) == 6 and ym_part.isdigit():
                months.append(ym_part)
        
        return sorted(months)
    
    def get_signal_count(self, exchange: str, inst_type: str, symbol: str, bar: str,
                         start_time: int = None, end_time: int = None,
                         action: str = None) -> int:
        df = self.load_signals(exchange, inst_type, symbol, bar, start_time, end_time, action)
        return len(df)
