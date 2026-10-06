# Where the barrier kernel waits (machine code)

Source: `cuobjdump -sass -arch sm_75 ~/gi-bundle/nvshmem_off380/lib_stock/libnvshmem_host.so.3.8.0`,
function `_Z36barrier_on_stream_kernel_threadgroupIL13threadgroup_t1EEvii` (warp scope, the variant the
host barrier launches). Offsets are relative to the start of the kernel, as cuda-gdb prints them.

```
/*1e50*/                   IMAD.WIDE R4, R6, 0x4, R4
/*1e60*/                   LDG.E.64.STRONG.SYS R6, [R38]
/*1e70*/                   LD.E.SYS R4, [R4]
/*1e80*/                   BMOV.32.CLEAR RZ, B0
/*1e90*/                   BSSY B0, 0x1f90
/*1ea0*/                   IADD3 R0, P0, R4, R30, RZ
/*1eb0*/                   LEA.HI.X.SX32 R9, R4, R17, 0x1, P0
/*1ec0*/                   LEA R8, P0, R0, c[0x3][0x68], 0x3
/*1ed0*/                   LEA.HI.X R9, R0, c[0x3][0x6c], R9, 0x3, P0
/*1ee0*/                   LDG.E.64.STRONG.SYS R4, [R8]
/*1ef0*/                   ISETP.GE.U32.AND P0, PT, R4, R6, PT
/*1f00*/                   ISETP.GE.AND.EX P0, PT, R5, R7, PT, P0
/*1f10*/               @P0 BRA 0x1f80
/*1f20*/                   VOTE.ANY R0, PT, PT
/*1f30*/                   YIELD
/*1f40*/                   VOTEU.ANY UR4, UPT, PT
/*1f50*/                   LOP3.LUT P0, RZ, R0, UR4, RZ, 0xc, !PT
/*1f60*/              @!P0 BRA.U 0x1ee0
/*1f70*/                   BRA 0x1f20
/*1f80*/                   BSYNC B0
/*1f90*/                   IADD3 R3, R3, R2, RZ
/*1fa0*/                   ISETP.GE.AND P0, PT, R3, 0x2, PT
/*1fb0*/               @P0 BRA 0x2020
```

Reading: lane 0 reloads a 64-bit value from an array whose base is a constant-bank pointer
(`c[0x3][0x68]`) plus an index, compares it with the expected count loaded before the loop, and
branches out only when it is greater or equal. After the loop the round counter is compared with 2,
the dissemination barrier for two PEs. Lanes 1 to 31 wait in `__cuda_sm70_warpsync`.
