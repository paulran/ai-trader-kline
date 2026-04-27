# AI-Trader-KLine

一个基于Python的股票K线分析系统，使用DeepSeek开源模型和强化学习进行交易决策。

## 项目结构

```
ai-trader-kline/
├── config.py           # 配置文件，包含所有参数设置
├── data_loader.py      # 数据加载和预处理模块
├── trading_env.py      # 强化学习交易环境
├── dqn_model.py        # DQN强化学习模型
├── deepseek_analyzer.py # DeepSeek LLM分析器
├── main.py             # 主程序入口
├── requirements.txt    # 依赖包列表
├── tools/
│   ├── get_okx_1min_candle_data.py  # OKX 1分钟K线数据获取工具
│   └── realtime_kline_analyzer.py   # 实时K线分析器（定时获取+AI分析）
├── data/
│   ├── train/          # 训练数据
│   ├── test/           # 测试数据
│   └── realtime/       # 实时数据保存目录
└── checkpoints/        # 模型保存目录
```

## 主要功能

### 1. 数据处理模块 (`data_loader.py`)
- 支持加载TimeOHLCV格式的CSV数据
- 自动计算技术指标：SMA、RSI、MACD、布林带等
- 支持生成示例数据（当没有真实数据时）
- 实时K线数据输入处理

### 2. 交易环境 (`trading_env.py`)
- 符合OpenAI Gym风格的强化学习环境
- 支持买入(Buy)、持有(Hold)、卖出(Sell)三种动作
- 包含交易手续费计算
- 完整的投资组合跟踪和统计指标计算
- 奖励函数设计考虑收益率、交易效率和最终收益

### 3. 强化学习模型 (`dqn_model.py`)
- 使用Deep Q-Network (DQN)算法
- 包含经验回放缓冲区
- 目标网络定期更新，提高训练稳定性
- 支持CPU/GPU/MPS加速
- 模型保存和加载功能

### 4. DeepSeek LLM分析器 (`deepseek_analyzer.py`)
- 支持两种模式：
  - **API模式**：使用DeepSeek官方API（需要API密钥）
  - **本地模式**：加载开源DeepSeek模型进行推理
- 自动生成K线分析提示词
- 技术指标分析（均线、RSI、MACD等）
- 规则回退机制（当LLM不可用时使用规则分析）
- 信号组合功能：结合RL和LLM的结果

### 5. 主程序 (`main.py`)
- **三种运行模式**：
  - `train`：训练强化学习模型
  - `predict`：使用训练好的模型进行预测
  - `interactive`：交互模式，支持实时命令操作

## 使用方法

### 1. 安装依赖
```bash
pip install -r requirements.txt
```

### 2. 训练模型
```bash
python main.py --mode train --episodes 1000
```

### 3. 预测模式
```bash
# 从文件加载K线数据进行预测
python main.py --mode predict --kline_file your_data.csv --use_llm

# 交互式输入实时K线数据
python main.py --mode predict --use_llm
```

### 4. 交互模式
```bash
python main.py --mode interactive
```
在交互模式下可以使用命令：
- `train [episodes]` - 训练模型
- `load [path]` - 加载模型
- `kline time,open,high,low,close,volume` - 输入K线数据
- `portfolio` - 查看投资组合状态
- `reset` - 重置投资组合

## 配置选项

可以通过环境变量或修改`config.py`来自定义：

- **模型配置**：选择DeepSeek模型名称、设备（CPU/GPU）
- **强化学习参数**：学习率、gamma、epsilon衰减等
- **交易参数**：初始资金、手续费率、窗口大小、最大交易股数
- **API配置**：如果使用DeepSeek API，需要设置`DEEPSEEK_API_KEY`

## 信号组合机制

系统会组合强化学习模型和LLM分析的结果：
- 强化学习模型提供基于历史数据的最优决策
- LLM提供基于技术分析的市场解读
- 使用投票机制，根据置信度加权，给出最终决策

## 技术指标

系统自动计算以下指标用于分析：
- SMA_5, SMA_10, SMA_20 - 简单移动平均线
- RSI - 相对强弱指标
- MACD - 移动平均收敛发散指标
- 布林带
- 收益率和动量

这个系统可以：
1. 使用历史TimeOHLCV数据进行强化学习训练
2. 结合DeepSeek LLM进行K线技术分析
3. 输入实时K线数据，返回Buy/Hold/Sell操作建议