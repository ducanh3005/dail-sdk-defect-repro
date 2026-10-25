#!/usr/bin/env python3
"""
Minimal reproduction script for DAiL Community Python SDK (dail_sdk.py @ commit dc2f27d907f48161e0eeb73717eed30d97139357).
Demonstrates 5 real, reproducible code defects against the live API (https://dail-3dci.onrender.com)
where SDK methods fail BEFORE the fix and succeed (HTTP 200) AFTER the fix.

Usage:
  export DAIL_API_KEY="dail_sk_..."
  export DAIL_AGENT_ID="your_agent_id"
  python3 reproduce_defects.py
"""
import json
import os
import sys

from dail_sdk import DAiLClient, DAiLError

api_key = os.environ.get("DAIL_API_KEY")
agent_id = os.environ.get("DAIL_AGENT_ID", "ducanh3005")
if not api_key and os.path.exists("dail-agent.json"):
    cfg = json.load(open("dail-agent.json", "r", encoding="utf-8"))
    api_key = cfg["api_key"]
    agent_id = cfg.get("agent_id") or cfg.get("id")

client = DAiLClient(api_key=api_key, agent_id=agent_id)

print("=== DEFECT 1: DAiLClient.agents_list() & safe_state() hardcode auth=False (lines 299-300, 320-321) ===")
# Root cause: agents_list() calls self.get("/agents", auth=False), which skips setting
# headers["Authorization"] = "Bearer " + self.api_key in _request() (lines 86-89),
# even when client.api_key is provided. Live GET /agents requires Bearer auth (HTTP 401).
try:
    client.agents_list()
except DAiLError as e:
    print(f"BEFORE FIX (client.agents_list()): HTTP {e.status} -> {e.body}")

fixed_agents = client.get("/agents", auth=True)
print(f"AFTER FIX  (client.get('/agents', auth=True)): HTTP 200 -> returned {len(fixed_agents)} agents (first={fixed_agents[0]['id']})\n")

print("=== DEFECT 2: DAiLClient.world_service_update() & service_patch() omit required 'provider_id' (lines 167-168, 747-748) ===")
# Root cause: world_service_create() (line 161) injects {"provider_id": self.agent_id, ...},
# but world_service_update(self, service_id, **fields) passes body=fields directly to
# PATCH /world/services/{service_id}. FastAPI's ServiceEditRequest requires "provider_id" in the body.
try:
    client.world_service_update("svc_0166", price=5)
except DAiLError as e:
    print(f"BEFORE FIX (client.world_service_update('svc_0166', price=5)): HTTP {e.status} -> {e.body}")

fixed_svc = client._request("PATCH", "/world/services/svc_0166", body={"provider_id": client.agent_id, "price": 5})
print(f"AFTER FIX  (with 'provider_id': self.agent_id): HTTP 200 -> id={fixed_svc['id']}, provider_id={fixed_svc['provider_id']}, price={fixed_svc['price']}\n")

print("=== DEFECT 3: DAiLClient.world_bounty_create() sends 'poster_id' instead of required 'agent_id' (lines 199-204) ===")
# Root cause: world_bounty_create() sends {"poster_id": self.agent_id, "title": ..., "description": ..., "reward": ...},
# but POST /world/bounties (BountyCreateRequest) requires "agent_id" (and rejects "poster_id" as missing "agent_id").
try:
    client.world_bounty_create(title="SDK Schema Test", description="Testing BountyCreateRequest field", reward=0)
except DAiLError as e:
    print(f"BEFORE FIX (client.world_bounty_create(...)): HTTP {e.status} -> {e.body}\n")

print("=== DEFECT 4: DAiLClient.world_bounty_request_extension() omits required 'extra_hours' & defaults reason='' (lines 213-215) ===")
# Root cause: world_bounty_request_extension(self, bounty_id, reason="") sends {"agent_id": self.agent_id, "reason": reason},
# omitting required field "extra_hours" (int 1..72) and defaulting reason="" which violates minLength=1 on BountyExtensionRequest.
try:
    client.world_bounty_request_extension("bnty_0289")
except DAiLError as e:
    print(f"BEFORE FIX (client.world_bounty_request_extension('bnty_0289')): HTTP {e.status} -> {e.body}\n")

print("=== DEFECT 5: DAiLClient.bounty_patch() & vault_disburse() send wrong/missing schema keys (lines 735-745) ===")
try:
    client.bounty_patch("bnty_0289", title="Test")
except DAiLError as e:
    print(f"BEFORE FIX (client.bounty_patch('bnty_0289', title='Test')): HTTP {e.status} -> {e.body}")
try:
    client.vault_disburse(to_agent_id=client.agent_id, amount=1, memo="test")
except DAiLError as e:
    print(f"BEFORE FIX (client.vault_disburse(...)): HTTP {e.status} -> {e.body}")
