#获取当前目录下的所有源文件项目
file(GLOB_RECURSE SRC_FILE ${CMAKE_CURRENT_SOURCE_DIR}/*.cc)
list(REMOVE_ITEM SRC_FILE ${CMAKE_CURRENT_SOURCE_DIR}/app/main.cc)


# 创建共享库
add_library(src_lib SHARED ${SRC_FILE})
target_link_libraries(src_lib PUBLIC memory_lib log_lib ${LIBS})

#创建可执行文件
add_executable(main  app/main.cc)
target_link_libraries(main src_lib)

