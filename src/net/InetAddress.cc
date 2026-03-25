#include <strings.h>
#include <string.h>

#include <InetAddress.h>

InetAddress::InetAddress(uint16_t port, std::string ip)
{
    ::memset(&addr_, 0, sizeof(addr_));
    addr_.sin_family = AF_INET; //设置地址族为 IPv4
    addr_.sin_port = ::htons(port); // 本地字节序转为网络字节序，Host TO Network Short 16位整数
    addr_.sin_addr.s_addr = ::inet_addr(ip.c_str());//转成32位无符号整数
}

std::string InetAddress::toIp() const
{
    //转成点分十进制字符串, AF_INET表示IPv4地址族, &addr_.sin_addr是指向IPv4地址的指针, buf是存储结果的缓冲区, sizeof buf是缓冲区的大小
    // addr_
    char buf[64] = {0};
    ::inet_ntop(AF_INET, &addr_.sin_addr, buf, sizeof buf); //net to pointer, 网络字节序转为点分十进制字符串
    return buf;
}

std::string InetAddress::toIpPort() const
{
    // ip:port
    char buf[64] = {0};
    ::inet_ntop(AF_INET, &addr_.sin_addr, buf, sizeof buf);
    size_t end = ::strlen(buf);
    uint16_t port = ::ntohs(addr_.sin_port);
    sprintf(buf+end, ":%u", port);
    return buf;
}

uint16_t InetAddress::toPort() const
{
    return ::ntohs(addr_.sin_port);
}

#if 0
#include <iostream>
int main()
{
    InetAddress addr(8080);
    std::cout << addr.toIpPort() << std::endl;
}
#endif