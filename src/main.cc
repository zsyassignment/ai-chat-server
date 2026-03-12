#include <string>

#include <Logger.h>
#include <sys/stat.h>
#include <algorithm>
#include <limits.h>
#include <sstream>
#include <thread>
#include <unistd.h>
#include <vector>

#include "AsyncLogging.h"
#include "HttpServer.h"
#include "LFU.h"
#include "TaskExecutor.h"
#include "openai.hpp"
#include "memoryPool.h"

// 日志文件滚动大小为1MB (1*1024*1024字节)
static const off_t kRollSize = 1*1024*1024;
AsyncLogging* g_asyncLog = NULL;
AsyncLogging * getAsyncLog(){
    return g_asyncLog;
}
 void asyncLog(const char* msg, int len)
{
    AsyncLogging* logging = getAsyncLog();
    if (logging)
    {
        logging->append(msg, len);
    }
}
int main(int argc,char *argv[]) {
    //第一步启动日志，双缓冲异步写入磁盘.
    //创建一个文件夹
    const std::string LogDir="logs";
    mkdir(LogDir.c_str(),0755);
    //使用std::stringstream 构建日志文件夹
    std::ostringstream LogfilePath;
    LogfilePath << LogDir << "/" << ::basename(argv[0]); // 完整的日志文件路径
    AsyncLogging log(LogfilePath.str(), kRollSize);
    g_asyncLog = &log;
    Logger::setOutput(asyncLog); // 为Logger设置输出回调, 重新配接输出位置
    log.start(); // 开启日志后端线程
    //第二步启动内存池和LFU缓存
    memoryPool::HashBucket::initMemoryPool();

    const int CACHE_CAPACITY = 128;
    KamaCache::KLfuCache<std::string, std::string> lfu(CACHE_CAPACITY);

    // 业务线程池，避免阻塞网络 I/O 线程
    size_t workerNum = std::max<size_t>(2, std::thread::hardware_concurrency());
    TaskExecutor executor(workerNum);
    executor.start();

    // OpenAI 客户端，API Key 从环境变量 OPENAI_API_KEY 读取
    OpenAIClient aiClient;
    aiClient.setModel("deepseek-chat");
    // 如果需要切换到 OpenAI 官方，可设置环境变量 OPENAI_BASE_URL=https://api.openai.com/v1/chat/completions 并选择对应模型

    // 选择静态资源目录：优先根据可执行文件位置推导
    auto pickStaticRoot = []() {
        std::vector<std::string> candidates;
        char exePath[PATH_MAX] = {0};
        ssize_t n = ::readlink("/proc/self/exe", exePath, sizeof(exePath) - 1);
        if (n > 0) {
            std::string exe(exePath, static_cast<size_t>(n));
            auto pos = exe.find_last_of('/');
            std::string exeDir = (pos == std::string::npos) ? std::string(".") : exe.substr(0, pos);
            candidates.push_back(exeDir + "/../www"); // if running from bin/
            candidates.push_back(exeDir + "/www");
        }
        candidates.push_back("./www");
        struct stat st;
        for (const auto& c : candidates) {
            if (::stat(c.c_str(), &st) == 0 && S_ISDIR(st.st_mode)) {
                return c;
            }
        }
        return std::string("./www");
    }();

    //第三步启动底层网络模块
    EventLoop loop;
    InetAddress addr(8080);
    HttpServer server(&loop, addr, "HttpServer", executor, aiClient, lfu, pickStaticRoot);
    server.setThreadNum(3);
    server.start();

    std::cout << "================================================Start Web Server================================================" << std::endl;
    loop.loop();
    std::cout << "================================================Stop Web Server=================================================" << std::endl;

    executor.stop();
    log.stop();
}