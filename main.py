import argparse
from typing import Any

from config import Config
from stock_trader import StockTrader


def run_train_mode(config: Config, args: Any) -> None:
    trader = StockTrader(config)
    print(f"开始训练模式，回合数: {args.episodes}")
    trader.train(episodes=args.episodes, verbose=args.verbose)


def run_predict_mode(config: Config, args: Any) -> None:
    import os
    trader = StockTrader(config)
    
    print("预测模式")
    
    model_loaded = False
    if args.model_path:
        try:
            trader.load_trained_model(args.model_path)
            model_loaded = True
        except Exception as e:
            print(f"警告: 加载指定模型失败: {e}")
            print("将尝试使用默认模型路径，或仅使用LLM分析")
    elif os.path.exists(config.BEST_MODEL_PATH):
        try:
            trader.load_trained_model(config.BEST_MODEL_PATH)
            model_loaded = True
        except Exception as e:
            print(f"警告: 加载默认模型失败: {e}")
    else:
        print("提示: 未找到预训练模型，将仅使用LLM分析和规则分析")
        print("      可以先运行 `python main.py --mode train` 来训练模型")
    
    if not model_loaded:
        print("\n建议:")
        print("  1. 如需使用强化学习模型，请先运行: python main.py --mode train --episodes 1000")
        print("  2. 当前将使用LLM分析和规则分析进行预测\n")
    
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


def run_interactive_mode(config: Config, args: Any) -> None:
    import os
    trader = StockTrader(config)
    
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


def run_realtime_mode(config: Config, args: Any) -> None:
    from realtime_analyzer import RealtimeAnalyzer
    
    analyzer = RealtimeAnalyzer(
        config=config,
        bar_type=args.bar,
        interval=args.interval
    )
    
    use_llm = not args.no_llm
    save_data = not args.no_save
    simulate_trade = args.simulate
    use_aligned_time = not getattr(args, 'no_align', False)
    
    analyzer.initialize_trader(
        model_path=args.model_path,
        use_llm=use_llm
    )
    
    if args.once:
        analyzer.run_once(
            use_llm=use_llm,
            save_data=save_data,
            simulate_trade=simulate_trade,
            use_aligned_time=use_aligned_time
        )
    else:
        analyzer.start(
            use_llm=use_llm,
            save_data=save_data,
            simulate_trade=simulate_trade,
            use_aligned_time=use_aligned_time
        )


def parse_args():
    parser = argparse.ArgumentParser(description='AI股票交易系统 - 基于强化学习和LLM的K线分析')
    
    parser.add_argument('--mode', type=str, default='predict',
                        choices=['train', 'predict', 'interactive', 'realtime'],
                        help='运行模式: train(训练), predict(预测), interactive(交互模式), realtime(实时模式)')
    
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
    
    parser.add_argument('--bar', type=str, default='1m',
                        choices=['1m', '15m'],
                        help='K线周期: 1m (1分钟) 或 15m (15分钟) (默认: 1m) [仅realtime模式]')
    
    parser.add_argument('--interval', type=int, default=None,
                        help='刷新间隔（秒），默认: 1m=60秒, 15m=900秒 [仅realtime模式]')
    
    parser.add_argument('--no_llm', action='store_true', default=False,
                        help='禁用LLM分析，仅使用规则分析和强化学习 [仅realtime模式]')
    
    parser.add_argument('--no_save', action='store_true', default=False,
                        help='不保存K线数据到CSV文件 [仅realtime模式]')
    
    parser.add_argument('--simulate', action='store_true', default=False,
                        help='启用模拟交易 [仅realtime模式]')
    
    parser.add_argument('--once', action='store_true', default=False,
                        help='仅运行一次，不进行定时循环 [仅realtime模式]')
    
    parser.add_argument('--no_align', action='store_true', default=False,
                        help='禁用时间对齐（不延后10秒）[仅realtime模式]')
    
    return parser.parse_args()


def main():
    args = parse_args()
    config = Config()
    
    if args.mode == 'train':
        run_train_mode(config, args)
    elif args.mode == 'predict':
        run_predict_mode(config, args)
    elif args.mode == 'interactive':
        run_interactive_mode(config, args)
    elif args.mode == 'realtime':
        run_realtime_mode(config, args)


if __name__ == '__main__':
    main()
