#获取当前目录下的所有源文件项目
file(GLOB LOG_FILE ${CMAKE_CURRENT_SOURCE_DIR}/*cc)

#创建静态库或共享库
add_library(log_lib SHARED ${LOG_FILE})