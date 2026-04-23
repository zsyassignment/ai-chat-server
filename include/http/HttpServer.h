#pragma once

#include <mutex>
#include <string>
#include <unordered_map>

#include <nlohmann/json_fwd.hpp>

#include "ChatPersistenceService.h"
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
               TaskExecutor& bizExecutor,
               TaskExecutor& dbExecutor,
               OpenAIClient& aiClient,
               KamaCache::KLfuCache<std::string, std::string>& cache,
               ChatPersistenceService& persistence,
               const std::string& staticDir);

    void setThreadNum(int numThreads) { server_.setThreadNum(numThreads); }
    void start();

private:
    void onConnection(const TcpConnectionPtr& conn);
    void onMessage(const TcpConnectionPtr& conn, Buffer* buf, Timestamp time);

    void handleRequest(const TcpConnectionPtr& conn, HttpRequest& req);
    void handleAuthAsync(const TcpConnectionPtr& conn,
                         const HttpRequest& req,
                         bool closeConnection,
                         bool registerMode);
    void handleSessionStateAsync(const TcpConnectionPtr& conn, const HttpRequest& req, bool closeConnection);
    void handleHistoryAsync(const TcpConnectionPtr& conn, const HttpRequest& req, bool closeConnection);
    void handleLogoutAsync(const TcpConnectionPtr& conn, const HttpRequest& req, bool closeConnection);
    void handleChatAsync(const TcpConnectionPtr& conn, const HttpRequest& req, bool closeConnection);
    void sendResponse(const TcpConnectionPtr& conn, HttpResponse& resp);
    void sendError(const TcpConnectionPtr& conn, HttpStatusCode code, const std::string& msg);
    void sendJson(const TcpConnectionPtr& conn,
                  bool closeConnection,
                  HttpStatusCode code,
                  const nlohmann::json& payload);
    std::string extractBearerToken(const HttpRequest& req) const;

    HttpContext& contextFor(const TcpConnectionPtr& conn);
    void removeContext(const TcpConnectionPtr& conn);

    TcpServer server_;
    HttpRouter router_;
    StaticFileHandler staticHandler_;
    TaskExecutor& bizExecutor_;
    TaskExecutor& dbExecutor_;
    OpenAIClient& aiClient_;
    KamaCache::KLfuCache<std::string, std::string>& cache_;
    ChatPersistenceService& persistence_;
    size_t historyLoadLimit_;
    size_t modelHistoryLimit_;

    std::unordered_map<std::string, HttpContext> contexts_;
    std::mutex contextMutex_;
};
