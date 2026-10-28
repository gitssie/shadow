#define _POSIX_C_SOURCE 200809L
#define _DARWIN_C_SOURCE 1
#include <assert.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>

#include "../src/Shadow.framework/Headers/Shadow/RuntimeImageIdentity.h"

static int descriptor_count(void) {
  int count = 0;
  for (int fd = 0; fd < 256; fd++)
    if (fcntl(fd, F_GETFD) != -1)
      count++;
  return count;
}

static void check(const char *first, const char *second, bool expected) {
  int before = descriptor_count();
  errno = EDOM;
  assert(shdw_runtime_image_same_file(first, second) == expected);
  assert(errno == EDOM);
  assert(descriptor_count() == before);
}

int main(void) {
  char directory[] = "/tmp/shadow-runtime-image-XXXXXX";
  assert(mkdtemp(directory));
  char file[PATH_MAX], hard[PATH_MAX], symbolic[PATH_MAX];
  char other[PATH_MAX], absent[PATH_MAX], fifo[PATH_MAX];
  snprintf(file, sizeof(file), "%s/file", directory);
  snprintf(hard, sizeof(hard), "%s/hard", directory);
  snprintf(symbolic, sizeof(symbolic), "%s/symbolic", directory);
  snprintf(other, sizeof(other), "%s/other", directory);
  snprintf(absent, sizeof(absent), "%s/absent", directory);
  snprintf(fifo, sizeof(fifo), "%s/fifo", directory);
  int fd = open(file, O_CREAT | O_EXCL | O_WRONLY, 0600);
  assert(fd >= 0);
  assert(write(fd, "a", 1) == 1);
  assert(close(fd) == 0);
  fd = open(other, O_CREAT | O_EXCL | O_WRONLY, 0600);
  assert(fd >= 0);
  assert(write(fd, "a", 1) == 1);
  assert(close(fd) == 0);
  assert(link(file, hard) == 0);
  assert(symlink(file, symbolic) == 0);
  assert(mkfifo(fifo, 0600) == 0);

  check(file, file, true);
  check(file, hard, true);
  check(file, symbolic, true);
  check(file, other, false);
  check(file, absent, false);
  check(absent, file, false);
  check(NULL, file, false);
  check(file, NULL, false);
  check(directory, directory, false);
  check(fifo, fifo, false);
  for (int i = 0; i < 100; i++) {
    check(file, absent, false);
    check(file, hard, true);
  }

  int first_fd = open(file, O_RDWR);
  int second_fd = open(other, O_RDWR);
  assert(first_fd >= 0 && second_fd >= 0);
  errno = EDOM;
  assert(shdw_runtime_image_contents_match(first_fd, second_fd));
  assert(errno == EDOM);
  char contents[9001];
  for (size_t i = 0; i < sizeof(contents); i++)
    contents[i] = (char)(i % 251);
  assert(pwrite(first_fd, contents, sizeof(contents), 0) == sizeof(contents));
  assert(pwrite(second_fd, contents, sizeof(contents), 0) == sizeof(contents));
  assert(lseek(first_fd, 17, SEEK_SET) == 17);
  assert(lseek(second_fd, 23, SEEK_SET) == 23);
  assert(shdw_runtime_image_contents_match(first_fd, second_fd));
  assert(lseek(first_fd, 0, SEEK_CUR) == 17);
  assert(lseek(second_fd, 0, SEEK_CUR) == 23);
  char changed = (char)(contents[9000] ^ 1);
  assert(pwrite(second_fd, &changed, 1, 9000) == 1);
  assert(!shdw_runtime_image_contents_match(first_fd, second_fd));
  assert(pwrite(second_fd, contents + 9000, 1, 9000) == 1);
  assert(ftruncate(second_fd, 9000) == 0);
  assert(!shdw_runtime_image_contents_match(first_fd, second_fd));
  assert(ftruncate(first_fd, 0) == 0);
  assert(ftruncate(second_fd, 0) == 0);
  assert(!shdw_runtime_image_contents_match(first_fd, second_fd));
  assert(ftruncate(first_fd, 4 * 1024 * 1024 + 1) == 0);
  assert(ftruncate(second_fd, 4 * 1024 * 1024 + 1) == 0);
  assert(!shdw_runtime_image_contents_match(first_fd, second_fd));
  struct stat before_write, after_write;
  assert(fstat(first_fd, &before_write) == 0);
  assert(ftruncate(first_fd, 1) == 0);
  assert(fstat(first_fd, &after_write) == 0);
  assert(!shdw_runtime_image_stat_unchanged(&before_write, &after_write));
  errno = EDOM;
  assert(!shdw_runtime_image_contents_match(-1, second_fd));
  assert(errno == EDOM);
  assert(close(first_fd) == 0);
  assert(close(second_fd) == 0);

  struct stat first, second;
  assert(stat(file, &first) == 0);
  second = first;
  second.st_dev = first.st_dev + 1;
  assert(!shdw_runtime_image_records_match(&first, &second, NULL, NULL));
  assert(!shdw_runtime_image_records_match(&first, &second, "", ""));
  assert(!shdw_runtime_image_records_match(&first, &second, file, other));
  assert(shdw_runtime_image_records_match(&first, &second, file, file));
  second.st_ino++;
  assert(!shdw_runtime_image_records_match(&first, &second, file, file));
  second = first;
  second.st_mode = S_IFDIR | 0700;
  assert(!shdw_runtime_image_records_match(&first, &second, file, file));

  assert(unlink(symbolic) == 0);
  assert(unlink(hard) == 0);
  assert(unlink(file) == 0);
  assert(unlink(other) == 0);
  assert(unlink(fifo) == 0);
  assert(rmdir(directory) == 0);
  puts("runtime image identity: pinned files, links, mount records, bounded content comparison, metadata stability, errno and descriptor cleanup passed");
  return 0;
}
