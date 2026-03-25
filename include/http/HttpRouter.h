#pragma once

#include <functional>
#include <string>
#include <unordered_map>

#include "HttpRequest.h"
#include "HttpResponse.h"

class HttpRouter {
public:
    using Handler = std::function<void(const HttpRequest&, HttpResponse&)>;

    void addRoute(HttpRequest::Method method, const std::string& path, Handler handler);
    bool route(const HttpRequest& req, HttpResponse& resp) const;
    void setNotFoundHandler(Handler handler) { notFoundHandler_ = std::move(handler); }

private:
    //路由表的键由HTTP方法和路径组成，值是对应的处理函数
    //如果只用路径，post和get方法请求一个路径是不同的
    struct RouteKey 
    {
        HttpRequest::Method method;
        std::string path;
        //重载==运算符，使RouteKey可以作为unordered_map的键
        bool operator==(const RouteKey& other) const 
        {
            return method == other.method && path == other.path;
        }
    };
    //仿函数，重载了operator()的结构体
    struct RouteKeyHash 
    {
        size_t operator()(const RouteKey& key) const 
        {
            //自定义的键unordered_map无法直接计算哈希值，需要提供一个哈希函数
            //这里使用了std::hash对HTTP方法和路径分别计算哈希值，并进行异或运算得到最终的哈希值
            return std::hash<int>()(static_cast<int>(key.method)) ^ std::hash<std::string>()(key.path);
        }
    };
    //第三个参数指定哈希函数
    std::unordered_map<RouteKey, Handler, RouteKeyHash> routes_;
    Handler notFoundHandler_;
};
