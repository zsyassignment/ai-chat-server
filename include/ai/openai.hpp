#pragma once

#include <functional>
#include <optional>
#include <string>
#include <vector>

// 轻量的 OpenAI API 客户端，基于 libcurl
class OpenAIClient {
public:
    struct ChatMessage {
        std::string role;
        std::string content;
    };

    explicit OpenAIClient(const std::string& apiKey = "");

    void setModel(const std::string& model) { model_ = model; }
    void setApiKey(const std::string& key) { apiKey_ = key; }
    void setBaseUrl(const std::string& url) { baseUrl_ = url; }

    // 阻塞调用 OpenAI Chat Completion，失败返回 std::nullopt
    std::optional<std::string> chatCompletion(const std::vector<ChatMessage>& messages) const;
    std::optional<std::string> chatCompletion(const std::string& userMessage) const;

    // 上游 stream=true，按增量回调返回 token，函数返回完整拼接文本
    std::optional<std::string> chatCompletionStream(
        const std::vector<ChatMessage>& messages,
        const std::function<void(const std::string&)>& onDelta) const;

private:
    std::string apiKey_;
    std::string model_;
    std::string baseUrl_;
};
