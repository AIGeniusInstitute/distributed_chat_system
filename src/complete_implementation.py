#!/usr/bin/env python3
"""
基于LangGraph和Redis的分布式WebSocket对话系统完整实现

功能特性：
1. 分布式WebSocket服务器集群
2. 使用Redis Pub/Sub实现消息一致性
3. 基于LangGraph检查点的断点恢复
4. 多端多机器用户对话支持
5. 高可用和可扩展架构
"""

import asyncio
import json
import logging
import uuid
from datetime import datetime
from typing import Dict, List, Any, Optional, Set, TypedDict
from enum import Enum

# 第三方库导入
try:
    from redis.asyncio import Redis
    from langgraph.checkpoint.redis import AsyncRedisSaver
    from langgraph.graph import StateGraph, START, END
    from websockets.server import serve, WebSocketServerProtocol
    from websockets.exceptions import ConnectionClosed
    import aiohttp
except ImportError as e:
    print(f"缺少依赖库: {e}")
    print("请运行: pip install redis websockets aiohttp langgraph-checkpoint-redis")
    exit(1)

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ============================================================================
# 类型定义
# ============================================================================

class MessageType(Enum):
    """消息类型枚举"""
    TEXT = "text"
    COMMAND = "command"
    SYSTEM = "system"
    HEARTBEAT = "heartbeat"
    ACK = "ack"
    ERROR = "error"
    HISTORY = "history"

class ConversationState(TypedDict):
    """对话状态类型定义"""
    user_id: str
    session_id: str
    device_id: str
    messages: List[Dict[str, Any]]
    context: Dict[str, Any]
    metadata: Dict[str, Any]
    current_node: str

class ServerConfig(TypedDict):
    """服务器配置类型"""
    redis_url: str
    redis_max_connections: int
    checkpoint_ttl: int
    websocket_host: str
    websocket_port: int
    max_message_size: int
    heartbeat_interval: int
    session_timeout: int
    server_id: str
    debug: bool

# ============================================================================
# 配置管理
# ============================================================================

class ConfigManager:
    """配置管理器"""
    
    DEFAULT_CONFIG: ServerConfig = {
        "redis_url": "redis://localhost:6379",
        "redis_max_connections": 20,
        "checkpoint_ttl": 120,  # 分钟
        "websocket_host": "0.0.0.0",
        "websocket_port": 8765,
        "max_message_size": 1048576,  # 1MB
        "heartbeat_interval": 30,  # 秒
        "session_timeout": 300,  # 秒
        "server_id": "node1",
        "debug": False
    }
    
    @classmethod
    def load_config(cls, config_file: Optional[str] = None) -> ServerConfig:
        """加载配置"""
        config = cls.DEFAULT_CONFIG.copy()
        
        # 可以从环境变量或配置文件加载
        import os
        for key in config.keys():
            env_key = f"CHAT_{key.upper()}"
            if env_key in os.environ:
                value = os.environ[env_key]
                # 类型转换
                if isinstance(config[key], int):
                    config[key] = int(value)
                elif isinstance(config[key], bool):
                    config[key] = value.lower() == "true"
                else:
                    config[key] = value
        
        return config

# ============================================================================
# Redis消息代理
# ============================================================================

class MessageBroker:
    """Redis消息代理"""
    
    def __init__(self, redis_client: Redis):
        self.redis = redis_client
        self.pubsub = None
        self.running = False
        self.message_handlers: Dict[str, List[callable]] = {}
        
    async def start(self):
        """启动消息代理"""
        self.pubsub = self.redis.pubsub()
        
        # 订阅系统频道
        channels = [
            "chat:messages",          # 聊天消息
            "chat:commands",          # 系统命令
            "chat:notifications",     # 系统通知
            "chat:heartbeats",        # 心跳检测
        ]
        
        for channel in channels:
            await self.pubsub.subscribe(channel)
            self.message_handlers[channel] = []
            
        self.running = True
        asyncio.create_task(self._message_loop())
        logger.info("消息代理已启动")
        
    async def stop(self):
        """停止消息代理"""
        self.running = False
        if self.pubsub:
            await self.pubsub.unsubscribe()
            await self.pubsub.close()
        logger.info("消息代理已停止")
        
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
                    if channel in self.message_handlers:
                        for handler in self.message_handlers[channel]:
                            try:
                                await handler(data)
                            except Exception as e:
                                logger.error(f"消息处理错误: {e}")
                                
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error(f"消息循环错误: {e}")
                await asyncio.sleep(1)
                
    def register_handler(self, channel: str, handler: callable):
        """注册消息处理函数"""
        if channel not in self.message_handlers:
            self.message_handlers[channel] = []
        self.message_handlers[channel].append(handler)
        
    async def publish(self, channel: str, data: Dict[str, Any]):
        """发布消息"""
        await self.redis.publish(channel, json.dumps(data))
        
    async def publish_message(self, user_id: str, session_id: str, 
                            message: Dict[str, Any], source_server: str):
        """发布聊天消息"""
        message_data = {
            "type": "user_message",
            "user_id": user_id,
            "session_id": session_id,
            "message": message,
            "timestamp": datetime.now().isoformat(),
            "source_server": source_server,
            "message_id": str(uuid.uuid4())
        }
        
        await self.publish("chat:messages", message_data)
        
    async def publish_command(self, command_type: str, data: Dict[str, Any]):
        """发布系统命令"""
        command_data = {
            "type": "system_command",
            "command": command_type,
            "data": data,
            "timestamp": datetime.now().isoformat()
        }
        
        await self.publish("chat:commands", command_data)

# ============================================================================
# 状态管理器
# ============================================================================

class StateManager:
    """对话状态管理器"""
    
    def __init__(self, checkpointer: AsyncRedisSaver, redis_client: Redis):
        self.checkpointer = checkpointer
        self.redis = redis_client
        
    async def create_session(self, user_id: str, device_id: str, 
                           initial_context: Optional[Dict[str, Any]] = None) -> ConversationState:
        """创建新会话"""
        session_id = str(uuid.uuid4())
        
        # 初始状态
        state: ConversationState = {
            "user_id": user_id,
            "session_id": session_id,
            "device_id": device_id,
            "messages": [],
            "context": initial_context or {
                "language": "zh-CN",
                "tone": "neutral",
                "topic": "general"
            },
            "metadata": {
                "created_at": datetime.now().isoformat(),
                "last_active": datetime.now().isoformat(),
                "message_count": 0,
                "recovery_count": 0
            },
            "current_node": "start",
            "checkpoint_id": None
        }
        
        # 保存初始检查点
        config = {
            "configurable": {
                "thread_id": f"user:{user_id}:session:{session_id}",
                "checkpoint_ns": "conversation"
            }
        }
        
        checkpoint_id = await self.checkpointer.put(config, state)
        state["checkpoint_id"] = checkpoint_id
        
        # 在Redis中记录会话
        session_info = {
            "device_id": device_id,
            "created_at": state["metadata"]["created_at"],
            "checkpoint_id": checkpoint_id,
            "server_id": "unknown"  # 将在连接时更新
        }
        
        await self.redis.hset(
            f"user:{user_id}:sessions",
            session_id,
            json.dumps(session_info)
        )
        
        logger.info(f"创建新会话: user={user_id}, session={session_id}")
        return state
        
    async def get_session_state(self, user_id: str, session_id: str) -> Optional[ConversationState]:
        """获取会话状态"""
        config = {
            "configurable": {
                "thread_id": f"user:{user_id}:session:{session_id}",
                "checkpoint_ns": "conversation"
            }
        }
        
        try:
            checkpoint_tuple = await self.checkpointer.get_tuple(config)
            if checkpoint_tuple:
                return checkpoint_tuple.state
        except Exception as e:
            logger.error(f"获取会话状态失败: {e}")
            
        return None
        
    async def update_session_state(self, user_id: str, session_id: str, 
                                 state: ConversationState) -> str:
        """更新会话状态"""
        config = {
            "configurable": {
                "thread_id": f"user:{user_id}:session:{session_id}",
                "checkpoint_ns": "conversation"
            }
        }
        
        # 更新元数据
        state["metadata"]["last_active"] = datetime.now().isoformat()
        state["metadata"]["message_count"] = len(state["messages"])
        
        # 保存检查点
        checkpoint_id = await self.checkpointer.put(config, state)
        state["checkpoint_id"] = checkpoint_id
        
        return checkpoint_id
        
    async def add_message_to_session(self, user_id: str, session_id: str,
                                   message: Dict[str, Any]) -> ConversationState:
        """添加消息到会话"""
        state = await self.get_session_state(user_id, session_id)
        
        if not state:
            raise ValueError(f"会话不存在: user={user_id}, session={session_id}")
            
        # 添加消息
        state["messages"].append(message)
        
        # 限制消息历史长度
        if len(state["messages"]) > 100:
            state["messages"] = state["messages"][-100:]
            
        # 更新状态
        await self.update_session_state(user_id, session_id, state)
        
        return state
        
    async def list_user_sessions(self, user_id: str) -> List[Dict[str, Any]]:
        """列出用户的所有会话"""
        sessions_data = await self.redis.hgetall(f"user:{user_id}:sessions")
        
        sessions = []
        for session_id, session_json in sessions_data.items():
            try:
                session_info = json.loads(session_json)
                session_info["session_id"] = session_id
                sessions.append(session_info)
            except json.JSONDecodeError:
                logger.error(f"解析会话数据失败: {session_json}")
                
        return sessions
        
    async def update_session_server(self, user_id: str, session_id: str, server_id: str):
        """更新会话所在的服务器"""
        session_json = await self.redis.hget(f"user:{user_id}:sessions", session_id)
        
        if session_json:
            session_info = json.loads(session_json)
            session_info["server_id"] = server_id
            session_info["last_connected"] = datetime.now().isoformat()
            
            await self.redis.hset(
                f"user:{user_id}:sessions",
                session_id,
                json.dumps(session_info)
            )

# ============================================================================
# LangGraph状态图
# ============================================================================

class ConversationGraphBuilder:
    """对话状态图构建器"""
    
    @staticmethod
    async def process_user_message(state: ConversationState) -> ConversationState:
        """处理用户消息节点"""
        if not state["messages"]:
            return state
            
        last_message = state["messages"][-1]
        
        # 这里可以添加消息处理逻辑
        # 例如：情感分析、意图识别、上下文更新等
        
        # 更新上下文
        if "content" in last_message:
            content = last_message["content"]
            if len(content) > 50:
                state["context"]["last_topic"] = content[:50] + "..."
            else:
                state["context"]["last_topic"] = content
                
        state["current_node"] = "processed"
        return state
        
    @staticmethod
    async def generate_response(state: ConversationState) -> ConversationState:
        """生成响应节点"""
        # 这里可以集成AI模型生成响应
        # 简化实现：返回echo响应
        
        if state["messages"]:
            last_message = state["messages"][-1]
            if last_message.get("role") == "user" and "content" in last_message:
                response = {
                    "role": "assistant",
                    "content": f"收到: {last_message['content']}",
                    "timestamp": datetime.now().isoformat(),
                    "message_id": str(uuid.uuid4())
                }
                state["messages"].append(response)
                
        state["current_node"] = "responded"
        return state
        
    @staticmethod
    async def update_conversation_context(state: ConversationState) -> ConversationState:
        """更新对话上下文节点"""
        # 分析对话历史，更新上下文
        if len(state["messages"]) > 5:
            # 提取关键词（简化实现）
            recent_messages = state["messages"][-5:]
            contents = [msg.get("content", "") for msg in recent_messages 
                       if "content" in msg]
            
            if contents:
                # 简单的上下文更新
                state["context"]["recent_topics"] = contents[-3:]
                
        state["current_node"] = "context_updated"
        return state
        
    @classmethod
    async def build_graph(cls, checkpointer: AsyncRedisSaver):
        """构建对话状态图"""
        
        # 定义状态类型
        class GraphState(TypedDict):
            user_id: str
            session_id: str
            device_id: str
            messages: List[Dict[str, Any]]
            context: Dict[str, Any]
            metadata: Dict[str, Any]
            current_node: str
            
        # 创建状态图
        builder = StateGraph(GraphState)
        
        # 添加节点
        builder.add_node("process_input", cls.process_user_message)
        builder.add_node("generate_response", cls.generate_response)
        builder.add_node("update_context", cls.update_conversation_context)
        
        # 添加边
        builder.add_edge(START, "process_input")
        builder.add_edge("process_input", "generate_response")
        builder.add_edge("generate_response", "update_context")
        builder.add_edge("update_context", END)
        
        # 编译图
        graph = builder.compile(checkpointer=checkpointer)
        
        return graph

# ============================================================================
# WebSocket连接管理器
# ============================================================================

class ConnectionManager:
    """WebSocket连接管理器"""
    
    def __init__(self, server_id: str, redis_client: Redis):
        self.server_id = server_id
        self.redis = redis_client
        self.connections: Dict[str, WebSocketServerProtocol] = {}  # session_id -> websocket
        self.user_sessions: Dict[str, Set[str]] = {}  # user_id -> session_ids
        
    async def register_connection(self, user_id: str, session_id: str, 
                                websocket: WebSocketServerProtocol):
        """注册连接"""
        self.connections[session_id] = websocket
        
        if user_id not in self.user_sessions:
            self.user_sessions[user_id] = set()
        self.user_sessions[user_id].add(session_id)
        
        # 在Redis中记录连接
        connection_key = f"connection:{session_id}"
        connection_info = {
            "user_id": user_id,
            "session_id": session_id,
            "server_id": self.server_id,
            "connected_at": datetime.now().isoformat(),
            "last_activity": datetime.now().isoformat()
        }
        
        await self.redis.setex(
            connection_key,
            3600,  # 1小时过期
            json.dumps(connection_info)
        )
        
        logger.info(f"注册连接: user={user_id}, session={session_id}")
        
    async def unregister_connection(self, session_id: str):
        """注销连接"""
        if session_id in self.connections:
            websocket = self.connections.pop(session_id)
            
            # 从用户会话中移除
            for user_id, sessions in self.user_sessions.items():
                if session_id in sessions:
                    sessions.remove(session_id)
                    if not sessions:
                        del self.user_sessions[user_id]
                    break
                    
            # 从Redis中移除连接记录
            await self.redis.delete(f"connection:{session_id}")
            
            logger.info(f"注销连接: session={session_id}")
            
    async def send_to_session(self, session_id: str, message: Dict[str, Any]):
        """发送消息到指定会话"""
        if session_id in self.connections:
            try:
                await self.connections[session_id].send(json.dumps(message))
                
                # 更新活动时间
                await self.redis.expire(f"connection:{session_id}", 3600)
                
            except ConnectionClosed:
                await self.unregister_connection(session_id)
            except Exception as e:
                logger.error(f"发送消息失败: {e}")
                
    async def send_to_user(self, user_id: str, message: Dict[str, Any]):
        """发送消息到用户的所有会话"""
        if user_id in self.user_sessions:
            for session_id in self.user_sessions[user_id]:
                await self.send_to_session(session_id, message)
                
    async def broadcast(self, message: Dict[str, Any]):
        """广播消息到所有连接"""
        for session_id, websocket in self.connections.items():
            try:
                await websocket.send(json.dumps(message))
            except ConnectionClosed:
                await self.unregister_connection(session_id)
            except Exception as e:
                logger.error(f"广播消息失败: {e}")

# ============================================================================
# WebSocket消息处理器
# ============================================================================

class MessageHandler:
    """WebSocket消息处理器"""
    
    def __init__(self, state_manager: StateManager, connection_manager: ConnectionManager,
                 message_broker: MessageBroker, conversation_graph, server_id: str):
        self.state_manager = state_manager
        self.connection_manager = connection_manager
        self.message_broker = message_broker
        self.conversation_graph = conversation_graph
        self.server_id = server_id
        
    async def handle_connect(self, websocket: WebSocketServerProtocol, 
                           auth_data: Dict[str, Any]) -> Dict[str, Any]:
        """处理连接请求"""
        user_id = auth_data.get("user_id")
        device_id = auth_data.get("device_id", "unknown")
        
        if not user_id:
            return {"error": "缺少user_id"}
            
        # 检查是否有可恢复的会话
        sessions = await self.state_manager.list_user_sessions(user_id)
        
        if sessions:
            # 尝试恢复最近会话
            latest_session = max(sessions, key=lambda x: x.get("created_at", ""))
            session_id = latest_session["session_id"]
            
            state = await self.state_manager.get_session_state(user_id, session_id)
            
            if state:
                # 更新会话服务器信息
                await self.state_manager.update_session_server(user_id, session_id, self.server_id)
                
                # 注册连接
                await self.connection_manager.register_connection(user_id, session_id, websocket)
                
                # 发送恢复消息
                recovery_msg = {
                    "type": MessageType.SYSTEM.value,
                    "content": "会话已恢复",
                    "timestamp": datetime.now().isoformat(),
                    "session_id": session_id,
                    "recovered": True,
                    "message_count": state["metadata"]["message_count"]
                }
                
                await websocket.send(json.dumps(recovery_msg))
                
                return {
                    "session_id": session_id,
                    "recovered": True,
                    "user_id": user_id
                }
                
        # 创建新会话
        state = await self.state_manager.create_session(user_id, device_id)
        session_id = state["session_id"]
        
        # 更新会话服务器信息
        await self.state_manager.update_session_server(user_id, session_id, self.server_id)
        
        # 注册连接
        await self.connection_manager.register_connection(user_id, session_id, websocket)
        
        # 发送欢迎消息
        welcome_msg = {
            "type": MessageType.SYSTEM.value,
            "content": "连接已建立，开始对话吧！",
            "timestamp": datetime.now().isoformat(),
            "session_id": session_id
        }
        
        await websocket.send(json.dumps(welcome_msg))
        
        return {
            "session_id": session_id,
            "recovered": False,
            "user_id": user_id
        }
        
    async def handle_text_message(self, user_id: str, session_id: str,
                                message_data: Dict[str, Any]):
        """处理文本消息"""
        # 构建消息对象
        message = {
            "role": "user",
            "content": message_data["content"],
            "timestamp": datetime.now().isoformat(),
            "message_id": str(uuid.uuid4()),
            "type": MessageType.TEXT.value
        }
        
        # 添加到会话状态
        state = await self.state_manager.add_message_to_session(user_id, session_id, message)
        
        # 通过状态图处理
        config = {
            "configurable": {
                "thread_id": f"user:{user_id}:session:{session_id}",
                "checkpoint_ns": "conversation"
            }
        }
        
        try:
            # 执行状态图
            new_state = await self.conversation_graph.ainvoke(state, config=config)
            
            # 获取生成的响应
            if new_state["messages"] and new_state["messages"][-1]["role"] == "assistant":
                response = new_state["messages"][-1]
                
                # 发送响应给客户端
                await self.connection_manager.send_to_session(session_id, response)
                
                # 通过消息代理广播（用于其他服务器）
                await self.message_broker.publish_message(
                    user_id=user_id,
                    session_id=session_id,
                    message=response,
                    source_server=self.server_id
                )
                
        except Exception as e:
            logger.error(f"处理消息失败: {e}")
            
            # 发送错误响应
            error_msg = {
                "type": MessageType.ERROR.value,
                "content": "处理消息时发生错误",
                "timestamp": datetime.now().isoformat(),
                "message_id": str(uuid.uuid4())
            }
            
            await self.connection_manager.send_to_session(session_id, error_msg)
            
    async def handle_command(self, user_id: str, session_id: str,
                           command_data: Dict[str, Any]):
        """处理命令消息"""
        command = command_data.get("command")
        
        if command == "get_history":
            await self.handle_get_history(user_id, session_id)
        elif command == "clear_history":
            await self.handle_clear_history(user_id, session_id)
        elif command == "get_sessions":
            await self.handle_get_sessions(user_id)
        else:
            error_msg = {
                "type": MessageType.ERROR.value,
                "content": f"未知命令: {command}",
                "timestamp": datetime.now().isoformat()
            }
            await self.connection_manager.send_to_session(session_id, error_msg)
            
    async def handle_get_history(self, user_id: str, session_id: str):
        """处理获取历史命令"""
        state = await self.state_manager.get_session_state(user_id, session_id)
        
        if state:
            history_msg = {
                "type": MessageType.HISTORY.value,
                "messages": state["messages"][-20:],  # 最近20条消息
                "timestamp": datetime.now().isoformat(),
                "total_count": len(state["messages"])
            }
            
            await self.connection_manager.send_to_session(session_id, history_msg)
            
    async def handle_clear_history(self, user_id: str, session_id: str):
        """处理清空历史命令"""
        state = await self.state_manager.get_session_state(user_id, session_id)
        
        if state:
            # 保留元数据，清空消息
            state["messages"] = []
            await self.state_manager.update_session_state(user_id, session_id, state)
            
            response_msg = {
                "type": MessageType.SYSTEM.value,
                "content": "历史记录已清空",
                "timestamp": datetime.now().isoformat()
            }
            
            await self.connection_manager.send_to_session(session_id, response_msg)
            
    async def handle_get_sessions(self, user_id: str):
        """处理获取会话列表命令"""
        sessions = await self.state_manager.list_user_sessions(user_id)
        
        sessions_msg = {
            "type": MessageType.SYSTEM.value,
            "content": "会话列表",
            "timestamp": datetime.now().isoformat(),
            "sessions": sessions
        }
        
        # 发送给用户的所有连接
        await self.connection_manager.send_to_user(user_id, sessions_msg)
        
    async def handle_heartbeat(self, user_id: str, session_id: str):
        """处理心跳消息"""
        # 更新活动时间
        await self.connection_manager.redis.expire(f"connection:{session_id}", 3600)
        
        # 发送心跳响应
        heartbeat_response = {
            "type": MessageType.HEARTBEAT.value,
            "timestamp": datetime.now().isoformat(),
            "server_time": datetime.now().isoformat(),
            "server_id": self.server_id
        }
        
        await self.connection_manager.send_to_session(session_id, heartbeat_response)

# ============================================================================
# 主WebSocket服务器
# ============================================================================

class WebSocketServer:
    """分布式WebSocket服务器"""
    
    def __init__(self, config: ServerConfig):
        self.config = config
        self.server_id = config["server_id"]
        
        # 组件
        self.redis_client = None  # 用于一般操作（字符串）
        self.redis_bytes_client = None  # 用于 AsyncRedisSaver（bytes）
        self.checkpointer = None
        self.state_manager = None
        self.message_broker = None
        self.connection_manager = None
        self.conversation_graph = None
        self.message_handler = None
        
        # 服务器状态
        self.running = False
        
    async def initialize(self):
        """初始化系统组件"""
        logger.info("初始化系统组件...")
        
        # 初始化Redis连接（用于一般操作）
        self.redis_client = await Redis.from_url(
            self.config["redis_url"],
            max_connections=self.config["redis_max_connections"],
            decode_responses=True,
            socket_keepalive=True,
            retry_on_timeout=True
        )

        # 初始化Redis连接（用于AsyncRedisSaver，需要bytes）
        self.redis_bytes_client = await Redis.from_url(
            self.config["redis_url"],
            max_connections=self.config["redis_max_connections"],
            decode_responses=False,  # AsyncRedisSaver需要bytes
            socket_keepalive=True,
            retry_on_timeout=True
        )
        
        # 测试Redis连接
        try:
            await self.redis_client.ping()
            logger.info("Redis连接成功")
        except Exception as e:
            logger.error(f"Redis连接失败: {e}")
            raise
            
        # 初始化RedisSaver
        self.checkpointer = AsyncRedisSaver(
            redis_client=self.redis_bytes_client
        )
        await self.checkpointer.asetup()
        logger.info("RedisSaver初始化完成")
        
        # 初始化状态管理器
        self.state_manager = StateManager(self.checkpointer, self.redis_client)
        
        # 初始化消息代理
        self.message_broker = MessageBroker(self.redis_client)
        
        # 初始化连接管理器
        self.connection_manager = ConnectionManager(self.server_id, self.redis_client)
        
        # 构建对话状态图
        self.conversation_graph = await ConversationGraphBuilder.build_graph(self.checkpointer)
        logger.info("对话状态图构建完成")
        
        # 初始化消息处理器
        self.message_handler = MessageHandler(
            state_manager=self.state_manager,
            connection_manager=self.connection_manager,
            message_broker=self.message_broker,
            conversation_graph=self.conversation_graph,
            server_id=self.server_id
        )
        
        # 注册消息处理函数
        await self._register_message_handlers()
        
        logger.info("系统初始化完成")
        
    async def _register_message_handlers(self):
        """注册消息处理函数"""
        
        async def handle_incoming_message(data: Dict[str, Any]):
            """处理来自其他服务器的消息"""
            message_type = data.get("type")
            
            if message_type == "user_message":
                user_id = data["user_id"]
                session_id = data["session_id"]
                message = data["message"]
                source_server = data["source_server"]
                
                # 如果不是本服务器发送的，转发给客户端
                if source_server != self.server_id:
                    if session_id in self.connection_manager.connections:
                        await self.connection_manager.send_to_session(session_id, message)
                    else:
                        # 会话不在本服务器，保存消息待恢复
                        await self._store_pending_message(user_id, session_id, message)
                        
        # 注册处理函数
        self.message_broker.register_handler("chat:messages", handle_incoming_message)
        
    async def _store_pending_message(self, user_id: str, session_id: str, 
                                   message: Dict[str, Any]):
        """存储待处理消息"""
        pending_key = f"pending:{user_id}:{session_id}"
        
        # 获取现有待处理消息
        existing = await self.redis_client.get(pending_key)
        pending_messages = []
        
        if existing:
            try:
                pending_messages = json.loads(existing)
            except json.JSONDecodeError:
                pending_messages = []
                
        # 添加新消息
        pending_messages.append({
            "message": message,
            "timestamp": datetime.now().isoformat(),
            "stored_at": self.server_id
        })
        
        # 保存（最多保留10条，1小时过期）
        await self.redis_client.setex(
            pending_key,
            3600,
            json.dumps(pending_messages[-10:])
        )
        
    async def handle_connection(self, websocket: WebSocketServerProtocol, path: str):
        """处理WebSocket连接"""
        logger.info(f"新连接: {websocket.remote_address}")
        
        try:
            # 等待认证消息
            auth_message = await websocket.recv()
            auth_data = json.loads(auth_message)
            
            # 处理连接
            result = await self.message_handler.handle_connect(websocket, auth_data)
            
            if "error" in result:
                error_msg = {
                    "type": MessageType.ERROR.value,
                    "content": result["error"],
                    "timestamp": datetime.now().isoformat()
                }
                await websocket.send(json.dumps(error_msg))
                await websocket.close()
                return
                
            user_id = result["user_id"]
            session_id = result["session_id"]
            
            logger.info(f"连接建立: user={user_id}, session={session_id}")
            
            # 处理消息循环
            async for message in websocket:
                await self._process_client_message(user_id, session_id, message)
                
        except ConnectionClosed:
            logger.info(f"连接关闭: {websocket.remote_address}")
        except json.JSONDecodeError:
            logger.error(f"消息格式错误: {websocket.remote_address}")
            error_msg = {
                "type": MessageType.ERROR.value,
                "content": "消息格式错误",
                "timestamp": datetime.now().isoformat()
            }
            try:
                await websocket.send(json.dumps(error_msg))
            except:
                pass
        except Exception as e:
            logger.error(f"连接处理错误: {e}")
        finally:
            # 清理连接
            if 'session_id' in locals():
                await self.connection_manager.unregister_connection(session_id)
                
    async def _process_client_message(self, user_id: str, session_id: str, 
                                    raw_message: str):
        """处理客户端消息"""
        try:
            message_data = json.loads(raw_message)
            message_type = message_data.get("type")
            
            if message_type == MessageType.TEXT.value:
                await self.message_handler.handle_text_message(user_id, session_id, message_data)
            elif message_type == MessageType.COMMAND.value:
                await self.message_handler.handle_command(user_id, session_id, message_data)
            elif message_type == MessageType.HEARTBEAT.value:
                await self.message_handler.handle_heartbeat(user_id, session_id)
            else:
                error_msg = {
                    "type": MessageType.ERROR.value,
                    "content": f"未知消息类型: {message_type}",
                    "timestamp": datetime.now().isoformat()
                }
                await self.connection_manager.send_to_session(session_id, error_msg)
                
        except json.JSONDecodeError:
            error_msg = {
                "type": MessageType.ERROR.value,
                "content": "消息格式错误",
                "timestamp": datetime.now().isoformat()
            }
            await self.connection_manager.send_to_session(session_id, error_msg)
        except Exception as e:
            logger.error(f"处理客户端消息失败: {e}")
            error_msg = {
                "type": MessageType.ERROR.value,
                "content": "处理消息时发生错误",
                "timestamp": datetime.now().isoformat()
            }
            await self.connection_manager.send_to_session(session_id, error_msg)
            
    async def start(self):
        """启动服务器"""
        # 启动消息代理
        await self.message_broker.start()
        
        # 启动WebSocket服务器
        server = await serve(
            self.handle_connection,
            self.config["websocket_host"],
            self.config["websocket_port"],
            max_size=self.config["max_message_size"]
        )
        
        self.running = True
        logger.info(f"WebSocket服务器启动在 {self.config['websocket_host']}:{self.config['websocket_port']}")
        
        try:
            await asyncio.Future()  # 永久运行
        except asyncio.CancelledError:
            logger.info("服务器接收到停止信号")
        finally:
            await self.shutdown()
            
    async def shutdown(self):
        """关闭服务器"""
        if not self.running:
            return
            
        self.running = False
        logger.info("正在关闭服务器...")
        
        # 关闭消息代理
        if self.message_broker:
            await self.message_broker.stop()
            
        # 关闭Redis连接
        if self.redis_client:
            await self.redis_client.close()
        if self.redis_bytes_client:
            await self.redis_bytes_client.close()
            
        logger.info("服务器已关闭")

# ============================================================================
# 客户端示例
# ============================================================================

class ChatClient:
    """聊天客户端示例"""
    
    def __init__(self, server_url: str, user_id: str, device_id: str = "web"):
        self.server_url = server_url
        self.user_id = user_id
        self.device_id = device_id
        self.websocket = None
        self.session_id = None
        
    async def connect(self):
        """连接服务器"""
        self.websocket = await websockets.connect(self.server_url)
        
        # 发送认证消息
        auth_message = {
            "user_id": self.user_id,
            "device_id": self.device_id,
            "timestamp": datetime.now().isoformat()
        }
        
        await self.websocket.send(json.dumps(auth_message))
        
        # 等待响应
        response = await self.websocket.recv()
        response_data = json.loads(response)
        
        if response_data.get("type") == MessageType.SYSTEM.value:
            self.session_id = response_data.get("session_id")
            print(f"连接成功! 会话ID: {self.session_id}")
            print(f"消息: {response_data.get('content')}")
            
        return response_data
        
    async def send_message(self, content: str):
        """发送消息"""
        if not self.websocket:
            raise ConnectionError("未连接")
            
        message = {
            "type": MessageType.TEXT.value,
            "content": content,
            "timestamp": datetime.now().isoformat()
        }
        
        await self.websocket.send(json.dumps(message))
        
        # 等待响应
        response = await self.websocket.recv()
        return json.loads(response)
        
    async def send_command(self, command: str, **kwargs):
        """发送命令"""
        if not self.websocket:
            raise ConnectionError("未连接")
            
        command_data = {
            "type": MessageType.COMMAND.value,
            "command": command,
            "timestamp": datetime.now().isoformat(),
            **kwargs
        }
        
        await self.websocket.send(json.dumps(command_data))
        
        # 等待响应
        response = await self.websocket.recv()
        return json.loads(response)
        
    async def listen(self):
        """监听服务器消息"""
        if not self.websocket:
            raise ConnectionError("未连接")
            
        async for message in self.websocket:
            data = json.loads(message)
            print(f"\n收到消息: {data}")
            
    async def close(self):
        """关闭连接"""
        if self.websocket:
            await self.websocket.close()
            self.websocket = None

# ============================================================================
# 主函数
# ============================================================================

async def main_server():
    """运行服务器"""
    # 加载配置
    config = ConfigManager.load_config()
    
    # 创建服务器
    server = WebSocketServer(config)
    
    try:
        # 初始化
        await server.initialize()
        
        # 启动
        await server.start()
        
    except KeyboardInterrupt:
        logger.info("接收到Ctrl+C信号")
    except Exception as e:
        logger.error(f"服务器运行错误: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await server.shutdown()

async def main_client():
    """运行客户端示例"""
    import sys
    
    if len(sys.argv) < 3:
        print("用法: python complete_implementation.py client <server_url> <user_id>")
        print("示例: python complete_implementation.py client ws://localhost:8765 user123")
        return
        
    server_url = sys.argv[2]
    user_id = sys.argv[3]
    
    client = ChatClient(server_url, user_id)
    
    try:
        # 连接
        await client.connect()
        
        # 启动监听任务
        listen_task = asyncio.create_task(client.listen())
        
        # 交互循环
        while True:
            try:
                user_input = await asyncio.get_event_loop().run_in_executor(
                    None, input, "\n输入消息 (或 'quit'退出): "
                )
                
                if user_input.lower() == 'quit':
                    break
                elif user_input.lower() == 'history':
                    await client.send_command("get_history")
                elif user_input.lower() == 'sessions':
                    await client.send_command("get_sessions")
                elif user_input.lower() == 'clear':
                    await client.send_command("clear_history")
                else:
                    await client.send_message(user_input)
                    
            except KeyboardInterrupt:
                break
                
    finally:
        listen_task.cancel()
        await client.close()

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "client":
        asyncio.run(main_client())
    else:
        # 默认运行服务器
        asyncio.run(main_server())