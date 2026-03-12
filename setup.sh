#!/bin/bash

# 设置遇到错误立即退出
set -e

# sudo apt-get update
# sudo apt-get install -y build-essential cmake libcurl4-openssl-dev

echo "mkdir build..."
cd "$(dirname "$0")"
if [ -d "build" ]; then
    rm -rf build/*
else
    mkdir build
fi
#使用valgrind进行内存泄漏检查时使用
# cmake -B build -DCMAKE_BUILD_TYPE=Debug 
cd build

echo "cmaking ..."

cmake ..

# -j$(nproc) 自动获取你 CPU 的核心数
make -j$(nproc)