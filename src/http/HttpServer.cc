#include "HttpServer.h"

#include <algorithm>
#include <cstdio>
#include <cstring>
#include <functional>
#include <vector>

#include <nlohmann/json.hpp>

#include "Buffer.h"
#include "Logger.h"

//http1.1规定如果不知道流式输出的总长度，必须声明transfer-encoding: chunked
//并且每次输出一块数据时，先输出该块数据的字节数（十六进制）和\r\n，再输出数据内容，最后再输出\r\n
//所有数据发送完后，发送一个0\r\n\r\n表示结束
namespace {
std::string toChunk(const std::string& payload)
{
    char lenHex[32] = {0};
    std::snprintf(lenHex, sizeof(lenHex), "%zx", payload.size());
    std::string chunk;
    chunk.reserve(std::strlen(lenHex) + 2 + payload.size() + 2);
    chunk.append(lenHex);
    chunk.append("\r\n");
    chunk.append(payload);
    chunk.append("\r\n");
    return chunk;
}

//前端使用eventsource接收数据，要求数据格式为event: 事件名\n data: 数据\n\n
std::string makeSseEvent(const std::string& eventName, const nlohmann::json& data)
{
    std::string out;
    out.reserve(32 + data.dump().size());
    out.append("event: ");
    out.append(eventName);
    out.append("\n");
    out.append("data: ");
    out.append(data.dump());
    out.append("\n\n");
    return out;
}

//防止切分到utf-8字符中间导致乱码，找到下一个合法的utf-8边界
size_t nextUtf8Boundary(const std::string& s, size_t from, size_t chunkBytes)
{
    size_t next = std::min(s.size(), from + chunkBytes);
    while (next < s.size() && (static_cast<unsigned char>(s[next]) & 0xC0) == 0x80)
    {
        ++next;
    }
    return next;
}
}

HttpServer::HttpServer(EventLoop* loop,
                       const InetAddress& addr,
                       const std::string& name,
                       TaskExecutor& executor,
                       OpenAIClient& aiClient,
                       KamaCache::KLfuCache<std::string, std::string>& cache,
                       const std::string& staticDir)
    : server_(loop, addr, name)
    , staticHandler_(staticDir)
    , executor_(executor)
    , aiClient_(aiClient)
    , cache_(cache) {
    server_.setConnectionCallback(
        //placeholders::_1是占位符，表示这个位置的参数会在调用时传入。std::bind会将TcpServer::onConnection成员函数与当前对象this绑定起来，并且指定当onConnection被调用时，传入的参数会被正确地转发到占位符的位置。
        std::bind(&HttpServer::onConnection, this, std::placeholders::_1));
    server_.setMessageCallback(
        std::bind(&HttpServer::onMessage, this, std::placeholders::_1, std::placeholders::_2, std::placeholders::_3));
    
    //如果没有路由规则匹配，默认使用静态文件处理器
    router_.setNotFoundHandler([this](const HttpRequest& req, HttpResponse& resp) {
        staticHandler_.handle(req.path(), resp);
    });
}

void HttpServer::start() {
    server_.start();
}

void HttpServer::onConnection(const TcpConnectionPtr& conn) 
{
    if (conn->connected()) 
    {
        LOG_INFO << "New HTTP connection from " << conn->peerAddress().toIpPort();
        std::lock_guard<std::mutex> lock(contextMutex_);
        //插入一个新的 HttpContext 对象到 contexts_ 哈希表中，每个请求有一个对应的 HttpContext 来维护解析状态和请求数据
        contexts_.emplace(conn->name(), HttpContext());
    } 
    else 
    {
        LOG_INFO << "Connection closed " << conn->peerAddress().toIpPort();
        removeContext(conn);
    }
}

void HttpServer::onMessage(const TcpConnectionPtr& conn, Buffer* buf, Timestamp time) 
{
    (void)time;
    auto& ctx = contextFor(conn);//返回对应连接的httpcontext解析器
    if (!ctx.parseRequest(buf)) 
    {
        sendError(conn, HttpStatusCode::k400BadRequest, "Bad Request");
        return;
    }

    //现在假设只能处理4MB的请求体，超过就拒绝，防止恶意攻击占满内存资源
    const size_t kMaxBodySize = 4 * 1024 * 1024; // 4MB safeguard
    if (ctx.request().body().size() > kMaxBodySize) 
    {
        sendError(conn, HttpStatusCode::k413PayloadTooLarge, "Payload Too Large");
        ctx.reset();
        return;
    }

    if (ctx.gotAll()) {
        handleRequest(conn, ctx.request());
        ctx.reset();
    }
}

void HttpServer::handleRequest(const TcpConnectionPtr& conn, HttpRequest& req) 
{
    bool close = !req.keepAlive();

    // 特例：如果是 POST /api/chat 就走专门的异步处理流程，其他请求走常规路由
    if (req.method() == HttpRequest::Method::kPost && req.path() == "/api/chat") 
    {
        handleChatAsync(conn, req, close);
        return;
    }

    if (req.method() == HttpRequest::Method::kGet || req.method() == HttpRequest::Method::kPost) 
    {
        HttpResponse resp(close);
        //路由解析
        if (!router_.route(req, resp)) 
        {
            resp.setStatusCode(HttpStatusCode::k404NotFound);
            resp.setStatusMessage("Not Found");
            resp.setContentType("text/plain; charset=utf-8");
            resp.setBody("404 Not Found");
        }
        sendResponse(conn, resp);
    } 
    else 
    {
        sendError(conn, HttpStatusCode::k405MethodNotAllowed, "Method Not Allowed");
    }
}

void HttpServer::handleChatAsync(const TcpConnectionPtr& conn, const HttpRequest& req, bool closeConnection) 
{
    //找到属于的I/O线程
    EventLoop* ioLoop = conn->getLoop();
    std::string body = req.body();

    //在处理请求之前先发送一个初始响应，告诉前端连接已建立，并告知ai提供商服务器将使用stream输出
    ioLoop->queueInLoop([conn, closeConnection]() {
        std::string headers =
            "HTTP/1.1 200 OK\r\n"
            "Content-Type: text/event-stream; charset=utf-8\r\n" //设置Content-Type: text/event-stream，告知浏览器不要断开tcp连接，并且按照eventsource的格式解析数据
            "Cache-Control: no-cache\r\n" //告知路由节点和nginx代理不要缓存而是要来一个发送一个
            "X-Accel-Buffering: no\r\n" //关闭eginx缓冲
            "Transfer-Encoding: chunked\r\n"; //分块输出
        headers += closeConnection ? "Connection: close\r\n\r\n" : "Connection: keep-alive\r\n\r\n";
        conn->send(headers);

        const auto startEvent = makeSseEvent("status", nlohmann::json{{"message", "已连接，正在处理请求..."}});
        conn->send(toChunk(startEvent));
    });

    //需要按值捕获因为后面的lambda会在另一个线程执行，按引用捕获可能会导致访问已销毁的对象
    executor_.submit([this, conn, ioLoop, body, closeConnection]() 
    {
        //C++ 结构体转 JSON 数组 (序列化)
        //[{"role": "user", "content": "你好"}, {"role": "assistant", "content": "你好！"}]
        auto toJsonHistory = [](const std::vector<OpenAIClient::ChatMessage>& msgs) 
        {
            nlohmann::json arr = nlohmann::json::array();
            for (const auto& m : msgs) 
            {
                arr.push_back({{"role", m.role}, {"content", m.content}});
            }
            return arr;
        };

        try 
        {
            LOG_INFO << "Received chat request: " << body;

            //使用nlohmann::json库解析请求体，提取用户消息和历史上下文
            auto jsonReq = nlohmann::json::parse(body);
            if (!jsonReq.contains("message") || !jsonReq["message"].is_string()) 
            {
                ioLoop->queueInLoop([conn, closeConnection]() {
                    conn->send(toChunk(makeSseEvent("error", nlohmann::json{{"message", "message required"}})));
                    conn->send("0\r\n\r\n");
                    if (closeConnection) {
                        conn->shutdown();
                    }
                });
                return;
            } 
            else 
            {
                //提取用户消息
                std::string userMessage = jsonReq["message"].get<std::string>();

                std::vector<OpenAIClient::ChatMessage> messages;
                if (jsonReq.contains("history") && jsonReq["history"].is_array()) 
                {
                    for (const auto& item : jsonReq["history"]) 
                    {
                        if (item.contains("role") && item.contains("content") && item["role"].is_string() && item["content"].is_string()) 
                        {
                            messages.push_back({item["role"].get<std::string>(), item["content"].get<std::string>()});
                        }
                    }
                }
                
                //最多包含16条历史消息，保持上下文简洁
                const size_t kMaxMessages = 16; // keep recent context compact
                if (messages.size() > kMaxMessages)
                {
                    messages.erase(messages.begin(), messages.end() - kMaxMessages);
                }

                messages.push_back({"user", userMessage});

                std::string cacheKey = toJsonHistory(messages).dump();
                std::string cached;
                if (cache_.get(cacheKey, cached)) 
                {
                    auto history = messages;
                    history.push_back({"assistant", cached});
                    ioLoop->queueInLoop([conn, cached, history, closeConnection, toJsonHistory]() {
                        conn->send(toChunk(makeSseEvent("status", nlohmann::json{{"message", "命中缓存，正在输出..."}})));

                        size_t pos = 0;
                        const size_t kChunkBytes = 48;
                        while (pos < cached.size()) {
                            size_t next = nextUtf8Boundary(cached, pos, kChunkBytes);
                            std::string piece = cached.substr(pos, next - pos);
                            conn->send(toChunk(makeSseEvent("delta", nlohmann::json{{"content", piece}})));
                            pos = next;
                        }

                        conn->send(toChunk(makeSseEvent("done", nlohmann::json{{"cached", true}, {"history", toJsonHistory(history)}})));
                        conn->send("0\r\n\r\n");
                        if (closeConnection) {
                            conn->shutdown();
                        }
                    });
                } 
                else 
                {
                    ioLoop->queueInLoop([conn]() {
                        conn->send(toChunk(makeSseEvent("status", nlohmann::json{{"message", "模型思考中..."}})));
                    });

                    auto answer = aiClient_.chatCompletionStream(
                        messages,
                        [ioLoop, conn](const std::string& delta) {
                            if (delta.empty()) {
                                return;
                            }
                            ioLoop->queueInLoop([conn, delta]() {
                                conn->send(toChunk(makeSseEvent("delta", nlohmann::json{{"content", delta}})));
                            });
                        });

                    if (answer.has_value()) {
                        cache_.put(cacheKey, *answer);
                        auto history = messages;
                        history.push_back({"assistant", *answer});
                        ioLoop->queueInLoop([conn, history, closeConnection, toJsonHistory]() {
                            conn->send(toChunk(makeSseEvent("done", nlohmann::json{{"cached", false}, {"history", toJsonHistory(history)}})));
                            conn->send("0\r\n\r\n");
                            if (closeConnection) {
                                conn->shutdown();
                            }
                        });
                    } else {
                        ioLoop->queueInLoop([conn, closeConnection]() {
                            conn->send(toChunk(makeSseEvent("error", nlohmann::json{{"message", "AI service unavailable"}})));
                            conn->send("0\r\n\r\n");
                            if (closeConnection) {
                                conn->shutdown();
                            }
                        });
                    }
                }
            }
        } 
        catch (const std::exception& ex) 
        {
            ioLoop->queueInLoop([conn, closeConnection, msg = std::string(ex.what())]() {
                conn->send(toChunk(makeSseEvent("error", nlohmann::json{{"message", std::string("invalid json: ") + msg}})));
                conn->send("0\r\n\r\n");
                if (closeConnection) {
                    conn->shutdown();
                }
            });
        }
    });
}

void HttpServer::sendResponse(const TcpConnectionPtr& conn, HttpResponse& resp) 
{
    Buffer buffer;
    resp.appendToBuffer(&buffer);
    std::string data = buffer.retrieveAllAsString();
    conn->send(data);
    if (resp.closeConnection()) 
    {
        conn->shutdown();
    }
}

void HttpServer::sendError(const TcpConnectionPtr& conn, HttpStatusCode code, const std::string& msg) 
{
    HttpResponse resp(true);
    resp.setStatusCode(code);
    resp.setStatusMessage(msg);
    resp.setContentType("text/plain; charset=utf-8");
    resp.setBody(msg);
    sendResponse(conn, resp);
}

HttpContext& HttpServer::contextFor(const TcpConnectionPtr& conn) 
{
    std::lock_guard<std::mutex> lock(contextMutex_);
    return contexts_[conn->name()];
}

void HttpServer::removeContext(const TcpConnectionPtr& conn) 
{
    std::lock_guard<std::mutex> lock(contextMutex_);
    contexts_.erase(conn->name());
}
