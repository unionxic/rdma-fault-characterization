/* [한국어 요약] partial read 측정기 — MEDIA_ERROR_PARTIAL_READ 시나리오 전용.
 * 실패가 예상되는 대형 O_DIRECT pread 후, 버퍼에 실제 착지한 "유효 prefix"의
 * 길이를 바이트 단위로 알아낸다. 방법: (1) 버퍼를 0xA5로 미리 오염시켜 "전달
 * 안 됨"과 진짜 데이터를 구분, (2) target이 미리 써둔 오프셋 식별 패턴
 * (pattern.h)과 대조하며 앞에서부터 스캔. read()가 -1(EIO)만 주고 경계를 안
 * 알려주는 사각지대를 실측하는 도구다. */
/* check_partial_read.c — measure the VALID PREFIX of a partial NVMe-oF read
 * (initiator / node 225). For the MEDIA_ERROR_PARTIAL_READ scenario.
 *
 * The initiator issues ONE large O_DIRECT pread of <len> bytes at <offset> of
 * the connected fabric namespace. The target's namespace was pre-filled with the
 * offset-identifying pattern (pattern.h); a dm-dust bad block sits at the read's
 * midpoint. After the read (which is expected to fail with EIO), we scan the
 * buffer to find how many LEADING bytes were actually delivered intact — i.e.
 * whether NVMe-oF/RDMA left "partial data + error" in the initiator buffer
 * (Fable note 2), and exactly where the valid prefix ends.
 *
 * The buffer is pre-poisoned with 0xA5 so undelivered regions are distinguishable
 * from a legitimately zero payload (the pattern is never 0xA5A5...).
 *
 * Usage: check_partial_read <device> <offset_bytes> <len_bytes>
 * Output (one line, KEY=VAL, space-separated) on stdout:
 *   errno=<n> pread_ret=<n> valid_prefix_bytes=<n> first_bad_block=<n> \
 *   last_block_valid_bytes=<n> len=<n> offset=<n>
 * Exit 0 always (the read failing is the expected case); parse errno= to judge.
 *
 * NOTE: caller (run_storage_experiment.sh) has already asserted <device> is the
 * fabric namespace and NOT the boot disk.
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

/* O_DIRECT is Linux-only; define to 0 elsewhere so the file still compiles for
 * desk-checking on non-Linux hosts. On Linux the real flag is used. */
#ifndef O_DIRECT
#define O_DIRECT 0
#endif

int main(int argc, char **argv) {
    if (argc != 4) {
        fprintf(stderr, "usage: %s <device> <offset_bytes> <len_bytes>\n", argv[0]);
        return 2;
    }
    const char *dev = argv[1];
    uint64_t offset = strtoull(argv[2], NULL, 0);
    uint64_t len    = strtoull(argv[3], NULL, 0);
    if (len == 0 || (len % PAT_BLOCK) != 0 || (offset % PAT_BLOCK) != 0) {
        fprintf(stderr, "offset and len must be nonzero multiples of %u\n", PAT_BLOCK);
        return 2;
    }

    int fd = open(dev, O_RDONLY | O_DIRECT);
    if (fd < 0) {
        /* fall back to buffered if O_DIRECT unsupported, but note it */
        fprintf(stderr, "O_DIRECT open failed (%s); retrying buffered\n", strerror(errno));
        fd = open(dev, O_RDONLY);
        if (fd < 0) { perror("open"); return 1; }
    }

    unsigned char *buf = NULL;
    if (posix_memalign((void **)&buf, 4096, len) != 0) {
        fprintf(stderr, "posix_memalign(%llu) failed\n", (unsigned long long)len);
        close(fd);
        return 1;
    }
    memset(buf, 0xA5, len);   /* poison so undelivered bytes are recognizable */

    errno = 0;
    ssize_t r = pread(fd, buf, len, (off_t)offset);
    int saved_errno = errno;

    /* Scan block-by-block from the start; the valid prefix is the run of blocks
     * that carry the correct pattern. Stop at the first block that doesn't. */
    uint64_t nblocks = len / PAT_BLOCK;
    uint64_t base_block = offset / PAT_BLOCK;
    uint64_t valid_prefix = 0;
    int64_t first_bad_block = -1;
    unsigned last_block_valid_bytes = 0;

    for (uint64_t k = 0; k < nblocks; k++) {
        const unsigned char *blk = buf + k * (uint64_t)PAT_BLOCK;
        uint64_t expect_idx = base_block + k;
        if (pattern_block_ok(blk, expect_idx)) {
            valid_prefix += PAT_BLOCK;
        } else {
            first_bad_block = (int64_t)(base_block + k);
            /* how many bytes inside this last block were valid (record-granular) */
            last_block_valid_bytes = pattern_block_valid_bytes(blk, expect_idx);
            valid_prefix += last_block_valid_bytes;
            break;
        }
    }

    printf("errno=%d pread_ret=%zd valid_prefix_bytes=%llu first_bad_block=%lld "
           "last_block_valid_bytes=%u len=%llu offset=%llu\n",
           saved_errno, r,
           (unsigned long long)valid_prefix,
           (long long)first_bad_block,
           last_block_valid_bytes,
           (unsigned long long)len,
           (unsigned long long)offset);

    free(buf);
    close(fd);
    return 0;
}
