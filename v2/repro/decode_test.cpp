// Self-check of the CQE classification table (nvshmemi_ibgda_load_err). Host only, no GPU, no NIC:
//   g++ -std=c++17 -I nvshmem/src/include -I nvshmem/build/src/include -I /usr/local/cuda/include repro/decode_test.cpp -o /tmp/decode_test && /tmp/decode_test
#include <assert.h>
#include <stdio.h>
#include "device_host_transport/nvshmem_common_ibgda.h"

int main() {
    // syndrome, vendor_err, expected class. Rows 1-9 are the old cause numbers of RECORD.md section 4 as raw mlx5 syndromes.
    const struct { int syn, ven; nvshmemx_op_error_class_t want; } t[] = {
        {0x04, 0x53, NVSHMEMX_OP_ERROR_REQUEST},  {0x04, 0x52, NVSHMEMX_OP_ERROR_REQUEST}, {0x04, 0x33, NVSHMEMX_OP_ERROR_REQUEST},
        {0x05, 0xf5, NVSHMEMX_OP_ERROR_LOCAL_QP}, {0x12, 0x8a, NVSHMEMX_OP_ERROR_REQUEST}, {0x13, 0x88, NVSHMEMX_OP_ERROR_PEER},
        {0x16, 0x87, NVSHMEMX_OP_ERROR_PEER},     {0x15, 0x81, NVSHMEMX_OP_ERROR_PEER},
        {0x05, 0xf9, NVSHMEMX_OP_ERROR_UNKNOWN} /* trailing flush */, {0x22, 0x00, NVSHMEMX_OP_ERROR_UNKNOWN} /* unlisted */};
    nvshmemx_op_error_t e;
    for (auto& r : t) {
        uint64_t rec = NVSHMEMI_IBGDA_ERR_RECORD(0x123456, 0xbeef, r.syn, r.ven);
        assert(nvshmemi_ibgda_load_err(&rec, &e) == NVSHMEMX_SUCCESS);
        assert(e.error_class == r.want && e.qpn == 0x123456 && e.wqe_counter == 0xbeef && e.syndrome == r.syn && e.vendor_err == r.ven);
    }
    uint64_t rec = 0;
    assert(nvshmemi_ibgda_load_err(&rec, &e) == NVSHMEMX_SUCCESS && e.error_class == NVSHMEMX_OP_ERROR_NONE);
    assert(nvshmemi_ibgda_load_err(nullptr, &e) == NVSHMEMX_ERROR_NOT_SUPPORTED && e.error_class == NVSHMEMX_OP_ERROR_NONE);
    assert(nvshmemi_ibgda_load_err(&rec, nullptr) == NVSHMEMX_ERROR_INVALID_VALUE);
    puts("decode_test PASSED");
}
