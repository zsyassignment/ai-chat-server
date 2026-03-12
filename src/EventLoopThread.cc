#include <EventLoopThread.h>
#include <EventLoop.h>

EventLoopThread::EventLoopThread(const ThreadInitCallback &cb,
                                 const std::string &name)
    : loop_(nullptr)
    , exiting_(false)
    , thread_(std::bind(&EventLoopThread::threadFunc, this), name)
    , mutex_()
    , cond_()
    , callback_(cb)
{
}

EventLoopThread::~EventLoopThread()
{
    exiting_ = true;
    if (loop_ != nullptr)
    {
        loop_->quit();
        thread_.join();
    }
}

EventLoop *EventLoopThread::startLoop()
{
    thread_.start(); // 启用底层线程Thread类对象thread_中通过start()创建的线程

    EventLoop *loop = nullptr;
    {
        std::unique_lock<std::mutex> lock(mutex_);
        //cond可以等一个条件，而信号量是一个计数器，cond可以有多个线程等待同一个条件，而信号量只能有一个线程等待一个信号量
        //信号量有记忆功能，cond没有记忆功能 例如当主线程调用startLoop()时 可能会先于新线程执行到cond_.wait() 这时如果cond_.wait()先于新线程执行到cond_.notify_one() 那么主线程就会一直阻塞在cond_.wait()上 直到新线程执行到cond_.notify_one()唤醒主线程 继续执行
        //while(loop_ == nullptr) { cond_.wait(lock); }
        cond_.wait(lock, [this](){return loop_ != nullptr;});
        loop = loop_;
    }
    return loop;
}

// 下面这个方法 是在单独的新线程里运行的
void EventLoopThread::threadFunc()
{
    //将eventloop对象创建为局部变量 这样就不需要考虑对象的销毁问题 因为当threadFunc函数退出时 loop对象会自动销毁
    EventLoop loop; // 创建一个独立的EventLoop对象 和上面的线程是一一对应的 级one loop per thread

    //有可能塞给了eventloop一个初始化的回调函数进行个性化设置 例如在回调函数里给eventloop绑定一个定时器 让eventloop在启动后就执行定时器回调函数
    if (callback_)
    {
        callback_(&loop);
    }

    {
        //主线程拿着这个锁，必须等主线程把loop_指针设置好之后才能释放锁 让新线程拿到这个锁，才能把loop_设置好
        std::unique_lock<std::mutex> lock(mutex_);
        loop_ = &loop;
        cond_.notify_one();
    }
    loop.loop();    // 执行EventLoop的loop() 开启了底层的Poller的poll()
    std::unique_lock<std::mutex> lock(mutex_);
    loop_ = nullptr;
}