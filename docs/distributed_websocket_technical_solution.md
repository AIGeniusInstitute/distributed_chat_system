# 基于LangGraph和Redis的分布式WebSocket对话系统技术方案

## 1. 系统概述

### 1.1 问题背景
在现代分布式系统中，实现多端多机器的用户对话系统面临以下挑战：
1. **消息一致性**：用户在不同设备或不同服务器上连接时，需要确保消息的同步和一致性
2. **断点恢复**：连接中断后能够恢复对话状态，保持上下文连续性
3. **分布式协调**：多服务器间的会话状态共享和消息路由
4. **状态持久化**：对话状态的持久化存储和快速恢复

### 1.2 解决方案架构
本方案采用LangGraph作为对话状态管理框架，Redis作为分布式协调和状态存储中间件，WebSocket作为实时通信协议，构建一个完整的分布式对话系统。

## 2. 核心技术组件

### 2.1 LangGraph
LangGraph是LangChain生态的扩展框架，专注于构建复杂、有状态的AI系统。其核心特性包括：
- **状态图（StateGraph）**：管理节点和边，支持动态路由、循环和状态管理
- **检查点（Checkpoint）**：在图执行的每一步保存状态，支持状态持久化、恢复和多轮交互
- **RedisSaver**：将状态图的检查点保存到Redis数据库，支持同步操作，适合生产环境中的高并发场景

### 2.2 Redis
Redis作为分布式系统的核心组件，提供以下功能：
- **Pub/Sub机制**：实现服务器间的消息广播和订阅
- **键值存储**：存储会话状态和检查点数据
- **分布式锁**：协调多服务器间的并发操作
- **TTL支持**：自动过期旧数据，减少存储占用

### 2.3 WebSocket
WebSocket提供全双工通信通道，支持：
- **实时消息传递**：低延迟的消息推送
- **连接管理**：连接建立、维护和断开处理
- **心跳机制**：保持连接活跃，检测连接状态

## 3. 系统架构设计

### 3.1 整体架构
```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│  客户端设备A    │    │  客户端设备B    │    │  客户端设备C    │
│  (Web/App)      │    │  (Web/App)      │    │  (Web/App)      │
└────────┬────────┘    └────────┬────────┘    └────────┬────────┘
         │                      │                      │
         │ WebSocket连接        │ WebSocket连接        │ WebSocket连接
         │                      │                      │
┌────────▼────────┐    ┌────────▼────────┐    ┌────────▼────────┐
│  WebSocket服务器1 │    │  WebSocket服务器2 │    │  WebSocket服务器3 │
│  (Node 1)       │    │  (Node 2)       │    │  (Node 3)       │
└────────┬────────┘    └────────┬────────┘    └────────┬────────┘
         │                      │                      │
         │ Redis Pub/Sub        │ Redis Pub/Sub        │ Redis Pub/Sub
         │                      │                      │
         └──────────┬───────────┴──────────┬───────────┘
                    │                      │
            ┌───────▼───────┐      ┌───────▼───────┐
            │   Redis集群   │      │  LangGraph    │
            │               │      │  状态引擎     │
            │  - 会话状态   │      │               │
            │  - 检查点数据 │      └───────────────┘
            │  - 消息队列   │
            └───────────────┘
```

### 3.2 数据流设计
1. **客户端连接**：客户端通过WebSocket连接到任意可用服务器
2. **会话注册**：服务器在Redis中注册会话信息，包括用户ID、设备ID、服务器节点
3. **消息处理**：接收客户端消息，通过LangGraph处理对话状态
4. **状态保存**：使用RedisSaver保存检查点到Redis
5. **消息广播**：通过Redis Pub/Sub将消息广播到所有相关服务器
6. **消息推送**：各服务器将消息推送到对应的客户端连接

### 3.3 状态管理设计
- **会话状态**：存储在Redis中，包含用户上下文、对话历史、当前状态
- **检查点机制**：使用LangGraph的检查点功能，每步对话都保存状态
- **状态恢复**：连接恢复时从Redis加载最近的检查点，继续对话

## 4. 关键技术实现

### 4.1 RedisSaver配置
```python
from langgraph.checkpoint.redis import RedisSaver
from redis import Redis

# Redis连接配置
redis_client = Redis.from_url(
    "redis://localhost:6379",
    max_connections=20,
    decode_responses=True
)

# RedisSaver初始化
checkpointer = RedisSaver(
    connection=redis_client,
    ttl_config={
        "default_ttl": 120,  # 默认存活时间120分钟
        "refresh_on_read": True  # 读取时刷新TTL
    }
)
checkpointer.setup()  # 初始化Redis索引
```

### 4.2 对话状态定义
```python
from typing import List, Dict, Any
from typing_extensions import TypedDict
from datetime import datetime

class ConversationState(TypedDict):
    """对话状态定义"""
    user_id: str
    session_id: str
    messages: List[Dict[str, Any]]  # 对话历史
    context: Dict[str, Any]  # 对话上下文
    metadata: Dict[str, Any]  # 元数据
    last_updated: datetime  # 最后更新时间
    current_node: str  # 当前状态图节点
    checkpoint_id: str  # 当前检查点ID
```

### 4.3 WebSocket服务器实现
```python
import asyncio
import json
import uuid
from typing import Dict, Set
from websockets.server import WebSocketServerProtocol
from websockets.exceptions import ConnectionClosed

class WebSocketServer:
    """分布式WebSocket服务器"""
    
    def __init__(self, redis_client, checkpointer):
        self.redis = redis_client
        self.checkpointer = checkpointer
        self.connections: Dict[str, WebSocketServerProtocol] = {}
        self.user_sessions: Dict[str, Set[str]] = {}  # 用户ID -> 会话ID集合
        
    async def handle_connection(self, websocket, path):
        """处理WebSocket连接"""
        session_id = str(uuid.uuid4())
        user_id = await self.authenticate(websocket)
        
        # 注册会话
        await self.register_session(user_id, session_id, websocket)
        
        try:
            async for message in websocket:
                await self.handle_message(user_id, session_id, message)
        except ConnectionClosed:
            await self.unregister_session(user_id, session_id)
```

### 4.4 消息一致性保证
```python
class MessageConsistencyManager:
    """消息一致性管理器"""
    
    def __init__(self, redis_client):
        self.redis = redis_client
        self.message_channel = "websocket:messages"
        
    async def publish_message(self, user_id: str, message: Dict[str, Any]):
        """发布消息到Redis Pub/Sub"""
        message_data = {
            "user_id": user_id,
            "message": message,
            "timestamp": datetime.now().isoformat(),
            "message_id": str(uuid.uuid4())
        }
        
        # 保存消息到Redis（用于断点恢复）
        await self.redis.setex(
            f"message:{message_data['message_id']}",
            3600,  # 1小时过期
            json.dumps(message_data)
        )
        
        # 发布到Redis频道
        await self.redis.publish(
            self.message_channel,
            json.dumps(message_data)
        )
        
    async def subscribe_messages(self):
        """订阅消息频道"""
        pubsub = self.redis.pubsub()
        await pubsub.subscribe(self.message_channel)
        
        async for message in pubsub.listen():
            if message["type"] == "message":
                data = json.loads(message["data"])
                await self.distribute_message(data)
```

### 4.5 断点恢复机制
```python
class SessionRecoveryManager:
    """会话恢复管理器"""
    
    def __init__(self, checkpointer, redis_client):
        self.checkpointer = checkpointer
        self.redis = redis_client
        
    async def save_checkpoint(self, user_id: str, state: ConversationState):
        """保存检查点"""
        config = {
            "configurable": {
                "thread_id": f"user:{user_id}",
                "checkpoint_ns": "conversation"
            }
        }
        
        # 保存到LangGraph检查点
        checkpoint_id = await self.checkpointer.put(config, state)
        
        # 在Redis中记录最新检查点
        await self.redis.setex(
            f"user:{user_id}:latest_checkpoint",
            7200,  # 2小时过期
            checkpoint_id
        )
        
        return checkpoint_id
        
    async def restore_session(self, user_id: str):
        """恢复会话"""
        # 获取最新检查点ID
        checkpoint_id = await self.redis.get(f"user:{user_id}:latest_checkpoint")
        
        if checkpoint_id:
            config = {
                "configurable": {
                    "thread_id": f"user:{user_id}",
                    "checkpoint_ns": "conversation"
                }
            }
            
            # 从检查点恢复状态
            checkpoint_tuple = await self.checkpointer.get_tuple(config)
            
            if checkpoint_tuple:
                # 获取未处理的消息
                pending_messages = await self.get_pending_messages(user_id)
                
                return {
                    "state": checkpoint_tuple.state,
                    "pending_messages": pending_messages,
                    "checkpoint_id": checkpoint_id
                }
        
        return None
```

## 5. 完整实现代码

### 5.1 项目结构
```
distributed-chat-system/
├── requirements.txt
├── config/
│   ├── __init__.py
│   └── settings.py
├── core/
│   ├── __init__.py
│   ├── state_manager.py
│   ├── message_broker.py
│   └── session_manager.py
├── websocket/
│   ├── __init__.py
│   ├── server.py
│   └── handler.py
├── langgraph/
│   ├── __init__.py
│   ├── graph_builder.py
│   └── nodes.py
├── redis/
│   ├── __init__.py
│   ├── client.py
│   └── pubsub.py
└── main.py
```

### 5.2 主应用程序
```python
# main.py
import asyncio
import logging
from typing import Dict, Any
from datetime import datetime

from redis.asyncio import Redis
from langgraph.checkpoint.redis import AsyncRedisSaver
from langgraph.graph import StateGraph, START, END
from websockets.server import serve

from core.state_manager import ConversationStateManager
from websocket.server import WebSocketServer
from redis.pubsub import MessageBroker

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class DistributedChatSystem:
    """分布式聊天系统主类"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.redis_client = None
        self.checkpointer = None
        self.state_manager = None
        self.message_broker = None
        self.websocket_server = None
        
    async def initialize(self):
        """初始化系统组件"""
        # 初始化Redis连接
        self.redis_client = await Redis.from_url(
            self.config["redis_url"],
            max_connections=self.config.get("redis_max_connections", 20),
            decode_responses=True
        )
        
        # 初始化RedisSaver
        self.checkpointer = AsyncRedisSaver(
            connection=self.redis_client,
            ttl_config={
                "default_ttl": self.config.get("checkpoint_ttl", 120),
                "refresh_on_read": True
            }
        )
        await self.checkpointer.setup()
        
        # 初始化状态管理器
        self.state_manager = ConversationStateManager(
            checkpointer=self.checkpointer,
            redis_client=self.redis_client
        )
        
        # 初始化消息代理
        self.message_broker = MessageBroker(
            redis_client=self.redis_client,
            channels=["websocket:messages", "system:notifications"]
        )
        
        # 初始化WebSocket服务器
        self.websocket_server = WebSocketServer(
            redis_client=self.redis_client,
            state_manager=self.state_manager,
            message_broker=self.message_broker,
            config=self.config
        )
        
        logger.info("系统初始化完成")
        
    async def build_conversation_graph(self):
        """构建对话状态图"""
        from langgraph.nodes import (
            process_user_message,
            generate_response,
            update_context,
            save_checkpoint
        )
        
        # 定义状态
        class ConversationState(TypedDict):
            user_id: str
            session_id: str
            messages: List[Dict[str, Any]]
            context: Dict[str, Any]
            current_intent: str
            metadata: Dict[str, Any]
            last_updated: datetime
            
        # 创建状态图
        builder = StateGraph(ConversationState)
        
        # 添加节点
        builder.add_node("process_input", process_user_message)
        builder.add_node("generate_response", generate_response)
        builder.add_node("update_context", update_context)
        builder.add_node("save_state", save_checkpoint)
        
        # 添加边
        builder.add_edge(START, "process_input")
        builder.add_edge("process_input", "generate_response")
        builder.add_edge("generate_response", "update_context")
        builder.add_edge("update_context", "save_state")
        builder.add_edge("save_state", END)
        
        # 编译图
        graph = builder.compile(checkpointer=self.checkpointer)
        
        return graph
        
    async def start(self):
        """启动系统"""
        # 启动消息代理
        await self.message_broker.start()
        
        # 启动WebSocket服务器
        server_config = {
            "host": self.config["websocket_host"],
            "port": self.config["websocket_port"],
            "ssl_context": self.config.get("ssl_context")
        }
        
        async with serve(
            self.websocket_server.handle_connection,
            server_config["host"],
            server_config["port"],
            ssl=server_config.get("ssl_context")
        ):
            logger.info(f"WebSocket服务器启动在 {server_config['host']}:{server_config['port']}")
            await asyncio.Future()  # 永久运行
            
    async def shutdown(self):
        """关闭系统"""
        if self.websocket_server:
            await self.websocket_server.shutdown()
            
        if self.message_broker:
            await self.message_broker.stop()
            
        if self.redis_client:
            await self.redis_client.close()
            
        logger.info("系统已关闭")

async def main():
    """主函数"""
    config = {
        "redis_url": "redis://localhost:6379",
        "redis_max_connections": 20,
        "checkpoint_ttl": 120,
        "websocket_host": "0.0.0.0",
        "websocket_port": 8765,
        "max_message_size": 1048576,  # 1MB
        "heartbeat_interval": 30,
        "session_timeout": 300
    }
    
    system = DistributedChatSystem(config)
    
    try:
        await system.initialize()
        await system.start()
    except KeyboardInterrupt:
        logger.info("接收到中断信号")
    finally:
        await system.shutdown()

if __name__ == "__main__":
    asyncio.run(main())
```

### 5.3 状态管理器实现
```python
# core/state_manager.py
import json
import asyncio
from typing import Dict, List, Any, Optional
from datetime import datetime
from uuid import uuid4

from langgraph.checkpoint.redis import AsyncRedisSaver
from redis.asyncio import Redis

class ConversationStateManager:
    """对话状态管理器"""
    
    def __init__(self, checkpointer: AsyncRedisSaver, redis_client: Redis):
        self.checkpointer = checkpointer
        self.redis = redis_client
        
    async def create_session(self, user_id: str, device_id: str) -> Dict[str, Any]:
        """创建新会话"""
        session_id = str(uuid4())
        
        initial_state = {
            "user_id": user_id,
            "session_id": session_id,
            "device_id": device_id,
            "messages": [],
            "context": {
                "topic": None,
                "language": "zh-CN",
                "tone": "neutral"
            },
            "metadata": {
                "created_at": datetime.now().isoformat(),
                "last_active": datetime.now().isoformat(),
                "message_count": 0
            },
            "current_node": "start",
            "checkpoint_id": None
        }
        
        # 保存初始状态
        config = {
            "configurable": {
                "thread_id": f"user:{user_id}:session:{session_id}",
                "checkpoint_ns": "conversation"
            }
        }
        
        checkpoint_id = await self.checkpointer.put(config, initial_state)
        initial_state["checkpoint_id"] = checkpoint_id
        
        # 在Redis中记录会话
        await self.redis.hset(
            f"user:{user_id}:sessions",
            session_id,
            json.dumps({
                "device_id": device_id,
                "created_at": initial_state["metadata"]["created_at"],
                "checkpoint_id": checkpoint_id
            })
        )
        
        return initial_state
        
    async def process_message(self, user_id: str, session_id: str, 
                            message: Dict[str, Any], graph) -> Dict[str, Any]:
        """处理消息并更新状态"""
        # 获取当前状态
        config = {
            "configurable": {
                "thread_id": f"user:{user_id}:session:{session_id}",
                "checkpoint_ns": "conversation"
            }
        }
        
        # 执行状态图
        new_state = await graph.ainvoke(
            {"messages": [message]},
            config=config
        )
        
        # 更新最后活跃时间
        new_state["metadata"]["last_active"] = datetime.now().isoformat()
        new_state["metadata"]["message_count"] += 1
        
        # 保存消息历史
        await self.redis.rpush(
            f"user:{user_id}:session:{session_id}:messages",
            json.dumps(message)
        )
        
        # 限制消息历史长度
        await self.redis.ltrim(
            f"user:{user_id}:session:{session_id}:messages",
            0, 99  # 保留最近100条消息
        )
        
        return new_state
        
    async def get_session_state(self, user_id: str, session_id: str) -> Optional[Dict[str, Any]]:
        """获取会话状态"""
        config = {
            "configurable": {
                "thread_id": f"user:{user_id}:session:{session_id}",
                "checkpoint_ns": "conversation"
            }
        }
        
        checkpoint_tuple = await self.checkpointer.get_tuple(config)
        
        if checkpoint_tuple:
            return checkpoint_tuple.state
            
        return None
        
    async def list_user_sessions(self, user_id: str) -> List[Dict[str, Any]]:
        """列出用户的所有会话"""
        sessions_data = await self.redis.hgetall(f"user:{user_id}:sessions")
        
        sessions = []
        for session_id, session_json in sessions_data.items():
            session_info = json.loads(session_json)
            session_info["session_id"] = session_id
            sessions.append(session_info)
            
        return sessions
```

### 5.4 WebSocket处理器
```python
# websocket/handler.py
import json
import asyncio
from typing import Dict, Any
from websockets.server import WebSocketServerProtocol

from core.state_manager import ConversationStateManager
from redis.pubsub import MessageBroker

class WebSocketHandler:
    """WebSocket消息处理器"""
    
    def __init__(self, state_manager: ConversationStateManager, 
                 message_broker: MessageBroker):
        self.state_manager = state_manager
        self.message_broker = message_broker
        self.active_sessions: Dict[str, Dict[str, Any]] = {}
        
    async def handle_connect(self, websocket: WebSocketServerProtocol, 
                           user_id: str, device_id: str) -> Dict[str, Any]:
        """处理连接请求"""
        # 检查是否有现有会话
        sessions = await self.state_manager.list_user_sessions(user_id)
        
        if sessions:
            # 恢复最近会话
            latest_session = max(sessions, key=lambda x: x["created_at"])
            session_id = latest_session["session_id"]
            
            # 恢复状态
            state = await self.state_manager.get_session_state(user_id, session_id)
            
            if state:
                # 发送恢复的消息
                await self.send_recovery_message(websocket, state, latest_session)
                return {"session_id": session_id, "recovered": True}
        
        # 创建新会话
        state = await self.state_manager.create_session(user_id, device_id)
        session_id = state["session_id"]
        
        # 发送欢迎消息
        welcome_message = {
            "type": "system",
            "content": "连接已建立，开始对话吧！",
            "timestamp": datetime.now().isoformat()
        }
        
        await websocket.send(json.dumps(welcome_message))
        
        return {"session_id": session_id, "recovered": False}
        
    async def handle_message(self, websocket: WebSocketServerProtocol,
                           user_id: str, session_id: str,
                           message_data: Dict[str, Any]) -> None:
        """处理客户端消息"""
        # 验证消息格式
        if not self.validate_message(message_data):
            error_response = {
                "type": "error",
                "code": "INVALID_MESSAGE",
                "message": "消息格式无效"
            }
            await websocket.send(json.dumps(error_response))
            return
            
        # 处理消息类型
        message_type = message_data.get("type", "text")
        
        if message_type == "text":
            await self.handle_text_message(websocket, user_id, session_id, message_data)
        elif message_type == "command":
            await self.handle_command_message(websocket, user_id, session_id, message_data)
        elif message_type == "heartbeat":
            await self.handle_heartbeat(websocket, user_id, session_id)
        else:
            # 未知消息类型
            error_response = {
                "type": "error",
                "code": "UNKNOWN_MESSAGE_TYPE",
                "message": f"未知的消息类型: {message_type}"
            }
            await websocket.send(json.dumps(error_response))
            
    async def handle_text_message(self, websocket: WebSocketServerProtocol,
                                user_id: str, session_id: str,
                                message_data: Dict[str, Any]) -> None:
        """处理文本消息"""
        # 构建消息对象
        message = {
            "type": "user",
            "content": message_data["content"],
            "timestamp": datetime.now().isoformat(),
            "message_id": str(uuid4())
        }
        
        # 通过消息代理广播
        await self.message_broker.publish_user_message(
            user_id=user_id,
            session_id=session_id,
            message=message
        )
        
        # 发送确认
        ack_message = {
            "type": "ack",
            "message_id": message["message_id"],
            "timestamp": datetime.now().isoformat()
        }
        
        await websocket.send(json.dumps(ack_message))
        
    async def handle_command_message(self, websocket: WebSocketServerProtocol,
                                   user_id: str, session_id: str,
                                   message_data: Dict[str, Any]) -> None:
        """处理命令消息"""
        command = message_data.get("command")
        
        if command == "get_history":
            # 获取历史消息
            await self.send_history(websocket, user_id, session_id)
        elif command == "clear_history":
            # 清空历史
            await self.clear_history(user_id, session_id)
            response = {
                "type": "system",
                "content": "历史记录已清空",
                "timestamp": datetime.now().isoformat()
            }
            await websocket.send(json.dumps(response))
        elif command == "switch_topic":
            # 切换话题
            topic = message_data.get("topic")
            await self.switch_topic(user_id, session_id, topic)
            response = {
                "type": "system",
                "content": f"话题已切换到: {topic}",
                "timestamp": datetime.now().isoformat()
            }
            await websocket.send(json.dumps(response))
        else:
            # 未知命令
            error_response = {
                "type": "error",
                "code": "UNKNOWN_COMMAND",
                "message": f"未知的命令: {command}"
            }
            await websocket.send(json.dumps(error_response))
            
    async def handle_heartbeat(self, websocket: WebSocketServerProtocol,
                             user_id: str, session_id: str) -> None:
        """处理心跳消息"""
        # 更新会话活跃时间
        await self.state_manager.update_session_activity(user_id, session_id)
        
        # 发送心跳响应
        heartbeat_response = {
            "type": "heartbeat",
            "timestamp": datetime.now().isoformat(),
            "server_time": datetime.now().isoformat()
        }
        
        await websocket.send(json.dumps(heartbeat_response))
        
    async def send_recovery_message(self, websocket: WebSocketServerProtocol,
                                  state: Dict[str, Any],
                                  session_info: Dict[str, Any]) -> None:
        """发送会话恢复消息"""
        recovery_message = {
            "type": "system",
            "content": "会话已恢复",
            "timestamp": datetime.now().isoformat(),
            "session_info": {
                "session_id": state["session_id"],
                "last_active": state["metadata"]["last_active"],
                "message_count": state["metadata"]["message_count"]
            }
        }
        
        await websocket.send(json.dumps(recovery_message))
        
        # 发送最近的消息历史
        await self.send_recent_history(websocket, state)
        
    async def send_recent_history(self, websocket: WebSocketServerProtocol,
                                state: Dict[str, Any]) -> None:
        """发送最近的消息历史"""
        if state["messages"]:
            history_message = {
                "type": "history",
                "messages": state["messages"][-10:],  # 最近10条消息
                "timestamp": datetime.now().isoformat()
            }
            
            await websocket.send(json.dumps(history_message))
            
    def validate_message(self, message_data: Dict[str, Any]) -> bool:
        """验证消息格式"""
        required_fields = ["type", "timestamp"]
        
        for field in required_fields:
            if field not in message_data:
                return False
                
        # 验证时间戳格式
        try:
            datetime.fromisoformat(message_data["timestamp"].replace('Z', '+00:00'))
        except (ValueError, TypeError):
            return False
            
        return True
```

### 5.5 Redis消息代理
```python
# redis/pubsub.py
import json
import asyncio
from typing import Dict, Any, List, Callable
from datetime import datetime

from redis.asyncio import Redis

class MessageBroker:
    """Redis消息代理"""
    
    def __init__(self, redis_client: Redis, channels: List[str]):
        self.redis = redis_client
        self.channels = channels
        self.pubsub = None
        self.handlers: Dict[str, List[Callable]] = {}
        self.running = False
        
    async def start(self):
        """启动消息代理"""
        self.pubsub = self.redis.pubsub()
        
        # 订阅所有频道
        for channel in self.channels:
            await self.pubsub.subscribe(channel)
            self.handlers[channel] = []
            
        self.running = True
        
        # 启动消息处理循环
        asyncio.create_task(self._message_loop())
        
    async def stop(self):
        """停止消息代理"""
        self.running = False
        
        if self.pubsub:
            await self.pubsub.unsubscribe()
            await self.pubsub.close()
            
    async def _message_loop(self):
        """消息处理循环"""
        while self.running:
            try:
                message = await self.pubsub.get_message(
                    ignore_subscribe_messages=True,
                    timeout=1.0
                )
                
                if message and message["type"] == "message":
                    channel = message["channel"].decode()
                    data = json.loads(message["data"])
                    
                    # 调用注册的处理函数
                    if channel in self.handlers:
                        for handler in self.handlers[channel]:
                            try:
                                await handler(data)
                            except Exception as e:
                                print(f"消息处理错误: {e}")
                                
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                print(f"消息循环错误: {e}")
                await asyncio.sleep(1)
                
    def register_handler(self, channel: str, handler: Callable):
        """注册消息处理函数"""
        if channel in self.handlers:
            self.handlers[channel].append(handler)
        else:
            self.handlers[channel] = [handler]
            
    async def publish(self, channel: str, data: Dict[str, Any]):
        """发布消息"""
        await self.redis.publish(channel, json.dumps(data))
        
    async def publish_user_message(self, user_id: str, session_id: str, 
                                 message: Dict[str, Any]):
        """发布用户消息"""
        message_data = {
            "type": "user_message",
            "user_id": user_id,
            "session_id": session_id,
            "message": message,
            "timestamp": datetime.now().isoformat(),
            "source": "websocket"
        }
        
        await self.publish("websocket:messages", message_data)
        
    async def publish_system_notification(self, notification_type: str,
                                        data: Dict[str, Any]):
        """发布系统通知"""
        notification = {
            "type": "system_notification",
            "notification_type": notification_type,
            "data": data,
            "timestamp": datetime.now().isoformat()
        }
        
        await self.publish("system:notifications", notification)
```

### 5.6 配置文件
```python
# config/settings.py
import os
from typing import Dict, Any

# Redis配置
REDIS_CONFIG = {
    "url": os.getenv("REDIS_URL", "redis://localhost:6379"),
    "max_connections": int(os.getenv("REDIS_MAX_CONNECTIONS", "20")),
    "decode_responses": True,
    "health_check_interval": 30
}

# WebSocket配置
WEBSOCKET_CONFIG = {
    "host": os.getenv("WEBSOCKET_HOST", "0.0.0.0"),
    "port": int(os.getenv("WEBSOCKET_PORT", "8765")),
    "max_message_size": int(os.getenv("MAX_MESSAGE_SIZE", "1048576")),  # 1MB
    "heartbeat_interval": int(os.getenv("HEARTBEAT_INTERVAL", "30")),  # 秒
    "session_timeout": int(os.getenv("SESSION_TIMEOUT", "300")),  # 秒
    "ssl_certfile": os.getenv("SSL_CERTFILE"),
    "ssl_keyfile": os.getenv("SSL_KEYFILE")
}

# LangGraph配置
LANGGRAPH_CONFIG = {
    "checkpoint_ttl": int(os.getenv("CHECKPOINT_TTL", "120")),  # 分钟
    "max_checkpoints_per_session": int(os.getenv("MAX_CHECKPOINTS", "100")),
    "checkpoint_interval": int(os.getenv("CHECKPOINT_INTERVAL", "10"))  # 消息数
}

# 系统配置
SYSTEM_CONFIG = {
    "log_level": os.getenv("LOG_LEVEL", "INFO"),
    "debug": os.getenv("DEBUG", "false").lower() == "true",
    "max_sessions_per_user": int(os.getenv("MAX_SESSIONS_PER_USER", "10")),
    "max_messages_per_session": int(os.getenv("MAX_MESSAGES_PER_SESSION", "1000")),
    "cleanup_interval": int(os.getenv("CLEANUP_INTERVAL", "3600"))  # 秒
}

def get_config() -> Dict[str, Any]:
    """获取完整配置"""
    return {
        "redis": REDIS_CONFIG,
        "websocket": WEBSOCKET_CONFIG,
        "langgraph": LANGGRAPH_CONFIG,
        "system": SYSTEM_CONFIG
    }
```

### 5.7 依赖文件
```txt
# requirements.txt
langgraph>=0.2.0
langgraph-checkpoint-redis>=0.0.2
redis>=5.2.1
websockets>=12.0
aiohttp>=3.9.0
asyncio>=3.4.3
python-dateutil>=2.8.2
pydantic>=2.5.0
uvicorn>=0.28.0
fastapi>=0.104.0
python-jose[cryptography]>=3.3.0
passlib[bcrypt]>=1.7.4
python-multipart>=0.0.6
```

## 6. 部署和运维

### 6.1 部署步骤
1. **环境准备**
   ```bash
   # 安装Python 3.10+
   sudo apt-get update
   sudo apt-get install python3.10 python3.10-venv
   
   # 安装Redis
   sudo apt-get install redis-server
   # 或使用Docker
   docker run -d -p 6379:6379 redis/redis-stack:latest
   
   # 创建虚拟环境
   python3.10 -m venv venv
   source venv/bin/activate
   ```

2. **安装依赖**
   ```bash
   pip install -r requirements.txt
   ```

3. **配置环境变量**
   ```bash
   export REDIS_URL="redis://localhost:6379"
   export WEBSOCKET_PORT="8765"
   export LOG_LEVEL="INFO"
   ```

4. **启动服务**
   ```bash
   python main.py
   ```

### 6.2 多服务器部署
```bash
# 服务器1
export SERVER_ID="node1"
export WEBSOCKET_HOST="0.0.0.0"
export WEBSOCKET_PORT="8765"
python main.py

# 服务器2
export SERVER_ID="node2"
export WEBSOCKET_HOST="0.0.0.0"
export WEBSOCKET_PORT="8766"
python main.py

# 服务器3
export SERVER_ID="node3"
export WEBSOCKET_HOST="0.0.0.0"
export WEBSOCKET_PORT="8767"
python main.py
```

### 6.3 负载均衡配置
```nginx
# nginx配置
upstream websocket_servers {
    server 192.168.1.100:8765;
    server 192.168.1.101:8766;
    server 192.168.1.102:8767;
}

server {
    listen 80;
    server_name chat.example.com;
    
    location /ws {
        proxy_pass http://websocket_servers;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 86400;
    }
}
```

## 7. 性能优化

### 7.1 Redis优化
```python
# Redis连接池优化
redis_client = await Redis.from_url(
    redis_url,
    max_connections=50,
    socket_keepalive=True,
    socket_keepalive_options={
        "TCP_KEEPIDLE": 60,
        "TCP_KEEPINTVL": 30,
        "TCP_KEEPCNT": 3
    },
    retry_on_timeout=True,
    health_check_interval=30
)
```

### 7.2 检查点优化
```python
# 检查点策略优化
checkpointer = AsyncRedisSaver(
    connection=redis_client,
    ttl_config={
        "default_ttl": 240,  # 4小时
        "refresh_on_read": True
    },
    checkpoint_strategy={
        "interval": 10,  # 每10条消息保存一次检查点
        "max_checkpoints": 50,  # 最多保存50个检查点
        "cleanup_old": True  # 自动清理旧检查点
    }
)
```

### 7.3 消息批处理
```python
class MessageBatcher:
    """消息批处理器"""
    
    def __init__(self, batch_size: int = 10, flush_interval: float = 1.0):
        self.batch_size = batch_size
        self.flush_interval = flush_interval
        self.batch: List[Dict[str, Any]] = []
        self.last_flush = time.time()
        
    async def add_message(self, message: Dict[str, Any]):
        """添加消息到批次"""
        self.batch.append(message)
        
        # 检查是否需要刷新
        if (len(self.batch) >= self.batch_size or 
            time.time() - self.last_flush >= self.flush_interval):
            await self.flush()
            
    async def flush(self):
        """刷新批次"""
        if self.batch:
            # 批量处理消息
            await self.process_batch(self.batch)
            self.batch.clear()
            self.last_flush = time.time()
```

## 8. 监控和日志

### 8.1 监控指标
```python
class SystemMonitor:
    """系统监控器"""
    
    def __init__(self, redis_client: Redis):
        self.redis = redis_client
        self.metrics: Dict[str, Any] = {
            "active_connections": 0,
            "messages_processed": 0,
            "sessions_active": 0,
            "redis_memory_usage": 0,
            "average_response_time": 0
        }
        
    async def update_metrics(self):
        """更新监控指标"""
        # 获取Redis信息
        info = await self.redis.info()
        self.metrics["redis_memory_usage"] = info["used_memory_human"]
        
        # 获取活跃连接数
        self.metrics["active_connections"] = len(self.connections)
        
        # 发布指标到Redis
        await self.redis.publish(
            "system:metrics",
            json.dumps({
                "timestamp": datetime.now().isoformat(),
                "metrics": self.metrics
            })
        )
```

### 8.2 日志配置
```python
import logging
import logging.handlers

def setup_logging(config: Dict[str, Any]):
    """配置日志系统"""
    log_level = getattr(logging, config.get("log_level", "INFO"))
    
    # 创建日志格式
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # 控制台处理器
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    
    # 文件处理器
    file_handler = logging.handlers.RotatingFileHandler(
        'distributed_chat.log',
        maxBytes=10485760,  # 10MB
        backupCount=5
    )
    file_handler.setFormatter(formatter)
    
    # Redis处理器（可选）
    redis_handler = RedisLogHandler(redis_client)
    redis_handler.setFormatter(formatter)
    
    # 配置根日志器
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)
    
    if config.get("enable_redis_logging", False):
        root_logger.addHandler(redis_handler)
```

## 9. 测试方案

### 9.1 单元测试
```python
# tests/test_state_manager.py
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock
from core.state_manager import ConversationStateManager

@pytest.mark.asyncio
async def test_create_session():
    """测试创建会话"""
    mock_checkpointer = AsyncMock()
    mock_redis = AsyncMock()
    
    manager = ConversationStateManager(mock_checkpointer, mock_redis)
    
    session = await manager.create_session("user123", "device456")
    
    assert session["user_id"] == "user123"
    assert "session_id" in session
    assert session["metadata"]["message_count"] == 0
```

### 9.2 集成测试
```python
# tests/test_integration.py
import pytest
import asyncio
import websockets
from main import DistributedChatSystem

@pytest.mark.asyncio
async def test_websocket_connection():
    """测试WebSocket连接"""
    config = {
        "redis_url": "redis://localhost:6379",
        "websocket_host": "localhost",
        "websocket_port": 8765
    }
    
    system = DistributedChatSystem(config)
    await system.initialize()
    
    # 启动服务器
    server_task = asyncio.create_task(system.start())
    
    # 等待服务器启动
    await asyncio.sleep(1)
    
    # 客户端连接
    async with websockets.connect("ws://localhost:8765/ws") as websocket:
        # 发送认证消息
        auth_message = {
            "type": "auth",
            "user_id": "test_user",
            "device_id": "test_device"
        }
        
        await websocket.send(json.dumps(auth_message))
        
        # 接收响应
        response = await websocket.recv()
        response_data = json.loads(response)
        
        assert response_data["type"] == "system"
        assert "session_id" in response_data
        
    # 清理
    server_task.cancel()
    await system.shutdown()
```

### 9.3 压力测试
```python
# tests/load_test.py
import asyncio
import websockets
import json
from datetime import datetime

async def simulate_user(user_id: str, server_url: str, message_count: int):
    """模拟用户行为"""
    async with websockets.connect(server_url) as websocket:
        # 认证
        auth_message = {
            "type": "auth",
            "user_id": user_id,
            "device_id": f"device_{user_id}"
        }
        await websocket.send(json.dumps(auth_message))
        await websocket.recv()  # 接收响应
        
        # 发送消息
        for i in range(message_count):
            message = {
                "type": "text",
                "content": f"消息 {i}",
                "timestamp": datetime.now().isoformat()
            }
            
            await websocket.send(json.dumps(message))
            response = await websocket.recv()
            
            # 模拟思考时间
            await asyncio.sleep(0.5)
            
async def run_load_test(num_users: int, messages_per_user: int):
    """运行负载测试"""
    server_url = "ws://localhost:8765/ws"
    
    tasks = []
    for i in range(num_users):
        user_id = f"load_test_user_{i}"
        task = asyncio.create_task(
            simulate_user(user_id, server_url, messages_per_user)
        )
        tasks.append(task)
        
    await asyncio.gather(*tasks)
    
    print(f"负载测试完成: {num_users}用户, 每人{messages_per_user}条消息")
```

## 10. 安全考虑

### 10.1 认证和授权
```python
class AuthenticationManager:
    """认证管理器"""
    
    def __init__(self, redis_client: Redis):
        self.redis = redis_client
        self.token_ttl = 3600  # 1小时
        
    async def authenticate(self, token: str) -> Optional[Dict[str, Any]]:
        """验证令牌"""
        user_data = await self.redis.get(f"auth:token:{token}")
        
        if user_data:
            user_info = json.loads(user_data)
            
            # 刷新令牌TTL
            await self.redis.expire(
                f"auth:token:{token}",
                self.token_ttl
            )
            
            return user_info
            
        return None
        
    async def create_token(self, user_id: str, 
                         device_id: str) -> str:
        """创建认证令牌"""
        token = str(uuid4())
        
        user_info = {
            "user_id": user_id,
            "device_id": device_id,
            "created_at": datetime.now().isoformat(),
            "permissions": ["chat", "history"]
        }
        
        await self.redis.setex(
            f"auth:token:{token}",
            self.token_ttl,
            json.dumps(user_info)
        )
        
        return token
```

### 10.2 消息加密
```python
from cryptography.fernet import Fernet

class MessageEncryptor:
    """消息加密器"""
    
    def __init__(self, encryption_key: str):
        self.cipher = Fernet(encryption_key.encode())
        
    def encrypt_message(self, message: Dict[str, Any]) -> str:
        """加密消息"""
        message_json = json.dumps(message)
        encrypted = self.cipher.encrypt(message_json.encode())
        return encrypted.decode()
        
    def decrypt_message(self, encrypted_message: str) -> Dict[str, Any]:
        """解密消息"""
        decrypted = self.cipher.decrypt(encrypted_message.encode())
        return json.loads(decrypted.decode())
```

### 10.3 速率限制
```python
class RateLimiter:
    """速率限制器"""
    
    def __init__(self, redis_client: Redis):
        self.redis = redis_client
        
    async def check_rate_limit(self, user_id: str, 
                             action: str, 
                             limit: int, 
                             window: int) -> bool:
        """检查速率限制"""
        key = f"ratelimit:{user_id}:{action}"
        
        # 使用Redis计数器
        current = await self.redis.incr(key)
        
        if current == 1:
            # 第一次设置过期时间
            await self.redis.expire(key, window)
            
        return current <= limit
```

## 11. 故障恢复

### 11.1 连接恢复
```python
class ConnectionRecovery:
    """连接恢复管理器"""
    
    def __init__(self, state_manager: ConversationStateManager):
        self.state_manager = state_manager
        
    async def recover_connection(self, user_id: str, 
                               old_session_id: str,
                               new_websocket) -> Dict[str, Any]:
        """恢复连接"""
        # 获取会话状态
        state = await self.state_manager.get_session_state(
            user_id, old_session_id
        )
        
        if not state:
            # 创建新会话
            return await self.state_manager.create_session(
                user_id, "recovered_device"
            )
            
        # 更新连接信息
        state["metadata"]["recovered_at"] = datetime.now().isoformat()
        state["metadata"]["recovery_count"] = (
            state["metadata"].get("recovery_count", 0) + 1
        )
        
        # 发送恢复通知
        recovery_message = {
            "type": "system",
            "content": "连接已恢复，继续对话",
            "timestamp": datetime.now().isoformat(),
            "recovery_info": {
                "old_session_id": old_session_id,
                "message_count": state["metadata"]["message_count"]
            }
        }
        
        await new_websocket.send(json.dumps(recovery_message))
        
        return state
```

### 11.2 数据备份
```python
class DataBackupManager:
    """数据备份管理器"""
    
    def __init__(self, redis_client: Redis, backup_interval: int = 3600):
        self.redis = redis_client
        self.backup_interval = backup_interval
        
    async def backup_sessions(self):
        """备份会话数据"""
        # 获取所有用户会话
        user_keys = await self.redis.keys("user:*:sessions")
        
        backup_data = {}
        
        for user_key in user_keys:
            user_id = user_key.split(":")[1]
            sessions = await self.redis.hgetall(user_key)
            
            backup_data[user_id] = {
                "backup_time": datetime.now().isoformat(),
                "sessions": sessions
            }
            
        # 保存备份
        backup_key = f"backup:sessions:{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        await self.redis.set(
            backup_key,
            json.dumps(backup_data)
        )
        
        # 设置过期时间（保留7天）
        await self.redis.expire(backup_key, 604800)
        
    async def restore_from_backup(self, backup_timestamp: str):
        """从备份恢复数据"""
        backup_key = f"backup:sessions:{backup_timestamp}"
        backup_data = await self.redis.get(backup_key)
        
        if backup_data:
            data = json.loads(backup_data)
            
            for user_id, user_data in data.items():
                # 恢复用户会话
                await self.redis.hset(
                    f"user:{user_id}:sessions",
                    mapping=user_data["sessions"]
                )
```

## 12. 总结

本技术方案提供了一个完整的基于LangGraph和Redis的分布式WebSocket对话系统实现。系统具有以下特点：

### 12.1 核心优势
1. **高可用性**：通过多服务器部署和Redis集群实现系统高可用
2. **强一致性**：使用Redis Pub/Sub和检查点机制保证消息一致性
3. **无缝恢复**：基于LangGraph检查点的断点恢复机制
4. **可扩展性**：水平扩展的架构设计，支持大规模用户并发
5. **状态管理**：强大的对话状态管理和上下文保持能力

### 12.2 适用场景
1. **多端聊天应用**：支持用户在不同设备间无缝切换
2. **客服系统**：需要保持对话上下文和状态恢复
3. **协作工具**：多用户实时协作和状态同步
4. **游戏服务器**：玩家状态管理和断线重连
5. **物联网平台**：设备状态同步和消息推送

### 12.3 未来扩展
1. **AI集成**：集成大语言模型实现智能对话
2. **多媒体支持**：支持图片、语音、视频消息
3. **离线消息**：实现可靠的离线消息存储和推送
4. **数据分析**：对话数据分析和用户行为洞察
5. **微服务架构**：进一步拆分为微服务架构

本方案提供了一个生产级的分布式对话系统实现，可以根据具体业务需求进行定制和扩展。