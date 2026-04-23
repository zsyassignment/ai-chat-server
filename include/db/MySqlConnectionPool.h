#pragma once

#include <condition_variable>
#include <cstddef>
#include <mutex>
#include <queue>
#include <string>

#include <mysql/mysql.h>

class MySqlConnectionPool {
public:
    struct Config {
        std::string host = "127.0.0.1";
        unsigned int port = 3306;
        std::string user = "root";
        std::string password;
        std::string database = "ai_chat_server";
        std::string charset = "utf8mb4";
        size_t poolSize = 8;
        unsigned int connectTimeoutSeconds = 3;
    };

    class Handle {
    public:
        Handle() = default;
        Handle(MySqlConnectionPool* owner, MYSQL* connection);
        ~Handle();

        Handle(const Handle&) = delete;
        Handle& operator=(const Handle&) = delete;

        Handle(Handle&& other) noexcept;
        Handle& operator=(Handle&& other) noexcept;

        MYSQL* get() const { return connection_; }
        explicit operator bool() const { return connection_ != nullptr; }

    private:
        MySqlConnectionPool* owner_ = nullptr;
        MYSQL* connection_ = nullptr;
    };

    explicit MySqlConnectionPool(Config config);
    ~MySqlConnectionPool();

    bool initialize(std::string* errorMessage = nullptr);
    bool ready() const;

    Handle acquire();
    const Config& config() const { return config_; }

private:
    MYSQL* createConnection(bool withDatabase, std::string* errorMessage) const;
    bool executeStatement(MYSQL* connection, const std::string& sql, std::string* errorMessage) const;
    void release(MYSQL* connection);

    Config config_;
    mutable std::mutex mutex_;
    std::condition_variable cv_;
    std::queue<MYSQL*> idleConnections_;
    bool initialized_ = false;
    bool libraryInitialized_ = false;
};
