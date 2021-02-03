#pragma once

template <class T>
class Ring {
    T* buffer;
    unsigned int max_size = 0;
    unsigned int begin = 0;
    unsigned int length = 0;
public:
    Ring(T* buffer, unsigned int max_size) {
        this->buffer = buffer;
        this->max_size = max_size;
    }
    void push_back(const T& value) {
        if (length == max_size) {
            return;
        }
        unsigned int end = begin + length;
        if (end >= max_size) {
            end -= max_size;
        }
        buffer[end] = value;
        length++;
    }
    T pop_front() {
        const T value = buffer[begin];
        length--;
        begin++;
        if (begin == max_size) {
            begin = 0;
        }
        return value;
    }
    unsigned int size() const {
        return length;
    }
    void clear() {
        length = 0;
    }
};