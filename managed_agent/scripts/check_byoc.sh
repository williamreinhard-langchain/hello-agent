#!/usr/bin/env bash
# Read-only check: does the Azure BYOC data plane serve the platform APIs `mda deploy` needs?
# Prints HTTP status codes only. Reads LANGSMITH_API_KEY / LANGSMITH_WORKSPACE_ID / LANGSMITH_ENDPOINT from ../.env.
set -euo pipefail
cd "$(dirname "$0")/.."

val() { grep -E "^$1=" .env | head -1 | cut -d= -f2- | tr -d "\"'" || true; }
KEY=$(val LANGSMITH_API_KEY)
WS=$(val LANGSMITH_WORKSPACE_ID)
DP=$(val LANGSMITH_ENDPOINT)

echo "mda: $(uv run mda --version 2>/dev/null | head -1)  (latest on PyPI: $(curl -s https://pypi.org/pypi/managed-deepagents/json | python3 -c 'import json,sys; print(json.load(sys.stdin)["info"]["version"])'))"
echo "data plane: $DP"
ok=1
for p in /api/v1/orgs/current "/api/v1/sessions?limit=1" "/api/v1/repos/?limit=1" "/v2/deployments?limit=1"; do
  code=$(curl -s -o /dev/null -w '%{http_code}' -H "x-api-key: $KEY" -H "x-tenant-id: $WS" "$DP$p")
  echo "  $code  $p"
  [ "$code" = 200 ] || ok=0
done
if [ $ok = 1 ]; then
  echo "PASS: data plane serves platform APIs. Try: env -u LANGSMITH_API_KEY -u LANGSMITH_GATEWAY_API_KEY uv run mda deploy --deployment-type dedicated --push-to <repo:tag> --yes"
else
  echo "NOT YET: data plane still rejects platform APIs (fix not live for this environment)."
fi

GW=$(val LANGSMITH_GATEWAY)
GKEY=$(val LANGSMITH_GATEWAY_API_KEY)
if [ -n "$GW" ] && [ -n "$GKEY" ]; then
  out=$(curl -s -o /tmp/check_byoc_gw.out -w '%{http_code}' -H "Authorization: Bearer $GKEY" "$GW/v1/models")
  echo "gateway: $out $(head -c 100 /tmp/check_byoc_gw.out)  ($GW/v1/models, bearer only, as the agent calls it)"
  rm -f /tmp/check_byoc_gw.out
  [ "$out" = 200 ] && echo "PASS: gateway accepts LANGSMITH_GATEWAY_API_KEY" || echo "FAIL: gateway key needs to be scoped to this workspace with a role that has gateway:invoke (Admin or Deployment Runtime)"
fi
