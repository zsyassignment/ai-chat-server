#pragma once

#include "noncopyable.h"

class InetAddress;//只声明了InetAddress类，Socket类中只使用了InetAddress类的指针或引用，所以不需要包含InetAddress.h头文件，使用前向声明即可。

// 封装socket fd
class Socket : noncopyable
{
public:
    explicit Socket(int sockfd)//sockfd是一个整数，表示socket文件描述符，使用explicit关键字可以防止隐式类型转换，避免一些潜在的错误
        : sockfd_(sockfd)
    {
    }
    ~Socket();

    int fd() const { return sockfd_; }
    void bindAddress(const InetAddress &localaddr);
    void listen();
    int accept(InetAddress *peeraddr);

    void shutdownWrite();
    //都是调用setsockopt函数来设置socket选项
    void setTcpNoDelay(bool on);//TCP_NODELAY选项可以禁用Nagle算法（把小包攒成大包再发送），减少数据包的延迟，提高网络性能
    void setReuseAddr(bool on);//SO_REUSEADDR选项允许在同一端口上绑定多个socket，常用于服务器重启时快速重新绑定端口，避免等待TIME_WAIT状态结束
    void setReusePort(bool on);
    void setKeepAlive(bool on); // SO_KEEPALIVE选项启用TCP连接的保活机制，定期发送探测包以检测连接是否仍然有效，适用于长时间保持连接的应用场景

private:
    const int sockfd_;
};
