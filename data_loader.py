import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple
from pathlib import Path
from datetime import datetime
from config import Config
from logger import logger
from sqlite_store import SQLiteKlineStore

class DataLoader:
    def __init__(self, config: Config = None):
        self.config = config or Config()
        self.config.create_directories()
        self.sqlite_store = SQLiteKlineStore(self.config)
    
    def load_csv_file(self, file_path: str) -> pd.DataFrame:
        df = pd.read_csv(file_path)
        return self._preprocess_dataframe(df)
    
    def _preprocess_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        required_columns = ['Time', 'Open', 'High', 'Low', 'Close', 'Volume']
        action_columns = ['Buy', 'Hold', 'Sell']
        
        for col in required_columns:
            if col not in df.columns:
                raise ValueError(f"缺少必要列: {col}")
        
        if 'Time' in df.columns:
            try:
                if pd.api.types.is_numeric_dtype(df['Time']):
                    first_value = df['Time'].iloc[0]
                    if first_value > 1e12:
                        df['Time'] = pd.to_datetime(df['Time'], unit='ms')
                    elif first_value > 1e9:
                        df['Time'] = pd.to_datetime(df['Time'], unit='s')
                    else:
                        df['Time'] = pd.to_datetime(df['Time'])
                else:
                    df['Time'] = pd.to_datetime(df['Time'])
            except Exception as e:
                raise ValueError(f"时间格式转换失败: {e}")
        
        numeric_columns = ['Open', 'High', 'Low', 'Close', 'Volume']
        if 'Amount' in df.columns:
            numeric_columns.append('Amount')
            df['Amount'] = pd.to_numeric(df['Amount'], errors='coerce').fillna(0)
        
        for col in numeric_columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')
            if df[col].isnull().any():
                raise ValueError(f"列 {col} 包含无效数值")
        
        for col in action_columns:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
                df[col] = df[col].astype(int)
        
        df = df.sort_values('Time').reset_index(drop=True)
        
        return df
    
    def load_training_data(self, start_time: int = None, end_time: int = None) -> List[pd.DataFrame]:
        data_frames = []
        
        exchange = self.config.EXCHANGE
        symbol = self.config.OKX_INST_ID
        inst_type = self.config.OKX_INST_TYPE
        
        sqlite_df = self.sqlite_store.load_klines(
            exchange=exchange,
            inst_type=inst_type,
            symbol=symbol,
            bar='1m',
            start_time=start_time,
            end_time=end_time
        )
        
        if not sqlite_df.empty:
            try:
                df = self._preprocess_dataframe(sqlite_df)
                data_frames.append(df)
                logger.info(f"从SQLite加载训练数据: {len(df)} 条记录")
            except Exception as e:
                logger.warning(f"警告: 无法处理SQLite数据: {e}")
        
        if not data_frames:
            logger.warning("警告: SQLite中没有找到有效的数据，将生成示例数据")
            sample_df = self.generate_sample_data()
            data_frames.append(sample_df)
        
        return data_frames
    
    def load_testing_data(self, start_time: int = None, end_time: int = None) -> List[pd.DataFrame]:
        data_frames = []
        
        exchange = self.config.EXCHANGE
        symbol = self.config.OKX_INST_ID
        inst_type = self.config.OKX_INST_TYPE
        
        sqlite_df = self.sqlite_store.load_klines(
            exchange=exchange,
            inst_type=inst_type,
            symbol=symbol,
            bar='1m',
            start_time=start_time,
            end_time=end_time
        )
        
        if not sqlite_df.empty:
            try:
                df = self._preprocess_dataframe(sqlite_df)
                data_frames.append(df)
                logger.info(f"从SQLite加载测试数据: {len(df)} 条记录")
            except Exception as e:
                logger.warning(f"警告: 无法处理SQLite数据: {e}")
        
        if not data_frames:
            logger.warning("警告: SQLite中没有找到有效的数据，将生成示例数据")
            sample_df = self.generate_sample_data()
            data_frames.append(sample_df)
        
        return data_frames
    
    def generate_sample_data(self, days: int = 252, volatility: float = 0.02) -> pd.DataFrame:
        dates = pd.date_range(start='2023-01-01', periods=days, freq='D')
        
        initial_price = 100.0
        prices = [initial_price]
        
        for _ in range(days - 1):
            change = np.random.normal(0, volatility)
            next_price = prices[-1] * (1 + change)
            prices.append(max(next_price, 1.0))
        
        opens = prices
        closes = prices
        highs = [p * (1 + np.random.uniform(0, volatility/2)) for p in prices]
        lows = [p * (1 - np.random.uniform(0, volatility/2)) for p in prices]
        volumes = [int(np.random.randint(1000000, 10000000)) for _ in range(days)]
        amounts = [volumes[i] * closes[i] for i in range(days)]
        
        df = pd.DataFrame({
            'Time': dates,
            'Open': opens,
            'High': highs,
            'Low': lows,
            'Close': closes,
            'Volume': volumes,
            'Amount': amounts
        })
        
        df = self._add_technical_indicators(df)
        df = self._generate_sample_actions(df)
        
        return df
    
    def _add_technical_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        df['SMA_5'] = df['Close'].rolling(window=5).mean()
        df['SMA_10'] = df['Close'].rolling(window=10).mean()
        df['SMA_20'] = df['Close'].rolling(window=20).mean()
        
        delta = df['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        df['RSI'] = 100 - (100 / (1 + rs))
        
        ema_12 = df['Close'].ewm(span=12, adjust=False).mean()
        ema_26 = df['Close'].ewm(span=26, adjust=False).mean()
        df['MACD'] = ema_12 - ema_26
        df['MACD_signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
        
        df['BB_upper'] = df['SMA_20'] + 2 * df['Close'].rolling(window=20).std()
        df['BB_lower'] = df['SMA_20'] - 2 * df['Close'].rolling(window=20).std()
        
        df['Returns'] = df['Close'].pct_change()
        
        return df
    
    def _generate_sample_actions(self, df: pd.DataFrame) -> pd.DataFrame:
        df['Buy'] = 0
        df['Hold'] = 0
        df['Sell'] = 0
        
        for i in range(len(df)):
            if i < 5:
                df.at[i, 'Hold'] = 1
                continue
            
            returns = df['Returns'].iloc[i-5:i].sum()
            
            if returns > 0.05:
                df.at[i, 'Buy'] = 1
            elif returns < -0.05:
                df.at[i, 'Sell'] = 1
            else:
                df.at[i, 'Hold'] = 1
        
        return df
    
    def prepare_state_features(self, df: pd.DataFrame, current_idx: int, window_size: int = None) -> np.ndarray:
        window_size = window_size or self.config.WINDOW_SIZE
        
        if current_idx < window_size - 1:
            padding = np.zeros((window_size - current_idx - 1, self._get_feature_count()))
            if current_idx >= 0:
                features = self._extract_features(df, 0, current_idx + 1)
                return np.vstack([padding, features])
            return padding
        
        features = self._extract_features(df, current_idx - window_size + 1, current_idx + 1)
        return features
    
    def _get_feature_count(self) -> int:
        return 15
    
    def _extract_features(self, df: pd.DataFrame, start_idx: int, end_idx: int) -> np.ndarray:
        df_slice = df.iloc[start_idx:end_idx].copy()
        
        df_slice['Open_norm'] = (df_slice['Open'] - df_slice['Open'].iloc[0]) / (df_slice['Open'].iloc[0] + 1e-8)
        df_slice['High_norm'] = (df_slice['High'] - df_slice['High'].iloc[0]) / (df_slice['High'].iloc[0] + 1e-8)
        df_slice['Low_norm'] = (df_slice['Low'] - df_slice['Low'].iloc[0]) / (df_slice['Low'].iloc[0] + 1e-8)
        df_slice['Close_norm'] = (df_slice['Close'] - df_slice['Close'].iloc[0]) / (df_slice['Close'].iloc[0] + 1e-8)
        df_slice['Volume_norm'] = (df_slice['Volume'] - df_slice['Volume'].iloc[0]) / (df_slice['Volume'].iloc[0] + 1e-8)
        
        df_slice['SMA_5_norm'] = (df_slice['SMA_5'] - df_slice['SMA_5'].iloc[0]) / (df_slice['SMA_5'].iloc[0] + 1e-8) if 'SMA_5' in df_slice.columns else 0
        df_slice['SMA_10_norm'] = (df_slice['SMA_10'] - df_slice['SMA_10'].iloc[0]) / (df_slice['SMA_10'].iloc[0] + 1e-8) if 'SMA_10' in df_slice.columns else 0
        df_slice['RSI_norm'] = df_slice['RSI'] / 100.0 if 'RSI' in df_slice.columns else 0.5
        df_slice['MACD_norm'] = (df_slice['MACD'] - df_slice['MACD'].iloc[0]) / (abs(df_slice['MACD'].iloc[0]) + 1e-8) if 'MACD' in df_slice.columns else 0
        
        features = np.column_stack([
            df_slice['Open_norm'].fillna(0).values,
            df_slice['High_norm'].fillna(0).values,
            df_slice['Low_norm'].fillna(0).values,
            df_slice['Close_norm'].fillna(0).values,
            df_slice['Volume_norm'].fillna(0).values,
            df_slice['SMA_5_norm'].fillna(0).values,
            df_slice['SMA_10_norm'].fillna(0).values,
            df_slice['RSI_norm'].fillna(0.5).values,
            df_slice['MACD_norm'].fillna(0).values,
            df_slice['Returns'].fillna(0).values if 'Returns' in df_slice.columns else np.zeros(len(df_slice)),
        ])
        
        return features
    
    def create_realtime_input(self, time: str, open: float, high: float, low: float, 
                               close: float, volume: float, amount: float = None) -> pd.DataFrame:
        data = {
            'Time': pd.to_datetime(time),
            'Open': open,
            'High': high,
            'Low': low,
            'Close': close,
            'Volume': volume
        }
        if amount is not None:
            data['Amount'] = amount
        df = pd.DataFrame([data])
        return df
