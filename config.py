import os
from typing import Optional

class Config:
    # 数据配置
    DATA_PATH = os.getenv("DATA_PATH", "./data")
    TRAIN_DATA_PATH = os.getenv("TRAIN_DATA_PATH", os.path.join(DATA_PATH, "train"))
    TEST_DATA_PATH = os.getenv("TEST_DATA_PATH", os.path.join(DATA_PATH, "test"))
    
    # 模型配置
    MODEL_NAME = os.getenv("MODEL_NAME", "deepseek-ai/DeepSeek-R1-Distill-Qwen-7B")
    MODEL_DEVICE = os.getenv("MODEL_DEVICE", "cpu")  # 可选: "cuda", "mps"
    
    # 强化学习配置
    RL_LEARNING_RATE = float(os.getenv("RL_LEARNING_RATE", "1e-4"))
    RL_GAMMA = float(os.getenv("RL_GAMMA", "0.99"))
    RL_EPSILON_START = float(os.getenv("RL_EPSILON_START", "1.0"))
    RL_EPSILON_END = float(os.getenv("RL_EPSILON_END", "0.01"))
    RL_EPSILON_DECAY = float(os.getenv("RL_EPSILON_DECAY", "0.995"))
    RL_TARGET_UPDATE = int(os.getenv("RL_TARGET_UPDATE", "100"))
    RL_MEMORY_SIZE = int(os.getenv("RL_MEMORY_SIZE", "10000"))
    RL_BATCH_SIZE = int(os.getenv("RL_BATCH_SIZE", "64"))
    RL_TRAIN_EPISODES = int(os.getenv("RL_TRAIN_EPISODES", "1000"))
    
    # 交易环境配置
    INITIAL_BALANCE = float(os.getenv("INITIAL_BALANCE", "100000"))
    TRANSACTION_FEE_RATE = float(os.getenv("TRANSACTION_FEE_RATE", "0.001"))  # 0.1% 手续费
    WINDOW_SIZE = int(os.getenv("WINDOW_SIZE", "30"))  # 观察窗口大小
    MAX_SHARES = int(os.getenv("MAX_SHARES", "100"))  # 每次最大交易股数
    
    # 动作空间
    ACTIONS = ["Buy", "Hold", "Sell"]
    ACTION_TO_INT = {"Buy": 0, "Hold": 1, "Sell": 2}
    INT_TO_ACTION = {0: "Buy", 1: "Hold", 2: "Sell"}
    
    # DeepSeek API配置（如果使用API而不是本地模型）
    DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
    DEEPSEEK_API_URL = os.getenv("DEEPSEEK_API_URL", "https://api.deepseek.com/v1/chat/completions")
    USE_DEEPSEEK_API = os.getenv("USE_DEEPSEEK_API", "false").lower() == "true"
    
    # 训练和模型保存路径
    CHECKPOINT_PATH = os.getenv("CHECKPOINT_PATH", "./checkpoints")
    BEST_MODEL_PATH = os.path.join(CHECKPOINT_PATH, "best_model.pt")
    LATEST_MODEL_PATH = os.path.join(CHECKPOINT_PATH, "latest_model.pt")
    
    # OKX API配置
    OKX_API_URL = os.getenv("OKX_API_URL", "https://www.okx.com/api/v5/market/candles")
    OKX_INST_ID = os.getenv("OKX_INST_ID", "BTC-USDT")
    OKX_BAR_1M = "1m"
    OKX_BAR_15M = "15m"
    OKX_TIMEOUT = int(os.getenv("OKX_TIMEOUT", "20"))
    
    # 实时分析配置
    REALTIME_INTERVAL_1M = int(os.getenv("REALTIME_INTERVAL_1M", "60"))
    REALTIME_INTERVAL_15M = int(os.getenv("REALTIME_INTERVAL_15M", "900"))
    REALTIME_DATA_PATH = os.getenv("REALTIME_DATA_PATH", os.path.join(DATA_PATH, "realtime"))
    REALTIME_USE_LLM = os.getenv("REALTIME_USE_LLM", "true").lower() == "true"
    REALTIME_SIMULATE_TRADE = os.getenv("REALTIME_SIMULATE_TRADE", "false").lower() == "true"
    
    # 飞书通知配置
    FEISHU_WEBHOOK_URL = os.getenv("FEISHU_WEBHOOK_URL", "")
    FEISHU_SECRET = os.getenv("FEISHU_SECRET", "")  # 可选：用于签名验证
    FEISHU_ENABLED = os.getenv("FEISHU_ENABLED", "false").lower() == "true"
    FEISHU_TIMEOUT = int(os.getenv("FEISHU_TIMEOUT", "10"))
    
    # 日志配置
    LOG_PATH = os.getenv("LOG_PATH", "./logs")
    LOG_FILENAME = os.getenv("LOG_FILENAME", "ai_trader.log")
    LOG_MAX_BYTES = int(os.getenv("LOG_MAX_BYTES", str(10 * 1024 * 1024)))  # 10MB
    LOG_BACKUP_COUNT = int(os.getenv("LOG_BACKUP_COUNT", "5"))  # 最多5个备份文件
    
    @classmethod
    def create_directories(cls):
        os.makedirs(cls.DATA_PATH, exist_ok=True)
        os.makedirs(cls.TRAIN_DATA_PATH, exist_ok=True)
        os.makedirs(cls.TEST_DATA_PATH, exist_ok=True)
        os.makedirs(cls.CHECKPOINT_PATH, exist_ok=True)
        os.makedirs(cls.REALTIME_DATA_PATH, exist_ok=True)
        os.makedirs(cls.LOG_PATH, exist_ok=True)
