#!/bin/sh
# Auth is whichever .env supplies: CLAUDE_CODE_OAUTH_TOKEN (plan quota, from
# `claude setup-token`) or ANTHROPIC_API_KEY (per-token API billing). Which one
# the CLI prefers when both are set is version-dependent, so drop the API key
# and let the plan token deterministically win: nothing bills the API.
if [ -n "$CLAUDE_CODE_OAUTH_TOKEN" ]; then
    unset ANTHROPIC_API_KEY
fi
exec "$@"
