import time
import hashlib
import hmac
import base64
import requests
from typing import Optional, Dict, Any
from config import Config


class FeishuNotifier:
    """飞书自定义机器人通知类
    
    支持通过飞书自定义机器人发送消息，包含以下功能：
    1. 发送文本消息
    2. 支持签名验证（可选）
    3. 支持配置 webhook 地址
    """
    
    def __init__(
        self,
        webhook_url: Optional[str] = None,
        secret: Optional[str] = None,
        timeout: Optional[int] = None,
        enabled: Optional[bool] = None
    ):
        """初始化飞书通知器
        
        Args:
            webhook_url: 飞书机器人 webhook 地址，默认从配置读取
            secret: 签名密钥，可选，默认从配置读取
            timeout: 请求超时时间（秒），默认从配置读取
            enabled: 是否启用通知，默认从配置读取
        """
        self.webhook_url = webhook_url or Config.FEISHU_WEBHOOK_URL
        self.secret = secret or Config.FEISHU_SECRET
        self.timeout = timeout or Config.FEISHU_TIMEOUT
        self.enabled = enabled if enabled is not None else Config.FEISHU_ENABLED
        
        if self.secret:
            self.enabled = True
    
    def _generate_sign(self, timestamp: int, secret: str) -> str:
        """生成飞书签名
        
        签名算法：HmacSHA256 算法，使用密钥对 时间戳 + "\n" + 密钥 进行签名，然后进行 Base64 编码。
        
        Args:
            timestamp: 当前时间戳（秒）
            secret: 签名密钥
            
        Returns:
            签名字符串
        """
        string_to_sign = f"{timestamp}\n{secret}"
        hmac_obj = hmac.new(
            secret.encode('utf-8'),
            string_to_sign.encode('utf-8'),
            hashlib.sha256
        )
        sign = base64.b64encode(hmac_obj.digest()).decode('utf-8')
        return sign
    
    def send(self, msg: str, msg_type: str = "text") -> Dict[str, Any]:
        """发送消息到飞书
        
        这是对外提供的主要接口，用法类似 send(msg)。
        
        Args:
            msg: 要发送的消息内容
            msg_type: 消息类型，目前支持 "text"
            
        Returns:
            包含发送结果的字典，结构如下：
            {
                'success': bool,  # 是否发送成功
                'message': str,   # 结果描述
                'response': dict, # 飞书 API 返回的原始响应（如果有）
                'error': str      # 错误信息（如果有）
            }
        """
        result = {
            'success': False,
            'message': '',
            'response': None,
            'error': None
        }
        
        if not self.enabled:
            result['message'] = '飞书通知功能未启用'
            return result
        
        if not self.webhook_url:
            result['error'] = '未配置飞书 webhook 地址'
            result['message'] = '发送失败：缺少 webhook 地址'
            return result
        
        try:
            payload = self._build_payload(msg, msg_type)
            
            headers = {
                'Content-Type': 'application/json'
            }
            
            if self.secret:
                timestamp = int(time.time())
                sign = self._generate_sign(timestamp, self.secret)
                payload['timestamp'] = str(timestamp)
                payload['sign'] = sign
            
            response = requests.post(
                self.webhook_url,
                json=payload,
                headers=headers,
                timeout=self.timeout
            )
            
            response_data = response.json()
            result['response'] = response_data
            
            if response.status_code == 200 and response_data.get('StatusCode') == 0:
                result['success'] = True
                result['message'] = '消息发送成功'
            else:
                result['error'] = response_data.get('msg', '未知错误')
                result['message'] = f'发送失败：{result["error"]}'
        
        except requests.exceptions.Timeout:
            result['error'] = '请求超时'
            result['message'] = '发送失败：请求超时'
        except requests.exceptions.RequestException as e:
            result['error'] = str(e)
            result['message'] = f'发送失败：网络错误'
        except Exception as e:
            result['error'] = str(e)
            result['message'] = f'发送失败：未知错误'
        
        return result
    
    def _build_payload(self, msg: str, msg_type: str) -> Dict[str, Any]:
        """构建请求 payload
        
        Args:
            msg: 消息内容
            msg_type: 消息类型
            
        Returns:
            飞书 API 要求的 payload 字典
        """
        if msg_type == "text":
            return {
                'msg_type': 'text',
                'content': {
                    'text': msg
                }
            }
        else:
            raise ValueError(f"不支持的消息类型: {msg_type}")
    
    def send_text(self, text: str) -> Dict[str, Any]:
        """发送文本消息（send 方法的别名）
        
        Args:
            text: 文本内容
            
        Returns:
            与 send 方法相同的结果字典
        """
        return self.send(text, msg_type="text")


# 全局单例实例，方便直接使用
_default_notifier: Optional[FeishuNotifier] = None


def get_notifier() -> FeishuNotifier:
    """获取全局默认的飞书通知器实例
    
    Returns:
        FeishuNotifier 实例
    """
    global _default_notifier
    if _default_notifier is None:
        _default_notifier = FeishuNotifier()
    return _default_notifier


def send(msg: str) -> Dict[str, Any]:
    """全局便捷方法：发送消息到飞书
    
    这是对外提供的主要接口，直接调用 send(msg) 即可发送消息。
    
    用法示例：
        # 简单使用
        send("Hello, Feishu!")
        
        # 带配置使用
        from config import Config
        Config.FEISHU_WEBHOOK_URL = "your_webhook_url"
        Config.FEISHU_ENABLED = True
        send("交易信号：买入 BTC-USDT")
    
    Args:
        msg: 要发送的消息内容
        
    Returns:
        包含发送结果的字典
    """
    return get_notifier().send(msg)
