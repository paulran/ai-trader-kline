import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple
from config import Config
from data_loader import DataLoader

class TradingEnv:
    def __init__(self, data: pd.DataFrame, config: Config = None):
        self.config = config or Config()
        self.data = data
        self.data_loader = DataLoader(self.config)
        
        self.initial_balance = self.config.INITIAL_BALANCE
        self.transaction_fee_rate = self.config.TRANSACTION_FEE_RATE
        self.window_size = self.config.WINDOW_SIZE
        self.max_shares = self.config.MAX_SHARES
        
        self.current_idx = 0
        self.balance = self.initial_balance
        self.shares_held = 0
        self.avg_cost = 0.0
        self.total_reward = 0.0
        self.done = False
        
        self.trade_history: List[Dict] = []
        self.portfolio_values: List[float] = []
        
    def reset(self) -> np.ndarray:
        self.current_idx = self.window_size - 1
        self.balance = self.initial_balance
        self.shares_held = 0
        self.avg_cost = 0.0
        self.total_reward = 0.0
        self.done = False
        
        self.trade_history = []
        self.portfolio_values = [self.initial_balance]
        
        return self._get_state()
    
    def step(self, action: int) -> Tuple[np.ndarray, float, bool, Dict]:
        if self.done:
            return self._get_state(), 0.0, True, {}
        
        current_price = self.data.iloc[self.current_idx]['Close']
        
        action_name = self.config.INT_TO_ACTION[action]
        trade_executed = False
        trade_info = {}
        
        if action_name == 'Buy' and self.balance > 0:
            shares_to_buy = min(
                int(self.balance / current_price),
                self.max_shares
            )
            
            if shares_to_buy > 0:
                cost = shares_to_buy * current_price
                fee = cost * self.transaction_fee_rate
                total_cost = cost + fee
                
                if total_cost <= self.balance:
                    new_total_shares = self.shares_held + shares_to_buy
                    new_total_cost = (self.shares_held * self.avg_cost) + cost
                    
                    self.avg_cost = new_total_cost / new_total_shares
                    self.shares_held = new_total_shares
                    self.balance -= total_cost
                    
                    trade_executed = True
                    trade_info = {
                        'type': 'Buy',
                        'shares': shares_to_buy,
                        'price': current_price,
                        'cost': cost,
                        'fee': fee,
                        'idx': self.current_idx
                    }
        
        elif action_name == 'Sell' and self.shares_held > 0:
            shares_to_sell = min(self.shares_held, self.max_shares)
            
            if shares_to_sell > 0:
                revenue = shares_to_sell * current_price
                fee = revenue * self.transaction_fee_rate
                total_revenue = revenue - fee
                
                self.shares_held -= shares_to_sell
                self.balance += total_revenue
                
                if self.shares_held == 0:
                    self.avg_cost = 0.0
                
                trade_executed = True
                trade_info = {
                    'type': 'Sell',
                    'shares': shares_to_sell,
                    'price': current_price,
                    'revenue': revenue,
                    'fee': fee,
                    'idx': self.current_idx
                }
        
        if trade_executed:
            self.trade_history.append(trade_info)
        
        portfolio_value = self._calculate_portfolio_value(current_price)
        self.portfolio_values.append(portfolio_value)
        
        reward = self._calculate_reward(portfolio_value, action_name, trade_executed)
        self.total_reward += reward
        
        self.current_idx += 1
        
        if self.current_idx >= len(self.data) - 1:
            self.done = True
            if self.shares_held > 0:
                liquidation_value = self.shares_held * current_price
                liquidation_fee = liquidation_value * self.transaction_fee_rate
                self.balance += (liquidation_value - liquidation_fee)
                self.shares_held = 0
        
        info = {
            'portfolio_value': portfolio_value,
            'balance': self.balance,
            'shares_held': self.shares_held,
            'avg_cost': self.avg_cost,
            'current_price': current_price,
            'action': action_name,
            'trade_executed': trade_executed,
            'trade_info': trade_info,
            'total_reward': self.total_reward,
            'idx': self.current_idx
        }
        
        next_state = self._get_state() if not self.done else np.zeros_like(self._get_state())
        
        return next_state, reward, self.done, info
    
    def _get_state(self) -> np.ndarray:
        state_features = self.data_loader.prepare_state_features(
            self.data, 
            self.current_idx, 
            self.window_size
        )
        
        portfolio_state = np.array([
            self.balance / self.initial_balance,
            self.shares_held / self.max_shares,
            (self.avg_cost / self.data.iloc[self.current_idx]['Close']) - 1 
                if self.shares_held > 0 and self.data.iloc[self.current_idx]['Close'] > 0 else 0.0
        ])
        
        portfolio_state = np.tile(portfolio_state, (self.window_size, 1))
        
        combined_state = np.concatenate([state_features, portfolio_state], axis=1)
        
        return combined_state.astype(np.float32)
    
    def _calculate_portfolio_value(self, current_price: float) -> float:
        return self.balance + (self.shares_held * current_price)
    
    def _calculate_reward(self, portfolio_value: float, action: str, trade_executed: bool) -> float:
        reward = 0.0
        
        if len(self.portfolio_values) >= 2:
            prev_value = self.portfolio_values[-2]
            if prev_value > 0:
                return_rate = (portfolio_value - prev_value) / prev_value
                reward = return_rate * 100
        
        if trade_executed and self.shares_held > 0:
            current_price = self.data.iloc[self.current_idx]['Close']
            if self.avg_cost > 0:
                profit_pct = (current_price - self.avg_cost) / self.avg_cost
                reward += profit_pct * 50
        
        if action == 'Hold' and self.shares_held > 0:
            current_price = self.data.iloc[self.current_idx]['Close']
            if self.avg_cost > 0:
                profit_pct = (current_price - self.avg_cost) / self.avg_cost
                reward += profit_pct * 10
        
        if self.done:
            total_return = (portfolio_value - self.initial_balance) / self.initial_balance
            if total_return > 0:
                reward += total_return * 200
        
        return reward
    
    def get_statistics(self) -> Dict:
        if len(self.portfolio_values) < 2:
            return {}
        
        portfolio_values = np.array(self.portfolio_values)
        total_return = (portfolio_values[-1] - self.initial_balance) / self.initial_balance * 100
        
        buy_hold_initial = self.data.iloc[self.window_size - 1]['Close']
        buy_hold_final = self.data.iloc[-1]['Close']
        buy_hold_return = (buy_hold_final - buy_hold_initial) / buy_hold_initial * 100
        
        returns = np.diff(portfolio_values) / portfolio_values[:-1]
        volatility = np.std(returns) * np.sqrt(252) * 100
        
        sharpe_ratio = 0.0
        if volatility > 0:
            risk_free_rate = 0.03 / 252
            excess_returns = returns - risk_free_rate
            sharpe_ratio = np.mean(excess_returns) / np.std(returns) * np.sqrt(252)
        
        max_drawdown = 0.0
        peak = portfolio_values[0]
        for value in portfolio_values:
            if value > peak:
                peak = value
            drawdown = (peak - value) / peak * 100
            if drawdown > max_drawdown:
                max_drawdown = drawdown
        
        win_trades = 0
        total_trades = len(self.trade_history)
        
        for i in range(1, len(self.trade_history)):
            prev_trade = self.trade_history[i-1]
            curr_trade = self.trade_history[i]
            
            if prev_trade['type'] == 'Buy' and curr_trade['type'] == 'Sell':
                if curr_trade['price'] > prev_trade['price']:
                    win_trades += 1
        
        win_rate = (win_trades / max(1, total_trades // 2)) * 100 if total_trades > 0 else 0.0
        
        return {
            'total_return_pct': total_return,
            'buy_hold_return_pct': buy_hold_return,
            'volatility_pct': volatility,
            'sharpe_ratio': sharpe_ratio,
            'max_drawdown_pct': max_drawdown,
            'total_trades': total_trades,
            'win_rate_pct': win_rate,
            'final_portfolio_value': portfolio_values[-1],
            'initial_balance': self.initial_balance
        }
    
    def render(self, mode: str = 'human'):
        stats = self.get_statistics()
        if not stats:
            print("环境尚未初始化，无法显示统计信息。")
            return
        
        print(f"\n{'='*60}")
        print("交易环境统计信息")
        print(f"{'='*60}")
        print(f"总收益率: {stats['total_return_pct']:.2f}%")
        print(f"买入持有收益率: {stats['buy_hold_return_pct']:.2f}%")
        print(f"波动率: {stats['volatility_pct']:.2f}%")
        print(f"夏普比率: {stats['sharpe_ratio']:.3f}")
        print(f"最大回撤: {stats['max_drawdown_pct']:.2f}%")
        print(f"总交易次数: {stats['total_trades']}")
        print(f"胜率: {stats['win_rate_pct']:.2f}%")
        print(f"最终投资组合价值: ${stats['final_portfolio_value']:,.2f}")
        print(f"{'='*60}\n")
