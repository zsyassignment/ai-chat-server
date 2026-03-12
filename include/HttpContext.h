
#pragma once

#include <string>

#include "HttpRequest.h"
//解析http报文
//http状态机，没收全就挂起等待，收全一行就解析一行，直到收全一个http请求为止
class Buffer;
class Timestamp;

class HttpContext {
public:
    enum class ParseState 
    { 
        kExpectRequestLine, // 需要解析请求行
        kExpectHeaders, //需要解析请求头
        kExpectBody, //需要解析请求体
        kGotAll //已经解析完一个完整的http请求了
    };

    HttpContext();

    bool parseRequest(Buffer* buf);
    bool gotAll() const { return state_ == ParseState::kGotAll; } //是否已经解析完一个完整的http请求了
    void reset();

    const HttpRequest& request() const { return request_; }
    HttpRequest& request() { return request_; }

private:
    bool processRequestLine(const char* begin, const char* end);

    ParseState state_;  // 当前解析状态
    HttpRequest request_;   // 解析结果存储在HttpRequest对象中
    size_t bodyExpected_; // 如果请求有body，记录body的长度，解析到这个长度就说明请求已经完全解析了
};
