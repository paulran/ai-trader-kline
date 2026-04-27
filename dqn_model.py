import torch
import torch.nn as nn
import torch.optim as optim
import torch.nn.functional as F
import numpy as np
import random
from collections import deque
from typing import Dict, List, Optional, Tuple
from config import Config


def _check_cuda_compatibility() -> bool:
    try:
        if torch.cuda.is_available():
            cuda_version = torch.version.cuda
            driver_version = torch.cuda.get_device_capability()
            print(f"CUDA版本: {cuda_version}")
            print(f"设备能力: {driver_version}")
            return True
    except Exception as e:
        print(f"CUDA兼容性检查失败: {e}")
    return False

class ReplayBuffer:
    def __init__(self, capacity: int):
        self.buffer = deque(maxlen=capacity)
    
    def push(self, state: np.ndarray, action: int, reward: float, 
             next_state: np.ndarray, done: bool):
        self.buffer.append((state, action, reward, next_state, done))
    
    def sample(self, batch_size: int) -> Tuple[np.ndarray, np.ndarray, np.ndarray, 
                                                 np.ndarray, np.ndarray]:
        batch = random.sample(self.buffer, min(len(self.buffer), batch_size))
        states, actions, rewards, next_states, dones = zip(*batch)
        
        return (
            np.array(states),
            np.array(actions),
            np.array(rewards, dtype=np.float32),
            np.array(next_states),
            np.array(dones, dtype=np.float32)
        )
    
    def __len__(self) -> int:
        return len(self.buffer)


class DQNNetwork(nn.Module):
    def __init__(self, input_shape: Tuple[int, int], action_size: int, 
                 hidden_size: int = 256):
        super(DQNNetwork, self).__init__()
        
        self.input_shape = input_shape
        self.flatten_size = input_shape[0] * input_shape[1]
        
        self.fc1 = nn.Linear(self.flatten_size, hidden_size)
        self.fc2 = nn.Linear(hidden_size, hidden_size)
        self.fc3 = nn.Linear(hidden_size, hidden_size // 2)
        self.fc4 = nn.Linear(hidden_size // 2, action_size)
        
        self.dropout = nn.Dropout(0.2)
        
    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = x.view(x.size(0), -1)
        
        x = F.relu(self.fc1(x))
        x = self.dropout(x)
        x = F.relu(self.fc2(x))
        x = self.dropout(x)
        x = F.relu(self.fc3(x))
        x = self.dropout(x)
        
        return self.fc4(x)


class DQNAgent:
    def __init__(self, config: Config = None, state_shape: Tuple[int, int] = None, 
                 action_size: int = None):
        self.config = config or Config()
        
        self.state_shape = state_shape or (self.config.WINDOW_SIZE, 15 + 3)
        self.action_size = action_size or 3
        
        self.hidden_size = 256
        self.learning_rate = self.config.RL_LEARNING_RATE
        self.gamma = self.config.RL_GAMMA
        self.epsilon_start = self.config.RL_EPSILON_START
        self.epsilon_end = self.config.RL_EPSILON_END
        self.epsilon_decay = self.config.RL_EPSILON_DECAY
        self.target_update = self.config.RL_TARGET_UPDATE
        self.memory_size = self.config.RL_MEMORY_SIZE
        self.batch_size = self.config.RL_BATCH_SIZE
        
        self.epsilon = self.epsilon_start
        
        cuda_available = False
        if self.config.MODEL_DEVICE == "cuda":
            cuda_available = _check_cuda_compatibility()
        
        if cuda_available:
            self.device = torch.device("cuda")
        elif self.config.MODEL_DEVICE == "mps" and torch.backends.mps.is_available():
            self.device = torch.device("mps")
        else:
            self.device = torch.device("cpu")
        
        print(f"使用设备: {self.device}")
        
        self.policy_net = DQNNetwork(self.state_shape, self.action_size, self.hidden_size).to(self.device)
        self.target_net = DQNNetwork(self.state_shape, self.action_size, self.hidden_size).to(self.device)
        self.target_net.load_state_dict(self.policy_net.state_dict())
        self.target_net.eval()
        
        self.optimizer = optim.Adam(self.policy_net.parameters(), lr=self.learning_rate)
        self.memory = ReplayBuffer(self.memory_size)
        
        self.steps_done = 0
        self.best_reward = float('-inf')
        
    def select_action(self, state: np.ndarray, training: bool = True) -> int:
        if training and random.random() < self.epsilon:
            return random.randrange(self.action_size)
        
        with torch.no_grad():
            state_tensor = torch.FloatTensor(state).unsqueeze(0).to(self.device)
            q_values = self.policy_net(state_tensor)
            return q_values.max(1)[1].item()
    
    def predict_action(self, state: np.ndarray) -> Tuple[int, List[float]]:
        with torch.no_grad():
            state_tensor = torch.FloatTensor(state).unsqueeze(0).to(self.device)
            q_values = self.policy_net(state_tensor)
            
            action = q_values.max(1)[1].item()
            q_values_list = q_values.cpu().numpy().flatten().tolist()
            
            return action, q_values_list
    
    def update_epsilon(self):
        self.epsilon = max(
            self.epsilon_end,
            self.epsilon * self.epsilon_decay
        )
    
    def optimize_model(self) -> Optional[float]:
        if len(self.memory) < self.batch_size:
            return None
        
        states, actions, rewards, next_states, dones = self.memory.sample(self.batch_size)
        
        states_tensor = torch.FloatTensor(states).to(self.device)
        actions_tensor = torch.LongTensor(actions).unsqueeze(1).to(self.device)
        rewards_tensor = torch.FloatTensor(rewards).to(self.device)
        next_states_tensor = torch.FloatTensor(next_states).to(self.device)
        dones_tensor = torch.FloatTensor(dones).to(self.device)
        
        current_q_values = self.policy_net(states_tensor).gather(1, actions_tensor)
        
        next_q_values = self.target_net(next_states_tensor).max(1)[0].detach()
        
        expected_q_values = rewards_tensor + (self.gamma * next_q_values * (1 - dones_tensor))
        
        loss = F.smooth_l1_loss(current_q_values.squeeze(), expected_q_values)
        
        self.optimizer.zero_grad()
        loss.backward()
        for param in self.policy_net.parameters():
            param.grad.data.clamp_(-1, 1)
        self.optimizer.step()
        
        self.steps_done += 1
        
        if self.steps_done % self.target_update == 0:
            self.target_net.load_state_dict(self.policy_net.state_dict())
        
        return loss.item()
    
    def save_model(self, path: str):
        import os
        
        checkpoint_dir = os.path.dirname(path)
        if checkpoint_dir and not os.path.exists(checkpoint_dir):
            os.makedirs(checkpoint_dir, exist_ok=True)
        
        checkpoint = {
            'policy_net_state_dict': self.policy_net.state_dict(),
            'target_net_state_dict': self.target_net.state_dict(),
            'optimizer_state_dict': self.optimizer.state_dict(),
            'epsilon': float(self.epsilon),
            'steps_done': int(self.steps_done),
            'best_reward': float(self.best_reward) if self.best_reward != float('-inf') else -1e18
        }
        
        torch.save(checkpoint, path)
        print(f"模型已保存到: {path}")
    
    def load_model(self, path: str):
        try:
            try:
                checkpoint = torch.load(
                    path, 
                    map_location=self.device, 
                    weights_only=False
                )
            except TypeError:
                checkpoint = torch.load(path, map_location=self.device)
        except Exception as e:
            print(f"加载模型时遇到问题，尝试使用安全加载方式: {e}")
            try:
                import warnings
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    checkpoint = torch.load(path, map_location=self.device, weights_only=False)
            except Exception as e2:
                raise RuntimeError(f"无法加载模型文件 {path}: {e2}")
        
        self.policy_net.load_state_dict(checkpoint['policy_net_state_dict'])
        self.target_net.load_state_dict(checkpoint['target_net_state_dict'])
        self.optimizer.load_state_dict(checkpoint['optimizer_state_dict'])
        
        self.epsilon = float(checkpoint.get('epsilon', self.epsilon_end))
        self.steps_done = int(checkpoint.get('steps_done', 0))
        
        best_reward_val = checkpoint.get('best_reward', -1e18)
        self.best_reward = float('-inf') if best_reward_val <= -1e18 else float(best_reward_val)
        
        print(f"模型已从 {path} 加载")
