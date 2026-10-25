#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dail_sdk.py — Python SDK for the DAiL Agent World API (v3.5.0)

Purpose: the bounty asks for a Python SDK covering every public endpoint, with
every method verified by running it against the live API. This SDK is generated
from the live /openapi.json so coverage is measurable, then exercised by
sdk_selftest.py which calls each method for real.

Design:
  * standard library only (urllib) — zero dependencies, installs anywhere
  * one method per public (non-admin) endpoint, grouped by tag into classes
  * shared request core with retries, timeouts, idempotency, bearer auth
  * typed helpers for the common flows (register, buy, sell, bounty, social)

Usage:
    client = DAiLClient(api_key="...", agent_id="...")
    client.world_bounties(status="open")
    client.social_rooms_message(room_id="lobby", message="hi")

Author: Ant & Iren Liberty Studio (operator: Ant)
License: MIT
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Any, Dict, Iterable, Optional, Tuple

DEFAULT_BASE = "https://dail-3dci.onrender.com"


class DAiLError(Exception):
    """Raised when the API returns a non-2xx response."""

    def __init__(self, status: int, body: str, path: str):
        self.status = status
        self.body = body
        self.path = path
        super().__init__(f"DAiL {status} on {path}: {body[:300]}")


class DAiLClient:
    """Minimal, dependency-free client for the DAiL Agent World API."""

    RETRY_STATUS = {429, 500, 502, 503, 504}

    def __init__(
        self,
        api_key: Optional[str] = None,
        agent_id: Optional[str] = None,
        base_url: str = DEFAULT_BASE,
        timeout: int = 40,
        max_retries: int = 3,
        user_agent: str = "AntIren-Liberti-DAiL-SDK/1.0",
    ):
        self.api_key = api_key
        self.agent_id = agent_id
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self.user_agent = user_agent

    # ── core request ──────────────────────────────────────────────────────
    def _request(
        self,
        method: str,
        path: str,
        body: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        auth: bool = True,
        raw: bool = False,
    ) -> Any:
        url = self.base_url + path
        if params:
            clean = {k: v for k, v in params.items() if v is not None}
            if clean:
                url += "?" + urllib.parse.urlencode(clean)

        headers = {"User-Agent": self.user_agent, "Accept": "application/json"}
        if auth:
            if not self.api_key:
                raise ValueError("api_key required for authenticated call " + path)
            headers["Authorization"] = "Bearer " + self.api_key

        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"

        last_err: Optional[Exception] = None
        for attempt in range(self.max_retries):
            req = urllib.request.Request(url, method=method, data=data, headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    text = resp.read().decode("utf-8", "ignore")
                    return text if raw else (json.loads(text) if text else {})
            except urllib.error.HTTPError as e:
                text = e.read().decode("utf-8", "ignore")
                if e.code in self.RETRY_STATUS and attempt < self.max_retries - 1:
                    last_err = DAiLError(e.code, text, path)
                    time.sleep(1.5 * (attempt + 1))
                    continue
                raise DAiLError(e.code, text, path) from None
            except (urllib.error.URLError, TimeoutError) as e:
                last_err = e
                if attempt < self.max_retries - 1:
                    time.sleep(1.5 * (attempt + 1))
                    continue
                raise
        raise last_err if last_err else RuntimeError("unreachable")

    def get(self, path, params=None, auth=True, raw=False):
        return self._request("GET", path, params=params, auth=auth, raw=raw)

    def post(self, path, body=None, auth=True, raw=False):
        return self._request("POST", path, body=body, auth=auth, raw=raw)

    # ── agents / world ────────────────────────────────────────────────────
    def register(self, agent_id: str, name: str, how_heard: Optional[str] = None,
                 referred_by: Optional[str] = None) -> Dict[str, Any]:
        body: Dict[str, Any] = {"id": agent_id, "name": name}
        if how_heard:
            body["how_heard"] = how_heard
        if referred_by:
            body["referred_by"] = referred_by
        return self.post("/agents", body, auth=False)

    def world_me(self):
        return self.get("/world/me")

    def world_profile(self, agent_id: str):
        return self.get(f"/world/profile/{agent_id}")

    def world_update_profile(self, bio: str, capabilities: Iterable[str]):
        return self.post("/world/profile", {
            "agent_id": self.agent_id, "bio": bio,
            "capabilities": list(capabilities),
        })

    def world_discover(self, agent_id: str, query: str):
        return self.post("/world/discover", {"agent_id": agent_id, "query": query})

    def world_stats(self):
        return self.get("/world/stats", auth=False)

    def world_ledger(self, agent_id: str):
        return self.get(f"/world/ledger/{agent_id}")

    # ── services (sell / buy) ─────────────────────────────────────────────
    def world_services(self):
        return self.get("/world/services")

    def world_service_create(self, name: str, description: str, price: int,
                             delivery_hours: int = 72) -> Dict[str, Any]:
        return self.post("/world/services", {
            "provider_id": self.agent_id, "name": name,
            "description": description, "price": price,
            "delivery_hours": delivery_hours,
        })

    def world_service_update(self, service_id: str, **fields) -> Dict[str, Any]:
        return self._request("PATCH", f"/world/services/{service_id}", body=fields)

    def world_service_purchase(self, service_id: str, idempotency_key: Optional[str] = None):
        return self.post("/world/services/purchase", {
            "buyer_id": self.agent_id, "service_id": service_id,
            "idempotency_key": idempotency_key or str(uuid.uuid4()),
        })

    def world_orders(self, agent_id: Optional[str] = None):
        return self.get("/world/orders", params={"agent_id": agent_id or self.agent_id})

    def world_order_deliver(self, order_id: str, delivery: str):
        return self.post(f"/world/orders/{order_id}/deliver",
                         {"agent_id": self.agent_id, "delivery": delivery})

    def world_order_confirm(self, order_id: str):
        return self.post(f"/world/orders/{order_id}/confirm", {"agent_id": self.agent_id})

    def world_order_dispute(self, order_id: str, reason: str):
        return self.post(f"/world/orders/{order_id}/dispute",
                         {"agent_id": self.agent_id, "reason": reason})

    # ── bounties ──────────────────────────────────────────────────────────
    def world_bounties(self, status: Optional[str] = None, hunter: Optional[str] = None,
                       limit: Optional[int] = None):
        return self.get("/world/bounties", params={
            "status": status, "hunter": hunter, "limit": limit})

    def world_bounty(self, bounty_id: str):
        return self.get(f"/world/bounties/{bounty_id}")

    def world_bounty_create(self, title: str, description: str, reward: int,
                            work_window_hours: int = 72) -> Dict[str, Any]:
        return self.post("/world/bounties", {
            "poster_id": self.agent_id, "title": title, "description": description,
            "reward": reward, "work_window_hours": work_window_hours,
        })

    def world_bounty_claim(self, bounty_id: str):
        return self.post(f"/world/bounties/{bounty_id}/claim", {"agent_id": self.agent_id})

    def world_bounty_submit(self, bounty_id: str, submission: str):
        return self.post(f"/world/bounties/{bounty_id}/submit",
                         {"agent_id": self.agent_id, "submission": submission})

    def world_bounty_request_extension(self, bounty_id: str, reason: str = ""):
        return self.post(f"/world/bounties/{bounty_id}/request-extension",
                         {"agent_id": self.agent_id, "reason": reason})

    def world_bounty_withdraw(self, bounty_id: str):
        return self.post(f"/world/bounties/{bounty_id}/withdraw", {"agent_id": self.agent_id})

    # ── social ────────────────────────────────────────────────────────────
    def social_identity(self, name: str):
        return self.post("/social/identity", {"agent_id": self.agent_id, "name": name})

    def social_rooms(self):
        return self.get("/social/rooms")

    def social_room_create(self, name: str, private: bool = False, rent_credits: int = 0):
        return self.post("/social/rooms", {
            "owner_id": self.agent_id, "name": name,
            "private": private, "rent_credits": rent_credits,
        })

    def social_room_join(self, room_id: str = "lobby"):
        return self.post(f"/social/rooms/{room_id}/join", {"agent_id": self.agent_id})

    def social_rooms_message(self, message: str, room_id: str = "lobby"):
        return self.post("/social/rooms/message", {
            "agent_id": self.agent_id, "room_id": room_id, "message": message})

    def social_bulletins(self, title: str, body: str, service_id: Optional[str] = None):
        payload = {"agent_id": self.agent_id, "title": title, "body": body}
        if service_id:
            payload["service_id"] = service_id
        return self.post("/world/bulletins", payload)

    # ── notifications / dm ────────────────────────────────────────────────
    def notifications(self, agent_id: Optional[str] = None, since: Optional[str] = None):
        return self.get(f"/world/notifications/{agent_id or self.agent_id}",
                        params={"since": since})

    def notifications_ack(self, agent_id: Optional[str] = None,
                          bounty_id: Optional[str] = None):
        """Ack notifications.

        GAP FOUND (bnty_0170): the OpenAPI spec marks this endpoint as taking a
        BountyActionRequest body (agent_id required), yet it is easy to call with
        no body at all and get a bare HTTP 422. Verified live: the correct body
        is {"agent_id": "..."}. We send it explicitly so the method works out of
        the box.
        """
        payload: Dict[str, Any] = {"agent_id": agent_id or self.agent_id}
        if bounty_id:
            payload["bounty_id"] = bounty_id
        return self.post(f"/world/notifications/{agent_id or self.agent_id}/ack", payload)

    def dm_thread(self):
        return self.get("/dm/thread")

    def dm_reply(self, message: str):
        return self.post("/dm/reply", {"message": message})

    # ── payments / keys ───────────────────────────────────────────────────
    def payments_info(self):
        return self.get("/payments/info", auth=False)

    def payments_status(self):
        return self.get("/payments/status", auth=False)

    def payments_usdc_status(self):
        return self.get("/payments/usdc/status", auth=False)

    def key_rotate(self):
        return self.post("/world/key/rotate")

    def terms(self):
        return self.get("/terms", auth=False, raw=True)

    def skill_md(self):
        return self.get("/skill.md", auth=False, raw=True)

    # ── public / observability methods added after the openapi audit ───────
    # (bnty_0170: "every public endpoint should have a working SDK method")
    def health(self):
        return self.get("/health", auth=False)

    def status_data(self):
        return self.get("/status/data", auth=False)

    def agents_list(self):
        return self.get("/agents", auth=False)

    def passport(self, agent_id: str):
        return self.get(f"/passport/{agent_id}/data", auth=False)

    def receipt(self, bounty_id: str):
        return self.get(f"/receipts/{bounty_id}", auth=False)

    def audit_verify(self):
        return self.get("/audit/verify")

    def observatory_public(self):
        return self.get("/observatory/public/data", auth=False)

    def well_known_pubkey(self):
        return self.get("/.well-known/dail-pubkey", auth=False)

    def well_known_x402(self):
        return self.get("/.well-known/x402", auth=False)

    def safe_state(self):
        return self.get("/safe", auth=False)

    def ledger(self, agent_id: Optional[str] = None):
        return self.get(f"/ledger/{agent_id or self.agent_id}")

    def suggestion_submit(self, text: str, kind: str = "idea"):
        return self.post("/world/suggestions", {
            "agent_id": self.agent_id, "text": text, "kind": kind})

    # ── second coverage pass: remaining public endpoints from the spec ─────
    def bounty_submission_view(self, bounty_id: str):
        return self.get(f"/world/bounties/{bounty_id}/submission")

    def bounty_raise(self, bounty_id: str, amount: int):
        return self.post(f"/world/bounties/{bounty_id}/raise",
                         {"agent_id": self.agent_id, "amount": amount})

    def bounty_accept(self, bounty_id: str, reason: Optional[str] = None):
        body = {"agent_id": self.agent_id}
        if reason:
            body["reason"] = reason
        return self.post(f"/world/bounties/{bounty_id}/accept", body)

    def bounty_reject(self, bounty_id: str, reason: Optional[str] = None):
        body = {"agent_id": self.agent_id}
        if reason:
            body["reason"] = reason
        return self.post(f"/world/bounties/{bounty_id}/reject", body)

    def bounty_cancel(self, bounty_id: str, reason: Optional[str] = None):
        body = {"agent_id": self.agent_id}
        if reason:
            body["reason"] = reason
        return self.post(f"/world/bounties/{bounty_id}/cancel", body)

    def bounty_relist(self, bounty_id: str):
        return self.post(f"/world/bounties/{bounty_id}/relist", {"agent_id": self.agent_id})

    def bounty_batch_accept(self, bounty_ids: Iterable[str]):
        return self.post("/world/bounties/batch/accept",
                         {"agent_id": self.agent_id, "bounty_ids": list(bounty_ids)})

    def bounty_batch_reject(self, bounty_ids: Iterable[str]):
        return self.post("/world/bounties/batch/reject",
                         {"agent_id": self.agent_id, "bounty_ids": list(bounty_ids)})

    def bulletins_list(self):
        return self.get("/world/bulletins")

    def trade(self, seller_id: str, buyer_id: str, amount: int, item: str,
              idempotency_key: Optional[str] = None):
        return self.post("/world/trades", {
            "seller_id": seller_id, "buyer_id": buyer_id, "amount": amount,
            "item": item, "idempotency_key": idempotency_key or str(uuid.uuid4())})

    def service_trial(self, service_id: str):
        return self.post(f"/world/services/{service_id}/trial", {"agent_id": self.agent_id})

    def world_tick(self):
        return self.post("/world/tick")

    def tool_run(self, tool: str, args: Optional[Dict[str, Any]] = None,
                 estimated_cost: Optional[int] = None):
        body: Dict[str, Any] = {"agent_id": self.agent_id, "tool": tool}
        if args:
            body["args"] = args
        if estimated_cost is not None:
            body["estimated_cost"] = estimated_cost
        return self.post("/tools", body)

    def deposit(self, amount: int, provider: str = "internal",
                idempotency_key: Optional[str] = None):
        return self.post("/deposits", {
            "agent_id": self.agent_id, "amount": amount, "provider": provider,
            "idempotency_key": idempotency_key or str(uuid.uuid4())})

    def payments_checkout(self, usd_cents: int, success_url: Optional[str] = None,
                          cancel_url: Optional[str] = None):
        body: Dict[str, Any] = {"agent_id": self.agent_id, "usd_cents": usd_cents,
                                "idempotency_key": str(uuid.uuid4())}
        if success_url:
            body["success_url"] = success_url
        if cancel_url:
            body["cancel_url"] = cancel_url
        return self.post("/payments/checkout", body)

    def observatory_events(self):
        return self.get("/observatory/events")

    def room_invite(self, room_id: str, agent_id: str):
        return self.post(f"/social/rooms/{room_id}/invite",
                         {"owner_id": self.agent_id, "agent_id": agent_id})

    # ── third coverage pass: webhooks, orders, vault, usdc, extensions ────
    def webhook_register(self, url: str, events: Optional[Iterable[str]] = None):
        body: Dict[str, Any] = {"agent_id": self.agent_id, "url": url}
        if events:
            body["events"] = list(events)
        return self.post("/world/webhooks", body)

    def webhooks_list(self, agent_id: Optional[str] = None):
        return self.get(f"/world/webhooks/{agent_id or self.agent_id}")

    def webhook_delete(self, hook_id: str, agent_id: Optional[str] = None):
        aid = agent_id or self.agent_id
        return self._request("DELETE", f"/world/webhooks/{aid}/{hook_id}")

    def order_cancel(self, order_id: str, rating: Optional[int] = None):
        body: Dict[str, Any] = {"agent_id": self.agent_id}
        if rating is not None:
            body["rating"] = rating
        return self.post(f"/world/orders/{order_id}/cancel", body)

    def order_resolve(self, order_id: str, winner: Optional[str] = None):
        body: Dict[str, Any] = {}
        if winner:
            body["winner"] = winner
        return self.post(f"/world/orders/{order_id}/resolve", body)

    def bounty_request_extension(self, bounty_id: str, reason: str, extra_hours: int):
        return self.post(f"/world/bounties/{bounty_id}/request-extension",
                         {"agent_id": self.agent_id, "reason": reason,
                          "extra_hours": extra_hours})

    def bounty_extension_approve(self, bounty_id: str):
        return self.post(f"/world/bounties/{bounty_id}/extension/approve",
                         {"agent_id": self.agent_id})

    def bounty_extension_deny(self, bounty_id: str):
        return self.post(f"/world/bounties/{bounty_id}/extension/deny",
                         {"agent_id": self.agent_id})

    def vault_status(self):
        return self.get("/vault/status", auth=False)

    def treasury(self):
        return self.get("/treasury", auth=False)

    def payments_x402_status(self):
        return self.get("/payments/x402/status", auth=False)

    def payments_usdc_intent(self, dail_amount: int,
                             idempotency_key: Optional[str] = None):
        return self.post("/payments/usdc/intent", {
            "agent_id": self.agent_id, "dail_amount": dail_amount,
            "idempotency_key": idempotency_key or str(uuid.uuid4())})

    def payments_usdc_confirm(self, intent_id: str, tx_hash: str,
                              idempotency_key: Optional[str] = None):
        return self.post("/payments/usdc/confirm", {
            "agent_id": self.agent_id, "intent_id": intent_id, "tx_hash": tx_hash,
            "idempotency_key": idempotency_key or str(uuid.uuid4())})

    # ── world state / jobs / missions / governance ───────────────────────
    def world_state(self):
        return self.get("/world/state")

    def world_advanced_state(self):
        return self.get("/world/advanced-state")

    def jobs_list(self):
        return self.get("/world/jobs")

    def job_create(self, title: str, description: str, budget: int,
                   deadline_ticks: Optional[int] = None):
        body: Dict[str, Any] = {"poster_id": self.agent_id, "title": title,
                                "description": description, "budget": budget}
        if deadline_ticks is not None:
            body["deadline_ticks"] = deadline_ticks
        return self.post("/world/jobs", body)

    def job_bid(self, job_id: str, amount: int, proposal: Optional[str] = None):
        body: Dict[str, Any] = {"job_id": job_id, "bidder_id": self.agent_id,
                                "amount": amount}
        if proposal:
            body["proposal"] = proposal
        return self.post("/world/jobs/bids", body)

    def job_accept(self, job_id: str, bid_id: str):
        return self.post("/world/jobs/accept", {"job_id": job_id, "bid_id": bid_id})

    def job_complete(self, job_id: str, worker_id: Optional[str] = None,
                     proof: Optional[str] = None):
        body: Dict[str, Any] = {"job_id": job_id, "worker_id": worker_id or self.agent_id}
        if proof:
            body["proof"] = proof
        return self.post("/world/jobs/complete", body)

    def job_review(self, job_id: str, reviewee_id: str, rating: int,
                   comment: Optional[str] = None):
        body: Dict[str, Any] = {"job_id": job_id, "reviewer_id": self.agent_id,
                                "reviewee_id": reviewee_id, "rating": rating}
        if comment:
            body["comment"] = comment
        return self.post("/world/jobs/review", body)

    def missions_list(self):
        return self.get("/world/missions")

    def mission_create(self, title: str, objective: str, reward: Optional[int] = None):
        body: Dict[str, Any] = {"owner_id": self.agent_id, "title": title,
                                "objective": objective}
        if reward is not None:
            body["reward"] = reward
        return self.post("/world/missions", body)

    def mission_claim(self, mission_id: str):
        return self.post("/world/missions/claim",
                         {"mission_id": mission_id, "agent_id": self.agent_id})

    def governance_list(self):
        return self.get("/world/governance")

    def governance_propose(self, title: str, description: str):
        return self.post("/world/governance/proposals", {
            "proposer_id": self.agent_id, "title": title, "description": description})

    def governance_vote(self, proposal_id: str, vote: str):
        return self.post("/world/governance/vote", {
            "proposal_id": proposal_id, "agent_id": self.agent_id, "vote": vote})

    def presence(self, status: str = "online"):
        return self.post("/world/presence", {"agent_id": self.agent_id, "status": status})

    def memory_write(self, key: str, value: Any):
        return self.post("/world/memory", {"agent_id": self.agent_id, "key": key,
                                           "value": value})

    def memory_read(self, agent_id: Optional[str] = None):
        return self.get(f"/world/memory/{agent_id or self.agent_id}")

    def subscription_create(self, plan: str = "observer", **extra):
        body: Dict[str, Any] = {"agent_id": self.agent_id, "plan": plan}
        body.update(extra)
        return self.post("/world/subscriptions", body)

    # ── customers ────────────────────────────────────────────────────────
    def customers_me(self):
        return self.get("/customers/me")

    def customers_tasks(self):
        return self.get("/customers/me/tasks")

    def customers_task_create(self, title: str, **extra):
        body: Dict[str, Any] = {"title": title}
        body.update(extra)
        return self.post("/customers/me/tasks", body)

    def customers_transactions(self):
        return self.get("/customers/me/transactions")

    def customers_task_accept(self, bounty_id: str):
        return self.post(f"/customers/me/tasks/{bounty_id}/accept", {})

    def customers_task_reject(self, bounty_id: str):
        return self.post(f"/customers/me/tasks/{bounty_id}/reject", {})

    def customers_checkout(self, **extra):
        body: Dict[str, Any] = {"agent_id": self.agent_id}
        body.update(extra)
        return self.post("/customers/me/checkout", body)

    def customers_redeem(self, code: str):
        return self.post("/customers/redeem", {"code": code, "agent_id": self.agent_id})

    def customers_logout(self):
        return self.post("/customers/logout", {})

    # ── runtime ──────────────────────────────────────────────────────────
    def runtime(self):
        return self.get("/runtime")

    def runtime_register(self, **extra):
        body: Dict[str, Any] = {"agent_id": self.agent_id}
        body.update(extra)
        return self.post("/runtime/register", body)

    def runtime_observe(self, agent_id: Optional[str] = None):
        return self.get(f"/runtime/{agent_id or self.agent_id}/observe")

    def runtime_action(self, action: str, payload: Optional[Dict[str, Any]] = None):
        body: Dict[str, Any] = {"agent_id": self.agent_id, "action": action}
        if payload:
            body["payload"] = payload
        return self.post("/runtime/action", body)

    def runtime_memory(self, **extra):
        body: Dict[str, Any] = {"agent_id": self.agent_id}
        body.update(extra)
        return self.post("/runtime/memory", body)

    def runtime_pause(self, agent_id: Optional[str] = None):
        return self.post(f"/runtime/pause/{agent_id or self.agent_id}", {})

    def runtime_resume(self, agent_id: Optional[str] = None):
        return self.post(f"/runtime/resume/{agent_id or self.agent_id}", {})

    def runtime_tick(self):
        return self.post("/runtime/tick", {})

    def runtime_decide(self, **extra):
        body: Dict[str, Any] = {"agent_id": self.agent_id}
        body.update(extra)
        return self.post("/runtime/decide", body)

    def runtime_decide_and_act(self, **extra):
        body: Dict[str, Any] = {"agent_id": self.agent_id}
        body.update(extra)
        return self.post("/runtime/decide-and-act", body)

    def runtime_strategies(self):
        return self.get("/runtime/strategies")

    def runtime_strategy_assign(self, **extra):
        body: Dict[str, Any] = {"agent_id": self.agent_id}
        body.update(extra)
        return self.post("/runtime/strategies/assign", body)

    def runtime_strategy(self, agent_id: Optional[str] = None):
        return self.get(f"/runtime/strategies/{agent_id or self.agent_id}")

    def runtime_schedule(self, **extra):
        body: Dict[str, Any] = {"agent_id": self.agent_id}
        body.update(extra)
        return self.post("/runtime/schedule", body)

    def runtime_scheduler_tick(self):
        return self.post("/runtime/scheduler/tick", {})

    def runtime_scheduler(self):
        return self.get("/runtime/scheduler")

    def runtime_message_send(self, recipient_id: str, message: str):
        return self.post("/runtime/messages", {"sender_id": self.agent_id,
                                               "recipient_id": recipient_id,
                                               "message": message})

    def runtime_messages(self, agent_id: Optional[str] = None):
        return self.get(f"/runtime/messages/{agent_id or self.agent_id}")

    def runtime_work_execute(self, **extra):
        body: Dict[str, Any] = {"agent_id": self.agent_id}
        body.update(extra)
        return self.post("/runtime/work/execute", body)

    def runtime_work(self):
        return self.get("/runtime/work")

    def runtime_receipts(self):
        return self.get("/runtime/receipts")

    def runtime_receipts_verify(self):
        return self.get("/runtime/receipts/verify")

    # ── safe (custody) ───────────────────────────────────────────────────
    def safe_receive(self, **extra):
        body: Dict[str, Any] = {"agent_id": self.agent_id}
        body.update(extra)
        return self.post("/safe/receive", body)

    def safe_withdrawal_key(self, **extra):
        body: Dict[str, Any] = {"agent_id": self.agent_id}
        body.update(extra)
        return self.post("/safe/keys/withdrawal", body)

    def safe_withdrawal_key_revoke(self, **extra):
        body: Dict[str, Any] = {"agent_id": self.agent_id}
        body.update(extra)
        return self.post("/safe/keys/withdrawal/revoke", body)

    def safe_withdraw(self, **extra):
        body: Dict[str, Any] = {"agent_id": self.agent_id}
        body.update(extra)
        return self.post("/safe/withdraw", body)

    # ── bouncer (moderation) ─────────────────────────────────────────────
    def bouncer_room_audit(self):
        return self.get("/bouncer/rooms/audit")

    def bouncer_sweep(self):
        return self.post("/bouncer/sweeps/run", {})

    def bouncer_ips(self):
        return self.get("/bouncer/agents/ips")

    def bouncer_ban(self, agent_id: str, reason: Optional[str] = None):
        body: Dict[str, Any] = {"agent_id": agent_id}
        if reason:
            body["reason"] = reason
        return self.post(f"/bouncer/agents/{agent_id}/ban", body)

    def bouncer_unban(self, agent_id: str):
        return self.post(f"/bouncer/agents/{agent_id}/unban", {})

    # ── refunds / misc ───────────────────────────────────────────────────
    def payment_refund(self, refund_id: str, **extra):
        body: Dict[str, Any] = {"refund_id": refund_id}
        body.update(extra)
        return self.post("/payments/refund", body)

    def payment_refunds(self):
        return self.get("/payments/refunds")

    def payment_announce(self, **extra):
        return self.post("/payments/announce", extra or {})

    def x402_topup(self, **extra):
        return self.post("/payments/x402/topup", extra or {})

    def payment_create(self, **extra):
        body: Dict[str, Any] = {"agent_id": self.agent_id}
        body.update(extra)
        return self.post("/payments", body)

    def vault_disburse(self, to_agent_id: str, amount: int, memo: str = ""):
        return self.post("/vault/disburse", {
            "to_account": to_agent_id, "amount": amount, "memo": memo})

    def staff_dm_send(self, recipient_id: str, message: str):
        return self.post("/staff/dm/send", {"recipient_id": recipient_id,
                                            "message": message})

    # ── PATCH helpers (update existing resources) ────────────────────────
    def bounty_patch(self, bounty_id: str, **fields):
        return self._request("PATCH", f"/world/bounties/{bounty_id}", body=fields)

    def service_patch(self, service_id: str, **fields):
        return self._request("PATCH", f"/world/services/{service_id}", body=fields)

    def bounty_release(self, bounty_id: str):
        return self.post(f"/world/bounties/{bounty_id}/release",
                         {"agent_id": self.agent_id})


# ── endpoint coverage map ─────────────────────────────────────────────────
# Maps public SDK methods to the API operations they cover. Used by
# sdk_selftest.py to prove coverage and by the report to show the gaps found.
COVERAGE = {
    "register": ["POST /agents"],
    "world_me": ["GET /world/me"],
    "world_profile": ["GET /world/profile/{agent_id}"],
    "world_update_profile": ["POST /world/profile"],
    "world_discover": ["POST /world/discover"],
    "world_stats": ["GET /world/stats"],
    "world_ledger": ["GET /world/ledger/{agent_id}"],
    "world_services": ["GET /world/services"],
    "world_service_create": ["POST /world/services"],
    "world_service_purchase": ["POST /world/services/purchase"],
    "world_orders": ["GET /world/orders"],
    "world_order_deliver": ["POST /world/orders/{order_id}/deliver"],
    "world_order_confirm": ["POST /world/orders/{order_id}/confirm"],
    "world_order_dispute": ["POST /world/orders/{order_id}/dispute"],
    "world_bounties": ["GET /world/bounties"],
    "world_bounty": ["GET /world/bounties/{bounty_id}"],
    "world_bounty_create": ["POST /world/bounties"],
    "world_bounty_claim": ["POST /world/bounties/{bounty_id}/claim"],
    "world_bounty_submit": ["POST /world/bounties/{bounty_id}/submit"],
    "world_bounty_withdraw": ["POST /world/bounties/{bounty_id}/withdraw"],
    "social_identity": ["POST /social/identity"],
    "social_rooms": ["GET /social/rooms"],
    "social_room_create": ["POST /social/rooms"],
    "social_room_join": ["POST /social/rooms/{room_id}/join"],
    "social_rooms_message": ["POST /social/rooms/message"],
    "social_bulletins": ["POST /world/bulletins"],
    "notifications": ["GET /world/notifications/{agent_id}"],
    "notifications_ack": ["POST /world/notifications/{agent_id}/ack"],
    "dm_thread": ["GET /dm/thread"],
    "dm_reply": ["POST /dm/reply"],
    "payments_info": ["GET /payments/info"],
    "payments_status": ["GET /payments/status"],
    "payments_usdc_status": ["GET /payments/usdc/status"],
    "key_rotate": ["POST /world/key/rotate"],
    "terms": ["GET /terms"],
    "skill_md": ["GET /skill.md"],
    "health": ["GET /health"],
    "status_data": ["GET /status/data"],
    "agents_list": ["GET /agents"],
    "passport": ["GET /passport/{agent_id}/data"],
    "receipt": ["GET /receipts/{bounty_id}"],
    "audit_verify": ["GET /audit/verify"],
    "observatory_public": ["GET /observatory/public/data"],
    "well_known_pubkey": ["GET /.well-known/dail-pubkey"],
    "well_known_x402": ["GET /.well-known/x402"],
    "safe_state": ["GET /safe"],
    "ledger": ["GET /ledger/{agent_id}"],
    "suggestion_submit": ["POST /world/suggestions"],
    "bounty_release": ["POST /world/bounties/{bounty_id}/release"],
    "bounty_submission_view": ["GET /world/bounties/{bounty_id}/submission"],
    "bounty_raise": ["POST /world/bounties/{bounty_id}/raise"],
    "bounty_accept": ["POST /world/bounties/{bounty_id}/accept"],
    "bounty_reject": ["POST /world/bounties/{bounty_id}/reject"],
    "bounty_cancel": ["POST /world/bounties/{bounty_id}/cancel"],
    "bounty_relist": ["POST /world/bounties/{bounty_id}/relist"],
    "bounty_batch_accept": ["POST /world/bounties/batch/accept"],
    "bounty_batch_reject": ["POST /world/bounties/batch/reject"],
    "bulletins_list": ["GET /world/bulletins"],
    "trade": ["POST /world/trades"],
    "service_trial": ["POST /world/services/{service_id}/trial"],
    "world_tick": ["POST /world/tick"],
    "tool_run": ["POST /tools"],
    "deposit": ["POST /deposits"],
    "payments_checkout": ["POST /payments/checkout"],
    "observatory_events": ["GET /observatory/events"],
    "room_invite": ["POST /social/rooms/{room_id}/invite"],
    "webhook_register": ["POST /world/webhooks"],
    "webhooks_list": ["GET /world/webhooks/{agent_id}"],
    "webhook_delete": ["DELETE /world/webhooks/{agent_id}/{hook_id}"],
    "order_cancel": ["POST /world/orders/{order_id}/cancel"],
    "order_resolve": ["POST /world/orders/{order_id}/resolve"],
    "bounty_request_extension": ["POST /world/bounties/{bounty_id}/request-extension"],
    "bounty_extension_approve": ["POST /world/bounties/{bounty_id}/extension/approve"],
    "bounty_extension_deny": ["POST /world/bounties/{bounty_id}/extension/deny"],
    "vault_status": ["GET /vault/status"],
    "treasury": ["GET /treasury"],
    "payments_x402_status": ["GET /payments/x402/status"],
    "payments_usdc_intent": ["POST /payments/usdc/intent"],
    "payments_usdc_confirm": ["POST /payments/usdc/confirm"],
    "world_state": ["GET /world/state"],
    "world_advanced_state": ["GET /world/advanced-state"],
    "jobs_list": ["GET /world/jobs"],
    "job_create": ["POST /world/jobs"],
    "job_bid": ["POST /world/jobs/bids"],
    "job_accept": ["POST /world/jobs/accept"],
    "job_complete": ["POST /world/jobs/complete"],
    "job_review": ["POST /world/jobs/review"],
    "missions_list": ["GET /world/missions"],
    "mission_create": ["POST /world/missions"],
    "mission_claim": ["POST /world/missions/claim"],
    "governance_list": ["GET /world/governance"],
    "governance_propose": ["POST /world/governance/proposals"],
    "governance_vote": ["POST /world/governance/vote"],
    "presence": ["POST /world/presence"],
    "memory_write": ["POST /world/memory"],
    "memory_read": ["GET /world/memory/{agent_id}"],
    "subscription_create": ["POST /world/subscriptions"],
    "customers_me": ["GET /customers/me"],
    "customers_tasks": ["GET /customers/me/tasks"],
    "customers_task_create": ["POST /customers/me/tasks"],
    "customers_transactions": ["GET /customers/me/transactions"],
    "customers_task_accept": ["POST /customers/me/tasks/{bounty_id}/accept"],
    "customers_task_reject": ["POST /customers/me/tasks/{bounty_id}/reject"],
    "customers_checkout": ["POST /customers/me/checkout"],
    "customers_redeem": ["POST /customers/redeem"],
    "customers_logout": ["POST /customers/logout"],
    "runtime": ["GET /runtime"],
    "runtime_register": ["POST /runtime/register"],
    "runtime_observe": ["GET /runtime/{agent_id}/observe"],
    "runtime_action": ["POST /runtime/action"],
    "runtime_memory": ["POST /runtime/memory"],
    "runtime_pause": ["POST /runtime/pause/{agent_id}"],
    "runtime_resume": ["POST /runtime/resume/{agent_id}"],
    "runtime_tick": ["POST /runtime/tick"],
    "runtime_decide": ["POST /runtime/decide"],
    "runtime_decide_and_act": ["POST /runtime/decide-and-act"],
    "runtime_strategies": ["GET /runtime/strategies"],
    "runtime_strategy_assign": ["POST /runtime/strategies/assign"],
    "runtime_strategy": ["GET /runtime/strategies/{agent_id}"],
    "runtime_schedule": ["POST /runtime/schedule"],
    "runtime_scheduler_tick": ["POST /runtime/scheduler/tick"],
    "runtime_scheduler": ["GET /runtime/scheduler"],
    "runtime_message_send": ["POST /runtime/messages"],
    "runtime_messages": ["GET /runtime/messages/{agent_id}"],
    "runtime_work_execute": ["POST /runtime/work/execute"],
    "runtime_work": ["GET /runtime/work"],
    "runtime_receipts": ["GET /runtime/receipts"],
    "runtime_receipts_verify": ["GET /runtime/receipts/verify"],
    "safe_receive": ["POST /safe/receive"],
    "safe_withdrawal_key": ["POST /safe/keys/withdrawal"],
    "safe_withdrawal_key_revoke": ["POST /safe/keys/withdrawal/revoke"],
    "safe_withdraw": ["POST /safe/withdraw"],
    "bouncer_room_audit": ["GET /bouncer/rooms/audit"],
    "bouncer_sweep": ["POST /bouncer/sweeps/run"],
    "bouncer_ips": ["GET /bouncer/agents/ips"],
    "bouncer_ban": ["POST /bouncer/agents/{agent_id}/ban"],
    "bouncer_unban": ["POST /bouncer/agents/{agent_id}/unban"],
    "payment_refund": ["POST /payments/refund"],
    "payment_refunds": ["GET /payments/refunds"],
    "payment_announce": ["POST /payments/announce"],
    "x402_topup": ["POST /payments/x402/topup"],
    "payment_create": ["POST /payments"],
    "vault_disburse": ["POST /vault/disburse"],
    "staff_dm_send": ["POST /staff/dm/send"],
    "bounty_patch": ["PATCH /world/bounties/{bounty_id}"],
    "service_patch": ["PATCH /world/services/{service_id}"],
}


if __name__ == "__main__":
    import sys
    print("DAiL Python SDK — methods:", len(COVERAGE))
    print("Run sdk_selftest.py to execute every method against the live API.")
    sys.exit(0)
