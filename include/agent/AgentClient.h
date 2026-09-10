#pragma once

#include <functional>
#include <optional>
#include <string>

// Blocking internal HTTP client used from the business worker pool. The public
// HTTP server remains the only browser-facing entry point.
class AgentClient {
public:
    using StreamCallback = std::function<void(const std::string&)>;

    explicit AgentClient(const std::string& baseUrl = "");

    bool streamRequest(const std::string& path,
                       const std::string& body,
                       const std::string& contentType,
                       const StreamCallback& onData,
                       std::string* errorMessage = nullptr) const;

    std::optional<std::string> requestJson(const std::string& method,
                                           const std::string& path,
                                           const std::string& body,
                                           const std::string& contentType,
                                           long* responseCode = nullptr,
                                           std::string* errorMessage = nullptr) const;

    const std::string& baseUrl() const { return baseUrl_; }

private:
    std::string endpoint(const std::string& path) const;

    std::string baseUrl_;
};
