# 部署和测试指南

## 1. 环境准备

### 1.1 系统要求
- **操作系统**: Ubuntu 20.04+ / CentOS 7+ / macOS 10.15+
- **Python**: 3.10 或更高版本
- **Redis**: 6.0+ (推荐 Redis Stack 8.0+)
- **内存**: 至少 2GB RAM
- **磁盘空间**: 至少 1GB 可用空间

### 1.2 安装依赖

#### 1.2.1 安装 Redis
```bash
# Ubuntu/Debian
sudo apt-get update
sudo apt-get install redis-server

# CentOS/RHEL
sudo yum install epel-release
sudo yum install redis

# 使用 Docker
docker run -d -p 6379:6379 --name redis-stack redis/redis-stack:latest

# 验证安装
redis-cli ping
# 应返回: PONG
```

#### 1.2.2 安装 Python 依赖
```bash
# 创建虚拟环境
python3 -m venv venv
source venv/bin/activate

# 安装依赖
pip install redis websockets aiohttp langgraph-checkpoint-redis

# 验证安装
python -c "import redis; import websockets; print('依赖安装成功')"
```

## 2. 单机部署

### 2.1 配置文件
创建配置文件 `config.yaml`:
```yaml
# config.yaml
redis:
  url: "redis://localhost:6379"
  max_connections: 20
  decode_responses: true

websocket:
  host: "0.0.0.0"
  port: 8765
  max_message_size: 1048576  # 1MB
  heartbeat_interval: 30  # 秒
  session_timeout: 300  # 秒

langgraph:
  checkpoint_ttl: 120  # 分钟
  max_checkpoints: 100

system:
  server_id: "node1"
  log_level: "INFO"
  debug: false
```

### 2.2 启动服务器
```bash
# 方法1: 直接运行
python complete_implementation.py

# 方法2: 使用环境变量
export REDIS_URL="redis://localhost:6379"
export WEBSOCKET_PORT="8765"
export SERVER_ID="node1"
python complete_implementation.py

# 方法3: 后台运行
nohup python complete_implementation.py > server.log 2>&1 &
```

### 2.3 验证服务器运行
```bash
# 检查进程
ps aux | grep python

# 检查日志
tail -f server.log

# 测试连接
curl -i -N -H "Connection: Upgrade" -H "Upgrade: websocket" \
  -H "Host: localhost:8765" -H "Origin: http://localhost" \
  http://localhost:8765
```

## 3. 集群部署

### 3.1 多节点配置
创建多个配置文件:

**node1.yaml**:
```yaml
redis:
  url: "redis://redis-cluster:6379"
  
websocket:
  host: "0.0.0.0"
  port: 8765
  
system:
  server_id: "node1"
```

**node2.yaml**:
```yaml
redis:
  url: "redis://redis-cluster:6379"
  
websocket:
  host: "0.0.0.0"
  port: 8766
  
system:
  server_id: "node2"
```

**node3.yaml**:
```yaml
redis:
  url: "redis://redis-cluster:6379"
  
websocket:
  host: "0.0.0.0"
  port: 8767
  
system:
  server_id: "node3"
```

### 3.2 启动集群
```bash
# 节点1
export CONFIG_FILE="node1.yaml"
python complete_implementation.py > node1.log 2>&1 &

# 节点2
export CONFIG_FILE="node2.yaml"
python complete_implementation.py > node2.log 2>&1 &

# 节点3
export CONFIG_FILE="node3.yaml"
python complete_implementation.py > node3.log 2>&1 &
```

### 3.3 负载均衡配置
使用 Nginx 作为负载均衡器:

```nginx
# nginx.conf
upstream websocket_cluster {
    server 192.168.1.100:8765;
    server 192.168.1.101:8766;
    server 192.168.1.102:8767;
    
    # 会话保持（基于IP哈希）
    ip_hash;
}

server {
    listen 80;
    server_name chat.example.com;
    
    location /ws {
        proxy_pass http://websocket_cluster;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # WebSocket超时设置
        proxy_read_timeout 86400;
        proxy_send_timeout 86400;
    }
}
```

## 4. Docker 部署

### 4.1 Dockerfile
```dockerfile
# Dockerfile
FROM python:3.10-slim

WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# 复制依赖文件
COPY requirements.txt .

# 安装Python依赖
RUN pip install --no-cache-dir -r requirements.txt

# 复制应用代码
COPY . .

# 创建非root用户
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

# 暴露端口
EXPOSE 8765

# 启动命令
CMD ["python", "complete_implementation.py"]
```

### 4.2 Docker Compose
```yaml
# docker-compose.yaml
version: '3.8'

services:
  redis:
    image: redis/redis-stack:latest
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data
    command: redis-server --appendonly yes
    
  chat-node1:
    build: .
    ports:
      - "8765:8765"
    environment:
      - REDIS_URL=redis://redis:6379
      - SERVER_ID=node1
      - WEBSOCKET_PORT=8765
    depends_on:
      - redis
    restart: unless-stopped
    
  chat-node2:
    build: .
    ports:
      - "8766:8766"
    environment:
      - REDIS_URL=redis://redis:6379
      - SERVER_ID=node2
      - WEBSOCKET_PORT=8766
    depends_on:
      - redis
    restart: unless-stopped
    
  nginx:
    image: nginx:alpine
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf:ro
      - ./ssl:/etc/nginx/ssl:ro
    depends_on:
      - chat-node1
      - chat-node2
    restart: unless-stopped

volumes:
  redis_data:
```

### 4.3 构建和运行
```bash
# 构建镜像
docker build -t distributed-chat .

# 启动服务
docker-compose up -d

# 查看日志
docker-compose logs -f

# 停止服务
docker-compose down
```

## 5. 测试方案

### 5.1 单元测试
创建测试文件 `test_system.py`:

```python
# test_system.py
import pytest
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from complete_implementation import (
    ConfigManager,
    StateManager,
    MessageBroker,
    ConnectionManager,
    ConversationGraphBuilder
)

@pytest.mark.asyncio
async def test_config_manager():
    """测试配置管理器"""
    config = ConfigManager.load_config()
    assert "redis_url" in config
    assert "websocket_port" in config
    assert config["websocket_port"] == 8765

@pytest.mark.asyncio
async def test_state_manager_create_session():
    """测试创建会话"""
    mock_checkpointer = AsyncMock()
    mock_redis = AsyncMock()
    
    manager = StateManager(mock_checkpointer, mock_redis)
    
    # 模拟检查点保存
    mock_checkpointer.put.return_value = "checkpoint-123"
    
    session = await manager.create_session("test_user", "test_device")
    
    assert session["user_id"] == "test_user"
    assert session["device_id"] == "test_device"
    assert session["checkpoint_id"] == "checkpoint-123"
    assert len(session["messages"]) == 0

@pytest.mark.asyncio
async def test_message_broker():
    """测试消息代理"""
    mock_redis = AsyncMock()
    mock_pubsub = AsyncMock()
    
    with patch('redis.asyncio.Redis.pubsub', return_value=mock_pubsub):
        broker = MessageBroker(mock_redis)
        
        # 启动代理
        await broker.start()
        
        # 测试发布消息
        test_data = {"test": "message"}
        await broker.publish("test_channel", test_data)
        
        # 验证Redis publish被调用
        mock_redis.publish.assert_called_once()
        
        await broker.stop()

@pytest.mark.asyncio
async def test_connection_manager():
    """测试连接管理器"""
    mock_redis = AsyncMock()
    mock_websocket = AsyncMock()
    
    manager = ConnectionManager("test_server", mock_redis)
    
    # 注册连接
    await manager.register_connection("user1", "session1", mock_websocket)
    
    assert "session1" in manager.connections
    assert "user1" in manager.user_sessions
    assert "session1" in manager.user_sessions["user1"]
    
    # 测试发送消息
    test_message = {"type": "test"}
    await manager.send_to_session("session1", test_message)
    
    # 验证消息发送
    mock_websocket.send.assert_called_once()
    
    # 注销连接
    await manager.unregister_connection("session1")
    
    assert "session1" not in manager.connections
```

运行测试:
```bash
# 安装测试依赖
pip install pytest pytest-asyncio

# 运行测试
pytest test_system.py -v
```

### 5.2 集成测试
创建集成测试文件 `test_integration.py`:

```python
# test_integration.py
import asyncio
import json
import websockets
import pytest
from datetime import datetime

@pytest.mark.asyncio
async def test_websocket_connection():
    """测试WebSocket连接"""
    server_url = "ws://localhost:8765"
    
    # 启动服务器（需要在另一个进程中）
    # 这里我们只测试客户端逻辑
    
    async with websockets.connect(server_url) as websocket:
        # 发送认证消息
        auth_message = {
            "user_id": "test_user",
            "device_id": "test_device",
            "timestamp": datetime.now().isoformat()
        }
        
        await websocket.send(json.dumps(auth_message))
        
        # 接收响应
        response = await websocket.recv()
        response_data = json.loads(response)
        
        assert response_data["type"] == "system"
        assert "session_id" in response_data
        
        # 发送测试消息
        test_message = {
            "type": "text",
            "content": "Hello, World!",
            "timestamp": datetime.now().isoformat()
        }
        
        await websocket.send(json.dumps(test_message))
        
        # 接收响应
        response = await websocket.recv()
        response_data = json.loads(response)
        
        assert response_data["type"] in ["text", "error"]
        
        # 发送心跳
        heartbeat = {
            "type": "heartbeat",
            "timestamp": datetime.now().isoformat()
        }
        
        await websocket.send(json.dumps(heartbeat))
        
        # 接收心跳响应
        response = await websocket.recv()
        response_data = json.loads(response)
        
        assert response_data["type"] == "heartbeat"

@pytest.mark.asyncio
async def test_session_recovery():
    """测试会话恢复"""
    server_url = "ws://localhost:8765"
    
    # 第一次连接
    async with websockets.connect(server_url) as websocket1:
        auth_message = {
            "user_id": "recovery_user",
            "device_id": "device1",
            "timestamp": datetime.now().isoformat()
        }
        
        await websocket1.send(json.dumps(auth_message))
        response1 = await websocket1.recv()
        response_data1 = json.loads(response1)
        
        session_id = response_data1["session_id"]
        
        # 发送一些消息
        for i in range(3):
            message = {
                "type": "text",
                "content": f"Message {i}",
                "timestamp": datetime.now().isoformat()
            }
            await websocket1.send(json.dumps(message))
            await websocket1.recv()  # 接收响应
            
    # 模拟连接断开后重新连接
    await asyncio.sleep(1)
    
    async with websockets.connect(server_url) as websocket2:
        # 使用相同的用户ID重新连接
        auth_message = {
            "user_id": "recovery_user",
            "device_id": "device1",
            "timestamp": datetime.now().isoformat()
        }
        
        await websocket2.send(json.dumps(auth_message))
        response2 = await websocket2.recv()
        response_data2 = json.loads(response2)
        
        # 应该恢复之前的会话
        assert response_data2.get("recovered", False) == True
        assert response_data2.get("session_id") == session_id
```

### 5.3 负载测试
创建负载测试脚本 `load_test.py`:

```python
# load_test.py
import asyncio
import json
import websockets
import random
from datetime import datetime
from typing import List

class LoadTestClient:
    """负载测试客户端"""
    
    def __init__(self, user_id: str, server_url: str):
        self.user_id = user_id
        self.server_url = server_url
        self.websocket = None
        self.session_id = None
        
    async def connect(self):
        """连接服务器"""
        self.websocket = await websockets.connect(self.server_url)
        
        auth_message = {
            "user_id": self.user_id,
            "device_id": f"device_{random.randint(1, 100)}",
            "timestamp": datetime.now().isoformat()
        }
        
        await self.websocket.send(json.dumps(auth_message))
        response = await self.websocket.recv()
        response_data = json.loads(response)
        
        self.session_id = response_data.get("session_id")
        return response_data
        
    async def send_messages(self, count: int):
        """发送多条消息"""
        for i in range(count):
            message = {
                "type": "text",
                "content": f"Load test message {i} from {self.user_id}",
                "timestamp": datetime.now().isoformat()
            }
            
            await self.websocket.send(json.dumps(message))
            
            # 随机等待
            await asyncio.sleep(random.uniform(0.1, 1.0))
            
            # 接收响应（非阻塞）
            try:
                await asyncio.wait_for(self.websocket.recv(), timeout=0.5)
            except asyncio.TimeoutError:
                pass
                
    async def close(self):
        """关闭连接"""
        if self.websocket:
            await self.websocket.close()

async def run_load_test(num_clients: int, messages_per_client: int, 
                       server_url: str = "ws://localhost:8765"):
    """运行负载测试"""
    print(f"开始负载测试: {num_clients}个客户端, 每个发送{messages_per_client}条消息")
    
    clients: List[LoadTestClient] = []
    
    # 创建客户端
    for i in range(num_clients):
        client = LoadTestClient(f"load_user_{i}", server_url)
        clients.append(client)
        
    # 连接所有客户端
    print("连接客户端...")
    connect_tasks = [client.connect() for client in clients]
    await asyncio.gather(*connect_tasks)
    
    # 发送消息
    print("发送消息...")
    start_time = datetime.now()
    
    send_tasks = [client.send_messages(messages_per_client) for client in clients]
    await asyncio.gather(*send_tasks)
    
    end_time = datetime.now()
    
    # 计算性能指标
    total_messages = num_clients * messages_per_client
    total_time = (end_time - start_time).total_seconds()
    
    print(f"\n负载测试完成!")
    print(f"总消息数: {total_messages}")
    print(f"总时间: {total_time:.2f}秒")
    print(f"吞吐量: {total_messages / total_time:.2f} 消息/秒")
    print(f"平均延迟: {total_time / total_messages * 1000:.2f} 毫秒/消息")
    
    # 关闭连接
    print("关闭连接...")
    close_tasks = [client.close() for client in clients]
    await asyncio.gather(*close_tasks)

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) != 3:
        print("用法: python load_test.py <客户端数量> <每个客户端消息数>")
        print("示例: python load_test.py 100 10")
        sys.exit(1)
        
    num_clients = int(sys.argv[1])
    messages_per_client = int(sys.argv[2])
    
    asyncio.run(run_load_test(num_clients, messages_per_client))
```

运行负载测试:
```bash
# 测试100个客户端，每个发送10条消息
python load_test.py 100 10

# 测试500个客户端，每个发送5条消息
python load_test.py 500 5
```

## 6. 监控和运维

### 6.1 健康检查
创建健康检查脚本 `health_check.py`:

```python
# health_check.py
import asyncio
import json
import websockets
import redis.asyncio as redis
from datetime import datetime
import sys

async def check_redis_health(redis_url: str) -> bool:
    """检查Redis健康状态"""
    try:
        client = await redis.from_url(redis_url, decode_responses=True)
        await client.ping()
        await client.close()
        return True
    except Exception as e:
        print(f"Redis健康检查失败: {e}")
        return False

async def check_websocket_health(server_url: str) -> bool:
    """检查WebSocket健康状态"""
    try:
        async with websockets.connect(server_url) as websocket:
            # 发送测试消息
            test_message = {
                "type": "health_check",
                "timestamp": datetime.now().isoformat()
            }
            
            await websocket.send(json.dumps(test_message))
            
            # 设置超时
            try:
                response = await asyncio.wait_for(websocket.recv(), timeout=5.0)
                response_data = json.loads(response)
                return response_data.get("type") == "system"
            except asyncio.TimeoutError:
                print("WebSocket响应超时")
                return False
                
    except Exception as e:
        print(f"WebSocket健康检查失败: {e}")
        return False

async def check_system_metrics(redis_url: str) -> dict:
    """检查系统指标"""
    try:
        client = await redis.from_url(redis_url, decode_responses=True)
        
        # 获取Redis信息
        info = await client.info()
        
        # 获取连接数
        connections = await client.keys("connection:*")
        
        # 获取会话数
        user_sessions = await client.keys("user:*:sessions")
        
        metrics = {
            "redis_memory_used": info.get("used_memory_human", "N/A"),
            "redis_connections": info.get("connected_clients", 0),
            "active_connections": len(connections),
            "active_sessions": len(user_sessions),
            "timestamp": datetime.now().isoformat()
        }
        
        await client.close()
        return metrics
        
    except Exception as e:
        print(f"获取系统指标失败: {e}")
        return {}

async def main():
    """主健康检查函数"""
    redis_url = "redis://localhost:6379"
    websocket_url = "ws://localhost:8765"
    
    print("开始系统健康检查...")
    print(f"Redis URL: {redis_url}")
    print(f"WebSocket URL: {websocket_url}")
    print("-" * 50)
    
    # 检查Redis
    redis_ok = await check_redis_health(redis_url)
    print(f"Redis状态: {'✓ 正常' if redis_ok else '✗ 异常'}")
    
    # 检查WebSocket
    websocket_ok = await check_websocket_health(websocket_url)
    print(f"WebSocket状态: {'✓ 正常' if websocket_ok else '✗ 异常'}")
    
    # 获取系统指标
    if redis_ok:
        metrics = await check_system_metrics(redis_url)
        print("\n系统指标:")
        for key, value in metrics.items():
            print(f"  {key}: {value}")
    
    # 总体状态
    print("-" * 50)
    overall_status = redis_ok and websocket_ok
    print(f"总体状态: {'✓ 健康' if overall_status else '✗ 不健康'}")
    
    return 0 if overall_status else 1

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
```

### 6.2 日志监控
配置日志轮转:

```python
# logging_config.py
import logging
import logging.handlers
import os

def setup_logging(log_dir: str = "logs", log_level: str = "INFO"):
    """配置日志系统"""
    
    # 创建日志目录
    os.makedirs(log_dir, exist_ok=True)
    
    # 日志格式
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # 控制台处理器
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    
    # 文件处理器（按大小轮转）
    file_handler = logging.handlers.RotatingFileHandler(
        os.path.join(log_dir, 'chat_server.log'),
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=10
    )
    file_handler.setFormatter(formatter)
    
    # 错误日志处理器
    error_handler = logging.handlers.RotatingFileHandler(
        os.path.join(log_dir, 'chat_server_error.log'),
        maxBytes=5 * 1024 * 1024,  # 5MB
        backupCount=5
    )
    error_handler.setFormatter(formatter)
    error_handler.setLevel(logging.ERROR)
    
    # 配置根日志器
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level))
    
    # 移除现有处理器
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
        
    # 添加新处理器
    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(error_handler)
```

### 6.3 性能监控
使用 Prometheus 和 Grafana 监控:

```python
# metrics_exporter.py
import asyncio
import time
from prometheus_client import start_http_server, Gauge, Counter, Histogram
import redis.asyncio as redis

# 定义指标
ACTIVE_CONNECTIONS = Gauge('chat_active_connections', '活跃连接数')
MESSAGES_PROCESSED = Counter('chat_messages_processed', '处理的消息总数')
MESSAGE_LATENCY = Histogram('chat_message_latency', '消息处理延迟', buckets=[0.1, 0.5, 1.0, 2.0, 5.0])
REDIS_MEMORY_USAGE = Gauge('chat_redis_memory_usage', 'Redis内存使用量(bytes)')

class MetricsExporter:
    """指标导出器"""
    
    def __init__(self, redis_url: str, port: int = 8000):
        self.redis_url = redis_url
        self.port = port
        self.running = False
        
    async def start(self):
        """启动指标导出器"""
        # 启动Prometheus HTTP服务器
        start_http_server(self.port)
        print(f"指标导出器启动在端口 {self.port}")
        
        self.running = True
        await self._update_metrics_loop()
        
    async def _update_metrics_loop(self):
        """更新指标循环"""
        redis_client = await redis.from_url(self.redis_url, decode_responses=True)
        
        while self.running:
            try:
                # 获取Redis信息
                info = await redis_client.info()
                
                # 更新指标
                REDIS_MEMORY_USAGE.set(info.get('used_memory', 0))
                
                # 获取连接数
                connections = await redis_client.keys("connection:*")
                ACTIVE_CONNECTIONS.set(len(connections))
                
                # 等待下一次更新
                await asyncio.sleep(10)
                
            except Exception as e:
                print(f"更新指标失败: {e}")
                await asyncio.sleep(30)
                
        await redis_client.close()
        
    def stop(self):
        """停止指标导出器"""
        self.running = False

# 在消息处理函数中添加指标记录
def record_message_metrics():
    """记录消息处理指标"""
    def decorator(func):
        async def wrapper(*args, **kwargs):
            start_time = time.time()
            
            try:
                result = await func(*args, **kwargs)
                
                # 记录延迟
                latency = time.time() - start_time
                MESSAGE_LATENCY.observe(latency)
                
                # 增加消息计数
                MESSAGES_PROCESSED.inc()
                
                return result
            except Exception as e:
                # 记录错误
                print(f"消息处理错误: {e}")
                raise
                
        return wrapper
    return decorator
```

## 7. 故障排除

### 7.1 常见问题

#### 问题1: Redis连接失败
**症状**: `Redis connection error` 或 `Connection refused`
**解决方案**:
```bash
# 检查Redis服务状态
sudo systemctl status redis

# 重启Redis
sudo systemctl restart redis

# 检查端口
netstat -tlnp | grep 6379

# 检查防火墙
sudo ufw allow 6379
```

#### 问题2: WebSocket连接失败
**症状**: `Connection refused` 或 `Timeout`
**解决方案**:
```bash
# 检查服务器是否运行
ps aux | grep python

# 检查端口占用
netstat -tlnp | grep 8765

# 检查防火墙
sudo ufw allow 8765

# 检查服务器日志
tail -f server.log
```

#### 问题3: 内存使用过高
**症状**: 系统变慢，Redis内存使用持续增长
**解决方案**:
```python
# 调整Redis配置
# 在Redis配置文件中添加:
maxmemory 512mb
maxmemory-policy allkeys-lru

# 调整检查点TTL
checkpointer = AsyncRedisSaver(
    connection=redis_client,
    ttl_config={
        "default_ttl": 60,  # 减少到60分钟
        "refresh_on_read": False  # 不刷新TTL
    }
)

# 定期清理旧会话
async def cleanup_old_sessions():
    """清理旧会话"""
    # 获取所有会话
    sessions = await redis_client.keys("user:*:sessions")
    
    for session_key in sessions:
        # 检查最后活动时间
        session_data = await redis_client.hgetall(session_key)
        for session_id, session_json in session_data.items():
            session_info = json.loads(session_json)
            last_active = datetime.fromisoformat(session_info.get("last_connected", ""))
            
            # 如果超过7天未活动，删除
            if (datetime.now() - last_active).days > 7:
                await redis_client.hdel(session_key, session_id)
```

#### 问题4: 消息丢失
**症状**: 客户端发送消息但未收到响应
**解决方案**:
```python
# 添加消息确认机制
async def send_message_with_ack(websocket, message, timeout=5.0):
    """发送带确认的消息"""
    message_id = str(uuid.uuid4())
    message["message_id"] = message_id
    
    await websocket.send(json.dumps(message))
    
    # 等待确认
    try:
        ack = await asyncio.wait_for(websocket.recv(), timeout=timeout)
        ack_data = json.loads(ack)
        
        if ack_data.get("type") == "ack" and ack_data.get("message_id") == message_id:
            return True
        else:
            return False
    except asyncio.TimeoutError:
        return False

# 添加重试机制
async def send_message_with_retry(websocket, message, max_retries=3):
    """带重试的消息发送"""
    for attempt in range(max_retries):
        try:
            success = await send_message_with_ack(websocket, message)
            if success:
                return True
        except Exception as e:
            print(f"发送消息失败 (尝试 {attempt + 1}): {e}")
            
        # 等待后重试
        await asyncio.sleep(1.0 * (attempt + 1))
        
    return False
```

### 7.2 调试技巧

#### 启用调试日志
```python
# 在配置中启用调试
config = {
    "debug": True,
    "log_level": "DEBUG"
}

# 在代码中添加调试日志
import logging
logger = logging.getLogger(__name__)

async def handle_message(self, message):
    logger.debug(f"收到消息: {message}")
    # ... 处理逻辑
    logger.debug(f"处理完成: {result}")
```

#### 使用Redis监控命令
```bash
# 监控Redis命令
redis-cli monitor

# 查看Redis内存使用
redis-cli info memory

# 查看连接信息
redis-cli info clients

# 查看键空间统计
redis-cli info keyspace
```

#### 网络调试
```bash
# 使用telnet测试连接
telnet localhost 8765

# 使用netcat测试
echo -e "GET / HTTP/1.1\r\nHost: localhost\r\nConnection: Upgrade\r\nUpgrade: websocket\r\n\r\n" | nc localhost 8765

# 使用curl测试WebSocket
curl -i -N -H "Connection: Upgrade" -H "Upgrade: websocket" \
  -H "Host: localhost" -H "Origin: http://localhost" \
  http://localhost:8765
```

## 8. 安全建议

### 8.1 认证和授权
```python
# 添加JWT认证
import jwt
from datetime import datetime, timedelta

class AuthenticationManager:
    """认证管理器"""
    
    def __init__(self, secret_key: str, algorithm: str = "HS256"):
        self.secret_key = secret_key
        self.algorithm = algorithm
        
    def create_token(self, user_id: str, expires_in: int = 3600) -> str:
        """创建JWT令牌"""
        payload = {
            "user_id": user_id,
            "exp": datetime.utcnow() + timedelta(seconds=expires_in),
            "iat": datetime.utcnow()
        }
        
        return jwt.encode(payload, self.secret_key, algorithm=self.algorithm)
        
    def verify_token(self, token: str) -> Optional[Dict[str, Any]]:
        """验证JWT令牌"""
        try:
            payload = jwt.decode(token, self.secret_key, algorithms=[self.algorithm])
            return payload
        except jwt.ExpiredSignatureError:
            print("令牌已过期")
            return None
        except jwt.InvalidTokenError:
            print("无效令牌")
            return None
```

### 8.2 输入验证
```python
def validate_message(message: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    """验证消息格式"""
    # 检查必需字段
    required_fields = ["type", "timestamp"]
    for field in required_fields:
        if field not in message:
            return False, f"缺少必需字段: {field}"
            
    # 验证消息类型
    valid_types = ["text", "command", "heartbeat", "system"]
    if message["type"] not in valid_types:
        return False, f"无效的消息类型: {message['type']}"
        
    # 验证时间戳
    try:
        datetime.fromisoformat(message["timestamp"].replace('Z', '+00:00'))
    except (ValueError, TypeError):
        return False, "无效的时间戳格式"
        
    # 验证内容长度
    if message["type"] == "text" and "content" in message:
        content = message["content"]
        if len(content) > 10000:  # 10KB限制
            return False, "消息内容过长"
        if len(content.strip()) == 0:
            return False, "消息内容不能为空"
            
    return True, None
```

### 8.3 速率限制
```python
class RateLimiter:
    """速率限制器"""
    
    def __init__(self, redis_client: Redis, limits: Dict[str, Tuple[int, int]]):
        """
        limits: {"action": (limit, window)}
        例如: {"send_message": (60, 60)}  # 每分钟60次
        """
        self.redis = redis_client
        self.limits = limits
        
    async def check_limit(self, user_id: str, action: str) -> Tuple[bool, Optional[int]]:
        """检查速率限制"""
        if action not in self.limits:
            return True, None
            
        limit, window = self.limits[action]
        key = f"ratelimit:{user_id}:{action}"
        
        # 使用Redis计数器
        current = await self.redis.incr(key)
        
        if current == 1:
            # 第一次设置过期时间
            await self.redis.expire(key, window)
            
        if current > limit:
            # 计算剩余时间
            ttl = await self.redis.ttl(key)
            return False, ttl
            
        return True, None
```

## 9. 备份和恢复

### 9.1 数据备份
```python
async def backup_sessions(redis_url: str, backup_dir: str = "backups"):
    """备份会话数据"""
    import os
    from datetime import datetime
    
    # 创建备份目录
    os.makedirs(backup_dir, exist_ok=True)
    
    # 连接Redis
    redis_client = await redis.from_url(redis_url, decode_responses=True)
    
    try:
        # 获取所有用户会话
        user_keys = await redis_client.keys("user:*:sessions")
        
        backup_data = {}
        
        for user_key in user_keys:
            user_id = user_key.split(":")[1]
            sessions = await redis_client.hgetall(user_key)
            
            backup_data[user_id] = {
                "backup_time": datetime.now().isoformat(),
                "sessions": sessions
            }
            
        # 保存备份文件
        backup_file = os.path.join(
            backup_dir,
            f"sessions_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        )
        
        with open(backup_file, 'w') as f:
            json.dump(backup_data, f, indent=2)
            
        print(f"备份完成: {backup_file}")
        
        # 保留最近7个备份
        backup_files = sorted([
            f for f in os.listdir(backup_dir)
            if f.startswith("sessions_backup_") and f.endswith(".json")
        ])
        
        if len(backup_files) > 7:
            for old_file in backup_files[:-7]:
                os.remove(os.path.join(backup_dir, old_file))
                
    finally:
        await redis_client.close()
```

### 9.2 数据恢复
```python
async def restore_sessions(redis_url: str, backup_file: str):
    """从备份恢复数据"""
    # 读取备份文件
    with open(backup_file, 'r') as f:
        backup_data = json.load(f)
        
    # 连接Redis
    redis_client = await redis.from_url(redis_url, decode_responses=True)
    
    try:
        for user_id, user_data in backup_data.items():
            sessions = user_data["sessions"]
            
            if sessions:
                # 恢复用户会话
                await redis_client.hset(
                    f"user:{user_id}:sessions",
                    mapping=sessions
                )
                
        print(f"恢复完成: {len(backup_data)}个用户")
        
    finally:
        await redis_client.close()
```

## 10. 扩展和优化

### 10.1 水平扩展
- **添加更多服务器节点**: 增加 `server_id` 和端口
- **使用Redis集群**: 提高Redis性能和可用性
- **添加消息队列**: 使用RabbitMQ或Kafka处理高并发消息
- **添加缓存层**: 使用Memcached缓存频繁访问的数据

### 10.2 垂直优化
- **优化Redis配置**: 调整内存策略和持久化设置
- **优化检查点策略**: 调整TTL和保存频率
- **添加连接池**: 优化数据库连接管理
- **启用压缩**: 对消息进行压缩减少网络流量

### 10.3 功能扩展
- **添加文件传输**: 支持图片、文件上传
- **添加群组聊天**: 支持多人群聊功能
- **添加消息搜索**: 支持历史消息搜索
- **添加AI助手**: 集成大语言模型提供智能回复
- **添加数据分析**: 分析用户行为和对话模式

通过以上部署和测试指南，您可以成功部署和运维基于LangGraph和Redis的分布式WebSocket对话系统。