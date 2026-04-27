import argparse
import os
import sys
import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple

from config import Config
from data_loader import DataLoader
from trading_env import TradingEnv
from dqn_model import DQNAgent
from deepseek_analyzer import DeepSeekAnalyzer


class StockTrader:
    def __init__(self, config: Config = None):
        self.config = config or Config()
        self.config.create_directories()
        
        self.data_loader = DataLoader(self.config)
        self.agent: Optional[DQNAgent] = None
        self.analyzer: Optional[DeepSeekAnalyzer] = None
        
        self.recent_actions: List[str] = []
        self.portfolio_info: Dict = {
            'shares_held': 0,
            'avg_cost': 0.0,
            'balance': self.config.INITIAL_BALANCE
        }
        
        self.historical_klines: pd.DataFrame = pd.DataFrame()
    
    def train(self, episodes: int = None, verbose: bool = True):
        if verbose:
            print("="*60)
            print("开始训练强化学习模型")
            print("="*60)
        
        episodes = episodes or self.config.RL_TRAIN_EPISODES
        
        train_data = self.data_loader.load_training_data()
        
        if not train_data:
            raise ValueError("没有可用的训练数据")
        
        sample_env = TradingEnv(train_data[0], self.config)
        sample_state = sample_env.reset()
        state_shape = sample_state.shape
        action_size = len(self.config.ACTIONS)
        
        self.agent = DQNAgent(
            config=self.config,
            state_shape=state_shape,
            action_size=action_size
        )
        
        best_total_return = float('-inf')
        
        for episode in range(episodes):
            total_reward = 0.0
            episode_trades = 0
            
            for data_idx, data in enumerate(train_data):
                env = TradingEnv(data, self.config)
                state = env.reset()
                done = False
                
                while not done:
                    action = self.agent.select_action(state, training=True)
                    next_state, reward, done, info = env.step(action)
                    
                    self.agent.memory.push(state, action, reward, next_state, done)
                    
                    loss = self.agent.optimize_model()
                    
                    state = next_state
                    total_reward += reward
                    
                    if info.get('trade_executed', False):
                        episode_trades += 1
                
                self.agent.update_epsilon()
            
            stats = env.get_statistics() if 'env' in locals() else {}
            total_return = stats.get('total_return_pct', 0)
            
            if total_return > best_total_return:
                best_total_return = total_return
                self.agent.best_reward = best_total_return
                self.agent.save_model(self.config.BEST_MODEL_PATH)
            
            self.agent.save_model(self.config.LATEST_MODEL_PATH)
            
            if verbose and (episode + 1) % max(1, episodes // 10) == 0:
                print(f"回合 {episode+1}/{episodes} - "
                      f"总奖励: {total_reward:.2f}, "
                      f"收益率: {total_return:.2f}%, "
                      f"交易次数: {episode_trades}, "
                      f"Epsilon: {self.agent.epsilon:.4f}")
        
        if verbose:
            print("="*60)
            print("训练完成")
            print(f"最佳收益率: {best_total_return:.2f}%")
            print("="*60)
        
        return best_total_return
    
    def load_trained_model(self, model_path: str = None):
        model_path = model_path or self.config.BEST_MODEL_PATH
        
        if not os.path.exists(model_path):
            raise FileNotFoundError(f"模型文件不存在: {model_path}")
        
        if self.agent is None:
            sample_data = self.data_loader.generate_sample_data(days=100)
            sample_env = TradingEnv(sample_data, self.config)
            sample_state = sample_env.reset()
            state_shape = sample_state.shape
            action_size = len(self.config.ACTIONS)
            
            self.agent = DQNAgent(
                config=self.config,
                state_shape=state_shape,
                action_size=action_size
            )
        
        self.agent.load_model(model_path)
        self.agent.epsilon = self.config.RL_EPSILON_END
        
        print("模型加载完成，准备进行预测")
    
    def initialize_analyzer(self):
        if self.analyzer is None:
            print("初始化DeepSeek分析器...")
            self.analyzer = DeepSeekAnalyzer(self.config)
    
    def predict_single_kline(self, time: str, open: float, high: float, 
                              low: float, close: float, volume: float,
                              use_llm: bool = True) -> Dict:
        new_kline = self.data_loader.create_realtime_input(
            time, open, high, low, close, volume
        )
        
        if self.historical_klines.empty:
            self.historical_klines = new_kline
        else:
            self.historical_klines = pd.concat([self.historical_klines, new_kline], ignore_index=True)
        
        if len(self.historical_klines) < self.config.WINDOW_SIZE:
            print(f"警告: 历史数据不足{self.config.WINDOW_SIZE}根K线，当前: {len(self.historical_klines)}根")
            print("建议继续添加更多历史数据以获得更准确的预测")
        
        if len(self.historical_klines) >= 5:
            self.historical_klines = self.data_loader._add_technical_indicators(self.historical_klines)
        
        result = {
            'kline_info': {
                'time': time,
                'open': open,
                'high': high,
                'low': low,
                'close': close,
                'volume': volume
            },
            'rl_prediction': None,
            'llm_analysis': None,
            'final_decision': None
        }
        
        if self.agent is not None and len(self.historical_klines) >= self.config.WINDOW_SIZE:
            current_idx = len(self.historical_klines) - 1
            state = self.data_loader.prepare_state_features(
                self.historical_klines,
                current_idx,
                self.config.WINDOW_SIZE
            )
            
            portfolio_state = np.array([
                self.portfolio_info['balance'] / self.config.INITIAL_BALANCE,
                self.portfolio_info['shares_held'] / self.config.MAX_SHARES,
                (self.portfolio_info['avg_cost'] / close) - 1 
                    if self.portfolio_info['shares_held'] > 0 and close > 0 else 0.0
            ])
            portfolio_state = np.tile(portfolio_state, (self.config.WINDOW_SIZE, 1))
            
            full_state = np.concatenate([state, portfolio_state], axis=1).astype(np.float32)
            
            rl_action_int, rl_q_values = self.agent.predict_action(full_state)
            rl_action_name = self.config.INT_TO_ACTION[rl_action_int]
            
            result['rl_prediction'] = {
                'action': rl_action_name,
                'action_int': rl_action_int,
                'q_values': rl_q_values
            }
        
        if use_llm:
            if self.analyzer is None:
                self.initialize_analyzer()
            
            llm_analysis = self.analyzer.analyze_kline(
                self.historical_klines,
                self.recent_actions,
                self.portfolio_info
            )
            result['llm_analysis'] = llm_analysis
        
        if result['rl_prediction'] is not None and result['llm_analysis'] is not None:
            if self.analyzer is None:
                self.initialize_analyzer()
            
            final_action_int, final_action_name, combination_info = self.analyzer.combine_signals(
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
            self.recent_actions.append(result['final_decision']['action'])
            if len(self.recent_actions) > 50:
                self.recent_actions = self.recent_actions[-50:]
        
        return result
    
    def simulate_trade(self, action: str, price: float):
        fee_rate = self.config.TRANSACTION_FEE_RATE
        max_shares = self.config.MAX_SHARES
        
        if action == 'Buy' and self.portfolio_info['balance'] > 0:
            max_possible = int(self.portfolio_info['balance'] / price)
            shares_to_buy = min(max_possible, max_shares)
            
            if shares_to_buy > 0:
                cost = shares_to_buy * price
                fee = cost * fee_rate
                total_cost = cost + fee
                
                if total_cost <= self.portfolio_info['balance']:
                    new_total_shares = self.portfolio_info['shares_held'] + shares_to_buy
                    new_total_cost = (self.portfolio_info['shares_held'] * self.portfolio_info['avg_cost']) + cost
                    
                    self.portfolio_info['avg_cost'] = new_total_cost / new_total_shares
                    self.portfolio_info['shares_held'] = new_total_shares
                    self.portfolio_info['balance'] -= total_cost
                    
                    print(f"模拟买入: {shares_to_buy}股 @ ${price:.2f}, 成本: ${total_cost:.2f}")
        
        elif action == 'Sell' and self.portfolio_info['shares_held'] > 0:
            shares_to_sell = min(self.portfolio_info['shares_held'], max_shares)
            
            if shares_to_sell > 0:
                revenue = shares_to_sell * price
                fee = revenue * fee_rate
                total_revenue = revenue - fee
                
                self.portfolio_info['shares_held'] -= shares_to_sell
                self.portfolio_info['balance'] += total_revenue
                
                if self.portfolio_info['shares_held'] == 0:
                    self.portfolio_info['avg_cost'] = 0.0
                
                print(f"模拟卖出: {shares_to_sell}股 @ ${price:.2f}, 收入: ${total_revenue:.2f}")
        
        elif action == 'Hold':
            print("模拟持有: 不执行任何操作")
        
        portfolio_value = self.portfolio_info['balance'] + (self.portfolio_info['shares_held'] * price)
        print(f"当前投资组合: 余额=${self.portfolio_info['balance']:.2f}, "
              f"持仓={self.portfolio_info['shares_held']}股, "
              f"总成本=${self.portfolio_info['avg_cost']:.2f}/股, "
              f"总价值=${portfolio_value:.2f}")
    
    def reset_portfolio(self):
        self.portfolio_info = {
            'shares_held': 0,
            'avg_cost': 0.0,
            'balance': self.config.INITIAL_BALANCE
        }
        self.recent_actions = []
        print("投资组合已重置")
    
    def load_historical_data(self, data: pd.DataFrame):
        self.historical_klines = data.copy()
        if len(self.historical_klines) >= 5:
            self.historical_klines = self.data_loader._add_technical_indicators(self.historical_klines)
        print(f"已加载 {len(self.historical_klines)} 根历史K线数据")


def main():
    parser = argparse.ArgumentParser(description='AI股票交易系统 - 基于强化学习和LLM的K线分析')
    
    parser.add_argument('--mode', type=str, default='predict',
                        choices=['train', 'predict', 'interactive'],
                        help='运行模式: train(训练), predict(预测), interactive(交互模式)')
    
    parser.add_argument('--model_path', type=str, default=None,
                        help='训练模型的路径（用于预测模式）')
    
    parser.add_argument('--episodes', type=int, default=1000,
                        help='训练回合数 (默认: 1000)')
    
    parser.add_argument('--use_llm', action='store_true', default=True,
                        help='是否使用LLM进行K线分析 (默认: True)')
    
    parser.add_argument('--verbose', action='store_true', default=True,
                        help='是否显示详细输出 (默认: True)')
    
    parser.add_argument('--kline_file', type=str, default=None,
                        help='包含K线数据的CSV文件路径（用于批量预测）')
    
    args = parser.parse_args()
    
    config = Config()
    trader = StockTrader(config)
    
    if args.mode == 'train':
        print(f"开始训练模式，回合数: {args.episodes}")
        trader.train(episodes=args.episodes, verbose=args.verbose)
    
    elif args.mode == 'predict':
        print("预测模式")
        
        if args.model_path:
            trader.load_trained_model(args.model_path)
        elif os.path.exists(config.BEST_MODEL_PATH):
            trader.load_trained_model(config.BEST_MODEL_PATH)
        else:
            print("警告: 未找到训练好的模型，将仅使用LLM分析")
        
        if args.use_llm:
            trader.initialize_analyzer()
        
        if args.kline_file:
            print(f"加载K线文件: {args.kline_file}")
            data = trader.data_loader.load_csv_file(args.kline_file)
            trader.load_historical_data(data)
            
            print(f"已加载 {len(data)} 根K线，开始分析最后一根K线...")
            
            latest = data.iloc[-1]
            result = trader.predict_single_kline(
                time=str(latest['Time']),
                open=latest['Open'],
                high=latest['High'],
                low=latest['Low'],
                close=latest['Close'],
                volume=latest['Volume'],
                use_llm=args.use_llm
            )
            
            print("\n" + "="*60)
            print("预测结果")
            print("="*60)
            
            if result['rl_prediction']:
                print(f"\n强化学习预测:")
                print(f"  推荐操作: {result['rl_prediction']['action']}")
                print(f"  Q值: {result['rl_prediction']['q_values']}")
            
            if result['llm_analysis']:
                print(f"\nLLM分析结果:")
                print(f"  技术分析: {result['llm_analysis']['analysis']}")
                print(f"  风险评估: {result['llm_analysis']['risk_assessment']}")
                print(f"  推荐操作: {result['llm_analysis']['recommended_action']}")
                print(f"  置信度: {result['llm_analysis']['confidence']:.2f}")
            
            if result['final_decision']:
                print(f"\n{'='*60}")
                print(f"最终决策: {result['final_decision']['action']}")
                print(f"{'='*60}")
                
                if 'combination_info' in result['final_decision']:
                    print(result['final_decision']['combination_info']['combination_reason'])
        
        else:
            print("\n请输入实时K线数据进行预测:")
            print("格式: time,open,high,low,close,volume")
            print("例如: 2024-01-15 10:30:00,150.50,152.00,149.80,151.20,10000000")
            print("输入 'quit' 退出")
            
            while True:
                try:
                    user_input = input("\n输入K线数据: ").strip()
                    
                    if user_input.lower() == 'quit':
                        break
                    
                    parts = user_input.split(',')
                    if len(parts) != 6:
                        print("错误: 请输入6个字段: time,open,high,low,close,volume")
                        continue
                    
                    time = parts[0].strip()
                    open_price = float(parts[1].strip())
                    high = float(parts[2].strip())
                    low = float(parts[3].strip())
                    close = float(parts[4].strip())
                    volume = float(parts[5].strip())
                    
                    result = trader.predict_single_kline(
                        time=time,
                        open=open_price,
                        high=high,
                        low=low,
                        close=close,
                        volume=volume,
                        use_llm=args.use_llm
                    )
                    
                    if result['final_decision']:
                        print(f"\n推荐操作: {result['final_decision']['action']}")
                        
                        if result['llm_analysis']:
                            print(f"分析: {result['llm_analysis']['analysis']}")
                            print(f"理由: {result['llm_analysis']['reason']}")
                        
                        simulate = input("是否模拟执行此操作? (y/n): ").strip().lower()
                        if simulate == 'y':
                            trader.simulate_trade(result['final_decision']['action'], close)
                    
                except Exception as e:
                    print(f"错误: {e}")
    
    elif args.mode == 'interactive':
        print("="*60)
        print("交互模式")
        print("="*60)
        print("可用命令:")
        print("  train - 训练模型")
        print("  load [path] - 加载模型")
        print("  kline [data] - 输入单根K线数据进行预测")
        print("  load_data [file] - 从CSV文件加载历史数据")
        print("  portfolio - 显示当前投资组合状态")
        print("  reset - 重置投资组合")
        print("  help - 显示帮助信息")
        print("  quit - 退出程序")
        print("="*60)
        
        while True:
            try:
                command = input("\nAI Trader > ").strip()
                
                if not command:
                    continue
                
                parts = command.split()
                cmd = parts[0].lower()
                
                if cmd == 'quit':
                    print("再见!")
                    break
                
                elif cmd == 'help':
                    print("""
命令说明:
  train [episodes] - 训练模型，可选指定回合数（默认1000）
  load [path] - 从指定路径加载模型
  kline time,open,high,low,close,volume - 输入K线数据进行预测
  load_data [csv_file] - 从CSV文件加载历史K线数据
  portfolio - 显示当前投资组合状态
  reset - 重置投资组合
  quit - 退出程序
                    """)
                
                elif cmd == 'train':
                    episodes = int(parts[1]) if len(parts) > 1 else 1000
                    print(f"开始训练，回合数: {episodes}")
                    trader.train(episodes=episodes)
                
                elif cmd == 'load':
                    if len(parts) < 2:
                        if os.path.exists(config.BEST_MODEL_PATH):
                            trader.load_trained_model(config.BEST_MODEL_PATH)
                        else:
                            print("请指定模型路径: load <model_path>")
                    else:
                        trader.load_trained_model(parts[1])
                
                elif cmd == 'kline':
                    if len(parts) < 2:
                        print("用法: kline time,open,high,low,close,volume")
                        continue
                    
                    kline_data = ' '.join(parts[1:])
                    data_parts = kline_data.split(',')
                    
                    if len(data_parts) != 6:
                        print("错误: 请输入6个字段: time,open,high,low,close,volume")
                        continue
                    
                    try:
                        time = data_parts[0].strip()
                        open_price = float(data_parts[1].strip())
                        high = float(data_parts[2].strip())
                        low = float(data_parts[3].strip())
                        close = float(data_parts[4].strip())
                        volume = float(data_parts[5].strip())
                        
                        result = trader.predict_single_kline(
                            time=time,
                            open=open_price,
                            high=high,
                            low=low,
                            close=close,
                            volume=volume,
                            use_llm=args.use_llm
                        )
                        
                        if result['final_decision']:
                            print(f"\n推荐操作: {result['final_decision']['action']}")
                            
                            if result['llm_analysis']:
                                print(f"分析: {result['llm_analysis']['analysis']}")
                                print(f"风险: {result['llm_analysis']['risk_assessment']}")
                                print(f"理由: {result['llm_analysis']['reason']}")
                            
                            simulate = input("模拟执行? (y/n): ").strip().lower()
                            if simulate == 'y':
                                trader.simulate_trade(result['final_decision']['action'], close)
                        
                    except Exception as e:
                        print(f"错误: {e}")
                
                elif cmd == 'load_data':
                    if len(parts) < 2:
                        print("用法: load_data <csv_file>")
                        continue
                    
                    try:
                        data = trader.data_loader.load_csv_file(parts[1])
                        trader.load_historical_data(data)
                        print(f"成功加载 {len(data)} 根K线数据")
                    except Exception as e:
                        print(f"加载失败: {e}")
                
                elif cmd == 'portfolio':
                    print(f"\n投资组合状态:")
                    print(f"  余额: ${trader.portfolio_info['balance']:.2f}")
                    print(f"  持仓: {trader.portfolio_info['shares_held']} 股")
                    print(f"  平均成本: ${trader.portfolio_info['avg_cost']:.2f}")
                    if len(trader.recent_actions) > 0:
                        print(f"  最近操作: {', '.join(trader.recent_actions[-5:])}")
                
                elif cmd == 'reset':
                    trader.reset_portfolio()
                    print("投资组合已重置")
                
                else:
                    print(f"未知命令: {cmd}，输入 'help' 查看可用命令")
            
            except Exception as e:
                print(f"错误: {e}")


if __name__ == '__main__':
    main()
