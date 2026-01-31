#!/usr/bin/env python3
"""
简化演示运行
快速展示分布式对话系统的核心功能
"""

import asyncio
import json
import time
import random
from datetime import datetime
import subprocess
import sys

def print_header(title):
    """打印标题"""
    print("\n" + "=" * 60)
    print(title)
    print("=" * 60)

def check_redis():
    """检查Redis"""
    print_header("1. 检查Redis状态")
    
    try:
        result = subprocess.run(['redis-cli', 'ping'], 
                              capture_output=True, text=True, timeout=5)
        if result.returncode == 0 and 'PONG' in result.stdout:
            print("✅ Redis运行正常")
            return True
        else:
            print("❌ Redis未运行")
            return False
    except:
        print("❌ 无法检查Redis")
        return False

async def simulate_distributed_chat():
    """模拟分布式聊天演示"""
    print_header("2. 模拟分布式聊天演示")
    
    print("场景: 3个用户在不同服务器上聊天")
    print("用户A -> 服务器1")
    print("用户B -> 服务器2")
    print("用户C -> 服务器3")
    print("所有消息通过Redis Pub/Sub同步")
    
    # 模拟消息流
    messages = [
        ("用户A", "服务器1", "大家好，我是用户A"),
        ("用户B", "服务器2", "你好用户A，我是用户B"),
        ("用户C", "服务器3", "我也在这里，我是用户C"),
        ("用户A", "服务器1", "分布式系统真有趣"),
        ("用户B", "服务器2", "是的，消息同步很重要"),
        ("用户C", "服务器3", "断点恢复功能也很实用"),
    ]
    
    print("\n模拟消息流:")
    for sender, server, content in messages:
        print(f"  [{server}] {sender}: {content}")
        await asyncio.sleep(0.5)
    
    print("\n✅ 消息同步演示完成")
    print("   所有用户都收到了所有消息")

async def simulate_session_recovery():
    """模拟会话恢复"""
    print_header("3. 模拟会话恢复演示")
    
    print("场景: 用户连接中断后重新连接")
    print("步骤:")
    print("  1. 用户建立连接并发送消息")
    print("  2. 连接意外中断")
    print("  3. 用户重新连接")
    print("  4. 恢复之前的会话状态")
    
    user_id = "demo_user_001"
    
    print(f"\n用户 {user_id} 建立连接...")
    await asyncio.sleep(1)
    
    print(f"用户 {user_id} 发送消息: '你好，这是第一条消息'")
    await asyncio.sleep(1)
    
    print(f"用户 {user_id} 发送消息: '这是第二条消息'")
    await asyncio.sleep(1)
    
    print(f"\n⚠️  连接中断...")
    await asyncio.sleep(2)
    
    print(f"\n用户 {user_id} 重新连接...")
    await asyncio.sleep(1)
    
    print(f"✅ 会话恢复成功")
    print(f"   恢复信息:")
    print(f"     - 用户ID: {user_id}")
    print(f"     - 消息历史: 2条消息")
    print(f"     - 最后活动: {datetime.now().isoformat()}")
    
    print("\n✅ 断点恢复演示完成")

async def simulate_multi_device():
    """模拟多端设备"""
    print_header("4. 模拟多端设备同步")
    
    print("场景: 同一用户在多个设备上登录")
    print("设备:")
    print("  - 手机 (连接到服务器1)")
    print("  - 电脑 (连接到服务器2)")
    print("  - 平板 (连接到服务器3)")
    
    user_id = "multi_device_user"
    
    print(f"\n用户 {user_id} 在3个设备上登录...")
    await asyncio.sleep(1)
    
    print(f"\n从手机发送消息: '来自手机的消息'")
    await asyncio.sleep(1)
    
    print(f"电脑收到消息: '来自手机的消息'")
    await asyncio.sleep(0.5)
    
    print(f"平板收到消息: '来自手机的消息'")
    await asyncio.sleep(0.5)
    
    print(f"\n从电脑发送消息: '来自电脑的消息'")
    await asyncio.sleep(1)
    
    print(f"手机收到消息: '来自电脑的消息'")
    await asyncio.sleep(0.5)
    
    print(f"平板收到消息: '来自电脑的消息'")
    await asyncio.sleep(0.5)
    
    print("\n✅ 多端设备同步演示完成")
    print("   所有设备都收到了相同的消息")

def show_system_architecture():
    """显示系统架构"""
    print_header("5. 系统架构展示")
    
    print("分布式WebSocket对话系统架构:")
    print("")
    print("┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐")
    print("│   客户端设备A   │    │   客户端设备B   │    │   客户端设备C   │")
    print("│  (Web/App)      │    │  (Web/App)      │    │  (Web/App)      │")
    print("└────────┬────────┘    └────────┬────────┘    └────────┬────────┘")
    print("         │                      │                      │")
    print("         │ WebSocket连接        │ WebSocket连接        │ WebSocket连接")
    print("         │                      │                      │")
    print("┌────────▼────────┐    ┌────────▼────────┐    ┌────────▼────────┐")
    print("│  WebSocket服务器1 │    │  WebSocket服务器2 │    │  WebSocket服务器3 │")
    print("│  (Node 1)       │    │  (Node 2)       │    │  (Node 3)       │")
    print("└────────┬────────┘    └────────┬────────┘    └────────┬────────┘")
    print("         │                      │                      │")
    print("         │ Redis Pub/Sub        │ Redis Pub/Sub        │ Redis Pub/Sub")
    print("         │                      │                      │")
    print("         └──────────┬───────────┴──────────┬───────────┘")
    print("                    │                      │")
    print("            ┌───────▼───────┐      ┌───────▼───────┐")
    print("            │   Redis集群   │      │  LangGraph    │")
    print("            │               │      │  状态引擎     │")
    print("            │  - 会话状态   │      │               │")
    print("            │  - 检查点数据 │      └───────────────┘")
    print("            │  - 消息队列   │")
    print("            └───────────────┘")
    print("")
    
    print("核心组件:")
    print("  1. WebSocket服务器: 处理客户端连接和消息路由")
    print("  2. Redis: 消息广播、状态存储、分布式协调")
    print("  3. LangGraph: 对话状态管理、检查点保存")
    print("")
    
    print("关键技术:")
    print("  ✅ Redis Pub/Sub: 实现跨服务器消息同步")
    print("  ✅ LangGraph检查点: 实现断点恢复")
    print("  ✅ WebSocket: 实现实时双向通信")
    print("  ✅ 分布式架构: 支持水平扩展")

def show_demo_options():
    """显示演示选项"""
    print_header("6. 完整演示选项")
    
    print("要运行完整演示，您有以下选项:")
    print("")
    print("选项1: 快速启动完整演示")
    print("  $ ./quick_start.sh")
    print("")
    print("选项2: 运行Python演示脚本")
    print("  $ python3 demo_distributed_chat.py")
    print("")
    print("选项3: 手动分步运行")
    print("  1. 启动Redis: redis-server --daemonize yes")
    print("  2. 安装依赖: pip install redis websockets aiohttp")
    print("  3. 运行演示: python3 demo_distributed_chat.py")
    print("")
    print("演示功能包括:")
    print("  • 3个WebSocket服务器集群")
    print("  • 5个客户端同时连接")
    print("  • 消息一致性展示")
    print("  • 断点恢复展示")
    print("  • 多端设备同步展示")
    print("")
    print("查看详细说明:")
    print("  $ cat demo_instructions.md")

async def main():
    """主函数"""
    print("=" * 60)
    print("分布式多端多机器对话系统演示")
    print("=" * 60)
    print("")
    print("这个演示展示基于LangGraph和Redis的分布式WebSocket对话系统")
    print("重点展示: 消息一致性、断点恢复、多端同步")
    print("")
    
    # 检查Redis
    if not check_redis():
        print("\n⚠️  Redis未运行，演示将使用模拟模式")
        print("要运行完整演示，请先启动Redis:")
        print("  $ redis-server --daemonize yes")
        print("")
        response = input("是否继续模拟演示? (y/n): ")
        if response.lower() != 'y':
            return
    
    # 运行模拟演示
    await simulate_distributed_chat()
    await simulate_session_recovery()
    await simulate_multi_device()
    
    # 显示架构
    show_system_architecture()
    
    # 显示演示选项
    show_demo_options()
    
    print("\n" + "=" * 60)
    print("演示完成!")
    print("=" * 60)
    print("")
    print("总结:")
    print("✅ 消息一致性: 通过Redis Pub/Sub实现跨服务器消息同步")
    print("✅ 断点恢复: 通过LangGraph检查点实现状态持久化和恢复")
    print("✅ 多端同步: 支持同一用户多设备消息同步")
    print("✅ 分布式架构: 支持多服务器集群部署")
    print("")
    print("所有代码和文档已准备就绪，可以运行完整演示。")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n演示被用户中断")
    except Exception as e:
        print(f"\n演示错误: {e}")