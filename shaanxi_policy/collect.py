"""Bounded incremental collection with persistent queues and source health."""

import copy
from datetime import datetime, timedelta

from industry_monitor_core.web import FetchError
from .extract import discover, extract, relevant
from .http import PolicyClient

USER_AGENT = "ShaanxiPolicyMonitor/0.1 (+https://github.com/Business-Unit-for-Enterprise-Service/shaanxi-policy-monitor)"


def empty_state():
    return {"schema_version": 1, "records": {}, "sources": {}, "events": [], "queue": {}}


def collect(sources, previous, instant, budget=12, client=None):
    state = copy.deepcopy(previous)
    stamp = instant.isoformat(timespec="seconds")
    today = instant.date().isoformat()
    client = client or PolicyClient(delay=2, timeout=15, user_agent=USER_AGENT)
    health = []
    for source in sources:
        sid = source["id"]
        report = {"id": sid, "name": source["name"], "url": source["url"], "region": source["region"], "status": "disabled", "checked": 0, "failed": 0, "pending": 0}
        if not source["enabled"]:
            report["message"] = source["reason"]
            health.append(report)
            continue
        info = state["sources"].setdefault(sid, {})
        report["last_success_at"] = info.get("last_success_at")
        queue = state["queue"].setdefault(sid, {})
        baseline = not info.get("initialized_at")
        try:
            listing = client.fetch(source["url"], source)
            links = discover(listing, source)
            for link in links:
                # Revisit visible policies, and older retained policies in a rotating queue.
                queue.setdefault(link["url"], {**link, "baseline": baseline, "queued_at": stamp})
            for url in source.get("seeds", []):
                queue.setdefault(url, {"url": url, "title": "参考政策", "baseline": baseline, "queued_at": stamp})
            info.setdefault("initialized_at", stamp)
            report["status"] = "ok"
            report["message"] = "已检查栏目首页；文章按预算轮换复查"
        except FetchError as error:
            report.update(status="failed", message=str(error))
            # Keep old records, but never misreport failure as no new policies.
            report["pending"] = len(queue)
            health.append(report)
            continue
        for url, old in state["records"].items():
            if old["source_id"] == sid and (instant - datetime.fromisoformat(old["last_checked_at"])).days >= 7:
                queue.setdefault(url, {"url": url, "title": old["title"], "baseline": False, "queued_at": stamp})
        # Oldest queued work first, then refresh the least recently checked article.
        pending = sorted(queue.values(), key=lambda item: (item["url"] in state["records"], item["queued_at"], state["records"].get(item["url"], {}).get("last_checked_at", "")))
        for item in pending[:budget]:
            url = item["url"]
            try:
                page = client.fetch(url, source)
                record = extract(page, source)
                if not relevant(record["title"]):
                    queue.pop(url, None)
                    report["checked"] += 1
                    continue
                old = state["records"].get(url)
                record["first_seen_at"] = old["first_seen_at"] if old else stamp
                record["last_checked_at"] = stamp
                record["last_changed_at"] = old["last_changed_at"] if old and old["content_hash"] == record["content_hash"] else stamp
                state["records"][url] = record
                if not old:
                    kind = "baseline" if item["baseline"] else "discovered"
                else:
                    kind = "updated" if old["content_hash"] != record["content_hash"] else None
                if kind and not any(e["date"] == today and e["url"] == url and e["kind"] == kind for e in state["events"]):
                    state["events"].append({"date": today, "url": url, "kind": kind, "at": stamp})
                queue.pop(url, None)
                report["checked"] += 1
            except FetchError as error:
                report["failed"] += 1
                report["message"] = "部分文章未能读取：" + str(error)
                # The next daily run retries. Never hammer a blocking response.
                if "HTTP 403" in str(error) or "HTTP 429" in str(error) or "Challenge" in str(error):
                    break
        report["pending"] = len(queue)
        if report["failed"] or report["pending"]:
            report["status"] = "partial"
        if not report["failed"]:
            info["last_success_at"] = stamp
            report["last_success_at"] = stamp
        info["last_attempt_at"] = stamp
        health.append(report)
    cutoff = (instant.date() - timedelta(days=90)).isoformat()
    state["events"] = [e for e in state["events"] if e["date"] >= cutoff]
    state["updated_at"] = stamp
    return state, health
