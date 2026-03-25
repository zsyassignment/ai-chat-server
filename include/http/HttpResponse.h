//http响应模块
#pragma once

#include <map>
#include <string>

class Buffer;
//实现了六种基本的HTTP状态码，分别是200、400、404、405、413和500
enum class HttpStatusCode 
{
    k200Ok = 200, //成功
    k400BadRequest = 400, //客户端请求有语法错误，服务器无法理解
    k404NotFound = 404, //服务器无法找到请求的资源，通常是因为URL错误或资源已被删除
    k405MethodNotAllowed = 405, //请求方法（GET、POST等）不被服务器支持
    k413PayloadTooLarge = 413, //请求体过大，服务器无法处理 
    k500InternalServerError = 500 //服务器内部错误，通常是由于服务器代码中的bug或资源不足引起的
};

class HttpResponse {
public:
    using Headers = std::map<std::string, std::string>;
    
    explicit HttpResponse(bool close = false);

    void setStatusCode(HttpStatusCode code) { statusCode_ = code; }
    void setStatusMessage(const std::string& message) { statusMessage_ = message; }
    void setCloseConnection(bool on) { closeConnection_ = on; }
    bool closeConnection() const { return closeConnection_; }

    void setContentType(const std::string& type) { addHeader("Content-Type", type); }
    void addHeader(const std::string& key, const std::string& value);

    void setBody(const std::string& body) { body_ = body; }
    const std::string& body() const { return body_; }

    void appendToBuffer(Buffer* output) const;

private:
    static const char* reasonPhrase(HttpStatusCode code); //根据状态码返回对应的原因短语，例如200对应"OK"，404对应"Not Found"等

    Headers headers_;
    HttpStatusCode statusCode_; //HTTP状态码
    std::string statusMessage_;   //状态消息，默认为空字符串，如果不为空则使用该消息替代默认的原因短语
    std::string body_; //响应体内容
    bool closeConnection_; //指示是否在发送完响应后关闭连接
};
