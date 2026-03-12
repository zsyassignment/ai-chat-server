#include "memoryPool.h"

namespace memoryPool 
{
MemoryPool::MemoryPool(size_t BlockSize)
    : BlockSize_ (BlockSize)
{}

MemoryPool::~MemoryPool()
{
    // 把连续的block删除
    Slot* cur = firstBlock_;
    while (cur)
    {
        Slot* next = cur->next;
        // 等同于 free(reinterpret_cast<void*>(firstBlock_));
        // 转化为 void 指针，因为 void 类型不需要调用析构函数，只释放空间
        operator delete(reinterpret_cast<void*>(cur));
        cur = next;
    }
}

void MemoryPool::init(size_t size)
{
    assert(size > 0);
    SlotSize_ = size;
    firstBlock_ = nullptr;
    curSlot_ = nullptr;
    freeList_ = nullptr;
    lastSlot_ = nullptr;
}

void* MemoryPool::allocate()
{
    // 优先使用空闲链表中的内存槽
    //两次检查freeList_，第一次检查是为了避免不必要的锁操作，如果freeList_已经有空闲槽了，就直接使用，不需要加锁；
    //第二次检查是在加锁之后，可能其他线程已经修改了freeList_，所以需要再次检查以确保线程安全。
    if (freeList_ != nullptr)
    {
        {
            std::lock_guard<std::mutex> lock(mutexForFreeList_);
            if (freeList_ != nullptr)
            {
                Slot* temp = freeList_;
                freeList_ = freeList_->next;
                return temp;
            }
        }
    }

    Slot* temp;
    {   
        std::lock_guard<std::mutex> lock(mutexForBlock_);
        if (curSlot_ >= lastSlot_)
        {
            // 当前内存块已无内存槽可用，开辟一块新的内存
            allocateNewBlock();
        }
    
        temp = curSlot_;
        // 这里不能直接 curSlot_ += SlotSize_ 因为curSlot_是Slot*类型，所以需要除以SlotSize_再加1
        curSlot_ += SlotSize_ / sizeof(Slot);
    }
    
    return temp; 
}

void MemoryPool::deallocate(void* ptr)
{
    if (ptr)
    {
        // 回收内存，将内存通过头插法插入到空闲链表中
        std::lock_guard<std::mutex> lock(mutexForFreeList_);
        //直接把ptr转换成Slot*类型，并把它的next指针指向当前的freeList_，然后把freeList_指向这个新的空闲槽，这样就把这个槽插入到了空闲链表的头部
        reinterpret_cast<Slot*>(ptr)->next = freeList_;
        //头插法插入到空闲链表中，freeList_指向新的空闲槽
        freeList_ = reinterpret_cast<Slot*>(ptr);
    }
}

void MemoryPool::allocateNewBlock()
{   
    //std::cout << "申请一块内存块，SlotSize: " << SlotSize_ << std::endl;
    //operator new只是申请内存，不会调用构造函数，返回一个指向新分配内存的指针
    // 头插法插入新的内存块，强行把申请来的内存指针转换成Slot*类型，并把它的next指针指向当前的firstBlock_
    //然后把firstBlock_指向这个新的内存块，这样就把这个内存块插入到了内存块链表的头部
    void* newBlock = operator new(BlockSize_);
    reinterpret_cast<Slot*>(newBlock)->next = firstBlock_;
    firstBlock_ = reinterpret_cast<Slot*>(newBlock);

    char* body = reinterpret_cast<char*>(newBlock) + sizeof(Slot*);
    size_t paddingSize = padPointer(body, SlotSize_); // 计算对齐需要填充内存的大小
    curSlot_ = reinterpret_cast<Slot*>(body + paddingSize);

    // 超过该标记位置，则说明该内存块已无内存槽可用，需向系统申请新的内存块
    //起始位置+内存块大小是内存块的结束位置，减去槽大小是最后一个槽的起始位置，再加1是为了保证lastSlot_指向的地址不超过内存块的结束位置
    lastSlot_ = reinterpret_cast<Slot*>(reinterpret_cast<size_t>(newBlock) + BlockSize_ - SlotSize_ + 1);

    freeList_ = nullptr;
}

// 让指针对齐到槽大小的倍数位置
size_t MemoryPool::padPointer(char* p, size_t align)
{
    // align 是槽大小，假如 align 是 8，p 的地址是 0x0003，那么 (align - reinterpret_cast<size_t>(p)) % align 就是 (8 - 3) % 8 = 5，这样就需要填充 5 个字节才能让 p 对齐到下一个 8 的倍数位置，即 0x1008。
    return (align - reinterpret_cast<size_t>(p)) % align;
}

void HashBucket::initMemoryPool()
{
    for (int i = 0; i < MEMORY_POOL_NUM; i++)
    {
        getMemoryPool(i).init((i + 1) * SLOT_BASE_SIZE);
    }
}   

// 单例模式
MemoryPool& HashBucket::getMemoryPool(int index)
{
    //单例模式保证了内存池对象的唯一性和全局访问性，避免了重复创建内存池对象导致的资源浪费，同时也提供了一个统一的接口来获取内存池对象，使得代码更加简洁和易于维护。
    //通过static关键字，memoryPool数组在程序的整个生命周期内只会被创建一次，并且在第一次调用getMemoryPool函数时进行初始化，之后的调用都会返回同一个内存池对象，确保了内存池对象的唯一性和全局访问性。
    //它还是线程安全的因为C++11及以后的标准保证了函数内静态变量的初始化是线程安全的
    //所以在多线程环境下调用getMemoryPool函数时，不会出现多个线程同时创建内存池对象的情况，从而避免了资源浪费和潜在的竞争条件。
    static MemoryPool memoryPool[MEMORY_POOL_NUM];
    return memoryPool[index];
}

} // namespace memoryPool
