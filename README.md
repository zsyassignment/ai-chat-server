# 高性能 AI 大模型流式对话服务器

基于 C++ 编写的轻量级、高并发 HTTP 服务器，原生支持 Server-Sent Events (SSE) 协议，可实现与 AI 大模型（如 OpenAI）的低延迟流式交互。

## ✨ 核心特性

- **流式对话体验**：原生支持 SSE 长连接传输，结合异步大模型客户端，实现 AI 结果的逐字推送，大幅降低首字响应延迟 。
- **高吞吐网络架构**：底层采用主从 Reactor 模式与 epoll 多路复用，解耦网络 I/O 监听与业务逻辑计算。
- **核心组件调优**：内置自主实现的内存池、LFU 缓存与双缓冲异步日志模块，有效降低系统碎片化率并保障高压下的稳定运行。
- **开箱即用**：项目自带 Web 端静态聊天页面，编译后即可在浏览器中获得完整的对话体验。

## 🛠️ 快速开始

### 1. 环境依赖

- Linux 操作系统
- CMake 及 C++11/14 编译器
- `libcurl` (用于大模型 API 请求交互)

### 2. 编译项目

项目根目录下提供了快捷配置脚本，你可以直接运行：

```bash
bash setup.sh
```

### 3.设置 API Key

```bash
export OPENAI_API_KEY="sk-xxxxxxxxx"
```

### 4.（可选）如果使用兼容 OpenAI 格式的其他模型接口，可修改 Base URL

```bash
export OPENAI_BASE_URL="[https://api.deepseek.com/v1/chat/completions](https://api.deepseek.com/v1/chat/completions)"
```

### 5.启动服务器（请根据实际生成的可执行文件名及参数调整）

```bash
./main
```


