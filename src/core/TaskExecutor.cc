#include "TaskExecutor.h"

TaskExecutor::TaskExecutor(size_t threadCount)
    : running_(false) 
{
    workers_.reserve(threadCount); // 预先分配线程容器的内存，避免频繁的内存分配和复制
}

TaskExecutor::~TaskExecutor() 
{
    stop();
}

void TaskExecutor::start() 
{
    if (running_) return;
    running_ = true;
    size_t count = workers_.capacity();
    for (size_t i = 0; i < count; ++i) 
    {
        workers_.emplace_back(new Thread([this]() { workerLoop(); }, "biz-worker"));
        workers_.back()->start();
    }
}

void TaskExecutor::stop() 
{
    {
        //线程的cv变量一直在读这个变量，存在数据竞争
        std::lock_guard<std::mutex> lock(mutex_);
        if (!running_) return;
        running_ = false;
    }
    cv_.notify_all();
    for (auto& worker : workers_) {
        if (worker->started()) {
            worker->join();
        }
    }
}

//外部提交任务接口
void TaskExecutor::submit(std::function<void()> task) {
    {
        std::lock_guard<std::mutex> lock(mutex_);
        tasks_.push(std::move(task));
    }
    cv_.notify_one(); //唤醒一个等待的工作线程来处理新提交的任务
}

void TaskExecutor::workerLoop() 
{
    while (true) 
    {
        std::function<void()> task;
        {
            std::unique_lock<std::mutex> lock(mutex_);
            cv_.wait(lock, [this]() { return !tasks_.empty() || !running_; });
            if (!running_ && tasks_.empty()) break;
            task = std::move(tasks_.front());
            tasks_.pop();
        }
        //在锁外执行，防止任务执行时间过长导致其他线程无法获取锁
        if (task) task();
    }
}
