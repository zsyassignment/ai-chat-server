#pragma once

#include <map>
#include <string>

class HttpRequest {
public:
    //enum class是C++11引入的强类型枚举，使用时需要加上枚举类型名，避免了普通枚举的命名冲突问题，同时也提供了更好的类型安全性
    enum class Method { kInvalid, kGet, kPost, kPut, kDelete };
    enum class Version { kUnknown, kHttp10, kHttp11 };

    using Headers = std::map<std::string, std::string>;

    HttpRequest();

    //处理method字段，设置method、获得枚举类型/字符串类型的method
    bool setMethod(const char* start, const char* end);
    Method method() const { return method_; }
    const char* methodString() const;

    //version字段的setter和getter
    void setVersion(Version v) { version_ = v; }
    Version version() const { return version_; }

    //path和query字段的setter和getter
    void setPath(const std::string& path) { path_ = path; }
    const std::string& path() const { return path_; }

    void setQuery(const std::string& query) { query_ = query; }
    const std::string& query() const { return query_; }

    //处理headers字段，添加请求头、获取请求头值、获取所有请求头
    void addHeader(const std::string& key, const std::string& value);
    std::string getHeader(const std::string& field) const;
    const Headers& headers() const { return headers_; }

    //处理body字段，设置请求体、获取请求体
    void setBody(const std::string& body) { body_ = body; }
    const std::string& body() const { return body_; }

    void swap(HttpRequest& other);
    bool keepAlive() const;

private:
    Method method_; //http请求方法
    Version version_; //http协议版本
    std::string path_; //请求路径
    std::string query_; //查询参数
    Headers headers_; //请求头
    std::string body_; //请求体
};
