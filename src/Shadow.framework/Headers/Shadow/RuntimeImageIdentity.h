#ifndef SHADOW_RUNTIME_IMAGE_IDENTITY_H
#define SHADOW_RUNTIME_IMAGE_IDENTITY_H

#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <stdbool.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

static inline bool shdw_runtime_image_stat_unchanged(const struct stat *before,
                                                     const struct stat *after) {
  if (before->st_dev != after->st_dev || before->st_ino != after->st_ino ||
      before->st_mode != after->st_mode || before->st_size != after->st_size)
    return false;
#if defined(__APPLE__)
  return before->st_mtimespec.tv_sec == after->st_mtimespec.tv_sec &&
         before->st_mtimespec.tv_nsec == after->st_mtimespec.tv_nsec &&
         before->st_ctimespec.tv_sec == after->st_ctimespec.tv_sec &&
         before->st_ctimespec.tv_nsec == after->st_ctimespec.tv_nsec;
#else
  return before->st_mtim.tv_sec == after->st_mtim.tv_sec &&
         before->st_mtim.tv_nsec == after->st_mtim.tv_nsec &&
         before->st_ctim.tv_sec == after->st_ctim.tv_sec &&
         before->st_ctim.tv_nsec == after->st_ctim.tv_nsec;
#endif
}

static inline bool shdw_runtime_image_pread_exact(int fd, void *buffer,
                                                  size_t size, off_t offset) {
  size_t read_size = 0;
  while (read_size < size) {
    ssize_t amount = pread(fd, (char *)buffer + read_size, size - read_size,
                           offset + (off_t)read_size);
    if (amount < 0 && errno == EINTR)
      continue;
    if (amount <= 0)
      return false;
    read_size += (size_t)amount;
  }
  return true;
}

static inline bool shdw_runtime_image_contents_match(int first_fd,
                                                      int second_fd) {
  int saved_errno = errno;
  bool matches = false;
  struct stat first, second, first_after, second_after;
  if (fstat(first_fd, &first) != 0 || fstat(second_fd, &second) != 0 ||
      !S_ISREG(first.st_mode) || !S_ISREG(second.st_mode) ||
      first.st_size <= 0 || first.st_size != second.st_size ||
      first.st_size > 4 * 1024 * 1024)
    goto done;
  for (off_t offset = 0; offset < first.st_size;) {
    char first_buffer[4096], second_buffer[4096];
    off_t remaining = first.st_size - offset;
    size_t size = remaining < (off_t)sizeof(first_buffer)
                      ? (size_t)remaining : sizeof(first_buffer);
    if (!shdw_runtime_image_pread_exact(first_fd, first_buffer, size, offset) ||
        !shdw_runtime_image_pread_exact(second_fd, second_buffer, size, offset) ||
        memcmp(first_buffer, second_buffer, size) != 0)
      goto done;
    offset += (off_t)size;
  }
  matches = fstat(first_fd, &first_after) == 0 &&
            fstat(second_fd, &second_after) == 0 &&
            shdw_runtime_image_stat_unchanged(&first, &first_after) &&
            shdw_runtime_image_stat_unchanged(&second, &second_after);
done:
  errno = saved_errno;
  return matches;
}

static inline bool shdw_runtime_image_records_match(
    const struct stat *first, const struct stat *second,
    const char *first_kernel_path, const char *second_kernel_path) {
  if (!S_ISREG(first->st_mode) || !S_ISREG(second->st_mode) ||
      first->st_ino != second->st_ino)
    return false;
  if (first->st_dev == second->st_dev)
    return true;
  return first_kernel_path && second_kernel_path && first_kernel_path[0] &&
         second_kernel_path[0] &&
         strcmp(first_kernel_path, second_kernel_path) == 0;
}

static inline bool shdw_runtime_image_same_file(const char *first_path,
                                                const char *second_path) {
  int saved_errno = errno;
  int first_fd = -1, second_fd = -1;
  bool matches = false;
  struct stat first, second;
  if (!first_path || !second_path)
    goto done;
  first_fd = open(first_path, O_RDONLY | O_NONBLOCK | O_CLOEXEC);
  if (first_fd < 0)
    goto done;
  second_fd = open(second_path, O_RDONLY | O_NONBLOCK | O_CLOEXEC);
  if (second_fd < 0 || fstat(first_fd, &first) != 0 ||
      fstat(second_fd, &second) != 0)
    goto done;
  matches = shdw_runtime_image_records_match(&first, &second, NULL, NULL);
#if defined(F_GETPATH)
  if (!matches && S_ISREG(first.st_mode) && S_ISREG(second.st_mode) &&
      first.st_ino == second.st_ino) {
    char first_kernel_path[PATH_MAX] = {0};
    char second_kernel_path[PATH_MAX] = {0};
    if (fcntl(first_fd, F_GETPATH, first_kernel_path) == 0 &&
        fcntl(second_fd, F_GETPATH, second_kernel_path) == 0 &&
        memchr(first_kernel_path, '\0', sizeof(first_kernel_path)) &&
        memchr(second_kernel_path, '\0', sizeof(second_kernel_path)))
      matches = shdw_runtime_image_records_match(
          &first, &second, first_kernel_path, second_kernel_path);
  }
#endif
  if (!matches && S_ISREG(first.st_mode) && S_ISREG(second.st_mode) &&
      first.st_ino == second.st_ino && first.st_dev != second.st_dev)
    matches = shdw_runtime_image_contents_match(first_fd, second_fd);
done:
  if (second_fd >= 0)
    close(second_fd);
  if (first_fd >= 0)
    close(first_fd);
  errno = saved_errno;
  return matches;
}

#endif
