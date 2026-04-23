#include "HttpServer.h"

#include <algorithm>
#include <cctype>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <functional>
#include <utility>
#include <vector>

#include <nlohmann/json.hpp>

#include "Buffer.h"
#include "Logger.h"

namespace {
constexpr size_t kSseChunkBytes = 48;
constexpr size_t kDefaultConversationLoadLimit = 0;
constexpr size_t kDefaultModelHistoryLimit = 16;

std::string trimCopy(const std::string& value)
{
    const auto start = value.find_first_not_of(" \t\r\n");
    if (start == std::string::npos) {
        return "";
    }
    const auto end = value.find_last_not_of(" \t\r\n");
    return value.substr(start, end - start + 1);
}

std::string lowerCopy(const std::string& value)
{
    std::string out = value;
    std::transform(out.begin(),
                   out.end(),
                   out.begin(),
                   [](unsigned char ch) { return static_cast<char>(std::tolower(ch)); });
    return out;
}

HttpStatusCode statusForPersistenceFailure(const std::string& message)
{
    const std::string normalized = lowerCopy(message);
    if (normalized.find("missing token") != std::string::npos ||
        normalized.find("invalid token") != std::string::npos ||
        normalized.find("invalid username or password") != std::string::npos) {
        return HttpStatusCode::k401Unauthorized;
    }
    if (normalized.find("conversation not found") != std::string::npos) {
        return HttpStatusCode::k404NotFound;
    }
    if (normalized.find("username already exists") != std::string::npos) {
        return HttpStatusCode::k409Conflict;
    }
    if (normalized.find("database unavailable") != std::string::npos ||
        normalized.find("mysql") != std::string::npos ||
        normalized.find("connection pool") != std::string::npos ||
        normalized.find("access denied") != std::string::npos ||
        normalized.find("can't connect") != std::string::npos ||
        normalized.find("cannot connect") != std::string::npos) {
        return HttpStatusCode::k503ServiceUnavailable;
    }
    if (normalized.find("required") != std::string::npos ||
        normalized.find("too long") != std::string::npos ||
        normalized.find("at least") != std::string::npos ||
        normalized.find("invalid conversation") != std::string::npos) {
        return HttpStatusCode::k400BadRequest;
    }
    return HttpStatusCode::k500InternalServerError;
}

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

size_t nextUtf8Boundary(const std::string& s, size_t from, size_t chunkBytes)
{
    size_t next = std::min(s.size(), from + chunkBytes);
    while (next < s.size() && (static_cast<unsigned char>(s[next]) & 0xC0) == 0x80) {
        ++next;
    }
    return next;
}

nlohmann::json toJsonHistory(const std::vector<OpenAIClient::ChatMessage>& messages)
{
    nlohmann::json history = nlohmann::json::array();
    for (const auto& message : messages) {
        history.push_back({{"role", message.role}, {"content", message.content}});
    }
    return history;
}

nlohmann::json toJsonConversations(
    const std::vector<ChatPersistenceService::ConversationSummary>& conversations)
{
    nlohmann::json items = nlohmann::json::array();
    for (const auto& conversation : conversations) {
        items.push_back({
            {"id", conversation.id},
            {"title", conversation.title},
            {"preview", conversation.preview},
            {"updated_at", conversation.updatedAt},
            {"message_count", conversation.messageCount}
        });
    }
    return items;
}

void appendConversationPayload(nlohmann::json& payload,
                               int64_t activeConversationId,
                               const std::string& activeConversationTitle,
                               const std::vector<ChatPersistenceService::ConversationSummary>& conversations,
                               const std::vector<OpenAIClient::ChatMessage>& history)
{
    payload["active_conversation_id"] = activeConversationId;
    payload["active_conversation_title"] = activeConversationTitle;
    payload["conversations"] = toJsonConversations(conversations);
    payload["history"] = toJsonHistory(history);
}

void streamCachedAnswer(const TcpConnectionPtr& conn, const std::string& answer)
{
    size_t pos = 0;
    while (pos < answer.size()) {
        const size_t next = nextUtf8Boundary(answer, pos, kSseChunkBytes);
        conn->send(toChunk(makeSseEvent("delta", nlohmann::json{{"content", answer.substr(pos, next - pos)}})));
        pos = next;
    }
}

bool tryParseInt64(const std::string& text, int64_t* value)
{
    const std::string trimmed = trimCopy(text);
    if (trimmed.empty()) {
        return false;
    }

    char* end = nullptr;
    const long long parsed = std::strtoll(trimmed.c_str(), &end, 10);
    if (end == trimmed.c_str() || *end != '\0') {
        return false;
    }
    if (value != nullptr) {
        *value = static_cast<int64_t>(parsed);
    }
    return true;
}

std::string queryValue(const HttpRequest& req, const std::string& key)
{
    const std::string query = req.query();
    size_t start = 0;
    while (start <= query.size()) {
        const size_t end = query.find('&', start);
        const std::string pair = query.substr(start, end == std::string::npos ? std::string::npos : end - start);
        const size_t eq = pair.find('=');
        const std::string currentKey = pair.substr(0, eq);
        if (currentKey == key) {
            if (eq == std::string::npos) {
                return "";
            }
            return pair.substr(eq + 1);
        }
        if (end == std::string::npos) {
            break;
        }
        start = end + 1;
    }
    return "";
}

bool extractConversationId(const HttpRequest& req, int64_t* conversationId, std::string* errorMessage)
{
    const std::string raw = queryValue(req, "conversation_id");
    if (raw.empty()) {
        return true;
    }

    int64_t parsed = 0;
    if (!tryParseInt64(raw, &parsed) || parsed <= 0) {
        if (errorMessage != nullptr) {
            *errorMessage = "invalid conversation id";
        }
        return false;
    }

    if (conversationId != nullptr) {
        *conversationId = parsed;
    }
    return true;
}

bool extractConversationId(const nlohmann::json& payload, int64_t* conversationId, std::string* errorMessage)
{
    auto it = payload.find("conversation_id");
    if (it == payload.end() || it->is_null()) {
        return true;
    }

    int64_t parsed = 0;
    if (it->is_number_integer() || it->is_number_unsigned()) {
        parsed = it->get<int64_t>();
    } else if (it->is_string()) {
        if (!tryParseInt64(it->get<std::string>(), &parsed)) {
            if (errorMessage != nullptr) {
                *errorMessage = "invalid conversation id";
            }
            return false;
        }
    } else {
        if (errorMessage != nullptr) {
            *errorMessage = "invalid conversation id";
        }
        return false;
    }

    if (parsed < 0) {
        if (errorMessage != nullptr) {
            *errorMessage = "invalid conversation id";
        }
        return false;
    }

    if (conversationId != nullptr) {
        *conversationId = parsed;
    }
    return true;
}

std::string mergeWarning(const std::string& primary, const std::string& secondary)
{
    if (!secondary.empty()) {
        return secondary;
    }
    if (primary == "ok") {
        return "";
    }
    return primary;
}
}

HttpServer::HttpServer(EventLoop* loop,
                       const InetAddress& addr,
                       const std::string& name,
                       TaskExecutor& bizExecutor,
                       TaskExecutor& dbExecutor,
                       OpenAIClient& aiClient,
                       KamaCache::KLfuCache<std::string, std::string>& cache,
                       ChatPersistenceService& persistence,
                       const std::string& staticDir)
    : server_(loop, addr, name)
    , staticHandler_(staticDir)
    , bizExecutor_(bizExecutor)
    , dbExecutor_(dbExecutor)
    , aiClient_(aiClient)
    , cache_(cache)
    , persistence_(persistence)
    , historyLoadLimit_(kDefaultConversationLoadLimit)
    , modelHistoryLimit_(kDefaultModelHistoryLimit)
{
    server_.setConnectionCallback(
        std::bind(&HttpServer::onConnection, this, std::placeholders::_1));
    server_.setMessageCallback(
        std::bind(&HttpServer::onMessage, this, std::placeholders::_1, std::placeholders::_2, std::placeholders::_3));

    router_.setNotFoundHandler([this](const HttpRequest& req, HttpResponse& resp) {
        staticHandler_.handle(req.path(), resp);
    });
}

void HttpServer::start()
{
    server_.start();
}

void HttpServer::onConnection(const TcpConnectionPtr& conn)
{
    if (conn->connected()) {
        LOG_INFO << "New HTTP connection from " << conn->peerAddress().toIpPort();
        std::lock_guard<std::mutex> lock(contextMutex_);
        contexts_.emplace(conn->name(), HttpContext());
    } else {
        LOG_INFO << "Connection closed " << conn->peerAddress().toIpPort();
        removeContext(conn);
    }
}

void HttpServer::onMessage(const TcpConnectionPtr& conn, Buffer* buf, Timestamp time)
{
    (void)time;
    auto& ctx = contextFor(conn);
    if (!ctx.parseRequest(buf)) {
        sendError(conn, HttpStatusCode::k400BadRequest, "Bad Request");
        return;
    }

    const size_t kMaxBodySize = 4 * 1024 * 1024;
    if (ctx.request().body().size() > kMaxBodySize) {
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
    const bool closeConnection = !req.keepAlive();

    if (req.method() == HttpRequest::Method::kPost && req.path() == "/api/auth/register") {
        handleAuthAsync(conn, req, closeConnection, true);
        return;
    }
    if (req.method() == HttpRequest::Method::kPost && req.path() == "/api/auth/login") {
        handleAuthAsync(conn, req, closeConnection, false);
        return;
    }
    if (req.method() == HttpRequest::Method::kPost && req.path() == "/api/auth/logout") {
        handleLogoutAsync(conn, req, closeConnection);
        return;
    }
    if (req.method() == HttpRequest::Method::kGet && req.path() == "/api/me") {
        handleSessionStateAsync(conn, req, closeConnection);
        return;
    }
    if (req.method() == HttpRequest::Method::kGet && req.path() == "/api/history") {
        handleHistoryAsync(conn, req, closeConnection);
        return;
    }
    if (req.method() == HttpRequest::Method::kPost && req.path() == "/api/chat") {
        handleChatAsync(conn, req, closeConnection);
        return;
    }

    if (req.method() == HttpRequest::Method::kGet || req.method() == HttpRequest::Method::kPost) {
        HttpResponse resp(closeConnection);
        if (!router_.route(req, resp)) {
            resp.setStatusCode(HttpStatusCode::k404NotFound);
            resp.setStatusMessage("Not Found");
            resp.setContentType("text/plain; charset=utf-8");
            resp.setBody("404 Not Found");
        }
        sendResponse(conn, resp);
    } else {
        sendError(conn, HttpStatusCode::k405MethodNotAllowed, "Method Not Allowed");
    }
}

void HttpServer::handleAuthAsync(const TcpConnectionPtr& conn,
                                 const HttpRequest& req,
                                 bool closeConnection,
                                 bool registerMode)
{
    nlohmann::json jsonReq;
    try {
        jsonReq = nlohmann::json::parse(req.body());
    } catch (const std::exception& ex) {
        sendJson(conn,
                 closeConnection,
                 HttpStatusCode::k400BadRequest,
                 nlohmann::json{{"ok", false}, {"message", std::string("invalid json: ") + ex.what()}});
        return;
    }

    if (!jsonReq.contains("username") || !jsonReq["username"].is_string() ||
        !jsonReq.contains("password") || !jsonReq["password"].is_string()) {
        sendJson(conn,
                 closeConnection,
                 HttpStatusCode::k400BadRequest,
                 nlohmann::json{{"ok", false}, {"message", "username and password are required"}});
        return;
    }

    const std::string username = jsonReq["username"].get<std::string>();
    const std::string password = jsonReq["password"].get<std::string>();
    EventLoop* ioLoop = conn->getLoop();

    dbExecutor_.submit([this, conn, ioLoop, closeConnection, registerMode, username, password]() {
        const auto result = registerMode
                                ? persistence_.registerUser(username, password, historyLoadLimit_)
                                : persistence_.loginUser(username, password, historyLoadLimit_);

        nlohmann::json payload{
            {"ok", result.ok},
            {"message", result.message}
        };
        HttpStatusCode status = registerMode ? HttpStatusCode::k201Created : HttpStatusCode::k200Ok;
        if (result.ok) {
            payload["username"] = result.username;
            payload["token"] = result.token;
            appendConversationPayload(payload,
                                      result.activeConversationId,
                                      result.activeConversationTitle,
                                      result.conversations,
                                      result.history);
        } else {
            status = statusForPersistenceFailure(result.message);
        }

        ioLoop->queueInLoop([this, conn, closeConnection, status, payload = std::move(payload)]() mutable {
            sendJson(conn, closeConnection, status, payload);
        });
    });
}

void HttpServer::handleSessionStateAsync(const TcpConnectionPtr& conn,
                                         const HttpRequest& req,
                                         bool closeConnection)
{
    const std::string token = extractBearerToken(req);
    if (token.empty()) {
        sendJson(conn,
                 closeConnection,
                 HttpStatusCode::k401Unauthorized,
                 nlohmann::json{{"ok", false}, {"message", "missing token"}});
        return;
    }

    EventLoop* ioLoop = conn->getLoop();
    dbExecutor_.submit([this, conn, ioLoop, closeConnection, token]() {
        const auto session = persistence_.loadSessionState(token, historyLoadLimit_);
        nlohmann::json payload{
            {"ok", session.ok && session.authenticated},
            {"message", session.message}
        };

        HttpStatusCode status = HttpStatusCode::k200Ok;
        if (session.ok && session.authenticated) {
            payload["username"] = session.username;
            appendConversationPayload(payload,
                                      session.activeConversationId,
                                      session.activeConversationTitle,
                                      session.conversations,
                                      session.history);
        } else {
            status = statusForPersistenceFailure(session.message);
        }

        ioLoop->queueInLoop([this, conn, closeConnection, status, payload = std::move(payload)]() mutable {
            sendJson(conn, closeConnection, status, payload);
        });
    });
}

void HttpServer::handleHistoryAsync(const TcpConnectionPtr& conn,
                                    const HttpRequest& req,
                                    bool closeConnection)
{
    const std::string token = extractBearerToken(req);
    if (token.empty()) {
        sendJson(conn,
                 closeConnection,
                 HttpStatusCode::k401Unauthorized,
                 nlohmann::json{{"ok", false}, {"message", "missing token"}});
        return;
    }

    int64_t conversationId = 0;
    std::string parseError;
    if (!extractConversationId(req, &conversationId, &parseError)) {
        sendJson(conn,
                 closeConnection,
                 HttpStatusCode::k400BadRequest,
                 nlohmann::json{{"ok", false}, {"message", parseError}});
        return;
    }

    EventLoop* ioLoop = conn->getLoop();
    dbExecutor_.submit([this, conn, ioLoop, closeConnection, token, conversationId]() {
        const auto session = persistence_.loadSessionState(token, historyLoadLimit_, conversationId);
        nlohmann::json payload{
            {"ok", session.ok && session.authenticated},
            {"message", session.message}
        };

        HttpStatusCode status = HttpStatusCode::k200Ok;
        if (session.ok && session.authenticated) {
            payload["username"] = session.username;
            appendConversationPayload(payload,
                                      session.activeConversationId,
                                      session.activeConversationTitle,
                                      session.conversations,
                                      session.history);
        } else {
            status = statusForPersistenceFailure(session.message);
        }

        ioLoop->queueInLoop([this, conn, closeConnection, status, payload = std::move(payload)]() mutable {
            sendJson(conn, closeConnection, status, payload);
        });
    });
}

void HttpServer::handleLogoutAsync(const TcpConnectionPtr& conn,
                                   const HttpRequest& req,
                                   bool closeConnection)
{
    const std::string token = extractBearerToken(req);
    if (token.empty()) {
        sendJson(conn,
                 closeConnection,
                 HttpStatusCode::k401Unauthorized,
                 nlohmann::json{{"ok", false}, {"message", "missing token"}});
        return;
    }

    EventLoop* ioLoop = conn->getLoop();
    dbExecutor_.submit([this, conn, ioLoop, closeConnection, token]() {
        std::string errorMessage;
        const bool ok = persistence_.logout(token, &errorMessage);
        const HttpStatusCode status = ok ? HttpStatusCode::k200Ok : statusForPersistenceFailure(errorMessage);
        nlohmann::json payload{
            {"ok", ok},
            {"message", ok ? "logged out" : errorMessage}
        };

        ioLoop->queueInLoop([this, conn, closeConnection, status, payload = std::move(payload)]() mutable {
            sendJson(conn, closeConnection, status, payload);
        });
    });
}

void HttpServer::handleChatAsync(const TcpConnectionPtr& conn,
                                 const HttpRequest& req,
                                 bool closeConnection)
{
    nlohmann::json jsonReq;
    try {
        jsonReq = nlohmann::json::parse(req.body());
    } catch (const std::exception& ex) {
        sendJson(conn,
                 closeConnection,
                 HttpStatusCode::k400BadRequest,
                 nlohmann::json{{"ok", false}, {"message", std::string("invalid json: ") + ex.what()}});
        return;
    }

    if (!jsonReq.contains("message") || !jsonReq["message"].is_string()) {
        sendJson(conn,
                 closeConnection,
                 HttpStatusCode::k400BadRequest,
                 nlohmann::json{{"ok", false}, {"message", "message required"}});
        return;
    }

    const std::string userMessage = trimCopy(jsonReq["message"].get<std::string>());
    if (userMessage.empty()) {
        sendJson(conn,
                 closeConnection,
                 HttpStatusCode::k400BadRequest,
                 nlohmann::json{{"ok", false}, {"message", "message required"}});
        return;
    }

    int64_t requestedConversationId = 0;
    std::string parseError;
    if (!extractConversationId(jsonReq, &requestedConversationId, &parseError)) {
        sendJson(conn,
                 closeConnection,
                 HttpStatusCode::k400BadRequest,
                 nlohmann::json{{"ok", false}, {"message", parseError}});
        return;
    }

    const std::string token = extractBearerToken(req);
    if (token.empty()) {
        sendJson(conn,
                 closeConnection,
                 HttpStatusCode::k401Unauthorized,
                 nlohmann::json{{"ok", false}, {"message", "missing token"}});
        return;
    }

    EventLoop* ioLoop = conn->getLoop();
    dbExecutor_.submit([this, conn, ioLoop, closeConnection, token, userMessage, requestedConversationId]() {
        auto session = persistence_.loadSessionState(token,
                                                     historyLoadLimit_,
                                                     requestedConversationId > 0 ? requestedConversationId : 0);
        if (!session.ok || !session.authenticated) {
            const HttpStatusCode status = statusForPersistenceFailure(session.message);
            ioLoop->queueInLoop([this, conn, closeConnection, status, msg = session.message]() {
                sendJson(conn, closeConnection, status, nlohmann::json{{"ok", false}, {"message", msg}});
            });
            return;
        }

        if (requestedConversationId <= 0) {
            session.activeConversationId = 0;
            session.activeConversationTitle.clear();
            session.history.clear();
        }

        auto modelMessages = session.history;
        if (modelMessages.size() > modelHistoryLimit_) {
            modelMessages.erase(modelMessages.begin(), modelMessages.end() - modelHistoryLimit_);
        }
        modelMessages.push_back({"user", userMessage});

        const std::string cacheKey =
            std::to_string(session.userId) + ":" + std::to_string(requestedConversationId) + ":" +
            toJsonHistory(modelMessages).dump();
        std::string cachedAnswer;

        ioLoop->queueInLoop([conn, closeConnection]() {
            std::string headers =
                "HTTP/1.1 200 OK\r\n"
                "Content-Type: text/event-stream; charset=utf-8\r\n"
                "Cache-Control: no-cache\r\n"
                "X-Accel-Buffering: no\r\n"
                "Transfer-Encoding: chunked\r\n";
            headers += closeConnection ? "Connection: close\r\n\r\n" : "Connection: keep-alive\r\n\r\n";
            conn->send(headers);
            conn->send(toChunk(makeSseEvent("status", nlohmann::json{{"message", "已连接，正在处理请求..."}})));
        });

        if (cache_.get(cacheKey, cachedAnswer)) {
            LOG_INFO << "Chat cache hit for user " << session.username;

            auto fullHistory = session.history;
            fullHistory.push_back({"user", userMessage});
            fullHistory.push_back({"assistant", cachedAnswer});

            std::string persistError;
            const auto saveResult =
                persistence_.saveConversation(session.userId,
                                              requestedConversationId,
                                              userMessage,
                                              cachedAnswer,
                                              &persistError);
            const bool persisted = saveResult.ok;
            const std::string warning = mergeWarning(saveResult.message, persistError);

            ioLoop->queueInLoop([conn,
                                 closeConnection,
                                 cachedAnswer,
                                 history = std::move(fullHistory),
                                 persisted,
                                 warning,
                                 saveResult]() mutable {
                conn->send(toChunk(makeSseEvent("status", nlohmann::json{{"message", "命中缓存，正在输出..."}})));
                streamCachedAnswer(conn, cachedAnswer);

                nlohmann::json donePayload{
                    {"cached", true},
                    {"persisted", persisted},
                    {"history", toJsonHistory(history)},
                    {"conversation_id", saveResult.conversationId},
                    {"conversation_title", saveResult.conversationTitle},
                    {"conversations", toJsonConversations(saveResult.conversations)}
                };
                if (!warning.empty()) {
                    donePayload["warning"] = warning;
                }
                conn->send(toChunk(makeSseEvent("done", donePayload)));
                conn->send("0\r\n\r\n");
                if (closeConnection) {
                    conn->shutdown();
                }
            });
            return;
        }

        bizExecutor_.submit([this,
                             conn,
                             ioLoop,
                             closeConnection,
                             session = std::move(session),
                             userMessage,
                             requestedConversationId,
                             modelMessages = std::move(modelMessages),
                             cacheKey]() mutable {
            ioLoop->queueInLoop([conn]() {
                conn->send(toChunk(makeSseEvent("status", nlohmann::json{{"message", "模型思考中..."}})));
            });

            auto answer = aiClient_.chatCompletionStream(
                modelMessages,
                [ioLoop, conn](const std::string& delta) {
                    if (delta.empty()) {
                        return;
                    }
                    ioLoop->queueInLoop([conn, delta]() {
                        conn->send(toChunk(makeSseEvent("delta", nlohmann::json{{"content", delta}})));
                    });
                });

            if (!answer.has_value()) {
                ioLoop->queueInLoop([conn, closeConnection]() {
                    conn->send(toChunk(makeSseEvent("error", nlohmann::json{{"message", "AI service unavailable"}})));
                    conn->send("0\r\n\r\n");
                    if (closeConnection) {
                        conn->shutdown();
                    }
                });
                return;
            }

            cache_.put(cacheKey, *answer);
            auto fullHistory = session.history;
            fullHistory.push_back({"user", userMessage});
            fullHistory.push_back({"assistant", *answer});

            dbExecutor_.submit([this,
                                conn,
                                ioLoop,
                                closeConnection,
                                userId = session.userId,
                                userMessage,
                                answer = *answer,
                                requestedConversationId,
                                history = std::move(fullHistory)]() mutable {
                std::string persistError;
                const auto saveResult =
                    persistence_.saveConversation(userId,
                                                  requestedConversationId,
                                                  userMessage,
                                                  answer,
                                                  &persistError);
                const bool persisted = saveResult.ok;
                const std::string warning = mergeWarning(saveResult.message, persistError);

                ioLoop->queueInLoop([conn,
                                     closeConnection,
                                     history = std::move(history),
                                     persisted,
                                     warning,
                                     saveResult]() mutable {
                    nlohmann::json donePayload{
                        {"cached", false},
                        {"persisted", persisted},
                        {"history", toJsonHistory(history)},
                        {"conversation_id", saveResult.conversationId},
                        {"conversation_title", saveResult.conversationTitle},
                        {"conversations", toJsonConversations(saveResult.conversations)}
                    };
                    if (!warning.empty()) {
                        donePayload["warning"] = warning;
                    }
                    conn->send(toChunk(makeSseEvent("done", donePayload)));
                    conn->send("0\r\n\r\n");
                    if (closeConnection) {
                        conn->shutdown();
                    }
                });
            });
        });
    });
}

void HttpServer::sendResponse(const TcpConnectionPtr& conn, HttpResponse& resp)
{
    Buffer buffer;
    resp.appendToBuffer(&buffer);
    conn->send(buffer.retrieveAllAsString());
    if (resp.closeConnection()) {
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

void HttpServer::sendJson(const TcpConnectionPtr& conn,
                          bool closeConnection,
                          HttpStatusCode code,
                          const nlohmann::json& payload)
{
    HttpResponse resp(closeConnection);
    resp.setStatusCode(code);
    resp.setStatusMessage(HttpResponse::reasonPhrase(code));
    resp.setContentType("application/json; charset=utf-8");
    resp.setBody(payload.dump());
    sendResponse(conn, resp);
}

std::string HttpServer::extractBearerToken(const HttpRequest& req) const
{
    const std::string header = trimCopy(req.getHeader("authorization"));
    const std::string prefix = "bearer ";
    if (header.size() < prefix.size()) {
        return "";
    }

    const std::string lowered = lowerCopy(header.substr(0, prefix.size()));
    if (lowered != prefix) {
        return "";
    }
    return trimCopy(header.substr(prefix.size()));
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
