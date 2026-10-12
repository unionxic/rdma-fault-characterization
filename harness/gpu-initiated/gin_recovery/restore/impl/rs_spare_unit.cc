// rs_spare_unit.cc - CPU unit test of the spare branch's pure functions (gin-restore work package 8, EXPERIMENT.md 9.3,
// 9.10.5, 9.11.3 M4). build_rs_spare.sh unit cuts the region between the two "gin-restore (rs, work package 8, spare
// branch): pure functions" markers of gin_host_gdaki.cc into rs_spare_pure.inc and compiles it here, so the test runs the
// library's own text. No NCCL, no CUDA, no network.
// Coverage: the activation gate (gdakiRsActExamine: absent, zombie/dead, reused PID, alive, no recorded start, no PID);
// the REJOIN record validation (gdakiRsRejoinValidate: version, nonce, incarnation, QP count, QPN match); the two-sided
// token-exchange state sequence (gdakiRsXchgStep: the legal order, out-of-order, nothing after RESTORED) and a CPU
// simulation of the exchange driving both sides through a message queue; the endpoint pack round-trip. Plus a model of the
// init transcript's divergence detection and masked own-slot comparison, mirroring src/misc/rs_spike.cc's nextEntry and
// compareOwn (the feasibility spike B1, 9.15.4, ran those end-to-end on the cluster; this test checks the logic).
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <string>
#include <vector>

#include "rs_spare_pure.inc"

static int nChecks = 0, nFail = 0;
#define CHECK(c) do { nChecks++; if (!(c)) { nFail++; fprintf(stderr, "FAIL %s:%d: %s\n", __FILE__, __LINE__, #c); } } while (0)
static bool has(const char* s, const char* sub) { return strstr(s, sub) != nullptr; }

// ---- the activation gate (9.10.5) ----
static void testActivate() {
  char why[192];
  struct gdakiRsActProbe p;
  // no PID to check: the buddy asserts the original is gone
  CHECK(gdakiRsActExamine(0, 0, p, why, sizeof(why)) == GDAKI_RS_ACT_GO && has(why, "no PID"));
  CHECK(gdakiRsActExamine(-1, 123, p, why, sizeof(why)) == GDAKI_RS_ACT_GO);
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

// A CPU simulation of the two-sided exchange: a survivor and a spare pass records through a queue; the survivor advances
// with gdakiRsXchgStep, the spare mirrors the same order, and the tokens agree (the spare's announced QPNs/PSNs flow
// survivor <- spare in REJOIN/READY and the survivor's in TOKEN).
namespace {
struct Rec { int type; uint32_t qpn[2], sqPsn[2]; };  // a tiny stand-in for the records that carry the token
enum { R_REJOIN, R_REJOIN_ACK, R_TOKEN, R_READY, R_DONE, R_RESTORED };
}
static void testExchangeSim() {
  const uint32_t spareQpn[2] = {0x200, 0x201}, spareSqPsn[2] = {0x11, 0x12};
  const uint32_t survQpn[2] = {0x100, 0x101}, survSqPsn[2] = {0x21, 0x22};
  std::vector<Rec> wire;  // the ordered records on the one connection
  int ss = GDAKI_RS_XS_HELD;   // survivor state
  int sp = GDAKI_RS_XS_HELD;   // spare state (mirrors)
  // spare -> REJOIN (its QPNs and send PSNs)
  wire.push_back({R_REJOIN, {spareQpn[0], spareQpn[1]}, {spareSqPsn[0], spareSqPsn[1]}});
  sp = gdakiRsXchgStep(sp, GDAKI_RS_EV_REJOIN);
  // survivor accepts, then prepares and sends TOKEN (its QPNs and new send PSNs)
  ss = gdakiRsXchgStep(ss, GDAKI_RS_EV_REJOIN);
  wire.push_back({R_REJOIN_ACK, {0, 0}, {0, 0}});
  ss = gdakiRsXchgStep(ss, GDAKI_RS_EV_PREPARE);
  wire.push_back({R_TOKEN, {survQpn[0], survQpn[1]}, {survSqPsn[0], survSqPsn[1]}});
  // spare connects (receive PSN = the survivor's send PSN, send PSN = the one it announced) and sends READY
  sp = gdakiRsXchgStep(sp, GDAKI_RS_EV_PREPARE);  // spare's mirror of "got the survivor's token"
  const Rec& tok = wire[2];
  CHECK(tok.type == R_TOKEN && tok.sqPsn[0] == survSqPsn[0] && tok.qpn[0] == survQpn[0]);
  sp = gdakiRsXchgStep(sp, GDAKI_RS_EV_READY);
  wire.push_back({R_READY, {spareQpn[0], spareQpn[1]}, {spareSqPsn[0], spareSqPsn[1]}});
  // survivor takes READY (its token must equal the REJOIN's), swaps, commits with the spare's PSN as receive PSN
  const Rec& rejoin = wire[0];
  const Rec& ready = wire[3];
  CHECK(ready.type == R_READY && ready.qpn[0] == rejoin.qpn[0] && ready.sqPsn[0] == rejoin.sqPsn[0]);
  ss = gdakiRsXchgStep(ss, GDAKI_RS_EV_READY);
  ss = gdakiRsXchgStep(ss, GDAKI_RS_EV_SWAP);
  // the Commit token the survivor builds: qpn = spare's, sqPsn = spare's (its own receive PSN), remoteQpn = survivor's
  CHECK(ready.qpn[0] == spareQpn[0] && ready.sqPsn[0] == spareSqPsn[0]);
  ss = gdakiRsXchgStep(ss, GDAKI_RS_EV_COMMIT);
  ss = gdakiRsXchgStep(ss, GDAKI_RS_EV_BASELINE);
  ss = gdakiRsXchgStep(ss, GDAKI_RS_EV_RKEYS);
  ss = gdakiRsXchgStep(ss, GDAKI_RS_EV_PUBLISH);
  CHECK(sp == GDAKI_RS_XS_READY);  // the spare's mirror: REJOIN, PREPARE, READY, then it waits for DONE_RS
  wire.push_back({R_DONE, {0, 0}, {0, 0}});
  // spare gets DONE_RS, starts its helper, sends RESTORED (the survivor drives commit/baseline/rkeys/publish)
  wire.push_back({R_RESTORED, {0, 0}, {0, 0}});
  ss = gdakiRsXchgStep(ss, GDAKI_RS_EV_RESTORED);
  CHECK(ss == GDAKI_RS_XS_RESTORED);
  // the record order on the wire is exactly the sequence
  const int want[] = {R_REJOIN, R_REJOIN_ACK, R_TOKEN, R_READY, R_DONE, R_RESTORED};
  CHECK(wire.size() == 6);
  for (size_t i = 0; i < wire.size(); i++) CHECK(wire[i].type == want[i]);
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
}

// ---- a model of the init transcript's divergence and masked comparison (mirrors src/misc/rs_spike.cc) ----
namespace {
struct Hdr { int kind, site, tag, peer, n, myIdx; uint64_t elt, len; };
// nextEntry's rule: the record diverges unless every header field matches.
static bool hdrMatch(const Hdr& a, const Hdr& b) {
  return a.kind == b.kind && a.site == b.site && a.tag == b.tag && a.peer == b.peer && a.n == b.n &&
         a.myIdx == b.myIdx && a.elt == b.elt && a.len == b.len;
}
// compareOwn's rule: a byte that differs outside the allowed ranges is a strict mismatch (the own slot's new fields are
// allowed to differ; every other byte must equal the recorded rank's).
static int strictDiff(const uint8_t* now, const uint8_t* rec, size_t len,
                      const std::vector<std::pair<size_t, size_t>>& allowed) {
  int strict = 0;
  for (size_t b = 0; b < len; b++) {
    if (now[b] == rec[b]) continue;
    bool ok = false;
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
  CHECK(strictDiff(now, rec, 64, allowed) == 0);
  now[40] = 0x55;  // a byte outside the allowed ranges
  CHECK(strictDiff(now, rec, 64, allowed) == 1);
  // a site with no allowed ranges (SITE_NONE-like): every difference is strict
  CHECK(strictDiff(now, rec, 64, {}) == 17);  // the 8 + 8 allowed bytes plus the one outside
}

int main() {
  testActivate();
  testRejoinValidate();
  testXchgSequence();
  testExchangeSim();
  testEndpoint();
  testTranscriptModel();
  printf("rs_spare_unit: %d checks, %d failed\n", nChecks, nFail);
  return nFail == 0 ? 0 : 1;
}
