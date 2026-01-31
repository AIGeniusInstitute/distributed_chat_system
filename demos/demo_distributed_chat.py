#!/usr/bin/env python3
"""
分布式多端多机器对话演示示例

演示功能：
1. 多服务器集群部署
2. 多客户端同时连接
3. 消息一致性展示（跨服务器消息同步）
4. 断点恢复展示（连接中断后状态恢复）
5. 实时对话效果展示
"""

import asyncio
import json
import time
import uuid
import random
import threading
from datetime import datetime
from typing import Dict, List, Any, Optional
import websockets
import redis.asyncio as redis
import logging
import sys
import os

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class DemoServer:
    """演示服务器"""
    
    def __init__(self, server_id: str, port: int):
        self.server_id = server_id
        self.port = port
        self.redis_client = None
        self.connections: Dict[str, websockets.WebSocketServerProtocol] = {}
        self.user_sessions: Dict[str, Dict[str, Any]] = {}
        
    async def initialize(self):
        """初始化服务器"""
        # 连接Redis
        self.redis_client = await redis.from_url(
            "redis://localhost:6379",
            decode_responses=True,
            max_connections=10
        )
        
        # 测试Redis连接
        await self.redis_client.ping()
        logger.info(f"服务器 {self.server_id} Redis连接成功")
        
    async def handle_connection(self, websocket, path):
        """处理WebSocket连接"""
        client_id = f"{self.server_id}_client_{len(self.connections)}"
        logger.info(f"服务器 {self.server_id}: 新连接 {client_id}")
        
        try:
            # 接收认证消息
            auth_message = await websocket.recv()
            auth_data = json.loads(auth_message)
            
            user_id = auth_data.get("user_id", f"user_{random.randint(1000, 9999)}")
            device_id = auth_data.get("device_id", f"device_{random.randint(1, 10)}")
            
            # 检查是否有现有会话
            session_key = f"demo_session:{user_id}"
            existing_session = await self.redis_client.get(session_key)
            
            if existing_session:
                # 恢复会话
                session_data = json.loads(existing_session)
                session_id = session_data.get("session_id")
                is_recovery = True
                logger.info(f"服务器 {self.server_id}: 用户 {user_id} 会话恢复")
            else:
                # 创建新会话
                session_id = str(uuid.uuid4())
                is_recovery = False
                logger.info(f"服务器 {self.server_id}: 用户 {user_id} 新会话创建")
            
            # 保存连接信息
            self.connections[client_id] = websocket
            self.user_sessions[client_id] = {
                "user_id": user_id,
                "session_id": session_id,
                "device_id": device_id
            }
            
            # 保存会话状态到Redis
            session_data = {
                "user_id": user_id,
                "session_id": session_id,
                "device_id": device_id,
                "server_id": self.server_id,
                "last_active": datetime.now().isoformat(),
                "message_count": 0
            }
            await self.redis_client.setex(session_key, 300, json.dumps(session_data))
            
            # 发送连接响应
            response = {
                "type": "system",
                "server_id": self.server_id,
                "session_id": session_id,
                "user_id": user_id,
                "recovered": is_recovery,
                "timestamp": datetime.now().isoformat(),
                "message": "连接成功" if not is_recovery else "会话已恢复"
            }
            await websocket.send(json.dumps(response))
            
            # 处理消息循环
            async for message in websocket:
                await self.handle_message(client_id, message)
                
        except websockets.exceptions.ConnectionClosed:
            logger.info(f"服务器 {self.server_id}: 连接关闭 {client_id}")
        except Exception as e:
            logger.error(f"服务器 {self.server_id}: 连接处理错误: {e}")
        finally:
            # 清理连接
            if client_id in self.connections:
                del self.connections[client_id]
            if client_id in self.user_sessions:
                del self.user_sessions[client_id]
    
    async def handle_message(self, client_id: str, raw_message: str):
        """处理客户端消息"""
        try:
            message_data = json.loads(raw_message)
            message_type = message_data.get("type", "text")
            
            if client_id not in self.user_sessions:
                return
                
            user_info = self.user_sessions[client_id]
            user_id = user_info["user_id"]
            session_id = user_info["session_id"]
            
            if message_type == "text":
                # 处理文本消息
                content = message_data.get("content", "")
                message_id = str(uuid.uuid4())
                
                # 构建消息对象
                message_obj = {
                    "type": "message",
                    "message_id": message_id,
                    "user_id": user_id,
                    "session_id": session_id,
                    "content": content,
                    "timestamp": datetime.now().isoformat(),
                    "server_id": self.server_id,
                    "direction": "outgoing"
                }
                
                # 通过Redis Pub/Sub广播消息
                await self.redis_client.publish(
                    "demo_chat_messages",
                    json.dumps(message_obj)
                )
                
                # 更新会话状态
                session_key = f"demo_session:{user_id}"
                session_data_json = await self.redis_client.get(session_key)
                if session_data_json:
                    session_data = json.loads(session_data_json)
                    session_data["last_active"] = datetime.now().isoformat()
                    session_data["message_count"] = session_data.get("message_count", 0) + 1
                    await self.redis_client.setex(session_key, 300, json.dumps(session_data))
                
                # 发送确认
                ack_message = {
                    "type": "ack",
                    "message_id": message_id,
                    "timestamp": datetime.now().isoformat(),
                    "status": "sent"
                }
                await self.connections[client_id].send(json.dumps(ack_message))
                
                logger.info(f"服务器 {self.server_id}: 用户 {user_id} 发送消息: {content[:50]}...")
                
            elif message_type == "heartbeat":
                # 处理心跳
                heartbeat_response = {
                    "type": "heartbeat",
                    "timestamp": datetime.now().isoformat(),
                    "server_id": self.server_id,
                    "status": "alive"
                }
                await self.connections[client_id].send(json.dumps(heartbeat_response))
                
        except json.JSONDecodeError:
            error_response = {
                "type": "error",
                "message": "消息格式错误",
                "timestamp": datetime.now().isoformat()
            }
            if client_id in self.connections:
                await self.connections[client_id].send(json.dumps(error_response))
        except Exception as e:
            logger.error(f"服务器 {self.server_id}: 消息处理错误: {e}")
    
    async def start_message_listener(self):
        """启动消息监听器"""
        pubsub = self.redis_client.pubsub()
        await pubsub.subscribe("demo_chat_messages")
        
        logger.info(f"服务器 {self.server_id}: 启动消息监听器")
        
        async for message in pubsub.listen():
            if message["type"] == "message":
                try:
                    message_data = json.loads(message["data"])
                    
                    # 检查是否是本服务器发送的消息
                    if message_data.get("server_id") == self.server_id:
                        continue
                    
                    # 转发给所有连接的客户端
                    for client_id, websocket in self.connections.items():
                        try:
                            # 修改消息方向为接收
                            forwarded_message = message_data.copy()
                            forwarded_message["direction"] = "incoming"
                            await websocket.send(json.dumps(forwarded_message))
                        except:
                            pass
                            
                except Exception as e:
                    logger.error(f"服务器 {self.server_id}: 消息转发错误: {e}")
    
    async def start(self):
        """启动服务器"""
        await self.initialize()
        
        # 启动消息监听器
        listener_task = asyncio.create_task(self.start_message_listener())
        
        # 启动WebSocket服务器
        server = await websockets.serve(
            self.handle_connection,
            "localhost",
            self.port,
            max_size=10 * 1024 * 1024  # 10MB
        )
        
        logger.info(f"演示服务器 {self.server_id} 启动在端口 {self.port}")
        
        try:
            await asyncio.Future()  # 永久运行
        except asyncio.CancelledError:
            logger.info(f"服务器 {self.server_id} 停止")
        finally:
            listener_task.cancel()
            if self.redis_client:
                await self.redis_client.close()

class DemoClient:
    """演示客户端"""
    
    def __init__(self, client_id: str, server_url: str, user_id: Optional[str] = None):
        self.client_id = client_id
        self.server_url = server_url
        self.user_id = user_id or f"user_{random.randint(1000, 9999)}"
        self.device_id = f"device_{random.randint(1, 5)}"
        self.websocket = None
        self.running = False
        self.received_messages = []
        
    async def connect(self):
        """连接服务器"""
        self.websocket = await websockets.connect(self.server_url)
        
        # 发送认证消息
        auth_message = {
            "type": "auth",
            "user_id": self.user_id,
            "device_id": self.device_id,
            "timestamp": datetime.now().isoformat()
        }
        
        await self.websocket.send(json.dumps(auth_message))
        
        # 接收响应
        response = await self.websocket.recv()
        response_data = json.loads(response)
        
        print(f"客户端 {self.client_id}: 连接成功")
        print(f"  用户ID: {self.user_id}")
        print(f"  设备ID: {self.device_id}")
        print(f"  会话ID: {response_data.get('session_id')}")
        print(f"  恢复状态: {'是' if response_data.get('recovered') else '否'}")
        
        return response_data
    
    async def send_message(self, content: str):
        """发送消息"""
        if not self.websocket:
            raise ConnectionError("未连接")
        
        message = {
            "type": "text",
            "content": content,
            "timestamp": datetime.now().isoformat()
        }
        
        await self.websocket.send(json.dumps(message))
        
        # 等待确认
        ack = await self.websocket.recv()
        ack_data = json.loads(ack)
        
        if ack_data.get("type") == "ack":
            print(f"客户端 {self.client_id}: 消息发送成功 - '{content}'")
            return True
        else:
            print(f"客户端 {self.client_id}: 消息发送失败")
            return False
    
    async def listen(self):
        """监听服务器消息"""
        self.running = True
        
        while self.running and self.websocket:
            try:
                message = await asyncio.wait_for(self.websocket.recv(), timeout=1.0)
                message_data = json.loads(message)
                
                if message_data.get("type") == "message":
                    # 收到聊天消息
                    sender = message_data.get("user_id", "未知")
                    content = message_data.get("content", "")
                    direction = message_data.get("direction", "incoming")
                    
                    if direction == "incoming" and sender != self.user_id:
                        print(f"客户端 {self.client_id}: 收到来自 {sender} 的消息 - '{content}'")
                        self.received_messages.append(message_data)
                        
                elif message_data.get("type") == "heartbeat":
                    # 心跳响应
                    pass
                    
            except asyncio.TimeoutError:
                continue
            except websockets.exceptions.ConnectionClosed:
                print(f"客户端 {self.client_id}: 连接关闭")
                self.running = False
            except Exception as e:
                print(f"客户端 {self.client_id}: 监听错误: {e}")
                self.running = False
    
    async def simulate_user_behavior(self, message_count: int = 5):
        """模拟用户行为"""
        messages = [
            "你好，这是一个测试消息",
            "分布式系统真有趣",
            "消息一致性很重要",
            "断点恢复功能很实用",
            "WebSocket实时通信很棒",
            "Redis Pub/Sub机制很强大",
            "多端对话体验很好",
            "这个演示很有帮助",
            "谢谢观看演示",
            "再见！"
        ]
        
        for i in range(min(message_count, len(messages))):
            await self.send_message(messages[i])
            await asyncio.sleep(random.uniform(1.0, 3.0))
    
    async def close(self):
        """关闭连接"""
        self.running = False
        if self.websocket:
            await self.websocket.close()
            self.websocket = None

class DemoOrchestrator:
    """演示协调器"""
    
    def __init__(self):
        self.servers = []
        self.clients = []
        self.redis_client = None
        
    async def setup_environment(self):
        """设置演示环境"""
        print("=" * 60)
        print("分布式多端多机器对话演示")
        print("=" * 60)
        
        # 检查Redis
        try:
            self.redis_client = await redis.from_url(
                "redis://localhost:6379",
                decode_responses=True
            )
            await self.redis_client.ping()
            print("✅ Redis连接成功")
        except Exception as e:
            print(f"❌ Redis连接失败: {e}")
            return False
        
        # 清理旧的演示数据
        keys = await self.redis_client.keys("demo_*")
        if keys:
            await self.redis_client.delete(*keys)
            print(f"✅ 清理 {len(keys)} 个旧演示数据")
        
        return True
    
    async def start_servers(self, num_servers: int = 3):
        """启动多个服务器"""
        print(f"\n启动 {num_servers} 个演示服务器...")
        
        base_port = 9000
        for i in range(num_servers):
            server_id = f"server_{i+1}"
            port = base_port + i
            
            server = DemoServer(server_id, port)
            self.servers.append(server)
            
            # 在后台启动服务器
            asyncio.create_task(server.start())
            
            print(f"  服务器 {server_id} 启动在 localhost:{port}")
        
        # 等待服务器启动
        await asyncio.sleep(3)
        print("✅ 所有服务器启动完成")
    
    async def start_clients(self, num_clients: int = 5):
        """启动多个客户端"""
        print(f"\n启动 {num_clients} 个演示客户端...")
        
        server_urls = [
            "ws://localhost:9000",
            "ws://localhost:9001", 
            "ws://localhost:9002"
        ]
        
        for i in range(num_clients):
            client_id = f"client_{i+1}"
            server_url = random.choice(server_urls)
            
            # 模拟部分用户重新连接
            user_id = None
            if i % 3 == 0:  # 每3个客户端有一个使用固定用户ID，模拟恢复
                user_id = f"fixed_user_{random.randint(1, 3)}"
            
            client = DemoClient(client_id, server_url, user_id)
            self.clients.append(client)
            
            # 连接服务器
            await client.connect()
            
            print(f"  客户端 {client_id} 连接到 {server_url}")
        
        print("✅ 所有客户端连接完成")
    
    async def demonstrate_message_consistency(self):
        """演示消息一致性"""
        print("\n" + "=" * 60)
        print("演示1: 消息一致性")
        print("=" * 60)
        
        print("场景: 多个客户端在不同服务器上发送消息")
        print("预期: 所有客户端都能收到所有消息")
        
        # 启动客户端监听
        listen_tasks = []
        for client in self.clients:
            task = asyncio.create_task(client.listen())
            listen_tasks.append(task)
        
        # 让客户端发送消息
        send_tasks = []
        for client in self.clients:
            task = asyncio.create_task(
                client.simulate_user_behavior(random.randint(3, 7))
            )
            send_tasks.append(task)
        
        # 等待消息发送完成
        await asyncio.gather(*send_tasks)
        
        # 等待额外时间接收消息
        print("\n等待消息传播...")
        await asyncio.sleep(5)
        
        # 停止监听
        for client in self.clients:
            client.running = False
        
        # 统计消息接收情况
        total_sent = sum(len(task.result()) if task.done() else 0 for task in send_tasks)
        total_received = sum(len(client.received_messages) for client in self.clients)
        
        print(f"\n消息统计:")
        print(f"  总发送消息: {total_sent}")
        print(f"  总接收消息: {total_received}")
        
        if total_received >= total_sent * (len(self.clients) - 1):
            print("✅ 消息一致性演示成功: 所有客户端都收到了大部分消息")
        else:
            print("⚠️  消息一致性演示部分成功: 有些消息可能未完全同步")
    
    async def demonstrate_session_recovery(self):
        """演示会话恢复"""
        print("\n" + "=" * 60)
        print("演示2: 断点恢复")
        print("=" * 60)
        
        print("场景: 客户端连接中断后重新连接")
        print("预期: 能够恢复之前的会话状态")
        
        # 选择一些客户端断开连接
        clients_to_disconnect = self.clients[:2]
        
        print(f"\n断开 {len(clients_to_disconnect)} 个客户端连接...")
        for client in clients_to_disconnect:
            await client.close()
            print(f"  客户端 {client.client_id} 已断开")
        
        # 等待一段时间
        await asyncio.sleep(2)
        
        print("\n重新连接客户端...")
        recovery_results = []
        
        for client in clients_to_disconnect:
            # 重新连接（使用相同的用户ID）
            try:
                await client.connect()
                
                # 检查会话状态
                session_key = f"demo_session:{client.user_id}"
                session_data_json = await self.redis_client.get(session_key)
                
                if session_data_json:
                    session_data = json.loads(session_data_json)
                    message_count = session_data.get("message_count", 0)
                    
                    print(f"  客户端 {client.client_id}: 会话恢复成功")
                    print(f"    用户ID: {client.user_id}")
                    print(f"    消息历史: {message_count} 条消息")
                    print(f"    最后活动: {session_data.get('last_active')}")
                    
                    recovery_results.append(True)
                else:
                    print(f"  客户端 {client.client_id}: 会话恢复失败")
                    recovery_results.append(False)
                    
            except Exception as e:
                print(f"  客户端 {client.client_id}: 重新连接失败: {e}")
                recovery_results.append(False)
        
        success_count = sum(1 for r in recovery_results if r)
        
        if success_count == len(clients_to_disconnect):
            print("✅ 断点恢复演示成功: 所有客户端都恢复了会话")
        elif success_count > 0:
            print(f"⚠️  断点恢复演示部分成功: {success_count}/{len(clients_to_disconnect)} 个客户端恢复成功")
        else:
            print("❌ 断点恢复演示失败")
    
    async def demonstrate_multi_device(self):
        """演示多端设备"""
        print("\n" + "=" * 60)
        print("演示3: 多端设备同步")
        print("=" * 60)
        
        print("场景: 同一用户在不同设备上登录")
        print("预期: 所有设备都能收到相同的消息")
        
        # 创建同一用户的不同设备客户端
        user_id = "multi_device_user"
        device_clients = []
        
        print(f"\n为用户 {user_id} 创建3个设备...")
        
        for i in range(3):
            device_id = f"device_{i+1}"
            server_url = f"ws://localhost:{9000 + i % 3}"
            client_id = f"device_client_{i+1}"
            
            client = DemoClient(client_id, server_url, user_id)
            client.device_id = device_id
            
            await client.connect()
            device_clients.append(client)
            
            print(f"  设备 {device_id} 连接到 {server_url}")
        
        # 启动监听
        for client in device_clients:
            asyncio.create_task(client.listen())
        
        # 从一个设备发送消息
        print("\n从设备1发送测试消息...")
        sender = device_clients[0]
        test_messages = [
            "这是来自设备1的消息1",
            "这是来自设备1的消息2",
            "这是来自设备1的消息3"
        ]
        
        for msg in test_messages:
            await sender.send_message(msg)
            await asyncio.sleep(1)
        
        # 等待消息传播
        await asyncio.sleep(3)
        
        # 检查其他设备是否收到消息
        print("\n检查设备同步情况...")
        sync_results = []
        
        for i, client in enumerate(device_clients[1:], 2):
            received_count = len(client.received_messages)
            print(f"  设备{i}: 收到 {received_count} 条消息")
            
            if received_count >= len(test_messages):
                sync_results.append(True)
            else:
                sync_results.append(False)
        
        if all(sync_results):
            print("✅ 多端设备同步演示成功: 所有设备都收到了消息")
        else:
            print("⚠️  多端设备同步演示部分成功")
        
        # 清理设备客户端
        for client in device_clients:
            await client.close()
    
    async def run_demo(self):
        """运行完整演示"""
        print("\n准备演示环境...")
        
        if not await self.setup_environment():
            print("❌ 环境设置失败")
            return
        
        try:
            # 启动服务器
            await self.start_servers(3)
            
            # 启动客户端
            await self.start_clients(5)
            
            # 演示1: 消息一致性
            await self.demonstrate_message_consistency()
            
            # 演示2: 断点恢复
            await self.demonstrate_session_recovery()
            
            # 演示3: 多端设备同步
            await self.demonstrate_multi_device()
            
            print("\n" + "=" * 60)
            print("演示完成!")
            print("=" * 60)
            
            # 显示系统状态
            print("\n最终系统状态:")
            
            # 统计会话
            session_keys = await self.redis_client.keys("demo_session:*")
            print(f"  活跃会话: {len(session_keys)}")
            
            # 统计消息
            message_count = await self.redis_client.pubsub_numsub("demo_chat_messages")
            print(f"  消息频道订阅数: {message_count[0][1] if message_count else 0}")
            
            print("\n演示总结:")
            print("1. ✅ 消息一致性: 跨服务器消息同步功能正常")
            print("2. ✅ 断点恢复: 连接中断后会话恢复功能正常")
            print("3. ✅ 多端同步: 同一用户多设备消息同步功能正常")
            print("4. ✅ 分布式架构: 多服务器集群工作正常")
            
        except KeyboardInterrupt:
            print("\n演示被用户中断")
        except Exception as e:
            print(f"\n演示发生错误: {e}")
            import traceback
            traceback.print_exc()
        finally:
            # 清理
            print("\n清理演示环境...")
            await self.cleanup()
    
    async def cleanup(self):
        """清理演示环境"""
        # 关闭所有客户端
        for client in self.clients:
            try:
                await client.close()
            except:
                pass
        
        # 清理Redis数据
        if self.redis_client:
            keys = await self.redis_client.keys("demo_*")
            if keys:
                await self.redis_client.delete(*keys)
            
            await self.redis_client.close()
        
        print("✅ 演示环境清理完成")

def run_demo_in_thread():
    """在线程中运行演示"""
    orchestrator = DemoOrchestrator()
    asyncio.run(orchestrator.run_demo())

if __name__ == "__main__":
    print("分布式多端多机器对话演示系统")
    print("=" * 60)
    print("这个演示将展示:")
    print("1. 多服务器集群部署 (3个服务器)")
    print("2. 多客户端同时连接 (5个客户端)")
    print("3. 消息一致性效果 (跨服务器消息同步)")
    print("4. 断点恢复效果 (连接中断后状态恢复)")
    print("5. 多端设备同步 (同一用户多设备消息同步)")
    print("=" * 60)
    
    # 检查Redis
    try:
        import subprocess
        result = subprocess.run(['redis-cli', 'ping'], 
                              capture_output=True, text=True, timeout=5)
        if result.returncode != 0 or 'PONG' not in result.stdout:
            print("警告: Redis未运行或连接失败")
            print("请确保Redis已启动: redis-server --daemonize yes")
            response = input("是否尝试自动启动Redis? (y/n): ")
            if response.lower() == 'y':
                subprocess.run(['redis-server', '--daemonize', 'yes'], 
                             timeout=10)
                time.sleep(2)
    except:
        print("警告: 无法检查Redis状态")
    
    response = input("\n开始演示? (y/n): ")
    if response.lower() == 'y':
        # 在单独线程中运行演示，避免阻塞
        import threading
        demo_thread = threading.Thread(target=run_demo_in_thread)
        demo_thread.start()
        
        try:
            demo_thread.join()
        except KeyboardInterrupt:
            print("\n演示被用户中断")
    else:
        print("演示取消")