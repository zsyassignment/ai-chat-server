#获取当前目录下的所有源文件项目
file(GLOB MEMORY_FILE ${CMAKE_CURRENT_SOURCE_DIR}/*cc)

#创建静态库或共享库
add_library(memory_lib SHARED ${MEMORY_FILE})