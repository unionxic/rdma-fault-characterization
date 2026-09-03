/*
 * common3.h - Experiment 3 specific definitions
 *
 * Part of: GPU-Initiated RDMA Fault Recovery Research
 * Experiment 3: QP Recovery Overhead Decomposition
 *
 * Adds recovery coordination message types without modifying common.h.
 */

#ifndef COMMON3_H
#define COMMON3_H

#include "common.h"

/*
 * Recovery coordination messages.
 * Use values >= 50 to avoid colliding with ctrl_msg_type_t enum (1..10, 99).
 */
#define MSG_RECOVERY_INIT_DONE 50
#define MSG_RECOVERY_RTS_DONE  51

/* Default iterations for Experiment 3 */
#define DEFAULT_RECOVERY_ITERATIONS 100

#endif /* COMMON3_H */
