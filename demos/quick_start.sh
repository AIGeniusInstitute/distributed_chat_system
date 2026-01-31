#!/bin/bash
# 分布式多端多机器对话演示快速启动脚本

echo "================================================"
echo "分布式WebSocket对话演示快速启动"
echo "================================================"

# 检查Python版本
echo "检查Python版本..."
python3 --version
if [ $? -ne 0 ]; then
    echo "错误: Python3未安装"
    exit 1
fi

# 检查Redis
echo "检查Redis..."
redis-cli ping 2>/dev/null | grep -q "PONG"
if [ $? -ne 0 ]; then
    echo "Redis未运行，尝试启动..."
    
    # 尝试启动Redis
    if command -v redis-server &> /dev/null; then
        redis-server --daemonize yes
        sleep 2
        redis-cli ping 2>/dev/null | grep -q "PONG"
        if [ $? -ne 0 ]; then
            echo "警告: Redis启动失败，请手动启动: redis-server --daemonize yes"
            read -p "是否继续? (y/n): " -n 1 -r
            echo
            if [[ ! $REPLY =~ ^[Yy]$ ]]; then
                exit 1
            fi
        else
            echo "✅ Redis启动成功"
        fi
    else
        echo "错误: Redis未安装"
        echo "请安装Redis:"
        echo "  Ubuntu: sudo apt-get install redis-server"
        echo "  macOS: brew install redis"
        echo "  或使用Docker: docker run -d -p 6379:6379 redis"
        exit 1
    fi
else
    echo "✅ Redis运行正常"
fi

# 检查Python依赖
echo "检查Python依赖..."
python3 -c "import websockets, redis, aiohttp" 2>/dev/null
if [ $? -ne 0 ]; then
    echo "安装Python依赖..."
    pip3 install --user websockets redis aiohttp
    if [ $? -ne 0 ]; then
        echo "错误: 依赖安装失败"
        exit 1
    fi
    echo "✅ Python依赖安装成功"
else
    echo "✅ Python依赖已安装"
fi

# 清理旧的演示数据
echo "清理旧的演示数据..."
redis-cli --raw keys "demo_*" 2>/dev/null | xargs -r redis-cli del 2>/dev/null
echo "✅ 旧数据清理完成"

# 启动演示
echo ""
echo "================================================"
echo "启动分布式对话演示..."
echo "================================================"
echo ""
echo "演示将展示:"
echo "1. 3个WebSocket服务器集群"
echo "2. 5个客户端同时连接"
echo "3. 消息一致性效果"
echo "4. 断点恢复效果"
echo "5. 多端设备同步"
echo ""
echo "按 Ctrl+C 停止演示"
echo ""

# 运行演示
python3 demo_distributed_chat.py

# 演示结束后的清理
echo ""
echo "================================================"
echo "演示结束，清理环境..."
echo "================================================"

# 清理演示数据
redis-cli --raw keys "demo_*" 2>/dev/null | xargs -r redis-cli del 2>/dev/null
echo "✅ 演示数据清理完成"

echo ""
echo "演示完成！"
echo "查看演示说明: cat demo_instructions.md"
echo "查看完整实现: cat complete_implementation.py"