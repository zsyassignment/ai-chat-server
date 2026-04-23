#include "ChatPersistenceService.h"

#include <algorithm>
#include <cctype>
#include <memory>
#include <sstream>
#include <stdexcept>
#include <tuple>
#include <utility>
#include <vector>

#include <openssl/rand.h>
#include <openssl/sha.h>

namespace {
using MySqlResultPtr = std::unique_ptr<MYSQL_RES, decltype(&mysql_free_result)>;
constexpr size_t kConversationSummaryLimit = 64;

std::string trimCopy(const std::string& value)
{
    const auto start = value.find_first_not_of(" \t\r\n");
    if (start == std::string::npos) {
        return "";
    }
    const auto end = value.find_last_not_of(" \t\r\n");
    return value.substr(start, end - start + 1);
}

std::string collapseWhitespace(const std::string& value)
{
    std::string out;
    out.reserve(value.size());
    bool previousSpace = false;
    for (unsigned char ch : value) {
        if (std::isspace(ch) != 0) {
            if (!previousSpace && !out.empty()) {
                out.push_back(' ');
            }
            previousSpace = true;
            continue;
        }
        previousSpace = false;
        out.push_back(static_cast<char>(ch));
    }
    return trimCopy(out);
}

std::string toHex(const unsigned char* data, size_t size)
{
    static const char* kHex = "0123456789abcdef";
    std::string out;
    out.reserve(size * 2);
    for (size_t i = 0; i < size; ++i) {
        out.push_back(kHex[(data[i] >> 4) & 0x0F]);
        out.push_back(kHex[data[i] & 0x0F]);
    }
    return out;
}

std::string utf8mb4Literal(const std::string& value)
{
    if (value.empty()) {
        return "_utf8mb4''";
    }
    return "CONVERT(0x" +
           toHex(reinterpret_cast<const unsigned char*>(value.data()), value.size()) +
           " USING utf8mb4)";
}

std::string randomHex(size_t bytes)
{
    std::string buffer(bytes, '\0');
    if (RAND_bytes(reinterpret_cast<unsigned char*>(&buffer[0]), static_cast<int>(buffer.size())) != 1) {
        throw std::runtime_error("RAND_bytes failed");
    }
    return toHex(reinterpret_cast<const unsigned char*>(buffer.data()), buffer.size());
}

std::string sha256Hex(const std::string& value)
{
    unsigned char digest[SHA256_DIGEST_LENGTH] = {0};
    SHA256(reinterpret_cast<const unsigned char*>(value.data()), value.size(), digest);
    return toHex(digest, sizeof(digest));
}

std::string quoteIdentifier(const std::string& value)
{
    std::string out;
    out.reserve(value.size() + 2);
    out.push_back('`');
    for (char ch : value) {
        if (ch == '`') {
            out.push_back('`');
        }
        out.push_back(ch);
    }
    out.push_back('`');
    return out;
}

std::string escapeString(MYSQL* connection, const std::string& value)
{
    std::string escaped(value.size() * 2 + 1, '\0');
    const unsigned long length = mysql_real_escape_string(connection,
                                                          &escaped[0],
                                                          value.c_str(),
                                                          value.size());
    escaped.resize(length);
    return escaped;
}

bool executeStatement(MYSQL* connection, const std::string& sql, std::string* errorMessage)
{
    if (mysql_query(connection, sql.c_str()) != 0) {
        if (errorMessage != nullptr) {
            *errorMessage = mysql_error(connection);
        }
        return false;
    }
    return true;
}

MySqlResultPtr executeQuery(MYSQL* connection, const std::string& sql, std::string* errorMessage)
{
    if (mysql_query(connection, sql.c_str()) != 0) {
        if (errorMessage != nullptr) {
            *errorMessage = mysql_error(connection);
        }
        return MySqlResultPtr(nullptr, mysql_free_result);
    }

    MYSQL_RES* rawResult = mysql_store_result(connection);
    if (rawResult == nullptr && mysql_field_count(connection) != 0) {
        if (errorMessage != nullptr) {
            *errorMessage = mysql_error(connection);
        }
        return MySqlResultPtr(nullptr, mysql_free_result);
    }
    return MySqlResultPtr(rawResult, mysql_free_result);
}

std::string readColumn(MYSQL_ROW row, unsigned long* lengths, unsigned int index)
{
    if (row == nullptr || row[index] == nullptr) {
        return "";
    }
    return std::string(row[index], lengths[index]);
}

bool columnExists(MYSQL* connection,
                  const std::string& tableName,
                  const std::string& columnName,
                  std::string* errorMessage)
{
    const std::string sql =
        "SHOW COLUMNS FROM " + quoteIdentifier(tableName) + " LIKE '" +
        escapeString(connection, columnName) + "'";
    auto result = executeQuery(connection, sql, errorMessage);
    if (!result || (errorMessage != nullptr && !errorMessage->empty())) {
        return false;
    }
    return mysql_fetch_row(result.get()) != nullptr;
}

bool indexExists(MYSQL* connection,
                 const std::string& tableName,
                 const std::string& indexName,
                 std::string* errorMessage)
{
    const std::string sql =
        "SHOW INDEX FROM " + quoteIdentifier(tableName) + " WHERE Key_name='" +
        escapeString(connection, indexName) + "'";
    auto result = executeQuery(connection, sql, errorMessage);
    if (!result || (errorMessage != nullptr && !errorMessage->empty())) {
        return false;
    }
    return mysql_fetch_row(result.get()) != nullptr;
}

bool foreignKeyExists(MYSQL* connection,
                      const std::string& tableName,
                      const std::string& constraintName,
                      std::string* errorMessage)
{
    const std::string sql =
        "SELECT CONSTRAINT_NAME FROM INFORMATION_SCHEMA.REFERENTIAL_CONSTRAINTS "
        "WHERE CONSTRAINT_SCHEMA = DATABASE() "
        "AND TABLE_NAME='" + escapeString(connection, tableName) + "' "
        "AND CONSTRAINT_NAME='" + escapeString(connection, constraintName) + "' "
        "LIMIT 1";
    auto result = executeQuery(connection, sql, errorMessage);
    if (!result || (errorMessage != nullptr && !errorMessage->empty())) {
        return false;
    }
    return mysql_fetch_row(result.get()) != nullptr;
}

bool tableHasNullConversationMessages(MYSQL* connection, std::string* errorMessage)
{
    auto result = executeQuery(connection,
                               "SELECT COUNT(*) FROM chat_messages WHERE conversation_id IS NULL",
                               errorMessage);
    if (!result || (errorMessage != nullptr && !errorMessage->empty())) {
        return false;
    }
    MYSQL_ROW row = mysql_fetch_row(result.get());
    if (row == nullptr) {
        return false;
    }
    unsigned long* lengths = mysql_fetch_lengths(result.get());
    return readColumn(row, lengths, 0) != "0";
}

std::string utf8Prefix(const std::string& value, size_t maxBytes)
{
    if (value.size() <= maxBytes) {
        return value;
    }

    size_t end = maxBytes;
    while (end > 0 && (static_cast<unsigned char>(value[end]) & 0xC0) == 0x80) {
        --end;
    }
    if (end == 0) {
        end = maxBytes;
    }
    return value.substr(0, end);
}

std::string buildConversationTitle(const std::string& seed)
{
    std::string title = collapseWhitespace(seed);
    const std::vector<std::string> prefixes = {
        "请问一下",
        "请问",
        "我想问一下",
        "我想问",
        "能不能帮我",
        "可以帮我",
        "帮我",
        "关于",
        "我最近想知道",
        "我最近在学"
    };

    for (const auto& prefix : prefixes) {
        if (title.rfind(prefix, 0) == 0) {
            title = trimCopy(title.substr(prefix.size()));
            break;
        }
    }

    const auto punctuationPos = title.find_first_of("\r\n!?！？。；;");
    if (punctuationPos != std::string::npos && punctuationPos >= 6) {
        title = title.substr(0, punctuationPos);
    }

    title = trimCopy(utf8Prefix(title, 48));
    if (title.empty()) {
        return "新对话";
    }
    return title;
}

std::string buildPreview(const std::string& value)
{
    const std::string normalized = collapseWhitespace(value);
    if (normalized.empty()) {
        return "";
    }
    return utf8Prefix(normalized, 84);
}

bool loadConversationMeta(MYSQL* connection,
                          int64_t userId,
                          int64_t conversationId,
                          std::string* title,
                          std::string* errorMessage)
{
    std::ostringstream sql;
    sql << "SELECT title FROM conversations WHERE id=" << conversationId
        << " AND user_id=" << userId << " LIMIT 1";
    auto result = executeQuery(connection, sql.str(), errorMessage);
    if (!result || (errorMessage != nullptr && !errorMessage->empty())) {
        return false;
    }

    MYSQL_ROW row = mysql_fetch_row(result.get());
    if (row == nullptr) {
        if (errorMessage != nullptr) {
            *errorMessage = "conversation not found";
        }
        return false;
    }

    if (title != nullptr) {
        unsigned long* lengths = mysql_fetch_lengths(result.get());
        *title = readColumn(row, lengths, 0);
    }
    return true;
}

bool migrateLegacyMessages(MYSQL* connection, std::string* errorMessage)
{
    if (!tableHasNullConversationMessages(connection, errorMessage)) {
        return errorMessage == nullptr || errorMessage->empty();
    }

    struct LegacyBatch {
        int64_t userId = 0;
        std::string createdAt;
        std::string updatedAt;
    };

    auto batchesResult = executeQuery(
        connection,
        "SELECT user_id, "
        "DATE_FORMAT(MIN(created_at), '%Y-%m-%d %H:%i:%s'), "
        "DATE_FORMAT(MAX(created_at), '%Y-%m-%d %H:%i:%s') "
        "FROM chat_messages "
        "WHERE conversation_id IS NULL "
        "GROUP BY user_id "
        "ORDER BY user_id ASC",
        errorMessage);
    if (!batchesResult || (errorMessage != nullptr && !errorMessage->empty())) {
        return false;
    }

    std::vector<LegacyBatch> batches;
    MYSQL_ROW row = nullptr;
    while ((row = mysql_fetch_row(batchesResult.get())) != nullptr) {
        unsigned long* lengths = mysql_fetch_lengths(batchesResult.get());
        LegacyBatch batch;
        batch.userId = std::stoll(readColumn(row, lengths, 0));
        batch.createdAt = readColumn(row, lengths, 1);
        batch.updatedAt = readColumn(row, lengths, 2);
        batches.push_back(std::move(batch));
    }

    if (batches.empty()) {
        return true;
    }

    if (!executeStatement(connection, "START TRANSACTION", errorMessage)) {
        return false;
    }

    for (const auto& batch : batches) {
        const std::string title = "History Session " + std::to_string(batch.userId);

        const std::string escapedCreatedAt = escapeString(connection, batch.createdAt);
        const std::string escapedUpdatedAt = escapeString(connection, batch.updatedAt);

        std::ostringstream insertConversationSql;
        insertConversationSql
            << "INSERT INTO conversations(user_id, title, created_at, updated_at) VALUES("
            << batch.userId << ", " << utf8mb4Literal(title) << ", '" << escapedCreatedAt << "', '"
            << escapedUpdatedAt << "')";
        if (!executeStatement(connection, insertConversationSql.str(), errorMessage)) {
            executeStatement(connection, "ROLLBACK", nullptr);
            return false;
        }

        const int64_t conversationId = static_cast<int64_t>(mysql_insert_id(connection));
        std::ostringstream updateSql;
        updateSql << "UPDATE chat_messages SET conversation_id=" << conversationId
                  << " WHERE user_id=" << batch.userId << " AND conversation_id IS NULL";
        if (!executeStatement(connection, updateSql.str(), errorMessage)) {
            executeStatement(connection, "ROLLBACK", nullptr);
            return false;
        }
    }

    if (!executeStatement(connection, "COMMIT", errorMessage)) {
        executeStatement(connection, "ROLLBACK", nullptr);
        return false;
    }
    return true;
}
}

ChatPersistenceService::ChatPersistenceService(MySqlConnectionPool::Config config)
    : pool_(std::move(config))
{
}

bool ChatPersistenceService::initialize()
{
    std::string errorMessage;
    if (!pool_.initialize(&errorMessage)) {
        initError_ = errorMessage;
        ready_ = false;
        return false;
    }

    if (!ensureSchema(&errorMessage)) {
        initError_ = errorMessage;
        ready_ = false;
        return false;
    }

    ready_ = true;
    initError_.clear();
    return true;
}

ChatPersistenceService::AuthResult ChatPersistenceService::registerUser(const std::string& username,
                                                                        const std::string& password,
                                                                        size_t historyLimit)
{
    AuthResult result;
    if (!ready_) {
        result.message = initError_.empty() ? "database unavailable" : initError_;
        return result;
    }

    const std::string normalizedUser = trimCopy(username);
    if (normalizedUser.empty() || password.empty()) {
        result.message = "username and password are required";
        return result;
    }
    if (normalizedUser.size() > 64) {
        result.message = "username too long";
        return result;
    }
    if (password.size() < 6) {
        result.message = "password must be at least 6 characters";
        return result;
    }

    try {
        auto connection = pool_.acquire();
        MYSQL* mysql = connection.get();
        const std::string escapedUser = escapeString(mysql, normalizedUser);
        std::string errorMessage;

        auto existsResult = executeQuery(mysql,
                                         "SELECT id FROM users WHERE username='" + escapedUser + "' LIMIT 1",
                                         &errorMessage);
        if (!errorMessage.empty()) {
            result.message = errorMessage;
            return result;
        }

        if (existsResult && mysql_fetch_row(existsResult.get()) != nullptr) {
            result.message = "username already exists";
            return result;
        }

        const std::string salt = randomHex(16);
        const std::string passwordHash = sha256Hex(salt + ":" + password);
        const std::string token = randomHex(32);

        const std::string insertUserSql =
            "INSERT INTO users(username, password_salt, password_hash, created_at) VALUES('" +
            escapedUser + "', '" + salt + "', '" + passwordHash + "', NOW())";
        if (!executeStatement(mysql, insertUserSql, &errorMessage)) {
            result.message = errorMessage;
            return result;
        }

        const int64_t userId = static_cast<int64_t>(mysql_insert_id(mysql));
        const std::string insertSessionSql =
            "INSERT INTO user_sessions(user_id, token, expires_at, created_at) VALUES(" +
            std::to_string(userId) + ", '" + token + "', DATE_ADD(NOW(), INTERVAL 7 DAY), NOW())";
        if (!executeStatement(mysql, insertSessionSql, &errorMessage)) {
            result.message = errorMessage;
            return result;
        }

        const auto sessionState = loadSessionState(token, historyLimit);
        result.ok = sessionState.ok && sessionState.authenticated;
        result.username = normalizedUser;
        result.token = token;
        result.message = result.ok ? "registered" : sessionState.message;
        result.activeConversationId = sessionState.activeConversationId;
        result.activeConversationTitle = sessionState.activeConversationTitle;
        result.conversations = std::move(sessionState.conversations);
        result.history = std::move(sessionState.history);
        return result;
    } catch (const std::exception& ex) {
        result.message = ex.what();
        return result;
    }
}

ChatPersistenceService::AuthResult ChatPersistenceService::loginUser(const std::string& username,
                                                                     const std::string& password,
                                                                     size_t historyLimit)
{
    AuthResult result;
    if (!ready_) {
        result.message = initError_.empty() ? "database unavailable" : initError_;
        return result;
    }

    const std::string normalizedUser = trimCopy(username);
    if (normalizedUser.empty() || password.empty()) {
        result.message = "username and password are required";
        return result;
    }

    try {
        auto connection = pool_.acquire();
        MYSQL* mysql = connection.get();
        const std::string escapedUser = escapeString(mysql, normalizedUser);
        std::string errorMessage;

        auto userResult = executeQuery(mysql,
                                       "SELECT id, password_salt, password_hash FROM users WHERE username='" +
                                           escapedUser + "' LIMIT 1",
                                       &errorMessage);
        if (!errorMessage.empty()) {
            result.message = errorMessage;
            return result;
        }

        if (!userResult) {
            result.message = "invalid username or password";
            return result;
        }

        MYSQL_ROW row = mysql_fetch_row(userResult.get());
        if (row == nullptr) {
            result.message = "invalid username or password";
            return result;
        }
        unsigned long* lengths = mysql_fetch_lengths(userResult.get());

        const int64_t userId = std::stoll(readColumn(row, lengths, 0));
        const std::string salt = readColumn(row, lengths, 1);
        const std::string passwordHash = readColumn(row, lengths, 2);
        if (sha256Hex(salt + ":" + password) != passwordHash) {
            result.message = "invalid username or password";
            return result;
        }

        const std::string token = randomHex(32);
        const std::string insertSessionSql =
            "INSERT INTO user_sessions(user_id, token, expires_at, created_at) VALUES(" +
            std::to_string(userId) + ", '" + token + "', DATE_ADD(NOW(), INTERVAL 7 DAY), NOW())";
        if (!executeStatement(mysql, insertSessionSql, &errorMessage)) {
            result.message = errorMessage;
            return result;
        }

        const auto sessionState = loadSessionState(token, historyLimit);
        result.ok = sessionState.ok && sessionState.authenticated;
        result.username = normalizedUser;
        result.token = token;
        result.message = result.ok ? "logged in" : sessionState.message;
        result.activeConversationId = sessionState.activeConversationId;
        result.activeConversationTitle = sessionState.activeConversationTitle;
        result.conversations = std::move(sessionState.conversations);
        result.history = std::move(sessionState.history);
        return result;
    } catch (const std::exception& ex) {
        result.message = ex.what();
        return result;
    }
}

ChatPersistenceService::SessionState ChatPersistenceService::loadSessionState(const std::string& token,
                                                                              size_t historyLimit,
                                                                              int64_t requestedConversationId)
{
    SessionState state;
    if (!ready_) {
        state.message = initError_.empty() ? "database unavailable" : initError_;
        return state;
    }

    if (token.empty()) {
        state.message = "missing token";
        return state;
    }

    try {
        auto connection = pool_.acquire();
        MYSQL* mysql = connection.get();
        const std::string escapedToken = escapeString(mysql, token);
        std::string errorMessage;

        executeStatement(mysql, "DELETE FROM user_sessions WHERE expires_at <= NOW()", nullptr);

        auto sessionResult = executeQuery(
            mysql,
            "SELECT u.id, u.username FROM user_sessions s "
            "JOIN users u ON u.id = s.user_id "
            "WHERE s.token='" + escapedToken + "' AND s.expires_at > NOW() LIMIT 1",
            &errorMessage);
        if (!errorMessage.empty()) {
            state.message = errorMessage;
            return state;
        }

        if (!sessionResult) {
            state.message = "invalid token";
            return state;
        }

        MYSQL_ROW row = mysql_fetch_row(sessionResult.get());
        if (row == nullptr) {
            state.message = "invalid token";
            return state;
        }
        unsigned long* lengths = mysql_fetch_lengths(sessionResult.get());

        state.userId = std::stoll(readColumn(row, lengths, 0));
        state.username = readColumn(row, lengths, 1);
        state.token = token;
        state.conversations = loadConversationSummaries(mysql, state.userId, &errorMessage);
        if (!errorMessage.empty()) {
            state.message = errorMessage;
            state.conversations.clear();
            return state;
        }

        if (requestedConversationId > 0) {
            std::string requestedTitle;
            if (!loadConversationMeta(mysql, state.userId, requestedConversationId, &requestedTitle, &errorMessage)) {
                state.message = errorMessage.empty() ? "conversation not found" : errorMessage;
                return state;
            }
            state.activeConversationId = requestedConversationId;
            state.activeConversationTitle = requestedTitle;
        } else if (!state.conversations.empty()) {
            state.activeConversationId = state.conversations.front().id;
            state.activeConversationTitle = state.conversations.front().title;
        }

        if (state.activeConversationId > 0) {
            state.history = loadConversationHistory(mysql, state.activeConversationId, historyLimit, &errorMessage);
            if (!errorMessage.empty()) {
                state.message = errorMessage;
                state.history.clear();
                return state;
            }
        }

        state.ok = true;
        state.authenticated = true;
        state.message = "ok";
        return state;
    } catch (const std::exception& ex) {
        state.message = ex.what();
        return state;
    }
}

bool ChatPersistenceService::logout(const std::string& token, std::string* errorMessage)
{
    if (!ready_) {
        if (errorMessage != nullptr) {
            *errorMessage = initError_.empty() ? "database unavailable" : initError_;
        }
        return false;
    }

    if (token.empty()) {
        if (errorMessage != nullptr) {
            *errorMessage = "missing token";
        }
        return false;
    }

    try {
        auto connection = pool_.acquire();
        MYSQL* mysql = connection.get();
        const std::string escapedToken = escapeString(mysql, token);
        const std::string sql = "DELETE FROM user_sessions WHERE token='" + escapedToken + "'";
        return executeStatement(mysql, sql, errorMessage);
    } catch (const std::exception& ex) {
        if (errorMessage != nullptr) {
            *errorMessage = ex.what();
        }
        return false;
    }
}

ChatPersistenceService::SaveConversationResult ChatPersistenceService::saveConversation(
    int64_t userId,
    int64_t requestedConversationId,
    const std::string& userMessage,
    const std::string& assistantMessage,
    std::string* errorMessage)
{
    SaveConversationResult result;
    if (!ready_) {
        result.message = initError_.empty() ? "database unavailable" : initError_;
        if (errorMessage != nullptr) {
            *errorMessage = result.message;
        }
        return result;
    }

    try {
        auto connection = pool_.acquire();
        MYSQL* mysql = connection.get();
        std::string localError;

        int64_t conversationId = requestedConversationId;
        std::string conversationTitle;
        if (conversationId > 0 &&
            !loadConversationMeta(mysql, userId, conversationId, &conversationTitle, &localError)) {
            result.message = localError.empty() ? "conversation not found" : localError;
            if (errorMessage != nullptr) {
                *errorMessage = result.message;
            }
            return result;
        }

        if (!executeStatement(mysql, "START TRANSACTION", &localError)) {
            result.message = localError;
            if (errorMessage != nullptr) {
                *errorMessage = result.message;
            }
            return result;
        }

        if (conversationId <= 0) {
            conversationTitle = buildConversationTitle(userMessage);
            const std::string insertConversationSql =
                "INSERT INTO conversations(user_id, title, created_at, updated_at) VALUES(" +
                std::to_string(userId) + ", " + utf8mb4Literal(conversationTitle) + ", NOW(), NOW())";
            if (!executeStatement(mysql, insertConversationSql, &localError)) {
                executeStatement(mysql, "ROLLBACK", nullptr);
                result.message = localError;
                if (errorMessage != nullptr) {
                    *errorMessage = result.message;
                }
                return result;
            }
            conversationId = static_cast<int64_t>(mysql_insert_id(mysql));
        }

        const std::string escapedUserMessage = escapeString(mysql, userMessage);
        const std::string escapedAssistantMessage = escapeString(mysql, assistantMessage);

        const std::string insertUserSql =
            "INSERT INTO chat_messages(user_id, conversation_id, role, content, created_at) VALUES(" +
            std::to_string(userId) + ", " + std::to_string(conversationId) +
            ", 'user', '" + escapedUserMessage + "', NOW())";
        if (!executeStatement(mysql, insertUserSql, &localError)) {
            executeStatement(mysql, "ROLLBACK", nullptr);
            result.message = localError;
            if (errorMessage != nullptr) {
                *errorMessage = result.message;
            }
            return result;
        }

        const std::string insertAssistantSql =
            "INSERT INTO chat_messages(user_id, conversation_id, role, content, created_at) VALUES(" +
            std::to_string(userId) + ", " + std::to_string(conversationId) +
            ", 'assistant', '" + escapedAssistantMessage + "', NOW())";
        if (!executeStatement(mysql, insertAssistantSql, &localError)) {
            executeStatement(mysql, "ROLLBACK", nullptr);
            result.message = localError;
            if (errorMessage != nullptr) {
                *errorMessage = result.message;
            }
            return result;
        }

        const std::string updateConversationSql =
            "UPDATE conversations SET updated_at=NOW() WHERE id=" + std::to_string(conversationId);
        if (!executeStatement(mysql, updateConversationSql, &localError)) {
            executeStatement(mysql, "ROLLBACK", nullptr);
            result.message = localError;
            if (errorMessage != nullptr) {
                *errorMessage = result.message;
            }
            return result;
        }

        if (!executeStatement(mysql, "COMMIT", &localError)) {
            executeStatement(mysql, "ROLLBACK", nullptr);
            result.message = localError;
            if (errorMessage != nullptr) {
                *errorMessage = result.message;
            }
            return result;
        }

        result.ok = true;
        result.message = "ok";
        result.conversationId = conversationId;
        result.conversationTitle = conversationTitle;
        result.conversations = loadConversationSummaries(mysql, userId, &localError);
        if (!localError.empty()) {
            result.message = localError;
        }
        return result;
    } catch (const std::exception& ex) {
        result.message = ex.what();
        if (errorMessage != nullptr) {
            *errorMessage = result.message;
        }
        return result;
    }
}

bool ChatPersistenceService::ensureSchema(std::string* errorMessage)
{
    try {
        auto connection = pool_.acquire();
        MYSQL* mysql = connection.get();

        const std::vector<std::string> ddlStatements = {
            "CREATE TABLE IF NOT EXISTS users ("
            "id BIGINT PRIMARY KEY AUTO_INCREMENT,"
            "username VARCHAR(64) NOT NULL UNIQUE,"
            "password_salt VARCHAR(64) NOT NULL,"
            "password_hash VARCHAR(64) NOT NULL,"
            "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
            ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4",
            "CREATE TABLE IF NOT EXISTS user_sessions ("
            "id BIGINT PRIMARY KEY AUTO_INCREMENT,"
            "user_id BIGINT NOT NULL,"
            "token VARCHAR(128) NOT NULL UNIQUE,"
            "expires_at DATETIME NOT NULL,"
            "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,"
            "INDEX idx_user_token(token),"
            "INDEX idx_user_expires(expires_at),"
            "CONSTRAINT fk_user_sessions_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE"
            ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4",
            "CREATE TABLE IF NOT EXISTS conversations ("
            "id BIGINT PRIMARY KEY AUTO_INCREMENT,"
            "user_id BIGINT NOT NULL,"
            "title VARCHAR(255) NOT NULL,"
            "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,"
            "updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,"
            "INDEX idx_conversations_user_updated(user_id, updated_at),"
            "CONSTRAINT fk_conversations_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE"
            ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4",
            "CREATE TABLE IF NOT EXISTS chat_messages ("
            "id BIGINT PRIMARY KEY AUTO_INCREMENT,"
            "user_id BIGINT NOT NULL,"
            "role ENUM('user','assistant') NOT NULL,"
            "content MEDIUMTEXT NOT NULL,"
            "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,"
            "INDEX idx_user_message(user_id, id),"
            "CONSTRAINT fk_chat_messages_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE"
            ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
        };

        for (const auto& ddl : ddlStatements) {
            if (!executeStatement(mysql, ddl, errorMessage)) {
                return false;
            }
        }

        std::string localError;
        if (!columnExists(mysql, "chat_messages", "conversation_id", &localError)) {
            if (!localError.empty()) {
                if (errorMessage != nullptr) {
                    *errorMessage = localError;
                }
                return false;
            }
            if (!executeStatement(mysql,
                                  "ALTER TABLE chat_messages ADD COLUMN conversation_id BIGINT NULL AFTER user_id",
                                  errorMessage)) {
                return false;
            }
        }

        localError.clear();
        if (!indexExists(mysql, "chat_messages", "idx_chat_messages_conversation", &localError)) {
            if (!localError.empty()) {
                if (errorMessage != nullptr) {
                    *errorMessage = localError;
                }
                return false;
            }
            if (!executeStatement(mysql,
                                  "ALTER TABLE chat_messages "
                                  "ADD INDEX idx_chat_messages_conversation(conversation_id, id)",
                                  errorMessage)) {
                return false;
            }
        }

        localError.clear();
        if (!foreignKeyExists(mysql, "chat_messages", "fk_chat_messages_conversation", &localError)) {
            if (!localError.empty()) {
                if (errorMessage != nullptr) {
                    *errorMessage = localError;
                }
                return false;
            }
            if (!executeStatement(mysql,
                                  "ALTER TABLE chat_messages "
                                  "ADD CONSTRAINT fk_chat_messages_conversation "
                                  "FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE",
                                  errorMessage)) {
                return false;
            }
        }

        return migrateLegacyMessages(mysql, errorMessage);
    } catch (const std::exception& ex) {
        if (errorMessage != nullptr) {
            *errorMessage = ex.what();
        }
        return false;
    }
}

std::vector<ChatPersistenceService::ConversationSummary> ChatPersistenceService::loadConversationSummaries(
    int64_t userId,
    std::string* errorMessage)
{
    try {
        auto connection = pool_.acquire();
        return loadConversationSummaries(connection.get(), userId, errorMessage);
    } catch (const std::exception& ex) {
        if (errorMessage != nullptr) {
            *errorMessage = ex.what();
        }
        return {};
    }
}

std::vector<ChatPersistenceService::ConversationSummary> ChatPersistenceService::loadConversationSummaries(
    MYSQL* connection,
    int64_t userId,
    std::string* errorMessage)
{
    std::vector<ConversationSummary> conversations;
    std::ostringstream sql;
    sql << "SELECT c.id, c.title, "
        << "DATE_FORMAT(c.updated_at, '%Y-%m-%d %H:%i:%s'), "
        << "COALESCE((SELECT m.content FROM chat_messages m "
        << "WHERE m.conversation_id = c.id ORDER BY m.id DESC LIMIT 1), ''), "
        << "(SELECT COUNT(*) FROM chat_messages m2 WHERE m2.conversation_id = c.id) "
        << "FROM conversations c "
        << "WHERE c.user_id=" << userId << " "
        << "ORDER BY c.updated_at DESC, c.id DESC "
        << "LIMIT " << kConversationSummaryLimit;

    auto result = executeQuery(connection, sql.str(), errorMessage);
    if (!result || (errorMessage != nullptr && !errorMessage->empty())) {
        return conversations;
    }

    MYSQL_ROW row = nullptr;
    while ((row = mysql_fetch_row(result.get())) != nullptr) {
        unsigned long* lengths = mysql_fetch_lengths(result.get());
        ConversationSummary summary;
        summary.id = std::stoll(readColumn(row, lengths, 0));
        summary.title = readColumn(row, lengths, 1);
        summary.updatedAt = readColumn(row, lengths, 2);
        summary.preview = buildPreview(readColumn(row, lengths, 3));
        const std::string messageCount = readColumn(row, lengths, 4);
        summary.messageCount = messageCount.empty() ? 0 : static_cast<size_t>(std::stoull(messageCount));
        conversations.push_back(std::move(summary));
    }
    return conversations;
}

std::vector<OpenAIClient::ChatMessage> ChatPersistenceService::loadConversationHistory(int64_t conversationId,
                                                                                       size_t historyLimit,
                                                                                       std::string* errorMessage)
{
    try {
        auto connection = pool_.acquire();
        return loadConversationHistory(connection.get(), conversationId, historyLimit, errorMessage);
    } catch (const std::exception& ex) {
        if (errorMessage != nullptr) {
            *errorMessage = ex.what();
        }
        return {};
    }
}

std::vector<OpenAIClient::ChatMessage> ChatPersistenceService::loadConversationHistory(MYSQL* connection,
                                                                                       int64_t conversationId,
                                                                                       size_t historyLimit,
                                                                                       std::string* errorMessage)
{
    std::vector<OpenAIClient::ChatMessage> history;
    if (conversationId <= 0) {
        return history;
    }

    std::ostringstream sql;
    sql << "SELECT role, content FROM chat_messages WHERE conversation_id=" << conversationId
        << " ORDER BY id ASC";
    if (historyLimit > 0) {
        sql << " LIMIT " << historyLimit;
    }

    auto result = executeQuery(connection, sql.str(), errorMessage);
    if (!result || (errorMessage != nullptr && !errorMessage->empty())) {
        return history;
    }

    MYSQL_ROW row = nullptr;
    while ((row = mysql_fetch_row(result.get())) != nullptr) {
        unsigned long* lengths = mysql_fetch_lengths(result.get());
        history.push_back({readColumn(row, lengths, 0), readColumn(row, lengths, 1)});
    }
    return history;
}
