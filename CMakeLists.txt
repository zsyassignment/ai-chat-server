# #顶层Cmake，设置全局链接库以及添加子目录，和项目的头文件.h位置
# #设置最低版本和项目名称
# cmake_minimum_required(VERSION 3.11)
# project(kama-webserver)

# include(FetchContent)
# find_package(CURL REQUIRED)

# # 引入 nlohmann/json (header-only)
# FetchContent_Declare(
#     nlohmann_json
#     URL https://github.com/nlohmann/json/releases/download/v3.11.3/json.tar.xz
# )
# FetchContent_MakeAvailable(nlohmann_json)

# #设置全局的c++标准
# set (CMAKE_CXX_STANDARD 17)
# set (CMAKE_CXX_STANDARD_REQUIRED True)

# #设置头文件目录，供所有子项目使用
# include_directories(${CMAKE_SOURCE_DIR}/include)

# # 设置输出目录
# set(CMAKE_RUNTIME_OUTPUT_DIRECTORY ${CMAKE_SOURCE_DIR}/bin)
# set(CMAKE_LIBRARY_OUTPUT_DIRECTORY ${CMAKE_SOURCE_DIR}/lib)

# #设置全局链接库
# set(LIBS
#     pthread 
#     CURL::libcurl
#     nlohmann_json::nlohmann_json
# )

# #添加子目录使用
# add_subdirectory(src)
# add_subdirectory(memory)
# add_subdirectory(log)

#顶层Cmake，设置全局链接库以及添加子目录，和项目的头文件.h位置
#设置最低版本和项目名称
cmake_minimum_required(VERSION 3.11)
project(kama-webserver)

find_package(CURL REQUIRED)

#设置全局的c++标准
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED True)

#设置头文件目录，供所有子项目使用
# 注意：确保你的 nlohmann/json.hpp 放在了这个 include 目录下
include_directories(${CMAKE_SOURCE_DIR}/include)

# 设置输出目录
set(CMAKE_RUNTIME_OUTPUT_DIRECTORY ${CMAKE_SOURCE_DIR}/bin)
set(CMAKE_LIBRARY_OUTPUT_DIRECTORY ${CMAKE_SOURCE_DIR}/lib)

#设置全局链接库
# 移除了 nlohmann_json::nlohmann_json，因为单头文件不需要链接库文件
set(LIBS
    pthread 
    CURL::libcurl
)

#添加子目录使用
add_subdirectory(src)
add_subdirectory(memory)
add_subdirectory(log)
