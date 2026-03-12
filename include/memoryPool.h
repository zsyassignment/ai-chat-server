#pragma once 

#include <cassert>
#include <cstdint>
#include <iostream>
#include <memory>
#include <mutex>

namespace memoryPool
{
#define MEMORY_POOL_NUM 64
#define SLOT_BASE_SIZE 8
#define MAX_SLOT_SIZE 512
//小对象分片分配器 slab allocator
//64个内存池，槽大小分别为8, 16, 24, ..., 512字节，每个内存池管理一个链表，链表中的每个节点是一个内存块，内存块中包含多个槽，每个槽可以存放一个对象

/* 具体内存池的槽大小没法确定，因为每个内存池的槽大小不同(8的倍数)
   所以这个槽结构体的sizeof 不是实际的槽大小 */
   //内嵌空闲链表，包含下一个空闲块的指针，被分配给用户后就变成了用户数据区，用户数据区的前8字节被用来存储下一个空闲块的指针，这样就可以通过这个指针来管理空闲块的链表
struct Slot 
{
    Slot* next;
};

class MemoryPool
{
public:
    MemoryPool(size_t BlockSize = 4096);
    ~MemoryPool();
    
    void init(size_t);

    void* allocate();
    void deallocate(void*);
private:
    void allocateNewBlock();//没有内存块可用时，向系统申请新的内存块，化整为零减少系统调用次数
    size_t padPointer(char* p, size_t align);//让指针对齐到槽大小的倍数位置，减少内存碎片，提高内存利用率

private:
    int        BlockSize_; // 内存块大小
    int        SlotSize_; // 槽大小
    Slot*      firstBlock_; // 指向内存池管理的首个实际内存块
    Slot*      curSlot_; // 指向当前未被使用过的槽
    Slot*      freeList_; // 指向空闲的槽(被使用过后又被释放的槽)
    Slot*      lastSlot_; // 作为当前内存块中最后能够存放元素的位置标识(超过该位置需申请新的内存块)
    std::mutex mutexForFreeList_; // 保证freeList_在多线程中操作的原子性
    std::mutex mutexForBlock_; // 保证多线程情况下避免不必要的重复开辟内存导致的浪费行为
};


class HashBucket
{
public:
    static void initMemoryPool();
    static MemoryPool& getMemoryPool(int index);

    static void* useMemory(size_t size)
    {
        if (size <= 0)
            return nullptr;
        if (size > MAX_SLOT_SIZE) // 大于512字节的内存，则使用new
            return operator new(size);

        // 相当于size / 8 向上取整（因为分配内存只能大不能小
        return getMemoryPool(((size + 7) / SLOT_BASE_SIZE) - 1).allocate();
    }

    static void freeMemory(void* ptr, size_t size)
    {
        if (!ptr)
            return;
        if (size > MAX_SLOT_SIZE)
        {
            operator delete(ptr);
            return;
        }

        getMemoryPool(((size + 7) / SLOT_BASE_SIZE) - 1).deallocate(ptr);
    }
//变长模板友元函数，允许newElement和deleteElement访问HashBucket的私有成员函数getMemoryPool、useMemory和freeMemory，从而实现内存池的分配和回收功能
    template<typename T, typename... Args> 
    friend T* newElement(Args&&... args);
    
    template<typename T>
    friend void deleteElement(T* p);
};
//这两个模板不是MemoryPool类的成员函数，而是全局函数，提供了一个统一的接口来创建和销毁对象，隐藏了内存池的具体实现细节，使得用户在使用时更加方便和直观。
template<typename T, typename... Args>
T* newElement(Args&&... args)
{
    T* p = nullptr;
    // 根据元素大小选取合适的内存池分配内存
    if ((p = reinterpret_cast<T*>(HashBucket::useMemory(sizeof(T)))) != nullptr)
        // 在分配的内存上构造对象
        //std::forward<Args>(args)... 是完美转发，保持参数的左值或右值属性，确保对象被正确构造
        //解包参数包，传递给T的构造函数
        //使用定位new，因为普通new先分配内存再调用构造函数，而定位new允许我们在已经分配好的内存上直接调用构造函数
        //自己写的内存池已经分配好了内存不能再使用普通new了，否则就会浪费内存，所以使用定位new在分配好的内存上直接构造对象
        new(p) T(std::forward<Args>(args)...);

    return p;
}

template<typename T>
void deleteElement(T* p)
{
    // 对象析构
    if (p)
    {
        //使用定位new构造的对象也不能直接delete，因为delete会先调用析构函数再释放内存，而我们使用的内存池已经管理了内存的分配和回收
        //所以我们需要先调用析构函数来销毁对象，然后再通过内存池来回收内存
        p->~T();
         // 内存回收
        HashBucket::freeMemory(reinterpret_cast<void*>(p), sizeof(T));
    }
}

} // namespace memoryPool