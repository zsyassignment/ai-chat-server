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
find_package(OpenSSL REQUIRED)
if(EXISTS "/usr/bin/mysql_config")
    set(MYSQL_CONFIG_EXECUTABLE "/usr/bin/mysql_config")
else()
    find_program(MYSQL_CONFIG_EXECUTABLE mysql_config REQUIRED)
endif()

execute_process(
    COMMAND ${MYSQL_CONFIG_EXECUTABLE} --cflags
    OUTPUT_VARIABLE MYSQL_CFLAGS
    OUTPUT_STRIP_TRAILING_WHITESPACE
)
execute_process(
    COMMAND ${MYSQL_CONFIG_EXECUTABLE} --libs
    OUTPUT_VARIABLE MYSQL_LIBS
    OUTPUT_STRIP_TRAILING_WHITESPACE
)

separate_arguments(MYSQL_CFLAGS_LIST UNIX_COMMAND "${MYSQL_CFLAGS}")
separate_arguments(MYSQL_LIBS_LIST UNIX_COMMAND "${MYSQL_LIBS}")

set(MYSQL_INCLUDE_DIRS "")
set(MYSQL_COMPILE_OPTIONS "")
foreach(mysql_flag ${MYSQL_CFLAGS_LIST})
    if(mysql_flag MATCHES "^-I(.+)")
        list(APPEND MYSQL_INCLUDE_DIRS "${CMAKE_MATCH_1}")
    else()
        list(APPEND MYSQL_COMPILE_OPTIONS "${mysql_flag}")
    endif()
endforeach()

set(MYSQL_LIBRARY_DIRS "")
set(MYSQL_LINK_FLAGS "")
foreach(mysql_flag ${MYSQL_LIBS_LIST})
    if(mysql_flag MATCHES "^-L(.+)")
        list(APPEND MYSQL_LIBRARY_DIRS "${CMAKE_MATCH_1}")
    else()
        list(APPEND MYSQL_LINK_FLAGS "${mysql_flag}")
    endif()
endforeach()
list(REMOVE_DUPLICATES MYSQL_LIBRARY_DIRS)
list(REMOVE_DUPLICATES MYSQL_INCLUDE_DIRS)

#设置全局的c++标准
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED True)

if(MYSQL_COMPILE_OPTIONS)
    add_compile_options(${MYSQL_COMPILE_OPTIONS})
endif()
include_directories(${MYSQL_INCLUDE_DIRS})
link_directories(${MYSQL_LIBRARY_DIRS})

#设置头文件目录，供所有子项目使用
# 注意：确保你的 nlohmann/json.hpp 放在了这个 include 目录下
include_directories(${CMAKE_SOURCE_DIR}/include)

# 递归添加 include 子目录，兼容分层后的头文件布局
file(GLOB_RECURSE PROJECT_INCLUDE_DIRS LIST_DIRECTORIES true ${CMAKE_SOURCE_DIR}/include/*)
foreach(dir ${PROJECT_INCLUDE_DIRS})
    if(IS_DIRECTORY ${dir})
        include_directories(${dir})
    endif()
endforeach()

# 设置输出目录
set(CMAKE_RUNTIME_OUTPUT_DIRECTORY ${CMAKE_SOURCE_DIR}/bin)
set(CMAKE_LIBRARY_OUTPUT_DIRECTORY ${CMAKE_SOURCE_DIR}/lib)

#设置全局链接库
# 移除了 nlohmann_json::nlohmann_json，因为单头文件不需要链接库文件
set(LIBS
    pthread 
    CURL::libcurl
    OpenSSL::Crypto
    ${MYSQL_LINK_FLAGS}
)

#添加子目录使用
add_subdirectory(src)
add_subdirectory(memory)
add_subdirectory(log)
