#include "Logger.h"
#include "CurrentThread.h"

namespace ThreadInfo
{
    //thread_local是C++11引入的一个关键字，用于声明线程局部存储变量。每个线程都会有自己独立的实例，这些变量在不同线程之间互不干扰。
    thread_local char t_errnobuf[512]; // 每个线程独立的错误信息缓冲
    thread_local char t_timer[64];     // 每个线程独立的时间格式化缓冲区
    thread_local time_t t_lastSecond;  // 每个线程记录上次格式化的时间

}
const char *getErrnoMsg(int savedErrno)
{
    //sterror_r是一个线程安全的函数，用于将错误码转换为对应的错误消息字符串。
    //它将错误消息写入提供的缓冲区中，并返回指向该缓冲区的指针。这样可以避免在多线程环境中使用strerror函数时可能出现的竞争条件和数据混乱问题。
    return strerror_r(savedErrno, ThreadInfo::t_errnobuf, sizeof(ThreadInfo::t_errnobuf));
}
// 根据Level 返回level_名字
const char *getLevelName[Logger::LogLevel::LEVEL_COUNT]{
    "TRACE ",
    "DEBUG ",
    "INFO  ",
    "WARN  ",
    "ERROR ",
    "FATAL ",
};
/**
 * 默认的日志输出函数
 * 将日志内容写入标准输出流(stdout)
 * @param data 要输出的日志数据
 * @param len 日志数据的长度W
 */
static void defaultOutput(const char *data, int len)
{
    fwrite(data, len, sizeof(char), stdout);
}

/**
 * 默认的刷新函数
 * 刷新标准输出流的缓冲区,确保日志及时输出
 * 在发生错误或需要立即看到日志时会被调用
 */
static void defaultFlush()
{
    fflush(stdout);
}
Logger::OutputFunc g_output = defaultOutput;
Logger::FlushFunc g_flush = defaultFlush;

Logger::Impl::Impl(Logger::LogLevel level, int savedErrno, const char *filename, int line)
    : time_(Timestamp::now()),
      stream_(),
      level_(level),
      line_(line),
      basename_(filename)
{
    // 根据时区格式化当前时间字符串, 也是一条log消息的开头
    formatTime();
    // 写入日志等级
    stream_ << GeneralTemplate(getLevelName[level], 6);
    if (savedErrno != 0)
    {
        stream_ << getErrnoMsg(savedErrno) << " (errno=" << savedErrno << ") ";
    }
}
// 根据时区格式化当前时间字符串, 也是一条log消息的开头
void Logger::Impl::formatTime()
{
    Timestamp now = Timestamp::now();
    //计算秒数
    time_t seconds = static_cast<time_t>(now.microSecondsSinceEpoch() / Timestamp::kMicroSecondsPerSecond);
    int microseconds = static_cast<int>(now.microSecondsSinceEpoch() % Timestamp::kMicroSecondsPerSecond);
    //计算剩余微秒数
    struct tm *tm_timer = localtime(&seconds);
    // 写入此线程存储的时间buf中
    snprintf(ThreadInfo::t_timer, sizeof(ThreadInfo::t_timer), "%4d/%02d/%02d %02d:%02d:%02d",
             tm_timer->tm_year + 1900,
             tm_timer->tm_mon + 1,
             tm_timer->tm_mday,
             tm_timer->tm_hour,
             tm_timer->tm_min,
             tm_timer->tm_sec);
    // 更新最后一次时间调用
    ThreadInfo::t_lastSecond = seconds;

    // muduo使用Fmt格式化整数，这里我们直接写入buf
    char buf[32] = {0};
    snprintf(buf, sizeof(buf), "%06d ", microseconds);

    
    stream_ << GeneralTemplate(ThreadInfo::t_timer, 17) << GeneralTemplate(buf, 7);
}
void Logger::Impl::finish()
{
    stream_ << " - " << GeneralTemplate(basename_.data_, basename_.size_)
            << ':' << line_ << '\n';
}
Logger::Logger(const char *filename, int line, LogLevel level) : impl_(level, 0, filename, line)
{
}
//宏定义LOG_INFO等会调用Logger构造函数创建一个临时对象，构造函数会根据当前时间、日志等级、文件名和行号等信息初始化日志消息的开头部分，并将这些信息写入到日志流中。
//当这个临时对象在表达式结束后被销毁时，析构函数会被调用，完成日志消息的格式化和输出。
Logger::~Logger()
{
    impl_.finish();
    const LogStream::Buffer &buffer = stream().buffer();
    // 输出(默认项终端输出)
    g_output(buffer.data(), buffer.length());
    // FATAL情况终止程序
    if (impl_.level_ == FATAL)
    {
        g_flush();
        abort();
    }
}
//默认是stdout输出日志，可以通过调用Logger::setOutput和Logger::setFlush来设置自定义的输出函数和刷新函数，以实现将日志输出到文件、网络等其他目的地。
void Logger::setOutput(OutputFunc out)
{
    g_output = out;
}

void Logger::setFlush(FlushFunc flush)
{
    g_flush = flush;
}