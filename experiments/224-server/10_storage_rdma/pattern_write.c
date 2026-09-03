/* [한국어 요약] 패턴 기록기 — target(224)에서 setup이 호출. 백킹 loop 디바이스의
 * 앞 N바이트에 4KB 블록마다 자기 오프셋을 식별할 수 있는 패턴(pattern.h)을
 * 써둔다. 나중에 initiator가 읽기 실패한 버퍼를 스캔할 때 "이 데이터가 어느
 * 오프셋에서 온 것인지"를 버퍼만 보고 판별하기 위한 사전 작업. */
/* pattern_write.c — write the offset-identifying pattern (see pattern.h) across
 * a backing file/device. Runs on the TARGET (224) during setup of the
 * MEDIA_ERROR_PARTIAL_READ scenario.
 *
 * Usage: pattern_write <path> <size_bytes>
 *   <path>       backing image path OR a loop device (must be safe: caller
 *                (target_setup.sh) has already asserted this is loop/file).
 *   <size_bytes> how many bytes to fill from offset 0 (block-aligned down).
 *
 * Writes sequentially in 4096-byte blocks; block i gets pattern_fill_block(i).
 * Exit 0 on success. This program does NOT open real disks itself — it trusts
 * the shell wrapper's safety asserts and simply writes what it is told.
 */
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <fcntl.h>
#include <unistd.h>
#include <errno.h>
#include <string.h>
#include "pattern.h"

int main(int argc, char **argv) {
    if (argc != 3) {
        fprintf(stderr, "usage: %s <path> <size_bytes>\n", argv[0]);
        return 2;
    }
    const char *path = argv[1];
    uint64_t size = strtoull(argv[2], NULL, 0);
    uint64_t nblocks = size / PAT_BLOCK;
    if (nblocks == 0) {
        fprintf(stderr, "pattern_write: size %llu < one block\n",
                (unsigned long long)size);
        return 2;
    }

    int fd = open(path, O_WRONLY);
    if (fd < 0) { perror("open"); return 1; }

    unsigned char *buf = NULL;
    if (posix_memalign((void **)&buf, 4096, PAT_BLOCK) != 0) {
        fprintf(stderr, "posix_memalign failed\n");
        close(fd);
        return 1;
    }

    for (uint64_t i = 0; i < nblocks; i++) {
        pattern_fill_block(buf, i);
        uint64_t off = i * (uint64_t)PAT_BLOCK;
        ssize_t w = pwrite(fd, buf, PAT_BLOCK, (off_t)off);
        if (w != (ssize_t)PAT_BLOCK) {
            fprintf(stderr, "pwrite at block %llu failed: %s\n",
                    (unsigned long long)i, strerror(errno));
            free(buf); close(fd);
            return 1;
        }
    }
    if (fsync(fd) != 0) { perror("fsync"); free(buf); close(fd); return 1; }
    free(buf);
    close(fd);
    fprintf(stderr, "pattern_write: wrote %llu blocks (%llu bytes)\n",
            (unsigned long long)nblocks, (unsigned long long)(nblocks * PAT_BLOCK));
    return 0;
}
