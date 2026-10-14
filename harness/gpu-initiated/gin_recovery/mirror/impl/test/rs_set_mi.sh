# rs_set_mi.sh - sourced by every gin-mirror test script (deploy_mi.sh, run_mi.sh, run_cost_mi.sh, cells_mi.sh, hold_mi.sh,
# chain_mi.sh): the one check of RS_SET, the deployment set ~/rs-bundle/<RS_SET>/ of this study. gin-restore's rule
# (../../../restore/impl/test/rs_set.sh) with one change: RS_SET must be set. gin-mirror never uses the first set's paths
# (~/rs-bundle/{lib,rstest,rscost,mr,ord}: gin-restore's), so an empty RS_SET is refused.
# Valid: a name of letters, digits, '.', '_' and '-' whose first character is a letter or a digit, with no '..', and not one of the first set's folder
# names (lib, rstest, rscost, mr, ord, mf, mfcm: the last two are the feasibility tools' folders).
# rs_set_check: returns 0 when RS_SET is valid, else prints why on stderr and returns 1.
rs_set_check() {
  local s=${RS_SET:-}
  [ -n "$s" ] || { echo "RS_SET is empty: gin-mirror runs only from a named deployment set (deploy_mi.sh)" >&2; return 1; }
  case "$s" in
    [A-Za-z0-9]*) ;;
    *) echo "RS_SET '$s': the first character must be a letter or a digit" >&2; return 1 ;;
  esac
  case "$s" in
    */*|*..*) echo "RS_SET '$s': no '/' and no '..'" >&2; return 1 ;;
  esac
  case "$s" in  # the integration's review: only these characters (the name goes unquoted into remote shell strings)
    *[!A-Za-z0-9._-]*) echo "RS_SET '$s': only letters, digits, '.', '_' and '-'" >&2; return 1 ;;
  esac
  case "$s" in
    lib|rstest|rscost|mr|ord|mf|mfcm) echo "RS_SET '$s' is a folder name of the first set or of the feasibility tools" >&2; return 1 ;;
  esac
  return 0
}
