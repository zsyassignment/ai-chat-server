# 高性能 AI 大模型流式对话服务器

基于 C++ 编写的轻量级、高并发 HTTP 服务器，原生支持 Server-Sent Events (SSE) 协议，可实现与 AI 大模型（如 OpenAI）的低延迟流式交互。

## ✨ 核心特性

- **流式对话体验**：原生支持 SSE 长连接传输，结合异步大模型客户端，实现 AI 结果的逐字推送，大幅降低首字响应延迟 。
- **高吞吐网络架构**：底层采用主从 Reactor 模式与 epoll 多路复用，解耦网络 I/O 监听与业务逻辑计算。
- **持久化与鉴权**：内置 MySQL 连接池、用户注册登录、Bearer Token 鉴权与对话历史持久化。
- **阻塞任务异步化**：数据库查询和模型调用都通过任务分发到线程池执行，避免阻塞 Reactor 核心 I/O 循环。
- **核心组件调优**：内置自主实现的内存池、LFU 缓存与双缓冲异步日志模块，有效降低系统碎片化率并保障高压下的稳定运行。
- **开箱即用**：项目自带 Web 端静态聊天页面，编译后即可在浏览器中获得完整的对话体验。

## 🛠️ 快速开始

### 1. 环境依赖

- Linux 操作系统
- CMake 及 C++11/14 编译器
- `libcurl` (用于大模型 API 请求交互)
- `mysql_config` / MySQL C Client 开发库
- OpenSSL 开发库（用于密码摘要与随机 token）

### 2. 编译项目

项目根目录下提供了快捷配置脚本，你可以直接运行：

```bash
bash setup.sh
```

### 3.一键加载本地环境变量

项目根目录下已经提供了适配你当前本地环境的脚本：

```bash
source ./env.local.sh
```

这个脚本默认配置为：

- MySQL 在 `127.0.0.1:3306`
- 用户名 `root`
- 空密码
- 数据库名 `ai_chat_server`

如果你后面改了本地配置，直接编辑 `env.local.sh` 即可。

注意：必须用 `source` 或 `. ./env.local.sh`，直接 `bash env.local.sh` 不会把 `export` 保留到当前终端。

### 4.手动设置 API Key（可选替代）

```bash
export OPENAI_API_KEY="sk-xxxxxxxxx"
```

### 5.手动配置 MySQL（可选替代）

```bash
export MYSQL_HOST="127.0.0.1"
export MYSQL_PORT="3306"
export MYSQL_USER="root"
export MYSQL_PASSWORD="your-password"
export MYSQL_DATABASE="ai_chat_server"
export MYSQL_POOL_SIZE="8"
export MYSQL_CONNECT_TIMEOUT="3"
export DB_WORKER_THREADS="4"
```

服务启动时会自动创建数据库和所需表结构；如果 MySQL 凭据不可用，静态页面仍能访问，但 `/api/auth/*`、`/api/me`、`/api/history` 和 `/api/chat` 会返回 `503 Service Unavailable`。

### 6.（可选）如果使用兼容 OpenAI 格式的其他模型接口，可修改 Base URL

```bash
export OPENAI_BASE_URL="[https://api.deepseek.com/v1/chat/completions](https://api.deepseek.com/v1/chat/completions)"
```

### 7.启动服务器（请根据实际生成的可执行文件名及参数调整）

```bash
source ./env.local.sh
./bin/main
```

启动后访问 `http://127.0.0.1:9856/`，先在页面中注册或登录，再发起对话。浏览器会保存 token，服务端会自动恢复最近的持久化历史记录。


