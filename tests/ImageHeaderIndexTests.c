#include <CoreFoundation/CoreFoundation.h>
#include <assert.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>

static atomic_int fail_creation;
static CFMutableSetRef test_create_set(CFAllocatorRef allocator, CFIndex capacity,
                                      const CFSetCallBacks *callbacks) {
  assert(capacity == 0 && callbacks == NULL);
  if (atomic_load(&fail_creation)) return NULL;
  return CFSetCreateMutable(allocator, capacity, callbacks);
}

// Only creation failure is injected; ordinary operations use CoreFoundation.
#define CFSetCreateMutable test_create_set
#include "../src/ShadowCore.dylib/hooks/Universal/ImageHeaderIndex.h"
#undef CFSetCreateMutable

static shdw_image_header_index_t index_state = SHDW_IMAGE_HEADER_INDEX_INITIALIZER;
static atomic_int remaining_writers;
static atomic_uint errors;

// These intentionally unmapped addresses establish that no key is dereferenced.
static const void *key(unsigned value) {
  return (const void *)(uintptr_t)(0x10000u + (uintptr_t)value * 16u);
}

static void *reader(void *argument) {
  uintptr_t seed = (uintptr_t)argument;
  unsigned count = 0;
  do {
    unsigned value = (unsigned)((seed * 1103515245u + count * 12345u) % 12000u);
    int found = shdw_image_header_index_contains(&index_state, key(value));
    if (found != 0 && found != 1) atomic_fetch_add(&errors, 1);
    if (shdw_image_header_index_contains(&index_state, NULL) != 0)
      atomic_fetch_add(&errors, 1);
    count++;
  } while (atomic_load(&remaining_writers) || count < 20000);
  return NULL;
}

static void *writer(void *argument) {
  (void)argument;
  for (unsigned i = 0; i < 30000; i++) {
    if (i % 500 == 0 && shdw_image_header_index_reset(&index_state) != 1)
      atomic_fetch_add(&errors, 1);
    if (shdw_image_header_index_add(&index_state, key(i % 12000)) != 1)
      atomic_fetch_add(&errors, 1);
    if (shdw_image_header_index_remove(&index_state, key((i + 77) % 12000)) != 1)
      atomic_fetch_add(&errors, 1);
  }
  atomic_fetch_sub(&remaining_writers, 1);
  return NULL;
}

static void *resetter(void *argument) {
  (void)argument;
  for (unsigned i = 0; i < 1500; i++) {
    if (shdw_image_header_index_reset(&index_state) != 1)
      atomic_fetch_add(&errors, 1);
  }
  atomic_fetch_sub(&remaining_writers, 1);
  return NULL;
}

int main(void) {
  assert(shdw_image_header_index_contains(NULL, key(1)) == -1);
  assert(shdw_image_header_index_reset(NULL) == -1);
  assert(shdw_image_header_index_add(NULL, key(1)) == -1);
  assert(shdw_image_header_index_remove(NULL, key(1)) == -1);
  assert(shdw_image_header_index_contains(&index_state, key(1)) == -1);
  assert(shdw_image_header_index_add(&index_state, key(1)) == -1);
  assert(shdw_image_header_index_remove(&index_state, key(1)) == -1);
  assert(shdw_image_header_index_init(&index_state) == 1);
  assert(shdw_image_header_index_contains(&index_state, NULL) == 0);
  assert(shdw_image_header_index_add(&index_state, NULL) == 0);
  assert(shdw_image_header_index_remove(&index_state, NULL) == 0);
  assert(shdw_image_header_index_contains(&index_state, key(20000)) == 0);
  for (unsigned i = 0; i < 12000; i++) {
    assert(shdw_image_header_index_add(&index_state, key(i)) == 1);
    assert(shdw_image_header_index_add(&index_state, key(i)) == 1);
  }
  for (unsigned i = 0; i < 12000; i++)
    assert(shdw_image_header_index_contains(&index_state, key(i)) == 1);
  assert(CFSetGetCount(index_state.headers) == 12000);
  assert(shdw_image_header_index_remove(&index_state, key(7)) == 1);
  assert(shdw_image_header_index_contains(&index_state, key(7)) == 0);
  assert(shdw_image_header_index_contains(&index_state, key(8)) == 1);
  assert(shdw_image_header_index_add(&index_state, key(7)) == 1);
  assert(shdw_image_header_index_contains(&index_state, key(7)) == 1);
  atomic_store(&fail_creation, 1);
  assert(shdw_image_header_index_reset(&index_state) == -1);
  assert(shdw_image_header_index_contains(&index_state, key(7)) == -1);
  assert(shdw_image_header_index_add(&index_state, key(7)) == -1);
  assert(shdw_image_header_index_remove(&index_state, key(7)) == -1);
  atomic_store(&fail_creation, 0);
  assert(shdw_image_header_index_init(&index_state) == 1);
  assert(shdw_image_header_index_contains(&index_state, key(7)) == 0);
  assert(shdw_image_header_index_reset(&index_state) == 1);
  for (unsigned i = 0; i < 12000; i++)
    assert(shdw_image_header_index_contains(&index_state, key(i)) == 0);

  pthread_t readers[4], mutation, reset;
  atomic_store(&remaining_writers, 2);
  for (uintptr_t i = 0; i < 4; i++)
    assert(pthread_create(&readers[i], NULL, reader, (void *)(i + 1)) == 0);
  assert(pthread_create(&mutation, NULL, writer, NULL) == 0);
  assert(pthread_create(&reset, NULL, resetter, NULL) == 0);
  assert(pthread_join(mutation, NULL) == 0);
  assert(pthread_join(reset, NULL) == 0);
  for (unsigned i = 0; i < 4; i++) assert(pthread_join(readers[i], NULL) == 0);
  assert(atomic_load(&errors) == 0);
  assert(shdw_image_header_index_reset(&index_state) == 1);
  assert(shdw_image_header_index_contains(&index_state, key(7)) == 0);
  puts("ImageHeaderIndex: identity, growth, allocation fallback, reset and concurrent access passed");
  return 0;
}
