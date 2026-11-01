# Evaluation-only guard at Bash's execution boundary. No whole-script text scan.
# It protects injected controller executables; it is not a complete shell sandbox.
__memweave_exec_boundary() {
  local __mw_line="$1" __mw_head __mw_candidate __mw_resolved
  local -a __mw_words
  # DEBUG supplies one actual Bash command. read stops at the header newline,
  # so a heredoc's C/text body is data rather than a new command list.
  read -r -a __mw_words <<< "$__mw_line"
  while [ "${#__mw_words[@]}" -gt 0 ]; do
    __mw_head="${__mw_words[0]}"
    __mw_head="${__mw_head//\'/}"; __mw_head="${__mw_head//\"/}"
    case "$__mw_head" in
      command)
        case " ${__mw_words[*]} " in *' -v '*|*' -V '*) return 0;; esac
        __mw_words=("${__mw_words[@]:1}")
        while [ "${#__mw_words[@]}" -gt 0 ] && [[ "${__mw_words[0]}" == -* ]]; do __mw_words=("${__mw_words[@]:1}"); done
        ;;
      exec) __mw_words=("${__mw_words[@]:1}");;
      env)
        __mw_words=("${__mw_words[@]:1}")
        while [ "${#__mw_words[@]}" -gt 0 ]; do
          case "${__mw_words[0]}" in
            -u|--unset|-C|--chdir) __mw_words=("${__mw_words[@]:2}");;
            -*|[A-Za-z_]*=*) __mw_words=("${__mw_words[@]:1}");;
            *) break;;
          esac
        done
        ;;
      timeout)
        __mw_words=("${__mw_words[@]:1}")
        while [ "${#__mw_words[@]}" -gt 0 ] && [[ "${__mw_words[0]}" == -* ]]; do
          case "${__mw_words[0]}" in -k|--kill-after|-s|--signal) __mw_words=("${__mw_words[@]:2}");; *) __mw_words=("${__mw_words[@]:1}");; esac
        done
        __mw_words=("${__mw_words[@]:1}")
        ;;
      *) break;;
    esac
  done
  [ "${#__mw_words[@]}" -gt 0 ] || return 0
  __mw_head="${__mw_words[0]//\'/}"; __mw_head="${__mw_head//\"/}"
  __mw_candidate="$(type -P -- "$__mw_head" 2>/dev/null || true)"
  [ -n "$__mw_candidate" ] || return 0
  __mw_resolved="$(readlink -f -- "$__mw_candidate" 2>/dev/null || printf '%s' "$__mw_candidate")"
  case "$__mw_resolved" in
    "${MEMWEAVE_EVAL_ASSET_ROOT:?}"/*)
      printf '{"event":"sealed_tool_rejected","tool":"bash","executables":["injected-runtime"],"pid":%s,"timestamp":"%s"}\n' "$$" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "${MEMWEAVE_EVAL_TRACE:?}"
      printf '%s\n' 'Sealed task: execution of injected controller runtime is forbidden.' >&2
      exit 126
      ;;
  esac
  return 0
}
trap '__memweave_exec_boundary "$BASH_COMMAND"' DEBUG
