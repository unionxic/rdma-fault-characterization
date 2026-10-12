// rs_spare_unit.cc - CPU unit test of the spare branch's pure functions (gin-restore work package 8, EXPERIMENT.md 9.3,
// 9.10.5, 9.11.3 M4). build_rs_spare.sh unit cuts the region between the two "gin-restore (rs, work package 8, spare
// branch): pure functions" markers of gin_host_gdaki.cc into rs_spare_pure.inc and compiles it here, so the test runs the
// library's own text. No NCCL, no CUDA, no network.
// Coverage: the activation gate (gdakiRsActExamine: absent, zombie/dead, reused PID, alive, no recorded start, no PID);
// the REJOIN record validation (gdakiRsRejoinValidate: version, nonce, incarnation, QP count, QPN match); the two-sided
// token-exchange state sequence (gdakiRsXchgStep: the legal order, out-of-order, nothing after RESTORED) and a CPU
// simulation of the exchange through the library's pure pieces (gdakiRsTokenMatch for READY against REJOIN,
// gdakiRsBuildCommitToken) against a model of ncclGinRecoverCommit's check and reconnect, showing both PSN directions
// agree; the spare's setup record against the transcript (gdakiRsSpareSetupMatch); the endpoint's wire layout. Plus a
// model of the init transcript's divergence detection and masked own-slot comparison, mirroring src/misc/rs_spike.cc's
// nextEntry and compareOwn (the feasibility test B1, 9.15.4, ran that code end-to-end on the cluster; this checks the
// rule only, not that file's text).
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <string>
#include <vector>

#include <algorithm>
#include <chrono>
#include <condition_variable>
#include <mutex>
#include <thread>

enum { GDAKI_POLICY_FAILFAST = 0, GDAKI_POLICY_HOLD = 1 };  // hk's line (as impl/rs_unit.cc)
#include "nccl_device/gin/gdaki/gin_gdaki_device_host_common.h"
#include "rs_pure.inc"  // packages 1-4: the Resume local check this package changes
#include "rs_spare_pure.inc"

static int nChecks = 0, nFail = 0;
#define CHECK(c) do { nChecks++; if (!(c)) { nFail++; fprintf(stderr, "FAIL %s:%d: %s\n", __FILE__, __LINE__, #c); } } while (0)
static bool has(const char* s, const char* sub) { return strstr(s, sub) != nullptr; }

// ---- the activation gate (9.10.5) ----
static void testActivate() {
  char why[192];
  struct gdakiRsActProbe p;
  // no PID to check: cannot confirm the original is gone -> wait (never activate on an assertion alone)
  CHECK(gdakiRsActExamine(0, 0, p, why, sizeof(why)) == GDAKI_RS_ACT_WAIT && has(why, "no PID"));
  CHECK(gdakiRsActExamine(-1, 123, p, why, sizeof(why)) == GDAKI_RS_ACT_WAIT);
  // /proc absent -> gone
  p = gdakiRsActProbe();
  p.exists = false;
  CHECK(gdakiRsActExamine(4242, 555, p, why, sizeof(why)) == GDAKI_RS_ACT_GO && has(why, "gone"));
  // a zombie or a dead task not reaped -> gone
  p.exists = true;
  p.start = 555;
  p.state = 'Z';
  CHECK(gdakiRsActExamine(4242, 555, p, why, sizeof(why)) == GDAKI_RS_ACT_GO && has(why, "zombie"));
  p.state = 'X';
  CHECK(gdakiRsActExamine(4242, 555, p, why, sizeof(why)) == GDAKI_RS_ACT_GO && has(why, "dead task"));
  // the PID was reused: a live process with a different start time -> the original is gone
  p.state = 'S';
  p.start = 999;
  CHECK(gdakiRsActExamine(4242, 555, p, why, sizeof(why)) == GDAKI_RS_ACT_GO && has(why, "reused"));
  // alive with the recorded start time -> never activate
  p.start = 555;
  p.state = 'R';
  CHECK(gdakiRsActExamine(4242, 555, p, why, sizeof(why)) == GDAKI_RS_ACT_WAIT && has(why, "still alive"));
  p.state = 'S';
  CHECK(gdakiRsActExamine(4242, 555, p, why, sizeof(why)) == GDAKI_RS_ACT_WAIT);
  // alive but no start time was recorded: cannot confirm it is gone -> wait (conservative)
  CHECK(gdakiRsActExamine(4242, 0, p, why, sizeof(why)) == GDAKI_RS_ACT_WAIT && has(why, "cannot confirm"));
}

// ---- the REJOIN record validation (RL6) ----
static void testRejoinValidate() {
  char why[192];
  const uint64_t ctxNonce = 0xabcdef0123456789ull;
  uint32_t own[4] = {0x100, 0x101, 0x102, 0x103};
  uint32_t rec[4] = {0x100, 0x101, 0x102, 0x103};  // the spare's recorded view of this rank's QPNs
  // valid: version 1, right nonce, incarnation known+1, QP count and QPNs match
  CHECK(gdakiRsRejoinValidate(1u, ctxNonce, ctxNonce, 1u, 0u, 4, 4, rec, own, why, sizeof(why)) && has(why, "valid"));
  // a later incarnation (known already 2, REJOIN 3)
  CHECK(gdakiRsRejoinValidate(1u, ctxNonce, ctxNonce, 3u, 2u, 4, 4, rec, own, why, sizeof(why)));
  // wrong version
  CHECK(!gdakiRsRejoinValidate(2u, ctxNonce, ctxNonce, 1u, 0u, 4, 4, rec, own, why, sizeof(why)) && has(why, "version"));
  // foreign nonce
  CHECK(!gdakiRsRejoinValidate(1u, ctxNonce ^ 1, ctxNonce, 1u, 0u, 4, 4, rec, own, why, sizeof(why)) && has(why, "nonce"));
  // wrong incarnation (not known+1)
  CHECK(!gdakiRsRejoinValidate(1u, ctxNonce, ctxNonce, 2u, 0u, 4, 4, rec, own, why, sizeof(why)) && has(why, "incarnation"));
  CHECK(!gdakiRsRejoinValidate(1u, ctxNonce, ctxNonce, 0u, 0u, 4, 4, rec, own, why, sizeof(why)));
  // QP count mismatch
  CHECK(!gdakiRsRejoinValidate(1u, ctxNonce, ctxNonce, 1u, 0u, 3, 4, rec, own, why, sizeof(why)) && has(why, "QP count"));
  // a QPN the spare recorded for this rank does not match this rank's live QPN
  rec[2] = 0x999;
  CHECK(!gdakiRsRejoinValidate(1u, ctxNonce, ctxNonce, 1u, 0u, 4, 4, rec, own, why, sizeof(why)) && has(why, "QPN"));
}

// ---- the two-sided token-exchange state sequence (9.11.3 M4) ----
static void testXchgSequence() {
  const int order[] = {GDAKI_RS_EV_REJOIN, GDAKI_RS_EV_PREPARE, GDAKI_RS_EV_READY, GDAKI_RS_EV_SWAP, GDAKI_RS_EV_COMMIT,
                       GDAKI_RS_EV_BASELINE, GDAKI_RS_EV_RKEYS, GDAKI_RS_EV_PUBLISH, GDAKI_RS_EV_RESTORED};
  // the legal order walks HELD -> ... -> RESTORED
  int st = GDAKI_RS_XS_HELD;
  for (int i = 0; i < 9; i++) {
    st = gdakiRsXchgStep(st, order[i]);
    CHECK(st == i + 1);
  }
  CHECK(st == GDAKI_RS_XS_RESTORED);
  // nothing follows RESTORED
  CHECK(gdakiRsXchgStep(GDAKI_RS_XS_RESTORED, GDAKI_RS_EV_REJOIN) == GDAKI_RS_XS_FAIL);
  // any out-of-order event fails: from each state, every event other than the one that advances it
  for (int s = GDAKI_RS_XS_HELD; s <= GDAKI_RS_XS_PUBLISHED; s++)
    for (int ev = GDAKI_RS_EV_REJOIN; ev <= GDAKI_RS_EV_RESTORED; ev++)
      if (ev != order[s]) CHECK(gdakiRsXchgStep(s, ev) == GDAKI_RS_XS_FAIL);
}

// A CPU simulation of the two-sided exchange, through the library's own pure pieces: the spare announces its QPNs and send
// PSNs (REJOIN), the survivor prepares (new send PSNs, TOKEN), the spare connects with receive PSN = the survivor's send
// PSN and READY repeats its token (gdakiRsTokenMatch against REJOIN), the survivor swaps rq.exch to the spare's QPNs and
// builds the Commit token (gdakiRsBuildCommitToken). A model of ncclGinRecoverCommit's check (remote qpn = rq.exch.qpn
// after the swap, remote remoteQpn = own QPN) and of its reconnect (receive PSN = remote sqPsn, send PSN = Prepare's) then
// shows both directions agree: what each side sends with is what the other receives with. Both sides' order runs through
// gdakiRsXchgStep. Negative cases: a READY whose PSN changed, a READY from another count, a stale Commit token.
namespace {
struct Qp { uint32_t qpn, exchQpn, rqPsn, sqPsn; };  // a QP's own QPN, its peer QPN (rq.exch.qpn) and its PSNs
// ncclGinRecoverCommit's token check and the PSNs it connects with (gin_host_gdaki.cc: remote->qpn[n] != rq.exch.qpn or
// remote->remoteQpn[n] != own QPN -> invalid; gdakiConnectQp(..., remote->sqPsn[idx], rq.newSqPsn))
static bool commitModel(unsigned n, const uint32_t* tQpn, const uint32_t* tRemoteQpn, const uint32_t* tSqPsn,
                        const uint32_t* newSqPsn, Qp* surv) {
  for (unsigned i = 0; i < n; i++)
    if (tQpn[i] != surv[i].exchQpn || tRemoteQpn[i] != surv[i].qpn) return false;
  for (unsigned i = 0; i < n; i++) {
    surv[i].rqPsn = tSqPsn[i];
    surv[i].sqPsn = newSqPsn[i];
  }
  return true;
}
}
static void testExchangeSim() {
  char why[192];
  const unsigned n = 3;
  Qp surv[3] = {{0x100, 0x900, 0, 0}, {0x101, 0x901, 0, 0}, {0x102, 0x902, 0, 0}};  // exchQpn: the dead QPNs
  Qp spare[3] = {{0x200, 0x100, 0, 0}, {0x201, 0x101, 0, 0}, {0x202, 0x102, 0, 0}}; // exchQpn: the survivor's (recorded)
  int ss = GDAKI_RS_XS_HELD, sp = GDAKI_RS_XS_HELD;
  // REJOIN: the spare's QPNs and fresh send PSNs, its view of the survivor's QPNs
  uint32_t rjQpn[3], rjPsn[3], rjRemote[3], ownQpn[3];
  for (unsigned i = 0; i < n; i++) {
    rjQpn[i] = spare[i].qpn;
    rjPsn[i] = 0x10 + i;
    rjRemote[i] = spare[i].exchQpn;
    ownQpn[i] = surv[i].qpn;
  }
  sp = gdakiRsXchgStep(sp, GDAKI_RS_EV_REJOIN);
  CHECK(gdakiRsRejoinValidate(1u, 7, 7, 1u, 0u, (int)n, (int)n, rjRemote, ownQpn, why, sizeof(why)));
  ss = gdakiRsXchgStep(ss, GDAKI_RS_EV_REJOIN);
  // survivor Prepare: new send PSNs, TOKEN (its QPNs are the ones the spare recorded)
  const uint32_t newSqPsn[3] = {0x777, 0x778, 0x779};
  ss = gdakiRsXchgStep(ss, GDAKI_RS_EV_PREPARE);
  for (unsigned i = 0; i < n; i++) CHECK(ownQpn[i] == spare[i].exchQpn);
  sp = gdakiRsXchgStep(sp, GDAKI_RS_EV_PREPARE);
  // spare connects: receive PSN = the survivor's new send PSN, send PSN = the announced one
  for (unsigned i = 0; i < n; i++) {
    spare[i].rqPsn = newSqPsn[i];
    spare[i].sqPsn = rjPsn[i];
  }
  sp = gdakiRsXchgStep(sp, GDAKI_RS_EV_READY);
  // READY repeats the REJOIN token; the survivor takes it only if it matches
  uint32_t rdQpn[3], rdPsn[3];
  for (unsigned i = 0; i < n; i++) { rdQpn[i] = spare[i].qpn; rdPsn[i] = spare[i].sqPsn; }
  CHECK(gdakiRsTokenMatch(n, rdQpn, rdPsn, n, rjQpn, rjPsn, why, sizeof(why)));
  ss = gdakiRsXchgStep(ss, GDAKI_RS_EV_READY);
  // swap: rq.exch.qpn := the spare's QPN; build the Commit token
  for (unsigned i = 0; i < n; i++) surv[i].exchQpn = rjQpn[i];
  ss = gdakiRsXchgStep(ss, GDAKI_RS_EV_SWAP);
  uint32_t tQpn[3], tRemote[3], tPsn[3];
  unsigned long long tEpoch[3];
  gdakiRsBuildCommitToken(n, rjQpn, rjPsn, ownQpn, tQpn, tRemote, tPsn, tEpoch);
  CHECK(commitModel(n, tQpn, tRemote, tPsn, newSqPsn, surv));
  for (unsigned i = 0; i < n; i++) CHECK(tEpoch[i] == 0);
  ss = gdakiRsXchgStep(ss, GDAKI_RS_EV_COMMIT);
  // both directions agree: each side sends with what the other receives with, and points at the other's QPN
  for (unsigned i = 0; i < n; i++) {
    CHECK(surv[i].sqPsn == spare[i].rqPsn);
    CHECK(spare[i].sqPsn == surv[i].rqPsn);
    CHECK(surv[i].exchQpn == spare[i].qpn && spare[i].exchQpn == surv[i].qpn);
  }
  ss = gdakiRsXchgStep(ss, GDAKI_RS_EV_BASELINE);
  ss = gdakiRsXchgStep(ss, GDAKI_RS_EV_RKEYS);
  ss = gdakiRsXchgStep(ss, GDAKI_RS_EV_PUBLISH);
  CHECK(sp == GDAKI_RS_XS_READY);  // the spare waits for DONE_RS here
  ss = gdakiRsXchgStep(ss, GDAKI_RS_EV_RESTORED);
  CHECK(ss == GDAKI_RS_XS_RESTORED);
  // negatives: a READY whose PSN changed, or of another count, is refused; a Commit before the swap is refused
  rdPsn[1] ^= 1;
  CHECK(!gdakiRsTokenMatch(n, rdQpn, rdPsn, n, rjQpn, rjPsn, why, sizeof(why)) && has(why, "QP 1"));
  CHECK(!gdakiRsTokenMatch(n - 1, rdQpn, rjPsn, n, rjQpn, rjPsn, why, sizeof(why)) && has(why, "QP count"));
  Qp before[3] = {{0x100, 0x900, 0, 0}, {0x101, 0x901, 0, 0}, {0x102, 0x902, 0, 0}};  // rq.exch not swapped
  CHECK(!commitModel(n, tQpn, tRemote, tPsn, newSqPsn, before));
  // the order is enforced: Commit before READY, or a second REJOIN, fails
  CHECK(gdakiRsXchgStep(GDAKI_RS_XS_PREPARED, GDAKI_RS_EV_COMMIT) == GDAKI_RS_XS_FAIL);
  CHECK(gdakiRsXchgStep(GDAKI_RS_XS_REJOINED, GDAKI_RS_EV_REJOIN) == GDAKI_RS_XS_FAIL);
}

// ---- the spare's setup record against the transcript's (masked comparison) ----
static void testSpareSetupMatch() {
  char why[192];
  const uint32_t MAGIC = 0x31535447u, SPARE = 1u << 2;
  const uint32_t rec = 0x1u | 0x2u | 0x100u;  // request, strict, a fact bit (as an original records it)
  CHECK(gdakiRsSpareSetupMatch(MAGIC, 3, rec, MAGIC, 3, rec | SPARE, SPARE, why, sizeof(why)) && has(why, "matches"));
  CHECK(!gdakiRsSpareSetupMatch(MAGIC, 3, rec, 0, 3, rec | SPARE, SPARE, why, sizeof(why)) && has(why, "off"));
  CHECK(!gdakiRsSpareSetupMatch(MAGIC, 3, rec, MAGIC, 1, rec | SPARE, SPARE, why, sizeof(why)) && has(why, "rank"));
  CHECK(!gdakiRsSpareSetupMatch(MAGIC, 3, rec | SPARE, MAGIC, 3, rec | SPARE, SPARE, why, sizeof(why)) &&
        has(why, "recorded by a spare"));
  CHECK(!gdakiRsSpareSetupMatch(MAGIC, 3, rec, MAGIC, 3, rec, SPARE, why, sizeof(why)) && has(why, "not marked"));
  CHECK(!gdakiRsSpareSetupMatch(MAGIC, 3, rec, MAGIC, 3, (rec | SPARE) ^ 0x200u, SPARE, why, sizeof(why)) &&
        has(why, "beyond the spare bit"));  // a variable differs (e.g. host RMA on in the spare)
  CHECK(!gdakiRsSpareSetupMatch(MAGIC, 3, rec, MAGIC, 3, (rec | SPARE) | 0x8u, SPARE, why, sizeof(why)));  // recovery off locally
}

// ---- the endpoint pack round-trip ----
static void testEndpoint() {
  struct gdakiRsEndpoint e;
  memset(&e, 0, sizeof(e));
  e.lid = 7;
  e.activeMtu = 5;
  e.ordering = 1;
  e.gidIndex = 3;
  for (int i = 0; i < 16; i++) e.gid[i] = (uint8_t)(i + 1);
  for (int i = 0; i < 32; i++) e.listenAddr[i] = (uint8_t)(0x40 + i);
  e.step = 123456789ull;
  uint8_t buf[72];
  CHECK(sizeof(e) == 72);
  memcpy(buf, &e, sizeof(e));
  struct gdakiRsEndpoint back;
  memcpy(&back, buf, sizeof(back));
  CHECK(memcmp(&e, &back, sizeof(e)) == 0);
  CHECK(back.lid == 7 && back.gidIndex == 3 && back.step == 123456789ull && back.listenAddr[31] == (uint8_t)(0x40 + 31));
  // the wire layout (rs_spare_api.h gdakiRsRejoinInfo, in gdakiTsMsg::executed[2..]): fixed offsets
  CHECK(offsetof(struct gdakiRsEndpoint, lid) == 0 && offsetof(struct gdakiRsEndpoint, activeMtu) == 4 &&
        offsetof(struct gdakiRsEndpoint, ordering) == 8 && offsetof(struct gdakiRsEndpoint, gidIndex) == 12 &&
        offsetof(struct gdakiRsEndpoint, gid) == 16 && offsetof(struct gdakiRsEndpoint, listenAddr) == 32 &&
        offsetof(struct gdakiRsEndpoint, step) == 64);
  CHECK(2 * 4 + sizeof(struct gdakiRsEndpoint) <= 64 * 4);  // fits executed[2 .. 63]
}

// ---- a model of the init transcript's divergence and masked comparison (mirrors src/misc/rs_spike.cc) ----
namespace {
struct Hdr { int kind, site, tag, peer, n, myIdx; uint64_t elt, len; };
// nextEntry's rule: the record diverges unless every header field matches.
static bool hdrMatch(const Hdr& a, const Hdr& b) {
  return a.kind == b.kind && a.site == b.site && a.tag == b.tag && a.peer == b.peer && a.n == b.n &&
         a.myIdx == b.myIdx && a.elt == b.elt && a.len == b.len;
}
// compareOwn's rule: at a call site with no strict comparison (SITE_NONE) every difference is allowed (only counted); at a
// strict site a byte that differs outside the site's allowed ranges is a strict mismatch.
static int strictDiff(const uint8_t* now, const uint8_t* rec, size_t len, bool siteNone,
                      const std::vector<std::pair<size_t, size_t>>& allowed) {
  int strict = 0;
  for (size_t b = 0; b < len; b++) {
    if (now[b] == rec[b]) continue;
    bool ok = siteNone;
    for (auto& a : allowed)
      if (b >= a.first && b < a.first + a.second) ok = true;
    if (!ok) strict++;
  }
  return strict;
}
}
static void testTranscriptModel() {
  const Hdr base{/*kind*/9, /*site*/1, /*tag*/0, /*peer*/-1, /*n*/2, /*myIdx*/0, /*elt*/64, /*len*/128};
  Hdr call = base;
  CHECK(hdrMatch(base, call));
  call.len = 127;  CHECK(!hdrMatch(base, call));  // a short read diverges
  call = base; call.site = 2;  CHECK(!hdrMatch(base, call));  // the wrong call site diverges
  call = base; call.n = 3;     CHECK(!hdrMatch(base, call));  // a different participant count diverges
  // masked own-slot: the recorded and the replayed differ only in the allowed fields (e.g. pidHash at [0,8), comm at
  // [16,24)) -> strict 0; a byte outside them -> strict > 0
  uint8_t rec[64], now[64];
  for (int i = 0; i < 64; i++) rec[i] = (uint8_t)i;
  memcpy(now, rec, 64);
  for (int i = 0; i < 8; i++) now[i] = 0xff;      // pidHash differs (allowed)
  for (int i = 16; i < 24; i++) now[i] = 0xee;    // comm differs (allowed)
  std::vector<std::pair<size_t, size_t>> allowed = {{0, 8}, {16, 8}};
  CHECK(strictDiff(now, rec, 64, false, allowed) == 0);
  now[40] = 0x55;  // a byte outside the allowed ranges
  CHECK(strictDiff(now, rec, 64, false, allowed) == 1);
  // a strict site with no allowed ranges (allGather3, the GIN connection count, the segments): every difference is strict
  CHECK(strictDiff(now, rec, 64, false, {}) == 17);  // the 8 + 8 bytes plus the one outside
  // SITE_NONE: every difference allowed (counted only)
  CHECK(strictDiff(now, rec, 64, true, {}) == 0);
}

// ---- the Resume local check as this package changes it (the region of packages 1-4) ----
static void testLocalSpare() {
  char why[GDAKI_RS_WHY_LEN];
  struct gdakiRsLocalIn ok;
  ok.ginType = 3;
  ok.nConn = 1;
  ok.haveSetup = true;
  ok.nUserCtx = 1;
  ok.tsOn = true;
  CHECK(gdakiRsLocalCheck(ok, why, sizeof(why)) == GDAKI_RS_L_OK);
  struct gdakiRsLocalIn x = ok;
  x.spare = true;  // a spare that did not replay a transcript: still condition 4, the new text
  CHECK(gdakiRsLocalCheck(x, why, sizeof(why)) == 4 && has(why, "spare process") && has(why, "NCCL_GIN_RESTORE_REPLAY"));
  x = ok;
  x.transcriptOk = false;  // the original does not record: the last condition
  const int code = gdakiRsLocalCheck(x, why, sizeof(why));
  CHECK(code == 29 && has(why, "NCCL_GIN_RESTORE_RECORD"));
  x.logMeasure = true;  // an earlier condition wins
  CHECK(gdakiRsLocalCheck(x, why, sizeof(why)) == 28);
  x = ok;
  x.replayClean = false;  // a spare whose replay was not clean: the condition after it
  x.replayWhy = "1 own-slot mismatch(es) outside the allowed fields";
  CHECK(gdakiRsLocalCheck(x, why, sizeof(why)) == 30 && has(why, "not clean") && has(why, "own-slot mismatch"));
  x.transcriptOk = false;
  CHECK(gdakiRsLocalCheck(x, why, sizeof(why)) == 29);
}

int main() {
  testActivate();
  testRejoinValidate();
  testXchgSequence();
  testExchangeSim();
  testSpareSetupMatch();
  testLocalSpare();
  testEndpoint();
  testTranscriptModel();
  printf("rs_spare_unit: %d checks, %d failed\n", nChecks, nFail);
  return nFail == 0 ? 0 : 1;
}
