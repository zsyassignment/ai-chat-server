#pragma once

#include <string>

#include "HttpResponse.h"

class StaticFileHandler {
public:
    explicit StaticFileHandler(const std::string& rootDir);
    bool handle(const std::string& urlPath, HttpResponse& resp) const;

private:
    std::string resolvePath(const std::string& urlPath) const;
    bool readFile(const std::string& fullPath, std::string& out) const;
    std::string detectMime(const std::string& path) const;

    std::string rootDir_; //静态文件根目录
};
