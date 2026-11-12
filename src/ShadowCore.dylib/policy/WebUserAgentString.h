#pragma once

// WebKit's String return ABI is a single pointer with a nontrivial destructor.
// Only forward native factory/continuation prvalues: C++17 constructs directly
// in WebKit's return slot; the native caller owns and destroys the result.
// Deleted copy/move operations prevent accidental ownership copies here.
struct SHDWWebUserAgentString {
    void *implementation = nullptr;
    SHDWWebUserAgentString() = default;
    SHDWWebUserAgentString(const SHDWWebUserAgentString &) = delete;
    SHDWWebUserAgentString(SHDWWebUserAgentString &&) = delete;
    ~SHDWWebUserAgentString() {}
};
static_assert(sizeof(SHDWWebUserAgentString) == sizeof(void *), "WebKit String return size");
static_assert(alignof(SHDWWebUserAgentString) == alignof(void *), "WebKit String return alignment");
