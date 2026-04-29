import torch
import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple
from config import Config
from transformers import AutoTokenizer, AutoModelForCausalLM, AutoConfig
import json
import requests
from logger import logger


class DeepSeekAnalyzer:
    def __init__(self, config: Config = None):
        self.config = config or Config()
        self.tokenizer = None
        self.model = None
        
        if self.config.USE_DEEPSEEK_API and self.config.DEEPSEEK_API_KEY:
            logger.info("使用DeepSeek API模式")
            self.use_api = True
        else:
            logger.info("使用本地模型模式（需要更多资源）")
            self.use_api = False
            self._load_local_model()
    
    def _load_local_model(self):
        try:
            logger.info(f"正在加载DeepSeek模型: {self.config.MODEL_NAME}")
            logger.info("注意: 加载大模型可能需要较长时间和较多内存")
            
            model_config = AutoConfig.from_pretrained(self.config.MODEL_NAME)
            
            self.tokenizer = AutoTokenizer.from_pretrained(
                self.config.MODEL_NAME,
                trust_remote_code=True
            )
            
            device_map = 'auto' if self.config.MODEL_DEVICE in ['cuda', 'mps'] else 'cpu'
            
            self.model = AutoModelForCausalLM.from_pretrained(
                self.config.MODEL_NAME,
                config=model_config,
                trust_remote_code=True,
                device_map=device_map,
                torch_dtype=torch.float16 if self.config.MODEL_DEVICE in ['cuda', 'mps'] else torch.float32,
                load_in_8bit=False,
                low_cpu_mem_usage=True
            )
            
            if self.tokenizer.pad_token is None:
                self.tokenizer.pad_token = self.tokenizer.eos_token
            
            self.model.eval()
            logger.info("DeepSeek模型加载完成")
            
        except Exception as e:
            logger.error(f"加载DeepSeek本地模型失败: {e}")
            logger.warning("将使用基于规则的分析作为替代方案")
            self.model = None
            self.tokenizer = None
    
    def _call_deepseek_api(self, prompt: str) -> str:
        if not self.config.DEEPSEEK_API_KEY:
            return "API密钥未配置"
        
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {self.config.DEEPSEEK_API_KEY}'
        }
        
        data = {
            'model': 'deepseek-chat',
            'messages': [
                {'role': 'system', 'content': '你是一位专业的股票分析师，擅长技术分析和K线解读。请根据提供的K线数据给出专业的交易建议。'},
                {'role': 'user', 'content': prompt}
            ],
            'max_tokens': 1000,
            'temperature': 0.3
        }
        
        try:
            response = requests.post(
                self.config.DEEPSEEK_API_URL,
                headers=headers,
                json=data,
                timeout=30
            )
            response.raise_for_status()
            result = response.json()
            return result['choices'][0]['message']['content']
        except Exception as e:
            logger.error(f"DeepSeek API调用失败: {e}")
            return f"API调用错误: {str(e)}"
    
    def _generate_prompt_from_kline(self, kline_data: pd.DataFrame, 
                                      recent_actions: List[str] = None,
                                      portfolio_info: Dict = None) -> str:
        if len(kline_data) == 0:
            return "没有可用的K线数据"
        
        latest = kline_data.iloc[-1]
        prev = kline_data.iloc[-2] if len(kline_data) >= 2 else latest
        
        recent_window = min(len(kline_data), 10)
        recent_data = kline_data.tail(recent_window)
        
        price_summary = f"""
当前K线数据摘要:
时间: {latest['Time']}
开盘价: {latest['Open']:.2f}
最高价: {latest['High']:.2f}
最低价: {latest['Low']:.2f}
收盘价: {latest['Close']:.2f}
成交量: {latest['Volume']:,}

价格变化:
相比前一根K线:
开盘变化: {((latest['Open'] - prev['Open']) / prev['Open'] * 100) if prev['Open'] > 0 else 0:.2f}%
收盘变化: {((latest['Close'] - prev['Close']) / prev['Close'] * 100) if prev['Close'] > 0 else 0:.2f}%
"""
        
        if 'SMA_5' in kline_data.columns:
            sma5 = latest.get('SMA_5', 0)
            sma10 = latest.get('SMA_10', 0)
            sma20 = latest.get('SMA_20', 0)
            price_summary += f"""
移动平均线:
SMA_5: {sma5:.2f}
SMA_10: {sma10:.2f}
SMA_20: {sma20:.2f}
当前价格与SMA_5关系: {'高于' if latest['Close'] > sma5 else '低于'}
"""
        
        if 'RSI' in kline_data.columns:
            rsi = latest.get('RSI', 50)
            price_summary += f"""
RSI指标: {rsi:.2f}
RSI状态: {'超买区域' if rsi > 70 else '超卖区域' if rsi < 30 else '中性区域'}
"""
        
        if 'MACD' in kline_data.columns:
            macd = latest.get('MACD', 0)
            signal = latest.get('MACD_signal', 0)
            price_summary += f"""
MACD指标:
MACD线: {macd:.4f}
信号线: {signal:.4f}
MACD状态: {'金叉' if macd > signal else '死叉'}
"""
        
        if recent_actions:
            price_summary += f"""
最近操作历史: {', '.join(recent_actions[-5:])}
"""
        
        if portfolio_info:
            price_summary += f"""
投资组合信息:
当前持仓: {portfolio_info.get('shares_held', 0)} 股
平均成本: {portfolio_info.get('avg_cost', 0):.2f}
当前余额: {portfolio_info.get('balance', 0):.2f}
"""
        
        recent_prices = [f"[{i+1}] O:{row['Open']:.2f} H:{row['High']:.2f} L:{row['Low']:.2f} C:{row['Close']:.2f} V:{row['Volume']:,}"
                         for i, (_, row) in enumerate(recent_data.iterrows())]
        
        price_summary += f"""
最近{recent_window}根K线数据:
{chr(10).join(recent_prices)}

请分析以上K线数据，判断当前适合的操作策略。你的回答需要包含:
1. 技术分析结论（趋势判断、支撑压力位等）
2. 风险评估
3. 推荐的操作: Buy（买入）、Hold（持有）、Sell（卖出）
4. 操作理由

请以JSON格式返回，格式如下:
{{
    "analysis": "技术分析结论",
    "risk_assessment": "风险评估",
    "recommended_action": "Buy/Hold/Sell",
    "reason": "操作理由",
    "confidence": 0.0-1.0之间的置信度
}}
"""
        
        return price_summary
    
    def analyze_kline(self, kline_data: pd.DataFrame, 
                      recent_actions: List[str] = None,
                      portfolio_info: Dict = None) -> Dict:
        prompt = self._generate_prompt_from_kline(kline_data, recent_actions, portfolio_info)
        
        if self.use_api and self.config.DEEPSEEK_API_KEY:
            response = self._call_deepseek_api(prompt)
            return self._parse_llm_response(response)
        
        elif self.model is not None and self.tokenizer is not None:
            return self._analyze_with_local_model(prompt)
        
        else:
            return self._rule_based_analysis(kline_data)
    
    def _analyze_with_local_model(self, prompt: str) -> Dict:
        try:
            inputs = self.tokenizer(
                prompt, 
                return_tensors='pt', 
                truncation=True, 
                max_length=4096,
                padding=True
            )
            
            if self.config.MODEL_DEVICE == 'cuda':
                inputs = {k: v.cuda() for k, v in inputs.items()}
            elif self.config.MODEL_DEVICE == 'mps':
                inputs = {k: v.to('mps') for k, v in inputs.items()}
            
            with torch.no_grad():
                outputs = self.model.generate(
                    **inputs,
                    max_new_tokens=500,
                    temperature=0.3,
                    do_sample=True,
                    pad_token_id=self.tokenizer.pad_token_id,
                    eos_token_id=self.tokenizer.eos_token_id
                )
            
            response = self.tokenizer.decode(outputs[0], skip_special_tokens=True)
            response = response[len(prompt):].strip()
            
            return self._parse_llm_response(response)
            
        except Exception as e:
            logger.error(f"本地模型推理失败: {e}")
            return {
                "analysis": "模型推理失败，使用规则分析",
                "risk_assessment": "未知",
                "recommended_action": "Hold",
                "reason": "模型不可用，使用默认持有策略",
                "confidence": 0.5
            }
    
    def _parse_llm_response(self, response: str) -> Dict:
        try:
            json_start = response.find('{')
            json_end = response.rfind('}') + 1
            
            if json_start != -1 and json_end > json_start:
                json_str = response[json_start:json_end]
                result = json.loads(json_str)
                
                action = result.get('recommended_action', 'Hold')
                if action not in ['Buy', 'Hold', 'Sell']:
                    action = 'Hold'
                
                return {
                    "analysis": result.get('analysis', '无分析'),
                    "risk_assessment": result.get('risk_assessment', '未知'),
                    "recommended_action": action,
                    "reason": result.get('reason', '无理由'),
                    "confidence": float(result.get('confidence', 0.5))
                }
        except json.JSONDecodeError:
            pass
        
        return self._text_based_action_extraction(response)
    
    def _text_based_action_extraction(self, text: str) -> Dict:
        text_lower = text.lower()
        
        buy_keywords = ['买入', 'buy', '建议买入', '推荐买入', '可以买入', '建仓', '加仓']
        sell_keywords = ['卖出', 'sell', '建议卖出', '推荐卖出', '可以卖出', '清仓', '减仓']
        hold_keywords = ['持有', 'hold', '建议持有', '推荐持有', '观望', '等待']
        
        action = 'Hold'
        confidence = 0.5
        
        buy_score = sum(1 for kw in buy_keywords if kw in text_lower)
        sell_score = sum(1 for kw in sell_keywords if kw in text_lower)
        hold_score = sum(1 for kw in hold_keywords if kw in text_lower)
        
        if buy_score > sell_score and buy_score > hold_score:
            action = 'Buy'
            confidence = min(0.9, 0.5 + buy_score * 0.1)
        elif sell_score > buy_score and sell_score > hold_score:
            action = 'Sell'
            confidence = min(0.9, 0.5 + sell_score * 0.1)
        else:
            action = 'Hold'
            confidence = min(0.9, 0.5 + hold_score * 0.1)
        
        return {
            "analysis": text[:500] if len(text) > 0 else "无详细分析",
            "risk_assessment": "从文本提取",
            "recommended_action": action,
            "reason": f"基于文本关键词分析，买入关键词:{buy_score}, 卖出关键词:{sell_score}, 持有关键词:{hold_score}",
            "confidence": confidence
        }
    
    def _rule_based_analysis(self, kline_data: pd.DataFrame) -> Dict:
        if len(kline_data) < 5:
            return {
                "analysis": "数据不足，无法进行有效分析",
                "risk_assessment": "未知",
                "recommended_action": "Hold",
                "reason": "历史数据不足5根K线，建议等待更多数据",
                "confidence": 0.3
            }
        
        latest = kline_data.iloc[-1]
        closes = kline_data['Close'].values
        
        short_ma = closes[-5:].mean() if len(closes) >= 5 else closes.mean()
        long_ma = closes[-20:].mean() if len(closes) >= 20 else closes.mean()
        current_price = closes[-1]
        
        rsi = latest.get('RSI', 50) if 'RSI' in kline_data.columns else 50
        macd = latest.get('MACD', 0) if 'MACD' in kline_data.columns else 0
        signal = latest.get('MACD_signal', 0) if 'MACD_signal' in kline_data.columns else 0
        
        recent_returns = np.diff(closes[-10:]) / closes[-10:-1]
        momentum = recent_returns.sum() if len(recent_returns) > 0 else 0
        
        signals = {
            'ma_signal': 0,
            'rsi_signal': 0,
            'macd_signal': 0,
            'momentum_signal': 0
        }
        
        if current_price > short_ma > long_ma:
            signals['ma_signal'] = 1
        elif current_price < short_ma < long_ma:
            signals['ma_signal'] = -1
        
        if rsi < 30:
            signals['rsi_signal'] = 1
        elif rsi > 70:
            signals['rsi_signal'] = -1
        
        if macd > signal and macd > 0:
            signals['macd_signal'] = 1
        elif macd < signal and macd < 0:
            signals['macd_signal'] = -1
        
        if momentum > 0.02:
            signals['momentum_signal'] = 1
        elif momentum < -0.02:
            signals['momentum_signal'] = -1
        
        total_signal = sum(signals.values())
        max_possible = len(signals)
        confidence = (abs(total_signal) / max_possible) * 0.5 + 0.3
        
        if total_signal >= 2:
            action = 'Buy'
            analysis = "多个技术指标显示买入信号："
            if signals['ma_signal'] == 1:
                analysis += "均线呈多头排列；"
            if signals['rsi_signal'] == 1:
                analysis += "RSI处于超卖区域；"
            if signals['macd_signal'] == 1:
                analysis += "MACD金叉；"
            if signals['momentum_signal'] == 1:
                analysis += "短期动量向上；"
            risk = "中低风险，建议关注成交量配合"
            reason = "综合技术分析，当前市场趋势偏多，适合买入"
        
        elif total_signal <= -2:
            action = 'Sell'
            analysis = "多个技术指标显示卖出信号："
            if signals['ma_signal'] == -1:
                analysis += "均线呈空头排列；"
            if signals['rsi_signal'] == -1:
                analysis += "RSI处于超买区域；"
            if signals['macd_signal'] == -1:
                analysis += "MACD死叉；"
            if signals['momentum_signal'] == -1:
                analysis += "短期动量向下；"
            risk = "中高风险，注意风险控制"
            reason = "综合技术分析，当前市场趋势偏空，建议卖出"
        
        else:
            action = 'Hold'
            analysis = "技术指标信号不一致，市场处于震荡或方向不明朗阶段"
            risk = "中等风险，建议观望"
            reason = "多空信号相互抵消，建议等待更明确的信号"
        
        return {
            "analysis": analysis,
            "risk_assessment": risk,
            "recommended_action": action,
            "reason": reason,
            "confidence": confidence,
            "signals": signals
        }
    
    def combine_signals(self, rl_action: int, llm_analysis: Dict, 
                        rl_q_values: List[float] = None) -> Tuple[int, str, Dict]:
        rl_action_name = ['Buy', 'Hold', 'Sell'][rl_action]
        llm_action = llm_analysis.get('recommended_action', 'Hold')
        llm_confidence = llm_analysis.get('confidence', 0.5)
        
        vote_weights = {
            'Buy': 0,
            'Hold': 0,
            'Sell': 0
        }
        
        vote_weights[rl_action_name] += 0.5
        
        llm_weight = 0.3 + (llm_confidence * 0.2)
        vote_weights[llm_action] += llm_weight
        
        if rl_q_values is not None and len(rl_q_values) == 3:
            q_total = sum(abs(q) for q in rl_q_values)
            if q_total > 0:
                for i, action_name in enumerate(['Buy', 'Hold', 'Sell']):
                    vote_weights[action_name] += (rl_q_values[i] / q_total) * 0.2
        
        final_action = max(vote_weights, key=vote_weights.get)
        final_action_int = {'Buy': 0, 'Hold': 1, 'Sell': 2}[final_action]
        
        combination_reason = f"""
信号组合分析:
- 强化学习模型建议: {rl_action_name}
- LLM分析建议: {llm_action} (置信度: {llm_confidence:.2f})
- 投票权重: Buy={vote_weights['Buy']:.2f}, Hold={vote_weights['Hold']:.2f}, Sell={vote_weights['Sell']:.2f}
- 最终决策: {final_action}
"""
        
        return final_action_int, final_action, {
            'rl_action': rl_action_name,
            'llm_action': llm_action,
            'llm_confidence': llm_confidence,
            'vote_weights': vote_weights,
            'combination_reason': combination_reason,
            'llm_analysis': llm_analysis
        }
