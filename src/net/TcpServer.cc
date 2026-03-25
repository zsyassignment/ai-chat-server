// #include <functional>
// #include <string.h>

// #include <TcpServer.h>
// #include <Logger.h>
// #include <TcpConnection.h>

// static EventLoop *CheckLoopNotNull(EventLoop *loop)
// {
//     if (loop == nullptr)
//     {
//         LOG_FATAL<<"main Loop is NULL!";
//     }
//     return loop;
// }

// TcpServer::TcpServer(EventLoop *loop,
//                      const InetAddress &listenAddr,
//                      const std::string &nameArg,
//                      Option option)
//     : loop_(CheckLoopNotNull(loop))
//     , ipPort_(listenAddr.toIpPort())
//     , name_(nameArg)
//     , acceptor_(new Acceptor(loop, listenAddr, option == kReusePort))
//     , threadPool_(new EventLoopThreadPool(loop, name_))
//     , connectionCallback_()
//     , messageCallback_()
//     , nextConnId_(1)
//     , started_(0)
// {
//     // 当有新用户连接时，Acceptor类中绑定的acceptChannel_会有读事件发生，执行handleRead()调用TcpServer::newConnection回调
//     acceptor_->setNewConnectionCallback(
//         std::bind(&TcpServer::newConnection, this, std::placeholders::_1, std::placeholders::_2));
// }

// TcpServer::~TcpServer()
// {
//     for(auto &item : connections_)
//     {
//         TcpConnectionPtr conn(item.second);
//         item.second.reset();    // 把原始的智能指针复位 让栈空间的TcpConnectionPtr conn指向该对象 当conn出了其作用域 即可释放智能指针指向的对象
//         // 销毁连接，在connectiondestroyed中会
//         conn->getLoop()->runInLoop(
//             std::bind(&TcpConnection::connectDestroyed, conn));
//     }
// }

// // 设置底层subloop的个数
// void TcpServer::setThreadNum(int numThreads)
// {
//     //调用threadPool_的setThreadNum方法设置线程池中线程的数量。这个方法会根据传入的numThreads参数调整线程池中的线程数量，以满足服务器的并发处理需求。
//     int numThreads_=numThreads;
//     threadPool_->setThreadNum(numThreads_);
// }

// // 开启服务器监听
// void TcpServer::start()
// {
//     if (started_.fetch_add(1) == 0)    // 防止一个TcpServer对象被start多次
//     {
//         threadPool_->start(threadInitCallback_);    // 启动底层的loop线程池
//         loop_->runInLoop(std::bind(&Acceptor::listen, acceptor_.get()));//listen是在主loop中执行的 监听新连接事件，runinloop保证了这一点
//     }
// }

// // 有一个新用户连接，acceptor会执行这个回调操作，负责将mainLoop接收到的请求连接(acceptChannel_会有读事件发生)通过回调轮询分发给subLoop去处理
// void TcpServer::newConnection(int sockfd, const InetAddress &peerAddr)
// {
//    // 轮询算法 选择一个subLoop 来管理connfd对应的channel
//     EventLoop *ioLoop = threadPool_->getNextLoop();
//     char buf[64] = {0};
//     snprintf(buf, sizeof buf, "-%s#%d", ipPort_.c_str(), nextConnId_);
//     ++nextConnId_;  // 这里没有设置为原子类是因为其只在mainloop中执行 不涉及线程安全问题
//     std::string connName = name_ + buf;

//     LOG_INFO<<"TcpServer::newConnection ["<<name_.c_str()<<"]- new connection ["<<connName.c_str()<<"]from "<<peerAddr.toIpPort().c_str();
    
//     // 通过sockfd获取其绑定的本机的ip地址和端口信息
//     sockaddr_in local;
//     ::memset(&local, 0, sizeof(local));
//     socklen_t addrlen = sizeof(local);
//     if(::getsockname(sockfd, (sockaddr *)&local, &addrlen) < 0)
//     {
//         LOG_ERROR<<"sockets::getLocalAddr";
//     }

//     InetAddress localAddr(local);
//     TcpConnectionPtr conn(new TcpConnection(ioLoop,
//                                             connName,
//                                             sockfd,
//                                             localAddr,
//                                             peerAddr));
//     connections_[connName] = conn;
//     // 下面的回调都是用户设置给TcpServer => TcpConnection的，至于Channel绑定的则是TcpConnection设置的四个，handleRead,handleWrite... 这下面的回调用于handlexxx函数中
//     conn->setConnectionCallback(connectionCallback_);
//     conn->setMessageCallback(messageCallback_);
//     conn->setWriteCompleteCallback(writeCompleteCallback_);

//     // 设置了如何关闭连接的回调
//     conn->setCloseCallback(
//         std::bind(&TcpServer::removeConnection, this, std::placeholders::_1));

//     ioLoop->runInLoop(
//         std::bind(&TcpConnection::connectEstablished, conn));
// }

// void TcpServer::removeConnection(const TcpConnectionPtr &conn)
// {
//     loop_->runInLoop(
//         std::bind(&TcpServer::removeConnectionInLoop, this, conn));
// }

// void TcpServer::removeConnectionInLoop(const TcpConnectionPtr &conn)
// {
//     LOG_INFO<<"TcpServer::removeConnectionInLoop ["<<
//              name_.c_str()<<"] - connection %s"<<conn->name().c_str();

//     connections_.erase(conn->name());
//     EventLoop *ioLoop = conn->getLoop();
//     ioLoop->queueInLoop(
//         std::bind(&TcpConnection::connectDestroyed, conn));
// }

#include <functional>
#include <string.h>

#include <TcpServer.h>
#include <Logger.h>
#include <TcpConnection.h>

// 辅助函数：防御性编程，主 Reactor 绝对不能为 nullptr
static EventLoop *CheckLoopNotNull(EventLoop *loop)
{
    if (loop == nullptr)
    {
        LOG_FATAL<<"main Loop is NULL!"; // 直接 abort 退出，不要让错误蔓延
    }
    return loop;
}

// 构造函数：初始化服务器大本营
TcpServer::TcpServer(EventLoop *loop,
                     const InetAddress &listenAddr,
                     const std::string &nameArg,
                     Option option)
    : loop_(CheckLoopNotNull(loop)) // 主 Reactor
    , ipPort_(listenAddr.toIpPort())
    , name_(nameArg)
    // 创建前台接待员 Acceptor，由主 Loop 管理
    , acceptor_(new Acceptor(loop, listenAddr, option == kReusePort))
    // 创建底层打工天团（线程池）
    , threadPool_(new EventLoopThreadPool(loop, name_))
    , connectionCallback_()
    , messageCallback_()
    , nextConnId_(1) // 连接 ID 从 1 开始
    , started_(0)
{
    // 极其关键：告诉 Acceptor，如果有新连接（读事件），请调用 TcpServer 的 newConnection 函数！
    // placeholders::_1 是 sockfd，_2 是 peerAddr
    acceptor_->setNewConnectionCallback(
        std::bind(&TcpServer::newConnection, this, std::placeholders::_1, std::placeholders::_2));
}

// 析构函数：服务器退出的优雅善后
TcpServer::~TcpServer()
{
    for(auto &item : connections_)
    {
        // 1. 拿到连接的智能指针
        TcpConnectionPtr conn(item.second);
        // 2. 把哈希表里的原始指针复位（释放 TcpServer 对该连接的所有权，引用计数 -1）
        item.second.reset();    
        
        // 3. 跨线程安全销毁：通知这个连接所在的从 Reactor 线程去执行 connectDestroyed
        conn->getLoop()->runInLoop(
            std::bind(&TcpConnection::connectDestroyed, conn));
    }
}

// 设置底层从 Reactor（SubLoop）的个数
void TcpServer::setThreadNum(int numThreads)
{
    int numThreads_=numThreads;
    threadPool_->setThreadNum(numThreads_);
}

// 开启服务器监听
void TcpServer::start()
{
    //防手抖设计：利用原子操作确保多线程调用 start() 时，只启动一次
    if (started_.fetch_add(1) == 0)    
    {
        // 1. 唤醒所有底层子线程，开始事件循环
        threadPool_->start(threadInitCallback_);    
        
        // 2. 跨线程投递：确保 Acceptor 的 listen 操作一定在主 Reactor 线程中执行
        loop_->runInLoop(std::bind(&Acceptor::listen, acceptor_.get()));
    }
}



//核心业务流程：处理新连接的交接大典
void TcpServer::newConnection(int sockfd, const InetAddress &peerAddr)
{
    // 1. 轮询算法：从线程池中挑一个最闲的 SubLoop（从 Reactor）
    EventLoop *ioLoop = threadPool_->getNextLoop();
    
    // 2. 组装一个全局唯一的连接名字
    char buf[64] = {0};
    snprintf(buf, sizeof buf, "-%s#%d", ipPort_.c_str(), nextConnId_);
    ++nextConnId_;  // 仅在主 Loop 执行，无多线程竞争，无需加锁或原子操作
    std::string connName = name_ + buf;

    LOG_INFO<<"TcpServer::newConnection ["<<name_.c_str()<<"]- new connection ["<<connName.c_str()<<"]from "<<peerAddr.toIpPort().c_str();
    
    // 3. 通过内核 API getsockname 获取本机的 IP 和端口信息
    sockaddr_in local;
    ::memset(&local, 0, sizeof(local));
    socklen_t addrlen = sizeof(local);
    if(::getsockname(sockfd, (sockaddr *)&local, &addrlen) < 0)
    {
        LOG_ERROR<<"sockets::getLocalAddr";
    }
    InetAddress localAddr(local);

    // 4. 将裸露的 sockfd 包装成高级的 TcpConnection 对象，设置channel的回调函数
    TcpConnectionPtr conn(new TcpConnection(ioLoop, connName, sockfd, localAddr, peerAddr));
    
    // 5. 登记造册：加入主 Reactor 的连接大账本，掌握其生命周期
    connections_[connName] = conn;
    
    // 6. 转移回调：把用户注册给 TcpServer 的业务逻辑回调，全部塞进 TcpConnection 里
    conn->setConnectionCallback(connectionCallback_);
    conn->setMessageCallback(messageCallback_);
    conn->setWriteCompleteCallback(writeCompleteCallback_);

    // 7. 设置内置回调：告诉 TcpConnection，你断开时必须调用 TcpServer::removeConnection 通知我
    conn->setCloseCallback(
        std::bind(&TcpServer::removeConnection, this, std::placeholders::_1));

    // 8. 踢给小弟去干活：让被选中的 SubLoop 线程去执行连接的初始化（注册 EPOLLIN 事件）
    ioLoop->runInLoop(
        std::bind(&TcpConnection::connectEstablished, conn));
}

// 客户端断开连接的入口：由 TcpConnection 触发
void TcpServer::removeConnection(const TcpConnectionPtr &conn)
{
    // 此时大概率在 SubLoop 线程里，必须跨线程把任务踢回给主 Reactor (loop_) 去处理，保护 connections_ 线程安全
    // 用主线程loop_的runInLoop方法把removeConnectionInLoop的调用投递到主线程中执行，确保了对connections_的访问是线程安全的。
    loop_->runInLoop(
        std::bind(&TcpServer::removeConnectionInLoop, this, conn));
}



// 真正的销毁逻辑：必须且只能在主 Reactor 线程中执行
void TcpServer::removeConnectionInLoop(const TcpConnectionPtr &conn)
{
    LOG_INFO<<"TcpServer::removeConnectionInLoop ["<<
             name_.c_str()<<"] - connection %s"<<conn->name().c_str();

    // 1. 从主账本中除名，TcpServer 释放该连接的所有权（引用计数 -1）
    connections_.erase(conn->name());
    
    EventLoop *ioLoop = conn->getLoop();
    // 2. 再次跨线程投递：把真正的底层收尾工作（比如从 epoll 中删 fd）踢回给当初管理它的 SubLoop 去执行
    ioLoop->queueInLoop(
        std::bind(&TcpConnection::connectDestroyed, conn));
}