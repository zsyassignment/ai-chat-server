#pragma once

#include <mutex>
#include <string>
#include <unordered_map>

#include "HttpContext.h"
#include "HttpRouter.h"
#include "StaticFileHandler.h"
#include "TaskExecutor.h"
#include "TcpServer.h"
#include "Timestamp.h"
#include "openai.hpp"
#include "LFU.h"

class HttpServer {
public:
    HttpServer(EventLoop* loop,
               const InetAddress& addr,
               const std::string& name,
               TaskExecutor& executor,
               OpenAIClient& aiClient,
               KamaCache::KLfuCache<std::string, std::string>& cache,
               const std::string& staticDir);

    void setThreadNum(int numThreads) { server_.setThreadNum(numThreads); }
    void start();

private:
    void onConnection(const TcpConnectionPtr& conn);
    void onMessage(const TcpConnectionPtr& conn, Buffer* buf, Timestamp time);

    void handleRequest(const TcpConnectionPtr& conn, HttpRequest& req);
    void handleChatAsync(const TcpConnectionPtr& conn, const HttpRequest& req, bool closeConnection);
    void sendResponse(const TcpConnectionPtr& conn, HttpResponse& resp);
    void sendError(const TcpConnectionPtr& conn, HttpStatusCode code, const std::string& msg);

    HttpContext& contextFor(const TcpConnectionPtr& conn);
    void removeContext(const TcpConnectionPtr& conn);

    TcpServer server_;
    HttpRouter router_;
    StaticFileHandler staticHandler_;
    TaskExecutor& executor_;
    OpenAIClient& aiClient_;
    KamaCache::KLfuCache<std::string, std::string>& cache_;

    std::unordered_map<std::string, HttpContext> contexts_;
    std::mutex contextMutex_;
};
