#ifndef SHADOW_IMAGE_HEADER_INDEX_H
#define SHADOW_IMAGE_HEADER_INDEX_H

#include <CoreFoundation/CoreFoundation.h>
#include <pthread.h>

// Initialize storage with the macro before sharing it. The mutex remains alive
// for the index's lifetime; reset replaces only the collection under that lock.
typedef struct {
  pthread_mutex_t mutex;
  CFMutableSetRef headers;
} shdw_image_header_index_t;

#define SHDW_IMAGE_HEADER_INDEX_INITIALIZER { PTHREAD_MUTEX_INITIALIZER, NULL }

// A failed creation makes membership unavailable, so callers can use their
// authoritative collection. Keys are opaque identities, never retained or read.
static inline int shdw_image_header_index_reset_with_allocator(
    shdw_image_header_index_t *index, CFAllocatorRef allocator) {
  if (!index) return -1;
  pthread_mutex_lock(&index->mutex);
  CFMutableSetRef fresh = CFSetCreateMutable(allocator, 0, NULL);
  CFMutableSetRef previous = index->headers;
  index->headers = fresh;
  if (previous) CFRelease(previous);
  int result = fresh ? 1 : -1;
  pthread_mutex_unlock(&index->mutex);
  return result;
}

static inline int shdw_image_header_index_reset(shdw_image_header_index_t *index) {
  return shdw_image_header_index_reset_with_allocator(index, kCFAllocatorDefault);
}

static inline int shdw_image_header_index_init(shdw_image_header_index_t *index) {
  return shdw_image_header_index_reset(index);
}

// Results: -1 unavailable, 0 absent (including NULL), 1 present.
static inline int shdw_image_header_index_contains(shdw_image_header_index_t *index,
                                                 const void *header) {
  if (!index) return -1;
  pthread_mutex_lock(&index->mutex);
  int result = !index->headers ? -1 :
      (header && CFSetContainsValue(index->headers, header) ? 1 : 0);
  pthread_mutex_unlock(&index->mutex);
  return result;
}

// Mutations return -1 when unavailable, 0 for a NULL key, otherwise 1.
static inline int shdw_image_header_index_add(shdw_image_header_index_t *index,
                                            const void *header) {
  if (!index) return -1;
  pthread_mutex_lock(&index->mutex);
  int result = !index->headers ? -1 : (header ? 1 : 0);
  if (result == 1) CFSetAddValue(index->headers, header);
  pthread_mutex_unlock(&index->mutex);
  return result;
}

static inline int shdw_image_header_index_remove(shdw_image_header_index_t *index,
                                               const void *header) {
  if (!index) return -1;
  pthread_mutex_lock(&index->mutex);
  int result = !index->headers ? -1 : (header ? 1 : 0);
  if (result == 1) CFSetRemoveValue(index->headers, header);
  pthread_mutex_unlock(&index->mutex);
  return result;
}

#endif
