/* [한국어 요약] 오프셋 식별 패턴 정의 — pattern_write.c(224, 기록)와
 * check_partial_read.c(225, 검사)가 공유. 두 사본(225/224)은 바이트 동일해야
 * 한다(패턴 불일치 = 측정 전체 무효). 4KB 블록 단위로 블록 번호를 인코딩. */
/* pattern.h — offset-identifying block pattern, SHARED SPEC.
 *
 * This exact file is duplicated in both mirrors:
 *   224/10_storage_rdma/pattern.h  (written by pattern_write.c on the target)
 *   225/10_storage_rdma/pattern.h  (verified by check_partial_read.c on the initiator)
 * They MUST stay byte-for-byte identical. If you change the layout, change both.
 *
 * Goal: give every 4096-byte block of the backing namespace a self-describing,
 * position-dependent content so that after a partial read the initiator can tell
 * *exactly* how many leading bytes were delivered intact (the valid prefix).
 *
 * Layout of one 4096-byte block at block index i (i = byte_offset / 4096):
 *   256 records of 16 bytes each:
 *     [0..7]  = PAT_MAGIC          (little-endian u64, constant)
 *     [8..15] = block_index i      (little-endian u64)
 * A block is "valid" iff ALL 256 records carry PAT_MAGIC and the correct index.
 * A short partial fill (e.g. delivered only the first 1500 bytes of a block) is
 * detected because the tail records do not match.
 */
#ifndef STORAGE_RDMA_PATTERN_H
#define STORAGE_RDMA_PATTERN_H

#include <stdint.h>
#include <string.h>

#define PAT_BLOCK     4096u
#define PAT_RECSZ     16u
#define PAT_RECS      (PAT_BLOCK / PAT_RECSZ)   /* 256 */
/* ASCII "PARTIAL!" as a little-endian u64 constant. */
#define PAT_MAGIC     0x21214C4149545241ULL     /* bytes: 41 52 54 49 41 4C 21 21 */

/* Fill a 4096-byte buffer with the pattern for block index i. */
static inline void pattern_fill_block(unsigned char *buf, uint64_t i) {
    uint64_t magic = PAT_MAGIC;
    unsigned r;
    for (r = 0; r < PAT_RECS; r++) {
        memcpy(buf + r * PAT_RECSZ + 0, &magic, 8);
        memcpy(buf + r * PAT_RECSZ + 8, &i, 8);
    }
}

/* Return 1 if the whole 4096-byte buffer matches the pattern for block i. */
static inline int pattern_block_ok(const unsigned char *buf, uint64_t i) {
    uint64_t magic, idx;
    unsigned r;
    for (r = 0; r < PAT_RECS; r++) {
        memcpy(&magic, buf + r * PAT_RECSZ + 0, 8);
        memcpy(&idx,   buf + r * PAT_RECSZ + 8, 8);
        if (magic != PAT_MAGIC || idx != i) return 0;
    }
    return 1;
}

/* Return the number of leading VALID BYTES within a single block buffer for
 * block index i: PAT_BLOCK if fully valid, else the offset of the first record
 * that fails to match (record-granular, 16B). Used to pin the partial boundary
 * inside the last touched block. */
static inline unsigned pattern_block_valid_bytes(const unsigned char *buf, uint64_t i) {
    uint64_t magic, idx;
    unsigned r;
    for (r = 0; r < PAT_RECS; r++) {
        memcpy(&magic, buf + r * PAT_RECSZ + 0, 8);
        memcpy(&idx,   buf + r * PAT_RECSZ + 8, 8);
        if (magic != PAT_MAGIC || idx != i) return r * PAT_RECSZ;
    }
    return PAT_BLOCK;
}

#endif /* STORAGE_RDMA_PATTERN_H */
