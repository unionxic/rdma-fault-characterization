# rs_set.sh - sourced by deploy_rs.sh, run_rs.sh, run_cost.sh, cells_rs.sh, hold_rs.sh and chain_rs.sh (2026-10-13): the
# one check of RS_SET, the name of a deployment set under ~/rs-bundle/<RS_SET>/ (empty: the first set, today's paths).
# Valid: empty, or a name whose first character is a letter or a digit, with no '/' and no '..', and not one of the first
# set's folder names (lib, rstest, rscost, mr, ord), so a set never lands inside the first set's folders.
# rs_set_check: returns 0 when RS_SET is valid, else prints why on stderr and returns 1.
rs_set_check() {
  local s=${RS_SET:-}
  [ -z "$s" ] && return 0
  case "$s" in
    [A-Za-z0-9]*) ;;
    *) echo "RS_SET '$s': the first character must be a letter or a digit" >&2; return 1 ;;
  esac
  case "$s" in
    */*|*..*) echo "RS_SET '$s': no '/' and no '..'" >&2; return 1 ;;
  esac
  case "$s" in
    lib|rstest|rscost|mr|ord) echo "RS_SET '$s' is a folder name of the first set" >&2; return 1 ;;
  esac
  return 0
}
