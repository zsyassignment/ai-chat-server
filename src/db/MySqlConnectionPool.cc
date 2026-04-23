#include "MySqlConnectionPool.h"

#include <stdexcept>
#include <utility>

namespace {
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
}

MySqlConnectionPool::Handle::Handle(MySqlConnectionPool* owner, MYSQL* connection)
    : owner_(owner)
    , connection_(connection)
{
}

MySqlConnectionPool::Handle::~Handle()
{
    if (owner_ != nullptr && connection_ != nullptr) {
        owner_->release(connection_);
    }
}

MySqlConnectionPool::Handle::Handle(Handle&& other) noexcept
    : owner_(other.owner_)
    , connection_(other.connection_)
{
    other.owner_ = nullptr;
    other.connection_ = nullptr;
}

MySqlConnectionPool::Handle& MySqlConnectionPool::Handle::operator=(Handle&& other) noexcept
{
    if (this != &other) {
        if (owner_ != nullptr && connection_ != nullptr) {
            owner_->release(connection_);
        }
        owner_ = other.owner_;
        connection_ = other.connection_;
        other.owner_ = nullptr;
        other.connection_ = nullptr;
    }
    return *this;
}

MySqlConnectionPool::MySqlConnectionPool(Config config)
    : config_(std::move(config))
{
}

MySqlConnectionPool::~MySqlConnectionPool()
{
    std::lock_guard<std::mutex> lock(mutex_);
    while (!idleConnections_.empty()) {
        mysql_close(idleConnections_.front());
        idleConnections_.pop();
    }
    if (libraryInitialized_) {
        mysql_library_end();
    }
}

bool MySqlConnectionPool::initialize(std::string* errorMessage)
{
    std::lock_guard<std::mutex> lock(mutex_);
    if (initialized_) {
        return true;
    }

    if (!libraryInitialized_) {
        if (mysql_library_init(0, nullptr, nullptr) != 0) {
            if (errorMessage != nullptr) {
                *errorMessage = "mysql_library_init failed";
            }
            return false;
        }
        libraryInitialized_ = true;
    }

    std::string localError;
    MYSQL* bootstrap = createConnection(false, &localError);
    if (bootstrap == nullptr) {
        if (errorMessage != nullptr) {
            *errorMessage = localError;
        }
        return false;
    }

    const std::string createDatabaseSql =
        "CREATE DATABASE IF NOT EXISTS " + quoteIdentifier(config_.database) +
        " CHARACTER SET " + config_.charset + " COLLATE utf8mb4_unicode_ci";
    if (!executeStatement(bootstrap, createDatabaseSql, &localError)) {
        mysql_close(bootstrap);
        if (errorMessage != nullptr) {
            *errorMessage = localError;
        }
        return false;
    }
    mysql_close(bootstrap);

    const size_t poolSize = config_.poolSize == 0 ? 1 : config_.poolSize;
    for (size_t i = 0; i < poolSize; ++i) {
        MYSQL* connection = createConnection(true, &localError);
        if (connection == nullptr) {
            while (!idleConnections_.empty()) {
                mysql_close(idleConnections_.front());
                idleConnections_.pop();
            }
            if (errorMessage != nullptr) {
                *errorMessage = localError;
            }
            return false;
        }
        idleConnections_.push(connection);
    }

    initialized_ = true;
    return true;
}

bool MySqlConnectionPool::ready() const
{
    std::lock_guard<std::mutex> lock(mutex_);
    return initialized_;
}

MySqlConnectionPool::Handle MySqlConnectionPool::acquire()
{
    MYSQL* connection = nullptr;
    {
        std::unique_lock<std::mutex> lock(mutex_);
        if (!initialized_) {
            throw std::runtime_error("mysql connection pool is not initialized");
        }

        cv_.wait(lock, [this]() { return !idleConnections_.empty(); });
        connection = idleConnections_.front();
        idleConnections_.pop();
    }

    std::string errorMessage;
    if (connection == nullptr || mysql_ping(connection) != 0) {
        if (connection != nullptr) {
            mysql_close(connection);
        }
        connection = createConnection(true, &errorMessage);
        if (connection == nullptr) {
            throw std::runtime_error(errorMessage.empty() ? "failed to reconnect mysql" : errorMessage);
        }
    }

    return Handle(this, connection);
}

MYSQL* MySqlConnectionPool::createConnection(bool withDatabase, std::string* errorMessage) const
{
    MYSQL* connection = mysql_init(nullptr);
    if (connection == nullptr) {
        if (errorMessage != nullptr) {
            *errorMessage = "mysql_init failed";
        }
        return nullptr;
    }

    mysql_options(connection, MYSQL_SET_CHARSET_NAME, config_.charset.c_str());
    mysql_options(connection, MYSQL_OPT_CONNECT_TIMEOUT, &config_.connectTimeoutSeconds);

    MYSQL* connected = mysql_real_connect(connection,
                                          config_.host.c_str(),
                                          config_.user.c_str(),
                                          config_.password.c_str(),
                                          withDatabase ? config_.database.c_str() : nullptr,
                                          config_.port,
                                          nullptr,
                                          0);
    if (connected == nullptr) {
        if (errorMessage != nullptr) {
            *errorMessage = mysql_error(connection);
        }
        mysql_close(connection);
        return nullptr;
    }

    mysql_set_character_set(connection, config_.charset.c_str());
    return connection;
}

bool MySqlConnectionPool::executeStatement(MYSQL* connection,
                                           const std::string& sql,
                                           std::string* errorMessage) const
{
    if (mysql_query(connection, sql.c_str()) != 0) {
        if (errorMessage != nullptr) {
            *errorMessage = mysql_error(connection);
        }
        return false;
    }
    return true;
}

void MySqlConnectionPool::release(MYSQL* connection)
{
    {
        std::lock_guard<std::mutex> lock(mutex_);
        idleConnections_.push(connection);
    }
    cv_.notify_one();
}
