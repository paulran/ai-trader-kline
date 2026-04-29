import unittest
from unittest.mock import patch, MagicMock
import time
import hashlib
import hmac
import base64

from feishu_notifier import FeishuNotifier, get_notifier, send
from config import Config


class TestFeishuNotifier(unittest.TestCase):
    """飞书通知器测试类"""
    
    def setUp(self):
        """测试前的准备工作"""
        self.test_webhook_url = "https://open.feishu.cn/open-apis/bot/v2/hook/test_token"
        self.test_secret = "test_secret_key"
        self.test_msg = "这是一条测试消息"
    
    def tearDown(self):
        """测试后的清理工作"""
        global _default_notifier
        import feishu_notifier
        feishu_notifier._default_notifier = None
    
    def test_init_with_default_config(self):
        """测试使用默认配置初始化"""
        notifier = FeishuNotifier()
        
        self.assertEqual(notifier.webhook_url, Config.FEISHU_WEBHOOK_URL)
        self.assertEqual(notifier.secret, Config.FEISHU_SECRET)
        self.assertEqual(notifier.timeout, Config.FEISHU_TIMEOUT)
        self.assertEqual(notifier.enabled, Config.FEISHU_ENABLED)
    
    def test_init_with_custom_config(self):
        """测试使用自定义配置初始化"""
        custom_url = "https://custom-webhook.example.com"
        custom_secret = "custom_secret"
        custom_timeout = 30
        custom_enabled = True
        
        notifier = FeishuNotifier(
            webhook_url=custom_url,
            secret=custom_secret,
            timeout=custom_timeout,
            enabled=custom_enabled
        )
        
        self.assertEqual(notifier.webhook_url, custom_url)
        self.assertEqual(notifier.secret, custom_secret)
        self.assertEqual(notifier.timeout, custom_timeout)
        self.assertTrue(notifier.enabled)
    
    def test_init_with_secret_enables_notifier(self):
        """测试提供密钥时自动启用通知"""
        notifier = FeishuNotifier(secret=self.test_secret)
        self.assertTrue(notifier.enabled)
    
    def test_generate_sign(self):
        """测试签名生成"""
        notifier = FeishuNotifier(secret=self.test_secret)
        timestamp = int(time.time())
        
        sign = notifier._generate_sign(timestamp, self.test_secret)
        
        expected_string_to_sign = f"{timestamp}\n{self.test_secret}"
        expected_hmac = hmac.new(
            self.test_secret.encode('utf-8'),
            expected_string_to_sign.encode('utf-8'),
            hashlib.sha256
        )
        expected_sign = base64.b64encode(expected_hmac.digest()).decode('utf-8')
        
        self.assertEqual(sign, expected_sign)
        self.assertIsInstance(sign, str)
        self.assertGreater(len(sign), 0)
    
    def test_build_payload_text(self):
        """测试构建文本消息 payload"""
        notifier = FeishuNotifier()
        test_text = "测试文本消息"
        
        payload = notifier._build_payload(test_text, "text")
        
        self.assertEqual(payload['msg_type'], 'text')
        self.assertEqual(payload['content']['text'], test_text)
    
    def test_build_payload_unsupported_type(self):
        """测试构建不支持的消息类型"""
        notifier = FeishuNotifier()
        
        with self.assertRaises(ValueError):
            notifier._build_payload("test", "image")
    
    @patch('feishu_notifier.requests.post')
    def test_send_success(self, mock_post):
        """测试成功发送消息"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'StatusCode': 0, 'msg': 'success'}
        mock_post.return_value = mock_response
        
        notifier = FeishuNotifier(
            webhook_url=self.test_webhook_url,
            enabled=True
        )
        
        result = notifier.send(self.test_msg)
        
        self.assertTrue(result['success'])
        self.assertEqual(result['message'], '消息发送成功')
        self.assertIsNotNone(result['response'])
        self.assertIsNone(result['error'])
        
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        self.assertEqual(call_args[0][0], self.test_webhook_url)
    
    @patch('feishu_notifier.requests.post')
    def test_send_with_secret(self, mock_post):
        """测试带签名的消息发送"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'StatusCode': 0, 'msg': 'success'}
        mock_post.return_value = mock_response
        
        notifier = FeishuNotifier(
            webhook_url=self.test_webhook_url,
            secret=self.test_secret
        )
        
        result = notifier.send(self.test_msg)
        
        self.assertTrue(result['success'])
        
        call_args = mock_post.call_args
        sent_payload = call_args[1]['json']
        
        self.assertIn('timestamp', sent_payload)
        self.assertIn('sign', sent_payload)
    
    def test_send_disabled(self):
        """测试未启用时发送消息"""
        notifier = FeishuNotifier(
            webhook_url=self.test_webhook_url,
            enabled=False
        )
        
        result = notifier.send(self.test_msg)
        
        self.assertFalse(result['success'])
        self.assertEqual(result['message'], '飞书通知功能未启用')
    
    def test_send_no_webhook(self):
        """测试未配置 webhook 时发送消息"""
        notifier = FeishuNotifier(enabled=True)
        
        result = notifier.send(self.test_msg)
        
        self.assertFalse(result['success'])
        self.assertIn('缺少 webhook 地址', result['message'])
    
    @patch('feishu_notifier.requests.post')
    def test_send_api_error(self, mock_post):
        """测试 API 返回错误"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'StatusCode': 9499, 'msg': 'invalid token'}
        mock_post.return_value = mock_response
        
        notifier = FeishuNotifier(
            webhook_url=self.test_webhook_url,
            enabled=True
        )
        
        result = notifier.send(self.test_msg)
        
        self.assertFalse(result['success'])
        self.assertIn('invalid token', result['error'])
    
    @patch('feishu_notifier.requests.post')
    def test_send_timeout(self, mock_post):
        """测试请求超时"""
        import requests
        mock_post.side_effect = requests.exceptions.Timeout()
        
        notifier = FeishuNotifier(
            webhook_url=self.test_webhook_url,
            enabled=True
        )
        
        result = notifier.send(self.test_msg)
        
        self.assertFalse(result['success'])
        self.assertIn('请求超时', result['message'])
    
    @patch('feishu_notifier.requests.post')
    def test_send_network_error(self, mock_post):
        """测试网络错误"""
        import requests
        mock_post.side_effect = requests.exceptions.RequestException("Connection refused")
        
        notifier = FeishuNotifier(
            webhook_url=self.test_webhook_url,
            enabled=True
        )
        
        result = notifier.send(self.test_msg)
        
        self.assertFalse(result['success'])
        self.assertIn('网络错误', result['message'])
    
    @patch('feishu_notifier.requests.post')
    def test_send_text_alias(self, mock_post):
        """测试 send_text 别名方法"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'StatusCode': 0, 'msg': 'success'}
        mock_post.return_value = mock_response
        
        notifier = FeishuNotifier(
            webhook_url=self.test_webhook_url,
            enabled=True
        )
        
        result = notifier.send_text(self.test_msg)
        
        self.assertTrue(result['success'])
        mock_post.assert_called_once()


class TestGlobalFunctions(unittest.TestCase):
    """测试全局函数"""
    
    def setUp(self):
        """测试前的准备工作"""
        import feishu_notifier
        feishu_notifier._default_notifier = None
    
    def tearDown(self):
        """测试后的清理工作"""
        import feishu_notifier
        feishu_notifier._default_notifier = None
    
    def test_get_notifier_creates_instance(self):
        """测试 get_notifier 创建实例"""
        notifier1 = get_notifier()
        notifier2 = get_notifier()
        
        self.assertIsNotNone(notifier1)
        self.assertIsInstance(notifier1, FeishuNotifier)
        self.assertIs(notifier1, notifier2)
    
    def test_send_uses_global_notifier(self):
        """测试 send 函数使用全局通知器"""
        with patch.object(FeishuNotifier, 'send') as mock_send:
            mock_send.return_value = {'success': True, 'message': 'test'}
            
            result = send("测试消息")
            
            mock_send.assert_called_once_with("测试消息")
            self.assertEqual(result['success'], True)


class TestConfigIntegration(unittest.TestCase):
    """测试与配置系统的集成"""
    
    def setUp(self):
        """测试前保存原始配置"""
        self.original_webhook = Config.FEISHU_WEBHOOK_URL
        self.original_secret = Config.FEISHU_SECRET
        self.original_enabled = Config.FEISHU_ENABLED
        self.original_timeout = Config.FEISHU_TIMEOUT
    
    def tearDown(self):
        """测试后恢复原始配置"""
        Config.FEISHU_WEBHOOK_URL = self.original_webhook
        Config.FEISHU_SECRET = self.original_secret
        Config.FEISHU_ENABLED = self.original_enabled
        Config.FEISHU_TIMEOUT = self.original_timeout
        
        import feishu_notifier
        feishu_notifier._default_notifier = None
    
    def test_notifier_uses_config_values(self):
        """测试通知器使用配置值"""
        test_url = "https://test-config-url.example.com"
        test_secret = "test-config-secret"
        test_enabled = True
        test_timeout = 15
        
        Config.FEISHU_WEBHOOK_URL = test_url
        Config.FEISHU_SECRET = test_secret
        Config.FEISHU_ENABLED = test_enabled
        Config.FEISHU_TIMEOUT = test_timeout
        
        notifier = FeishuNotifier()
        
        self.assertEqual(notifier.webhook_url, test_url)
        self.assertEqual(notifier.secret, test_secret)
        self.assertTrue(notifier.enabled)
        self.assertEqual(notifier.timeout, test_timeout)
    
    @patch('feishu_notifier.requests.post')
    def test_send_with_configured_webhook(self, mock_post):
        """测试使用配置的 webhook 发送消息"""
        Config.FEISHU_WEBHOOK_URL = "https://configured-url.example.com"
        Config.FEISHU_ENABLED = True
        
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'StatusCode': 0, 'msg': 'success'}
        mock_post.return_value = mock_response
        
        result = send("通过配置发送的消息")
        
        self.assertTrue(result['success'])
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        self.assertEqual(call_args[0][0], "https://configured-url.example.com")


def run_tests():
    """运行所有测试"""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    suite.addTests(loader.loadTestsFromTestCase(TestFeishuNotifier))
    suite.addTests(loader.loadTestsFromTestCase(TestGlobalFunctions))
    suite.addTests(loader.loadTestsFromTestCase(TestConfigIntegration))
    
    runner = unittest.TextTestRunner(verbosity=2)
    runner.run(suite)


if __name__ == '__main__':
    run_tests()
