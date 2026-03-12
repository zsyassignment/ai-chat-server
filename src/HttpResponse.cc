#include "HttpResponse.h"

#include <cstdio>
#include <cstring>

#include "Buffer.h"

HttpResponse::HttpResponse(bool close)
    : statusCode_(HttpStatusCode::k200Ok)
    , statusMessage_("OK")
    , closeConnection_(close) {}

void HttpResponse::addHeader(const std::string& key, const std::string& value) 
{
    headers_[key] = value;
}

void HttpResponse::appendToBuffer(Buffer* output) const 
{
    //构造相应行第一行 HTTP/版本 状态码 原因短语\r\n
    char buf[64];
    const char* phrase = statusMessage_.empty() ? reasonPhrase(statusCode_) : statusMessage_.c_str();
    snprintf(buf, sizeof buf, "HTTP/1.1 %d %s\r\n", static_cast<int>(statusCode_), phrase);
    output->append(buf, strlen(buf));

    //处理Connection头部，根据closeConnection_的值决定是"close"还是"keep-alive"
    if (closeConnection_) 
    {
        output->append("Connection: close\r\n", 19);
    } 
    else 
    {
        output->append("Connection: keep-alive\r\n", 24);
    }

    //如果用户没有设置Content-Length头部，则自动添加一个Content-Length头部，值为body的长度
    auto it = headers_.find("Content-Length");
    if (it == headers_.end()) 
    {
        snprintf(buf, sizeof buf, "Content-Length: %zu\r\n", body_.size());
        output->append(buf, strlen(buf));
    }

    //添加用户设置的其他头部
    for (const auto& header : headers_) 
    {
        output->append(header.first.c_str(), header.first.size());//头
        output->append(": ", 2);
        output->append(header.second.c_str(), header.second.size());//值
        output->append("\r\n", 2);
    }

    output->append("\r\n", 2); //添加空行，表示头部结束
    output->append(body_.c_str(), body_.size());
}

const char* HttpResponse::reasonPhrase(HttpStatusCode code) 
{
    switch (code) 
    {
        case HttpStatusCode::k200Ok: return "OK";
        case HttpStatusCode::k400BadRequest: return "Bad Request";
        case HttpStatusCode::k404NotFound: return "Not Found";
        case HttpStatusCode::k405MethodNotAllowed: return "Method Not Allowed";
        case HttpStatusCode::k413PayloadTooLarge: return "Payload Too Large";
        case HttpStatusCode::k500InternalServerError: return "Internal Server Error";
        default: return "Unknown";
    }
}
