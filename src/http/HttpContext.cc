#include "HttpContext.h"

#include <algorithm>
#include <cstdlib>

#include "Buffer.h"

HttpContext::HttpContext()
    : state_(ParseState::kExpectRequestLine), bodyExpected_(0) {}

void HttpContext::reset() 
{
    state_ = ParseState::kExpectRequestLine; //状态回归初始状态
    //empty是临时变量换完以后函数结束就被自动销毁了
    HttpRequest empty;
    request_.swap(empty); //和一个空的httprequest交换，清空httprequest对象
    bodyExpected_ = 0;
}
//处理请求行（第一行） 方法 路径 http版本
bool HttpContext::processRequestLine(const char* begin, const char* end) 
{
    //第一个空格（解析方法）
    const char* start = begin;
    const char* space = std::find(start, end, ' ');
    if (space == end || !request_.setMethod(start, space)) 
    {
        return false;
    }

    //第二个空格（解析路径）例如：https://www.example.com/search?keyword=cpp&sort=desc
    start = space + 1;
    space = std::find(start, end, ' ');
    if (space == end) 
    {
        return false;
    }
    const char* question = std::find(start, space, '?');
    if (question == space) 
    {
        request_.setPath(std::string(start, space)); //没有问号全是路径
    } 
    else 
    {
        request_.setPath(std::string(start, question)); //有问号路径是从start到问号的部分，其他事query
        request_.setQuery(std::string(question + 1, space));
    }

    //第三个空格（解析http版本）例如HTTP/1.1
    start = space + 1;
    if (end - start == 8 && std::equal(start, end, "HTTP/1.1")) 
    {
        request_.setVersion(HttpRequest::Version::kHttp11);
    } 
    else if (end - start == 8 && std::equal(start, end, "HTTP/1.0")) 
    {
        request_.setVersion(HttpRequest::Version::kHttp10);
    } 
    else 
    {
        return false;
    }
    return true;
}

//http解析状态机，没收全就挂起等待，收全一行就解析一行，直到收全一个http请求为止
bool HttpContext::parseRequest(Buffer* buf) 
{
    bool ok = true;
    while (ok) 
    {
        //状态一：需要解析请求行
        if (state_ == ParseState::kExpectRequestLine) 
        {
            const char* end = buf->peek() + buf->readableBytes();//可读部分的结束位置

            //search(起始位置迭代器，结束位置迭代器， 搜索元素起始，搜索元素结束)
            //直接在给定的内存上搜索，零拷贝，相比std::string::find要拷贝构造string对象效率更高
            //strstr使用\0来标识字符串结束，不能处理包含\0的字符串，而search可以处理任意内存块
            const char* crlf = std::search(buf->peek(), end, "\r\n", "\r\n" + 2);
            //没有换行符说明没有收全一行，挂起等待
            if (crlf == end) break;

            //开始处理行
            ok = processRequestLine(buf->peek(), crlf);
            if (!ok) break;
            buf->retrieve(crlf - buf->peek() + 2); //别忘了还有\r\n，前面找的是第一个换行符的位置，所以要加上2
            state_ = ParseState::kExpectHeaders;
        } 
        //状态二：需要解析请求头
        else if (state_ == ParseState::kExpectHeaders) 
        {
            const char* end = buf->peek() + buf->readableBytes();
            const char* crlf = std::search(buf->peek(), end, "\r\n", "\r\n" + 2);
            if (crlf == end) break;

            //第一个就是\r\r说明这一行是空行，请求头已经解析完了
            if (crlf == buf->peek()) 
            {
                buf->retrieve(2);
                auto lenStr = request_.getHeader("Content-Length");
                bodyExpected_ = lenStr.empty() ? 0 : static_cast<size_t>(atoi(lenStr.c_str()));//字符串转数字
                if (bodyExpected_ > 0) 
                {
                    state_ = ParseState::kExpectBody;
                } 
                else 
                {
                    state_ = ParseState::kGotAll;
                }
                continue;
            }
            //解析请求头key:value
            const char* colon = std::find(buf->peek(), crlf, ':');
            if (colon != crlf) 
            {
                std::string field(buf->peek(), colon);
                std::string value(colon + 1, crlf);
                request_.addHeader(field, value);
            }
            buf->retrieve(crlf - buf->peek() + 2);
        } 
        else if (state_ == ParseState::kExpectBody) 
        {
            //可读字节数不足说明没有收全请求体，挂起等待
            //todo：如果请求体很大，可能会导致内存占用过高，可以考虑限制请求体的最大长度，超过限制就返回错误响应或者流式处理内存缓冲区不够用则再开辟文件缓冲区
            if (buf->readableBytes() < bodyExpected_) break;

            //底层的 Buffer 重构为基于引用计数的块状链表结构（类似 brpc 的 IOBuf）。
            //这样在提取 Body 时，只需要切分（Cut）链表节点并增加引用计数，就能实现从网络层到业务层的绝对零拷贝传递。
            //引用计数清零前不会把节点回收，业务层处理完后再把引用计数清零，节点就会被回收到内存池中。保证数据生命周期
            //但是现在底层是vector实现的buffer所以只能拷贝
            request_.setBody(std::string(buf->peek(), buf->peek() + bodyExpected_));
            buf->retrieve(bodyExpected_);
            state_ = ParseState::kGotAll;
        } 
        else 
        {
            break;
        }
    }
    return ok;
}
