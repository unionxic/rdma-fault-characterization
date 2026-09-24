/*
 * tr_prm.h - copied from ../nvshmem_rootcause/nrc_prm.h (unchanged layouts) plus 2RST_QP; the subset of the mlx5 PRM command layouts that tr_probe.c needs, in the
 * mlx5_ifc "one byte per bit" convention that rdma-core's DEVX_SET/DEVX_GET macros use.
 *
 * Layouts copied from NVIDIA DOCA GPUNetIO's include/host/mlx5_ifc.h and mlx5_prm.h as
 * bundled in NCCL v2.32.3-1 (src/transport/net_ib/gdaki/doca-gpunetio, BSD-3-Clause,
 * Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES), which carry the newer qpc fields
 * (send_dbr_mode, cd_master, ...) that the Linux kernel's mlx5_ifc.h in MLNX OFED 23.10
 * lacks. query_cq and the q-counter commands are not in that file; they are copied from
 * MLNX OFED 23.10's include/linux/mlx5/mlx5_ifc.h (dual BSD/GPL). The three QP modify
 * commands (RST2INIT, INIT2RTR, RTR2RTS) share one layout, declared once as modify_qp_in.
 */
#ifndef TR_PRM_H
#define TR_PRM_H

#include <stdint.h>

typedef uint8_t u8;

enum {
    MLX5_CMD_OP_QUERY_HCA_CAP = 0x100,
    MLX5_CMD_OP_CREATE_CQ = 0x400,
    MLX5_CMD_OP_QUERY_CQ = 0x402,
    MLX5_CMD_OP_CREATE_QP = 0x500,
    MLX5_CMD_OP_RST2INIT_QP = 0x502,
    MLX5_CMD_OP_INIT2RTR_QP = 0x503,
    MLX5_CMD_OP_RTR2RTS_QP = 0x504,
    MLX5_CMD_OP_2ERR_QP = 0x507,
    MLX5_CMD_OP_2RST_QP = 0x50a,
    MLX5_CMD_OP_QUERY_QP = 0x50b,
    MLX5_CMD_OP_ALLOC_Q_COUNTER = 0x771,
    MLX5_CMD_OP_DEALLOC_Q_COUNTER = 0x772,
    MLX5_CMD_OP_QUERY_Q_COUNTER = 0x773,
};

enum {
    NRC_QPC_ST_RC = 0x0,
    NRC_QPC_PM_STATE_MIGRATED = 0x3,
    NRC_QPC_RQ_TYPE_REGULAR = 0x0,
    NRC_QPC_RQ_TYPE_SRQ = 0x1,
    NRC_QPC_RQ_TYPE_ZERO_SIZE_RQ = 0x3,
};

struct mlx5_ifc_ads_bits {
    u8 fl[0x1];
    u8 free_ar[0x1];
    u8 reserved_at_2[0xe];
    u8 pkey_index[0x10];

    u8 reserved_at_20[0x8];
    u8 grh[0x1];
    u8 mlid[0x7];
    u8 rlid[0x10];

    u8 ack_timeout[0x5];
    u8 reserved_at_45[0x3];
    u8 src_addr_index[0x8];
    u8 reserved_at_50[0x4];
    u8 stat_rate[0x4];
    u8 hop_limit[0x8];

    u8 reserved_at_60[0x4];
    u8 tclass[0x8];
    u8 flow_label[0x14];

    u8 rgid_rip[16][0x8];

    u8 reserved_at_100[0x4];
    u8 f_dscp[0x1];
    u8 f_ecn[0x1];
    u8 reserved_at_106[0x1];
    u8 f_eth_prio[0x1];
    u8 ecn[0x2];
    u8 dscp[0x6];
    u8 udp_sport[0x10];

    u8 dei_cfi[0x1];
    u8 eth_prio[0x3];
    u8 sl[0x4];
    u8 vhca_port_num[0x8];
    u8 rmac_47_32[0x10];

    u8 rmac_31_0[0x20];
};

struct mlx5_ifc_qpc_bits {
    u8 state[0x4];
    u8 lag_tx_port_affinity[0x4];
    u8 st[0x8];
    u8 reserved_at_10[0x2];
    u8 isolate_vl_tc[0x1];
    u8 pm_state[0x2];
    u8 reserved_at_15[0x1];
    u8 req_e2e_credit_mode[0x2];
    u8 offload_type[0x4];
    u8 end_padding_mode[0x2];
    u8 reserved_at_1e[0x2];

    u8 wq_signature[0x1];
    u8 block_lb_mc[0x1];
    u8 atomic_like_write_en[0x1];
    u8 latency_sensitive[0x1];
    u8 reserved_at_24[0x1];
    u8 drain_sigerr[0x1];
    u8 reserved_at_26[0x2];
    u8 pd[0x18];

    u8 mtu[0x3];
    u8 log_msg_max[0x5];
    u8 reserved_at_48[0x1];
    u8 log_rq_size[0x4];
    u8 log_rq_stride[0x3];
    u8 no_sq[0x1];
    u8 log_sq_size[0x4];
    u8 reserved_at_55[0x3];
    u8 ts_format[0x2];
    u8 data_in_order[0x1];
    u8 rlky[0x1];
    u8 ulp_stateless_offload_mode[0x4];

    u8 counter_set_id[0x8];
    u8 uar_page[0x18];

    u8 send_dbr_mode[0x2];
    u8 reserved_at_82[0x6];
    u8 user_index[0x18];

    u8 reserved_at_a0[0x3];
    u8 log_page_size[0x5];
    u8 remote_qpn[0x18];

    struct mlx5_ifc_ads_bits primary_address_path;

    struct mlx5_ifc_ads_bits secondary_address_path;

    u8 log_ack_req_freq[0x4];
    u8 reserved_at_384[0x4];
    u8 log_sra_max[0x3];
    u8 reserved_at_38b[0x2];
    u8 retry_count[0x3];
    u8 rnr_retry[0x3];
    u8 reserved_at_393[0x1];
    u8 fre[0x1];
    u8 cur_rnr_retry[0x3];
    u8 cur_retry_count[0x3];
    u8 reserved_at_39b[0x5];

    u8 reserved_at_3a0[0x20];

    u8 reserved_at_3c0[0x8];
    u8 next_send_psn[0x18];

    u8 reserved_at_3e0[0x8];
    u8 cqn_snd[0x18];

    u8 reserved_at_400[0x8];
    u8 deth_sqpn[0x18];

    u8 reserved_at_420[0x20];

    u8 reserved_at_440[0x8];
    u8 last_acked_psn[0x18];

    u8 reserved_at_460[0x8];
    u8 ssn[0x18];

    u8 reserved_at_480[0x8];
    u8 log_rra_max[0x3];
    u8 reserved_at_48b[0x1];
    u8 atomic_mode[0x4];
    u8 rre[0x1];
    u8 rwe[0x1];
    u8 rae[0x1];
    u8 reserved_at_493[0x1];
    u8 page_offset[0x6];
    u8 reserved_at_49a[0x3];
    u8 cd_slave_receive[0x1];
    u8 cd_slave_send[0x1];
    u8 cd_master[0x1];

    u8 reserved_at_4a0[0x3];
    u8 min_rnr_nak[0x5];
    u8 next_rcv_psn[0x18];

    u8 reserved_at_4c0[0x8];
    u8 xrcd[0x18];

    u8 reserved_at_4e0[0x8];
    u8 cqn_rcv[0x18];

    u8 dbr_addr[0x40];

    u8 q_key[0x20];

    u8 reserved_at_560[0x5];
    u8 rq_type[0x3];
    u8 srqn_rmpn_xrqn[0x18];

    u8 reserved_at_580[0x8];
    u8 rmsn[0x18];

    u8 hw_sq_wqebb_counter[0x10];
    u8 sw_sq_wqebb_counter[0x10];

    u8 hw_rq_counter[0x20];

    u8 sw_rq_counter[0x20];

    u8 reserved_at_600[0x20];

    u8 reserved_at_620[0xf];
    u8 cgs[0x1];
    u8 cs_req[0x8];
    u8 cs_res[0x8];

    u8 dc_access_key[0x40];

    u8 reserved_at_680[0x3];
    u8 dbr_umem_valid[0x1];

    u8 reserved_at_684[0x9c];

    u8 dbr_umem_id[0x20];
};

struct mlx5_ifc_create_qp_out_bits {
    u8 status[0x8];
    u8 reserved_at_8[0x18];
    u8 syndrome[0x20];
    u8 reserved_at_40[0x8];
    u8 qpn[0x18];
    u8 reserved_at_60[0x20];
};

struct mlx5_ifc_create_qp_in_bits {
    u8 opcode[0x10];
    u8 uid[0x10];
    u8 reserved_at_20[0x10];
    u8 op_mod[0x10];
    u8 reserved_at_40[0x40];
    u8 opt_param_mask[0x20];
    u8 reserved_at_a0[0x20];
    struct mlx5_ifc_qpc_bits qpc;
    u8 wq_umem_offset[0x40];
    u8 wq_umem_id[0x20];
    u8 wq_umem_valid[0x1];
    u8 reserved_at_861[0x1f];
};

/* rst2init / init2rtr / rtr2rts share one layout */
struct mlx5_ifc_modify_qp_in_bits {
    u8 opcode[0x10];
    u8 uid[0x10];
    u8 reserved_at_20[0x10];
    u8 op_mod[0x10];
    u8 reserved_at_40[0x8];
    u8 qpn[0x18];
    u8 reserved_at_60[0x20];
    u8 opt_param_mask[0x20];
    u8 reserved_at_a0[0x20];
    struct mlx5_ifc_qpc_bits qpc;
    u8 reserved_at_800[0x80];
};

struct mlx5_ifc_modify_qp_out_bits {
    u8 status[0x8];
    u8 reserved_at_8[0x18];
    u8 syndrome[0x20];
    u8 reserved_at_40[0x40];
};

struct mlx5_ifc_qp_2err_in_bits {
    u8 opcode[0x10];
    u8 uid[0x10];
    u8 vhca_tunnel_id[0x10];
    u8 op_mod[0x10];
    u8 reserved_at_40[0x8];
    u8 qpn[0x18];
    u8 reserved_at_60[0x20];
};

/* 2RST has the same layout as 2ERR */
struct mlx5_ifc_qp_2rst_in_bits {
    u8 opcode[0x10];
    u8 uid[0x10];
    u8 vhca_tunnel_id[0x10];
    u8 op_mod[0x10];
    u8 reserved_at_40[0x8];
    u8 qpn[0x18];
    u8 reserved_at_60[0x20];
};

struct mlx5_ifc_query_qp_out_bits {
    u8 status[0x8];
    u8 reserved_at_8[0x18];
    u8 syndrome[0x20];
    u8 reserved_at_40[0x40];
    u8 opt_param_mask[0x20];
    u8 reserved_at_a0[0x20];
    struct mlx5_ifc_qpc_bits qpc;
    u8 reserved_at_800[0x80];
    u8 pas[0x40];
};

struct mlx5_ifc_query_qp_in_bits {
    u8 opcode[0x10];
    u8 reserved_at_10[0x10];
    u8 reserved_at_20[0x10];
    u8 op_mod[0x10];
    u8 reserved_at_40[0x8];
    u8 qpn[0x18];
    u8 reserved_at_60[0x20];
};

struct mlx5_ifc_cqc_bits {
    u8 status[0x4];
    u8 as_notify[0x1];
    u8 initiator_src_dct[0x1];
    u8 dbr_umem_valid[0x1];
    u8 reserved_at_7[0x1];
    u8 cqe_sz[0x3];
    u8 cc[0x1];
    u8 reserved_at_c[0x1];
    u8 scqe_break_moderation_en[0x1];
    u8 oi[0x1];
    u8 cq_period_mode[0x2];
    u8 cqe_comp_en[0x1];
    u8 mini_cqe_res_format[0x2];
    u8 st[0x4];
    u8 reserved_at_18[0x1];
    u8 cqe_comp_layout[0x7];
    u8 dbr_umem_id[0x20];
    u8 reserved_at_40[0x14];
    u8 page_offset[0x6];
    u8 reserved_at_5a[0x2];
    u8 mini_cqe_res_format_ext[0x2];
    u8 cq_timestamp_format[0x2];
    u8 reserved_at_60[0x3];
    u8 log_cq_size[0x5];
    u8 uar_page[0x18];
    u8 reserved_at_80[0x4];
    u8 cq_period[0xc];
    u8 cq_max_count[0x10];
    u8 reserved_at_a0[0x18];
    u8 c_eqn[0x8];
    u8 reserved_at_c0[0x3];
    u8 log_page_size[0x5];
    u8 reserved_at_c8[0x18];
    u8 reserved_at_e0[0x20];
    u8 reserved_at_100[0x8];
    u8 last_notified_index[0x18];
    u8 reserved_at_120[0x8];
    u8 last_solicit_index[0x18];
    u8 reserved_at_140[0x8];
    u8 consumer_counter[0x18];
    u8 reserved_at_160[0x8];
    u8 producer_counter[0x18];
    u8 local_partition_id[0xc];
    u8 process_id[0x14];
    u8 reserved_at_1A0[0x20];
    u8 dbr_addr[0x40];
};

struct mlx5_ifc_create_cq_in_bits {
    u8 opcode[0x10];
    u8 uid[0x10];
    u8 reserved_at_20[0x10];
    u8 op_mod[0x10];
    u8 reserved_at_40[0x40];
    struct mlx5_ifc_cqc_bits cq_context;
    u8 cq_umem_offset[0x40];
    u8 cq_umem_id[0x20];
    u8 cq_umem_valid[0x1];
    u8 reserved_at_2e1[0x1f];
    u8 reserved_at_300[0x580];
};

struct mlx5_ifc_create_cq_out_bits {
    u8 status[0x8];
    u8 reserved_at_8[0x18];
    u8 syndrome[0x20];
    u8 reserved_at_40[0x8];
    u8 cqn[0x18];
    u8 reserved_at_60[0x20];
};

struct mlx5_ifc_query_cq_in_bits {
    u8 opcode[0x10];
    u8 reserved_at_10[0x10];
    u8 reserved_at_20[0x10];
    u8 op_mod[0x10];
    u8 reserved_at_40[0x8];
    u8 cqn[0x18];
    u8 reserved_at_60[0x20];
};

struct mlx5_ifc_query_cq_out_bits {
    u8 status[0x8];
    u8 reserved_at_8[0x18];
    u8 syndrome[0x20];
    u8 reserved_at_40[0x40];
    struct mlx5_ifc_cqc_bits cq_context;
    u8 reserved_at_280[0x600];
};

struct mlx5_ifc_alloc_q_counter_in_bits {
    u8 opcode[0x10];
    u8 uid[0x10];
    u8 reserved_at_20[0x10];
    u8 op_mod[0x10];
    u8 reserved_at_40[0x40];
};

struct mlx5_ifc_alloc_q_counter_out_bits {
    u8 status[0x8];
    u8 reserved_at_8[0x18];
    u8 syndrome[0x20];
    u8 reserved_at_40[0x18];
    u8 counter_set_id[0x8];
    u8 reserved_at_60[0x20];
};

struct mlx5_ifc_query_q_counter_in_bits {
    u8 opcode[0x10];
    u8 reserved_at_10[0x10];
    u8 reserved_at_20[0x10];
    u8 op_mod[0x10];
    u8 other_vport[0x1];
    u8 reserved_at_41[0xf];
    u8 vport_number[0x10];
    u8 reserved_at_60[0x60];
    u8 clear[0x1];
    u8 aggregate[0x1];
    u8 reserved_at_c2[0x1e];
    u8 reserved_at_e0[0x18];
    u8 counter_set_id[0x8];
};

struct mlx5_ifc_query_q_counter_out_bits {
    u8 status[0x8];
    u8 reserved_at_8[0x18];
    u8 syndrome[0x20];
    u8 reserved_at_40[0x40];
    u8 rx_write_requests[0x20];
    u8 reserved_at_a0[0x20];
    u8 rx_read_requests[0x20];
    u8 reserved_at_e0[0x20];
    u8 rx_atomic_requests[0x20];
    u8 reserved_at_120[0x20];
    u8 rx_dct_connect[0x20];
    u8 reserved_at_160[0x20];
    u8 out_of_buffer[0x20];
    u8 reserved_at_1a0[0x20];
    u8 out_of_sequence[0x20];
    u8 reserved_at_1e0[0x20];
    u8 duplicate_request[0x20];
    u8 reserved_at_220[0x20];
    u8 rnr_nak_retry_err[0x20];
    u8 reserved_at_260[0x20];
    u8 packet_seq_err[0x20];
    u8 reserved_at_2a0[0x20];
    u8 implied_nak_seq_err[0x20];
    u8 reserved_at_2e0[0x20];
    u8 local_ack_timeout_err[0x20];
    u8 reserved_at_320[0xa0];
    u8 resp_local_length_error[0x20];
    u8 req_local_length_error[0x20];
    u8 resp_local_qp_error[0x20];
    u8 local_operation_error[0x20];
    u8 resp_local_protection[0x20];
    u8 req_local_protection[0x20];
    u8 resp_cqe_error[0x20];
    u8 req_cqe_error[0x20];
    u8 req_mw_binding[0x20];
    u8 req_bad_response[0x20];
    u8 req_remote_invalid_request[0x20];
    u8 resp_remote_invalid_request[0x20];
    u8 req_remote_access_errors[0x20];
    u8 resp_remote_access_errors[0x20];
    u8 req_remote_operation_errors[0x20];
    u8 req_transport_retries_exceeded[0x20];
    u8 cq_overflow[0x20];
    u8 resp_cqe_flush_error[0x20];
    u8 req_cqe_flush_error[0x20];
    u8 reserved_at_620[0x20];
    u8 roce_adp_retrans[0x20];
    u8 roce_adp_retrans_to[0x20];
    u8 roce_slow_restart[0x20];
    u8 roce_slow_restart_cnps[0x20];
    u8 roce_slow_restart_trans[0x20];
    u8 reserved_at_6e0[0x120];
};

struct mlx5_ifc_dealloc_q_counter_in_bits {
    u8 opcode[0x10];
    u8 reserved_at_10[0x10];
    u8 reserved_at_20[0x10];
    u8 op_mod[0x10];
    u8 reserved_at_40[0x18];
    u8 counter_set_id[0x8];
    u8 reserved_at_60[0x20];
};

struct mlx5_ifc_dealloc_q_counter_out_bits {
    u8 status[0x8];
    u8 reserved_at_8[0x18];
    u8 syndrome[0x20];
    u8 reserved_at_40[0x40];
};

#endif
