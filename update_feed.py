#!/usr/bin/env python3
"""Fetch NIH-related opportunities and render a searchable static funding feed."""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

ROOT = Path(__file__).resolve().parent
API = "https://api.grants.gov/v1/api"
GUIDE_RSS = "https://grants.nih.gov/grants/guide/newsfeed/fundingopps.xml"
TOPICS_URL = "https://grants.nih.gov/funding/find-a-fit-for-your-research/highlighted-topics"
UA = "NIH-Funding-Radar/1.0 (personal research funding monitor)"


def clean(value: Any) -> str:
    text = re.sub(r"<[^>]+>", " ", str(value or ""))
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def request_bytes(url: str, payload: dict | None = None) -> bytes:
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {"User-Agent": UA, "Accept": "application/json, application/xml, text/html"}
    if data is not None: headers["Content-Type"] = "application/json"
    with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=headers), timeout=45) as response:
        return response.read()


def iso_date(value: str) -> str:
    if not value:
        return ""
    for fmt in ("%m/%d/%Y", "%b %d, %Y %I:%M:%S %p %Z", "%Y-%m-%d-%H-%M-%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(value.strip(), fmt).date().isoformat()
        except ValueError:
            pass
    try:
        return parsedate_to_datetime(value).date().isoformat()
    except (TypeError, ValueError, OverflowError):
        pass
    match = re.search(r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w* \d{1,2}, \d{4}", value)
    if match:
        return datetime.strptime(match.group(), "%B %d, %Y").date().isoformat()
    return ""


def post(session: object, endpoint: str, payload: dict) -> dict:
    body = json.loads(request_bytes(f"{API}/{endpoint}", payload))
    if body.get("errorcode") not in (None, 0):
        raise RuntimeError(body.get("msg", f"Grants.gov error {body['errorcode']}"))
    return body.get("data", body)


def collect_grants(session: object, max_items: int) -> list[dict]:
    payload = {"rows": min(max_items, 1000), "agencies": "HHS-NIH11", "oppStatuses": "forecasted|posted", "sortBy": "openDate|desc"}
    hits = post(session, "search2", payload).get("oppHits", [])
    results = []
    for hit in hits:
        number = clean(hit.get("number"))
        item = {
            "id": f"grant:{hit.get('id', number)}", "kind": "Funding opportunity",
            "number": number, "title": clean(hit.get("title")),
            "agency": clean(hit.get("agencyName") or hit.get("agencyCode")),
            "posted": iso_date(hit.get("openDate", "")), "deadline": iso_date(hit.get("closeDate", "")),
            "status": clean(hit.get("oppStatus", "posted")).title(),
            "url": f"https://www.grants.gov/search-results-detail/{hit.get('id')}",
            "description": "", "source": "Grants.gov"
        }
        try:
            detail = post(session, "fetchOpportunity", {"opportunityId": int(hit["id"])})
            synopsis = detail.get("synopsis") or {}
            item["description"] = clean(synopsis.get("synopsisDesc"))
            item["posted"] = iso_date(synopsis.get("postingDate", "")) or item["posted"]
            item["deadline"] = iso_date(detail.get("originalDueDateDesc", "")) or item["deadline"]
            item["agency"] = clean(synopsis.get("agencyName")) or item["agency"]
        except Exception as exc:
            print(f"warning: detail fetch failed for {number}: {exc}", file=sys.stderr)
        results.append(item)
    return results


def collect_guide(session: object) -> list[dict]:
    root = ET.fromstring(request_bytes(GUIDE_RSS))
    results = []
    for node in root.findall(".//item"):
        title = clean(node.findtext("title", "")); link = clean(node.findtext("link", ""))
        number = (re.search(r"\b(?:NOT|PA|PAR|PAS|RFA)-[A-Z]+-\d{2}-\d+\b", title) or [""])[0]
        results.append({
            "id": f"guide:{number or hashlib.sha1(link.encode()).hexdigest()[:12]}",
            "kind": "NIH Guide notice", "number": number, "title": title,
            "agency": "NIH", "posted": iso_date(clean(node.findtext("pubDate", ""))),
            "deadline": "", "status": "Published", "url": link,
            "description": clean(node.findtext("description", "")), "source": "NIH Guide"
        })
    return results


def collect_topics(session: object) -> list[dict]:
    """Parse server-rendered topic tables/cards. If NIH changes markup, fail visibly."""
    page = request_bytes(TOPICS_URL).decode("utf-8", "replace")
    results = []
    for row in re.findall(r"<tr\b[^>]*>(.*?)</tr>", page, re.I | re.S):
        cells = re.findall(r"<t[dh]\b[^>]*>(.*?)</t[dh]>", row, re.I | re.S)
        if len(cells) < 4:
            continue
        link = re.search(r"<a\b[^>]*href=[\"']([^\"']+)", cells[0], re.I)
        title = clean(cells[0])
        if not title:
            continue
        url = urljoin(TOPICS_URL, html.unescape(link.group(1))) if link else TOPICS_URL
        results.append({
            "id": "topic:" + hashlib.sha1(url.encode()).hexdigest()[:12], "kind": "Highlighted topic",
            "number": "", "title": title, "agency": clean(cells[1]), "posted": iso_date(clean(cells[-2])),
            "deadline": iso_date(clean(cells[-1])), "status": "Highlighted", "url": url,
            "description": f"Participating ICOs: {clean(cells[2])}", "source": "NIH Highlighted Topics"
        })
    if not results:
        # NIH currently injects rows client-side. This sentinel makes page changes visible in the feed.
        marker = hashlib.sha1(clean(page).encode()).hexdigest()[:12]
        results.append({
            "id": f"topics-page:{marker}", "kind": "Highlighted topics update", "number": "",
            "title": "Review NIH Highlighted Topics", "agency": "NIH", "posted": datetime.now(timezone.utc).date().isoformat(),
            "deadline": "", "status": "Page monitored", "url": TOPICS_URL,
            "description": "NIH loads topic rows dynamically; the daily monitor tracks the official page and links to the current list.",
            "source": "NIH Highlighted Topics"
        })
    return results


def score_item(item: dict, cfg: dict) -> dict:
    text = " ".join(str(item.get(k, "")) for k in ("title", "description", "agency", "number")).lower()
    groups, matches, score = [], [], 0
    for group, terms in cfg["keywords"].items():
        found = [term for term in terms if re.search(rf"(?<!\w){re.escape(term.lower())}(?!\w)", text)]
        if found:
            groups.append(group); matches.extend(found)
            score += min(5, 2 + len(found))
    if any(inst.lower() in text for inst in cfg.get("priority_institutes", [])):
        score += 2
    if re.search(r"\b(RFA|PAR|PAS)-", item.get("number", ""), re.I):
        score += 1
    excluded = [term for term in cfg.get("exclude_keywords", []) if term.lower() in text]
    score -= 5 * len(excluded)
    item.update(score=max(score, 0), topics=groups, matches=sorted(set(matches)), excluded=excluded)
    return item


def load_seen(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {"items": {}}


def render(items: list[dict], cfg: dict, out: Path, errors: list[str]) -> None:
    template = (ROOT / "templates" / "index.html").read_text()
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    payload = json.dumps({"items": items, "updated": now, "errors": errors}, ensure_ascii=False).replace("</", "<\\/")
    page = template.replace("{{SITE_TITLE}}", html.escape(cfg["site_title"])).replace("{{DATA}}", payload)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page)


def demo_items() -> list[dict]:
    today = datetime.now(timezone.utc).date()
    return [{"id":"demo:1","kind":"Funding opportunity","number":"RFA-HD-27-001","title":"Maternal and Infant Nutrition Research (demonstration)","agency":"NICHD","posted":str(today),"deadline":str(today+timedelta(days=90)),"status":"Posted","url":"https://grants.nih.gov/","description":"Example opportunity involving lactation, human milk, infant nutrition, metabolomics, and the microbiome.","source":"Demonstration"}]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=ROOT / "config.json")
    parser.add_argument("--output", type=Path, default=ROOT / "docs" / "index.html")
    parser.add_argument("--state", type=Path, default=ROOT / "data" / "state.json")
    parser.add_argument("--demo", action="store_true", help="Build without network using a sample item")
    args = parser.parse_args()
    cfg = json.loads(args.config.read_text())
    session = object()
    raw, errors = (demo_items(), []) if args.demo else ([], [])
    collectors = [("grants_gov", "Grants.gov", collect_grants, (session, cfg["max_items"])), ("nih_guide", "NIH Guide", collect_guide, (session,)), ("highlighted_topics", "Highlighted Topics", collect_topics, (session,))]
    if not args.demo:
        for key, name, fn, fn_args in collectors:
            if cfg["sources"].get(key, True):
                try: raw.extend(fn(*fn_args))
                except Exception as exc: errors.append(f"{name}: {exc}")
    state = load_seen(args.state); old = state.get("items", {}); now = datetime.now(timezone.utc)
    dedup = {item["id"]: item for item in raw if item.get("title")}
    scored = []
    cutoff = (now - timedelta(days=cfg["lookback_days"])).date().isoformat()
    for item in dedup.values():
        item["first_seen"] = old.get(item["id"], {}).get("first_seen", now.date().isoformat())
        item["is_new"] = item["id"] not in old
        item = score_item(item, cfg)
        if item["score"] >= cfg["minimum_score"] and (not item["posted"] or item["posted"] >= cutoff): scored.append(item)
    scored.sort(key=lambda x: (x["is_new"], x["score"], x["posted"]), reverse=True)
    args.state.parent.mkdir(parents=True, exist_ok=True)
    args.state.write_text(json.dumps({"updated": now.isoformat(), "items": {x["id"]:{"first_seen":x["first_seen"]} for x in dedup.values()}}, indent=2))
    (args.state.parent / "feed.json").write_text(json.dumps({"updated":now.isoformat(),"items":scored,"errors":errors}, indent=2))
    render(scored, cfg, args.output, errors)
    print(f"wrote {args.output} with {len(scored)} relevant items ({len(errors)} source errors)")
    return 1 if not raw else 0


if __name__ == "__main__": raise SystemExit(main())
