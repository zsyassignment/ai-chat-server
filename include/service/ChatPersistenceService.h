#pragma once

#include <cstdint>
#include <string>
#include <vector>

#include "MySqlConnectionPool.h"
#include "openai.hpp"

class ChatPersistenceService {
public:
    struct ConversationSummary {
        int64_t id = 0;
        std::string title;
        std::string preview;
        std::string updatedAt;
        size_t messageCount = 0;
    };

    struct SessionState {
        bool ok = false;
        bool authenticated = false;
        int64_t userId = 0;
        std::string username;
        std::string token;
        std::string message;
        int64_t activeConversationId = 0;
        std::string activeConversationTitle;
        std::vector<ConversationSummary> conversations;
        std::vector<OpenAIClient::ChatMessage> history;
    };

    struct AuthResult {
        bool ok = false;
        std::string username;
        std::string token;
        std::string message;
        int64_t activeConversationId = 0;
        std::string activeConversationTitle;
        std::vector<ConversationSummary> conversations;
        std::vector<OpenAIClient::ChatMessage> history;
    };

    struct SaveConversationResult {
        bool ok = false;
        std::string message;
        int64_t conversationId = 0;
        std::string conversationTitle;
        std::vector<ConversationSummary> conversations;
    };

    explicit ChatPersistenceService(MySqlConnectionPool::Config config);

    bool initialize();
    bool ready() const { return ready_; }
    const std::string& initError() const { return initError_; }

    AuthResult registerUser(const std::string& username, const std::string& password, size_t historyLimit);
    AuthResult loginUser(const std::string& username, const std::string& password, size_t historyLimit);
    SessionState loadSessionState(const std::string& token,
                                  size_t historyLimit,
                                  int64_t requestedConversationId = 0);
    bool logout(const std::string& token, std::string* errorMessage = nullptr);
    SaveConversationResult saveConversation(int64_t userId,
                                            int64_t requestedConversationId,
                                            const std::string& userMessage,
                                            const std::string& assistantMessage,
                                            std::string* errorMessage = nullptr);

private:
    bool ensureSchema(std::string* errorMessage);

    std::vector<ConversationSummary> loadConversationSummaries(int64_t userId, std::string* errorMessage);
    std::vector<ConversationSummary> loadConversationSummaries(MYSQL* connection,
                                                               int64_t userId,
                                                               std::string* errorMessage);

    std::vector<OpenAIClient::ChatMessage> loadConversationHistory(int64_t conversationId,
                                                                   size_t historyLimit,
                                                                   std::string* errorMessage);
    std::vector<OpenAIClient::ChatMessage> loadConversationHistory(MYSQL* connection,
                                                                   int64_t conversationId,
                                                                   size_t historyLimit,
                                                                   std::string* errorMessage);

    MySqlConnectionPool pool_;
    bool ready_ = false;
    std::string initError_;
};
