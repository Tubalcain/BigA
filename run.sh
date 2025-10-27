#!/bin/bash

# BigA Stock Analysis - Linux/Mac启动脚本

echo "========================================"
echo "BigA Stock Analysis"
echo "========================================"
echo

# 检查虚拟环境
if [ ! -d "venv" ]; then
    echo "正在创建虚拟环境..."
    python3 -m venv venv
fi

# 激活虚拟环境
echo "激活虚拟环境..."
source venv/bin/activate

# 安装依赖（如果需要）
echo
echo "检查依赖..."
pip install -q -r requirements.txt

# 运行应用
echo
echo "启动BigA Stock Analysis..."
echo "浏览器将自动打开 http://localhost:8501"
echo
streamlit run app.py

