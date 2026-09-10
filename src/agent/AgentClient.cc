#include "AgentClient.h"

#include <curl/curl.h>
#include <cstdlib>
#include <cstring>

#include "Logger.h"

namespace {
struct StreamWriteContext {
    const AgentClient::StreamCallback* callback;
    bool callbackFailed{false};
};

size_t writeStream(void* contents, size_t size, size_t nmemb, void* userp)
{
    const size_t total = size * nmemb;
    auto* context = static_cast<StreamWriteContext*>(userp);
    try {
        if (context->callback && *context->callback) {
            (*context->callback)(std::string(static_cast<char*>(contents), total));
        }
    } catch (...) {
        context->callbackFailed = true;
        return 0;
    }
    return total;
}

size_t writeString(void* contents, size_t size, size_t nmemb, void* userp)
{
    const size_t total = size * nmemb;
    auto* output = static_cast<std::string*>(userp);
    output->append(static_cast<char*>(contents), total);
    return total;
}

void setCommonOptions(CURL* curl, const std::string& url)
{
    curl_easy_setopt(curl, CURLOPT_URL, url.c_str());
    curl_easy_setopt(curl, CURLOPT_NOSIGNAL, 1L);
    curl_easy_setopt(curl, CURLOPT_CONNECTTIMEOUT, 5L);
    curl_easy_setopt(curl, CURLOPT_TIMEOUT, 600L);
}

std::string contentTypeHeader(const std::string& contentType)
{
    return "Content-Type: " +
        (contentType.empty() ? std::string("application/json") : contentType);
}
}

AgentClient::AgentClient(const std::string& baseUrl)
    : baseUrl_(baseUrl)
{
    if (baseUrl_.empty()) {
        const char* configured = std::getenv("AGENT_SERVICE_URL");
        baseUrl_ = configured && std::strlen(configured) > 0
            ? configured
            : "http://127.0.0.1:8010";
    }
    while (!baseUrl_.empty() && baseUrl_.back() == '/') {
        baseUrl_.pop_back();
    }
}

std::string AgentClient::endpoint(const std::string& path) const
{
    if (path.empty()) return baseUrl_;
    return baseUrl_ + (path.front() == '/' ? path : "/" + path);
}

bool AgentClient::streamRequest(const std::string& path,
                                const std::string& body,
                                const std::string& contentType,
                                const StreamCallback& onData,
                                std::string* errorMessage) const
{
    CURL* curl = curl_easy_init();
    if (!curl) {
        if (errorMessage) *errorMessage = "failed to initialize libcurl";
        return false;
    }

    struct curl_slist* headers = nullptr;
    const std::string typeHeader = contentTypeHeader(contentType);
    headers = curl_slist_append(headers, typeHeader.c_str());
    headers = curl_slist_append(headers, "Accept: text/event-stream");

    StreamWriteContext context{&onData, false};
    setCommonOptions(curl, endpoint(path));
    curl_easy_setopt(curl, CURLOPT_HTTPHEADER, headers);
    curl_easy_setopt(curl, CURLOPT_POST, 1L);
    curl_easy_setopt(curl, CURLOPT_POSTFIELDS, body.c_str());
    curl_easy_setopt(curl, CURLOPT_POSTFIELDSIZE, static_cast<long>(body.size()));
    curl_easy_setopt(curl, CURLOPT_FAILONERROR, 1L);
    curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, writeStream);
    curl_easy_setopt(curl, CURLOPT_WRITEDATA, &context);

    const CURLcode result = curl_easy_perform(curl);
    long statusCode = 0;
    curl_easy_getinfo(curl, CURLINFO_RESPONSE_CODE, &statusCode);
    curl_slist_free_all(headers);
    curl_easy_cleanup(curl);

    if (result != CURLE_OK || context.callbackFailed || statusCode >= 400) {
        if (errorMessage) {
            if (context.callbackFailed) {
                *errorMessage = "agent stream consumer failed";
            } else if (result != CURLE_OK) {
                *errorMessage = curl_easy_strerror(result);
            } else {
                *errorMessage = "agent service returned HTTP " + std::to_string(statusCode);
            }
        }
        LOG_ERROR << "Agent stream failed: status=" << statusCode
                  << " curl=" << curl_easy_strerror(result);
        return false;
    }
    return true;
}

std::optional<std::string> AgentClient::requestJson(const std::string& method,
                                                    const std::string& path,
                                                    const std::string& body,
                                                    const std::string& contentType,
                                                    long* responseCode,
                                                    std::string* errorMessage) const
{
    CURL* curl = curl_easy_init();
    if (!curl) {
        if (errorMessage) *errorMessage = "failed to initialize libcurl";
        return std::nullopt;
    }

    std::string response;
    struct curl_slist* headers = nullptr;
    headers = curl_slist_append(headers, "Accept: application/json");
    if (method != "GET") {
        const std::string typeHeader = contentTypeHeader(contentType);
        headers = curl_slist_append(headers, typeHeader.c_str());
    }

    setCommonOptions(curl, endpoint(path));
    curl_easy_setopt(curl, CURLOPT_HTTPHEADER, headers);
    curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, writeString);
    curl_easy_setopt(curl, CURLOPT_WRITEDATA, &response);
    if (method == "POST") {
        curl_easy_setopt(curl, CURLOPT_POST, 1L);
        curl_easy_setopt(curl, CURLOPT_POSTFIELDS, body.c_str());
        curl_easy_setopt(curl, CURLOPT_POSTFIELDSIZE, static_cast<long>(body.size()));
    } else if (method != "GET") {
        curl_easy_setopt(curl, CURLOPT_CUSTOMREQUEST, method.c_str());
        if (!body.empty()) {
            curl_easy_setopt(curl, CURLOPT_POSTFIELDS, body.c_str());
            curl_easy_setopt(curl, CURLOPT_POSTFIELDSIZE, static_cast<long>(body.size()));
        }
    }

    const CURLcode result = curl_easy_perform(curl);
    long status = 0;
    curl_easy_getinfo(curl, CURLINFO_RESPONSE_CODE, &status);
    if (responseCode) *responseCode = status;
    curl_slist_free_all(headers);
    curl_easy_cleanup(curl);

    if (result != CURLE_OK) {
        if (errorMessage) *errorMessage = curl_easy_strerror(result);
        return std::nullopt;
    }
    return response;
}
