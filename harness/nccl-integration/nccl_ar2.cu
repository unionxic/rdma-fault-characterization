// Minimal 2-rank NCCL all-reduce driver for the 2-node RoCE test.
// No MPI: rank 0 creates the ncclUniqueId and ships it to rank 1 over TCP
// (bootstrap/mgmt net), then both call ncclCommInitRank. Loops all-reduce so a
// peer kill mid-run exercises the patched IB completion path on the survivor.
//   usage: nccl_ar2 <rank 0|1> <peer_ip> <tcp_port> [iters] [count] [sleep_ms]
#include <nccl.h>
#include <cuda_runtime.h>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <unistd.h>
#include <arpa/inet.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <sys/socket.h>

#define CK(c)   do{ cudaError_t e=(c); if(e!=cudaSuccess){fprintf(stderr,"CUDA %s:%d %s\n",__FILE__,__LINE__,cudaGetErrorString(e));exit(1);} }while(0)
#define NK(c)   do{ ncclResult_t r=(c); if(r!=ncclSuccess){fprintf(stderr,"NCCL %s:%d %s\n",__FILE__,__LINE__,ncclGetErrorString(r));exit(2);} }while(0)

static int sendall(int fd,const void*b,size_t n){const char*p=(const char*)b;size_t o=0;while(o<n){ssize_t k=send(fd,p+o,n-o,0);if(k<=0)return -1;o+=k;}return 0;}
static int recvall(int fd,void*b,size_t n){char*p=(char*)b;size_t o=0;while(o<n){ssize_t k=recv(fd,p+o,n-o,0);if(k<=0)return -1;o+=k;}return 0;}

int main(int argc,char**argv){
  if(argc<4){fprintf(stderr,"usage: %s <rank 0|1> <peer_ip> <port> [iters] [count] [sleep_ms]\n",argv[0]);return 1;}
  int rank=atoi(argv[1]); const char*peer=argv[2]; int port=atoi(argv[3]);
  int iters=argc>4?atoi(argv[4]):20; size_t count=argc>5?strtoul(argv[5],0,10):(1<<20); int sleep_ms=argc>6?atoi(argv[6]):500;
  int one=1; ncclUniqueId id;

  if(rank==0){
    NK(ncclGetUniqueId(&id));
    int ls=socket(AF_INET,SOCK_STREAM,0); setsockopt(ls,SOL_SOCKET,SO_REUSEADDR,&one,sizeof one);
    sockaddr_in a{}; a.sin_family=AF_INET; a.sin_addr.s_addr=INADDR_ANY; a.sin_port=htons(port);
    if(bind(ls,(sockaddr*)&a,sizeof a)){perror("bind");return 1;} listen(ls,1);
    fprintf(stderr,"[rank0] waiting for rank1 on :%d\n",port);
    int cs=accept(ls,0,0); setsockopt(cs,IPPROTO_TCP,TCP_NODELAY,&one,sizeof one);
    if(sendall(cs,&id,sizeof id)){perror("send id");return 1;} close(cs); close(ls);
  } else {
    int cs=socket(AF_INET,SOCK_STREAM,0); sockaddr_in a{}; a.sin_family=AF_INET; a.sin_port=htons(port);
    inet_pton(AF_INET,peer,&a.sin_addr);
    while(connect(cs,(sockaddr*)&a,sizeof a)){usleep(200000); cs=socket(AF_INET,SOCK_STREAM,0); a.sin_family=AF_INET;a.sin_port=htons(port);inet_pton(AF_INET,peer,&a.sin_addr);}
    setsockopt(cs,IPPROTO_TCP,TCP_NODELAY,&one,sizeof one);
    if(recvall(cs,&id,sizeof id)){perror("recv id");return 1;} close(cs);
  }

  CK(cudaSetDevice(0));
  float *sbuf,*rbuf; CK(cudaMalloc(&sbuf,count*sizeof(float))); CK(cudaMalloc(&rbuf,count*sizeof(float)));
  float *h=(float*)malloc(count*sizeof(float)); for(size_t i=0;i<count;i++) h[i]=(rank+1);
  CK(cudaMemcpy(sbuf,h,count*sizeof(float),cudaMemcpyHostToDevice));
  cudaStream_t st; CK(cudaStreamCreate(&st));
  ncclComm_t comm; NK(ncclCommInitRank(&comm,2,id,rank));
  fprintf(stderr,"[rank%d] comm ready, %d iters count=%zu\n",rank,iters,count);

  for(int it=0; it<iters; it++){
    ncclResult_t r=ncclAllReduce(sbuf,rbuf,count,ncclFloat,ncclSum,comm,st);
    if(r!=ncclSuccess){fprintf(stderr,"[rank%d] iter %d ncclAllReduce -> %s\n",rank,it,ncclGetErrorString(r)); break;}
    cudaError_t ce=cudaStreamSynchronize(st);
    ncclResult_t as; ncclCommGetAsyncError(comm,&as);
    if(ce!=cudaSuccess || as!=ncclSuccess){
      fprintf(stderr,"[rank%d] iter %d sync=%s async=%s\n",rank,it,cudaGetErrorString(ce),ncclGetErrorString(as)); break;
    }
    CK(cudaMemcpy(h,rbuf,sizeof(float),cudaMemcpyDeviceToHost));
    fprintf(stderr,"[rank%d] iter %2d ok, rbuf[0]=%.0f (expect 3)\n",rank,it,h[0]);
    usleep(sleep_ms*1000);
  }
  fprintf(stderr,"[rank%d] done\n",rank);
  ncclCommDestroy(comm); cudaFree(sbuf); cudaFree(rbuf); free(h);
  return 0;
}
