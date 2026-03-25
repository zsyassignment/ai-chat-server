#pragma once

#include "noncopyable.h"
#include "Thread.h"
#include "FixedBuffer.h"
#include "LogStream.h"
#include "LogFile.h"

#include <vector>
#include <memory>
#include <mutex>
#include <condition_variable>
//双缓冲异步日志类，前端线程将日志消息写入当前缓冲区，当当前缓冲区满时，将其放入缓冲区队列，并切换到下一个缓冲区继续写入。
//后端线程从队列中取出满的缓冲区，将日志消息写入磁盘文件。
class AsyncLogging
{
public:
    AsyncLogging(const std::string &basename, off_t rollSize, int flushInterval=3);
    ~AsyncLogging()
    {
        if (running_)
        {
            stop();
        }
    }
    // 前端调用append写入日志
    void append(const char *logline, int len);
    void start()
    {
        running_ = true;
        thread_.start();
    }
    void stop()
    {
        running_ = false;
        cond_.notify_one();//提醒线程running_变为false了，线程函数会退出
    }

private:
    using LargeBuffer = FixedBuffer<kLargeBufferSize>;
    using BufferVector = std::vector<std::unique_ptr<LargeBuffer>>;
    // BufferVector::value_type 是 std::vector<std::unique_ptr<Buffer>> 的元素类型，也就是 std::unique_ptr<Buffer>。
    using BufferPtr = BufferVector::value_type;
    void threadFunc();
    const int flushInterval_; // 日志刷新时间
    std::atomic<bool> running_;
    const std::string basename_;
    const off_t rollSize_;
    Thread thread_;
    std::mutex mutex_;
    std::condition_variable cond_;
    //双缓冲，currentbuffer满了直接放到buffers里，然后切换到nextbuffer继续写入，后端线程从buffers里取出满的buffer写入磁盘
    BufferPtr currentBuffer_;
    BufferPtr nextBuffer_;
    BufferVector buffers_;
};