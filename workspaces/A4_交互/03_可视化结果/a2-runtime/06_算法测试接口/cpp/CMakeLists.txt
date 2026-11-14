cmake_minimum_required(VERSION 3.16)
project(A2RoutePerformance LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

get_filename_component(INTERFACE_DIR "${CMAKE_CURRENT_SOURCE_DIR}/.." ABSOLUTE)
get_filename_component(A2_DIR "${INTERFACE_DIR}/.." ABSOLUTE)
set(ALGORITHM_DIR "${A2_DIR}/01_实现清单")

add_library(route_algorithms STATIC
    "${ALGORITHM_DIR}/dijkstra.cpp"
    "${ALGORITHM_DIR}/astar.cpp"
    "${ALGORITHM_DIR}/bidirectional_astar.cpp"
    "${ALGORITHM_DIR}/ch.cpp")
target_include_directories(route_algorithms PUBLIC "${ALGORITHM_DIR}")

add_executable(route_benchmark
    benchmark_main.cpp
    cache_io.cpp
    rgraph_io.cpp
    query_io.cpp)
target_include_directories(route_benchmark PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}")
target_link_libraries(route_benchmark PRIVATE route_algorithms)

if(MINGW)
    target_link_options(route_benchmark PRIVATE -municode)
endif()

if(MSVC)
    target_compile_options(route_algorithms PRIVATE /O2 /W4 /utf-8)
    target_compile_options(route_benchmark PRIVATE /O2 /W4 /utf-8)
else()
    target_compile_options(route_algorithms PRIVATE -O3 -Wall -Wextra -Wpedantic)
    target_compile_options(route_benchmark PRIVATE -O3 -Wall -Wextra -Wpedantic)
endif()
