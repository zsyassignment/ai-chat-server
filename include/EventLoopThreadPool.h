#pragma once

#include <functional>
#include <string>
#include <vector>
#include <memory>

#include "noncopyable.h"
class EventLoop;
class EventLoopThread;
//主从reactor模型中，EventLoopThreadPool是一个线程池类，管理多个EventLoopThread对象
//每个EventLoopThread对象包含一个独立的EventLoop实例。主线程（main loop）负责监听新连接，并将新连接分配给子线程（sub loop）处理。
//子线程通过轮询的方式获取下一个可用的EventLoop实例来处理事件。用户可以通过设置线程数量来决定是否使用多线程模式，如果线程数量为0，则所有事件都在主线程中处理。
class EventLoopThreadPool : noncopyable
{
public:
    using ThreadInitCallback = std::function<void(EventLoop *)>;

    EventLoopThreadPool(EventLoop *baseLoop, const std::string &nameArg);
    ~EventLoopThreadPool();

    void setThreadNum(int numThreads) { numThreads_ = numThreads; }

    void start(const ThreadInitCallback &cb = ThreadInitCallback());

// 如果工作在多线程中，baseLoop_(mainLoop)会默认以轮询的方式分配Channel给subLoop
    EventLoop *getNextLoop();

    std::vector<EventLoop *> getAllLoops(); // 获取所有的EventLoop

    bool started() const { return started_; } // 是否已经启动
    const std::string name() const { return name_; } // 获取名字

private:
    EventLoop *baseLoop_; // 用户使用muduo创建的loop 如果线程数为1 那直接使用用户创建的loop 否则创建多EventLoop
    std::string name_;//线程池名称，通常由用户指定，线程池中EventLoopThread名称依赖于线程池名称。
    bool started_;//是否已经启动标志
    int numThreads_;//线程池中线程的数量
    int next_; // 新连接到来，所选择EventLoop的索引
    std::vector<std::unique_ptr<EventLoopThread>> threads_;//IO线程的列表
    std::vector<EventLoop *> loops_;//线程池中EventLoop的列表，指向的是EVentLoopThread线程函数创建的EventLoop对象。
};