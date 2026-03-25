#include "HttpRequest.h"

#include <algorithm>
#include <strings.h>

namespace {
// 去除字符串两端的空白字符，使用匿名命名空间避免污染全局命名空间
inline std::string trim(const std::string& s) 
{
    //找到第一个不在" \t\r\n"中的字符位置
    auto start = s.find_first_not_of(" \t\r\n");
    if (start == std::string::npos)
    {
        return "";
    } 
    auto end = s.find_last_not_of(" \t\r\n");

    return s.substr(start, end - start + 1);
}
}

HttpRequest::HttpRequest()
    : method_(Method::kInvalid)
    , version_(Version::kUnknown) {}

bool HttpRequest::setMethod(const char* start, const char* end) 
{
    std::string m(start, end);
    if (m == "GET")
    {
        method_ = Method::kGet;
    }else if (m == "POST")
    {
        method_ = Method::kPost;
    }
    else if (m == "PUT")
    {
        method_ = Method::kPut;
    }
    else if (m == "DELETE")
    {
        method_ = Method::kDelete;
    }
    else
    {
        method_ = Method::kInvalid;
    } 
    //判断是不是合法请求方法
    return method_ != Method::kInvalid;
}

const char* HttpRequest::methodString() const 
{
    //enum枚举值转回字符串
    switch (method_) 
    {
        case Method::kGet: return "GET";
        case Method::kPost: return "POST";
        case Method::kPut: return "PUT";
        case Method::kDelete: return "DELETE";
        default: return "INVALID";
    }
}

void HttpRequest::addHeader(const std::string& key, const std::string& value) 
{
    //key和value分别是请求头的字段名和字段值，去除两端空白字符后存入headers_中
    headers_[key] = trim(value);
}

std::string HttpRequest::getHeader(const std::string& field) const 
{
    //如果直接写headers_[field]，如果field不存在会自动创建一个空字符串并返回引用，这样就无法区分field不存在和field存在但值为空的情况，所以使用find方法查找
    //而且const函数不能修改成员变量，所以不能使用operator[]，只能使用find方法查找
    auto it = headers_.find(field);
    if (it != headers_.end()) {
        return it->second;
    }
    return "";
}

//复用httprequest对象时避免复制，清空httprequest时与emptyrequest交换
void HttpRequest::swap(HttpRequest& other) 
{
    //逐个交换
    std::swap(method_, other.method_);
    std::swap(version_, other.version_);
    path_.swap(other.path_);
    query_.swap(other.query_);
    headers_.swap(other.headers_);
    body_.swap(other.body_);
}

//处理http长连接/短连接
bool HttpRequest::keepAlive() const 
{
    auto connection = getHeader("Connection");
    if (!connection.empty()) 
    {
        //如果有connection字段，判断是否为close，如果是close则返回false，否则返回true
        return strcasecmp(connection.c_str(), "close") != 0;
    }
    // HTTP/1.1 默认 keep-alive，HTTP/1.0 默认关闭
    return version_ == Version::kHttp11;
}
