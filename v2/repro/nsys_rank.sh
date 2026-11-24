#!/bin/bash
# Runs the command under Nsight Systems on the MPI rank NSYS_RANK (default 0) and plainly on the others.
# env: NSYS_OUT (report path) NSYS_SEC (collection time, default 80; the program keeps running after it) NSYS_OPTS (more nsys options)
if [ "$OMPI_COMM_WORLD_RANK" = "${NSYS_RANK:-0}" ]; then
  exec nsys profile -o "$NSYS_OUT" --force-overwrite true --trace=cuda,nvtx,osrt --duration=${NSYS_SEC:-80} --kill=none $NSYS_OPTS "$@"
fi
exec "$@"
