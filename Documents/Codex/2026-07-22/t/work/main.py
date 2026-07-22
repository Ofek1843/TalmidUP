from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import hashlib
import json
import os
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("RADAR_DATA_DIR", str(BASE_DIR / "data")))
OUT_DIR = DATA_DIR / "out"
STATE_FILE = DATA_DIR / ".state.json"
SOURCES_FILE = BASE_DIR / "sources.json"
DEFAULT_NOTIFY_SCORE = 18
DEFAULT_TOP_ALERT_COUNT = 1

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


@dataclasses.dataclass(frozen=True)
class Source:
    name: str
    type: str
    url: str


@dataclasses.dataclass(frozen=True)
class Item:
    source: str
    title: str
    link: str
    summary: str
    published: str
    mode: str


@dataclasses.dataclass(frozen=True)
class OpportunityProfile:
    score: int
    reasons: list[str]
    build_type: str
    monetization: str
    urgency: int
    confidence: int


class TrendingParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_h1 = False
        self.links: list[tuple[str, str]] = []
        self.current_href: str | None = None
        self.current_text: list[str] = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a" and attrs.get("href", "").startswith("/"):
            self.current_href = attrs.get("href")
            self.current_text = []
        if tag == "h1":
            self.in_h1 = True

    def handle_data(self, data):
        if self.current_href and self.in_h1:
            self.current_text.append(data.strip())

    def handle_endtag(self, tag):
        if tag == "h1":
            self.in_h1 = False
        if tag == "a" and self.current_href:
            text = " ".join(part for part in self.current_text if part).strip()
            if text:
                self.links.append((text, self.current_href))
            self.current_href = None
            self.current_text = []


def load_sources() -> dict[str, list[Source]]:
    raw = json.loads(SOURCES_FILE.read_text(encoding="utf-8"))
    return {mode: [Source(**entry) for entry in entries] for mode, entries in raw.items()}


def load_state() -> dict[str, str]:
    if not STATE_FILE.exists():
        return {}
    return json.loads(STATE_FILE.read_text(encoding="utf-8"))


def save_state(state: dict[str, str]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as response:
        return response.read().decode("utf-8", errors="ignore")


def fetch_json(url: str, payload: dict | None = None, method: str = "GET") -> dict:
    data = None
    headers = {"User-Agent": "Mozilla/5.0"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.loads(response.read().decode("utf-8", errors="ignore"))


def telegram_configured() -> bool:
    return bool(os.environ.get("TELEGRAM_BOT_TOKEN") and os.environ.get("TELEGRAM_CHAT_ID"))


def send_telegram_message(text: str) -> None:
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text[:3900],
        "disable_web_page_preview": True,
    }
    fetch_json(url, payload=payload, method="POST")


def parse_rss(source: Source, mode: str) -> list[Item]:
    xml = fetch(source.url)
    root = ET.fromstring(xml)
    channel = root.find("channel")
    if channel is None:
        return []

    items: list[Item] = []
    for entry in channel.findall("item")[:25]:
        title = (entry.findtext("title") or "").strip()
        link = (entry.findtext("link") or "").strip()
        summary = (entry.findtext("description") or "").strip()
        published = (entry.findtext("pubDate") or "").strip()
        if title:
            items.append(
                Item(
                    source=source.name,
                    title=title,
                    link=link,
                    summary=summary,
                    published=published,
                    mode=mode,
                )
            )
    return items


def parse_github_trending(source: Source, mode: str) -> list[Item]:
    html = fetch(source.url)
    parser = TrendingParser()
    parser.feed(html)
    items: list[Item] = []
    for title, href in parser.links[:20]:
        items.append(
            Item(
                source=source.name,
                title=title,
                link=f"https://github.com{href}",
                summary="Trending repository",
                published=dt.datetime.utcnow().isoformat(),
                mode=mode,
            )
        )
    return items


def score_opportunity(item: Item) -> tuple[int, list[str]]:
    text = f"{item.title} {item.summary}".lower()
    score = 0
    reasons: list[str] = []
    positive = {
        r"\bpay\b": 18,
        r"\bpricing\b": 10,
        r"\balternative\b": 14,
        r"\bwish\b": 12,
        r"\bmissing\b": 10,
        r"\bmanual\b": 8,
        r"\bannoying\b": 8,
        r"\bneed\b": 6,
        r"\blooking for\b": 14,
        r"\bfeature request\b": 16,
    }
    negative = {r"\bshowcase\b": 5, r"\blaunch\b": 4}
    for pattern, points in positive.items():
        if re.search(pattern, text):
            score += points
            reasons.append(pattern.replace("\\b", ""))
    for pattern, points in negative.items():
        if re.search(pattern, text):
            score -= points
    return max(score, 0), reasons


def score_tech(item: Item) -> tuple[int, list[str]]:
    text = f"{item.title} {item.summary}".lower()
    score = 0
    reasons: list[str] = []
    keywords = {
        r"\bapi\b": 10,
        r"\bmodel\b": 14,
        r"\bagent\b": 16,
        r"\bconnectors\b": 10,
        r"\bchangelog\b": 8,
        r"\bpricing\b": 8,
        r"\brelease\b": 8,
        r"\bbeta\b": 6,
        r"\btrending\b": 4,
    }
    for pattern, points in keywords.items():
        if re.search(pattern, text):
            score += points
            reasons.append(pattern.replace("\\b", ""))
    return score, reasons


def infer_build_type(text: str) -> str:
    if any(term in text for term in ["automation", "manual", "workflow", "process", "ops", "crm", "support", "report", "tracking"]):
        return "service"
    if any(term in text for term in ["game", "fun", "entertain", "play", "creator", "template", "tool", "plugin"]):
        return "product"
    if any(term in text for term in ["team", "company", "business", "agency", "sales", "lead", "client"]):
        return "b2b product"
    return "product"


def infer_monetization(build_type: str, score: int) -> str:
    if build_type == "service":
        return "setup fee + monthly retainer"
    if build_type == "b2b product":
        return "subscription"
    if score >= 25:
        return "subscription or paid launch"
    return "one-time payment or paid beta"


def evaluate_opportunity(item: Item) -> OpportunityProfile:
    text = f"{item.title} {item.summary}".lower()
    score, reasons = score_opportunity(item)
    urgency = 0
    if any(term in text for term in ["every week", "every day", "always", "repeatedly", "again", "still"]):
        urgency += 20
    if any(term in text for term in ["pay", "pricing", "alternative", "missing", "wish"]):
        urgency += 15
    if any(term in text for term in ["frustrated", "annoying", "hate", "broken", "slow"]):
        urgency += 10
    confidence = min(100, score + urgency + (10 if reasons else 0))
    build_type = infer_build_type(text)
    monetization = infer_monetization(build_type, score)
    return OpportunityProfile(
        score=score,
        reasons=reasons,
        build_type=build_type,
        monetization=monetization,
        urgency=urgency,
        confidence=confidence,
    )


def hash_item(item: Item) -> str:
    h = hashlib.sha256()
    h.update((item.source + item.title + item.link).encode("utf-8"))
    return h.hexdigest()[:16]


def collect(mode: str, sources: dict[str, list[Source]]) -> list[Item]:
    selected = sources.get(mode, [])
    items: list[Item] = []
    for source in selected:
        try:
            if source.type == "rss":
                items.extend(parse_rss(source, mode))
            elif source.type == "html" and "github.com/trending" in source.url:
                items.extend(parse_github_trending(source, mode))
        except Exception as exc:
            items.append(
                Item(
                    source=source.name,
                    title=f"{source.name} fetch error",
                    link=source.url,
                    summary=str(exc),
                    published=dt.datetime.utcnow().isoformat(),
                    mode=mode,
                )
            )
    return items


def enrich(items: Iterable[Item]) -> list[dict]:
    enriched = []
    for item in items:
        if item.mode == "opportunity":
            profile = evaluate_opportunity(item)
            label = "opportunity"
        else:
            score, reasons = score_tech(item)
            label = "tech"
        enriched.append(
            {
                "id": hash_item(item),
                "label": label,
                "score": profile.score if item.mode == "opportunity" else score,
                "reasons": profile.reasons if item.mode == "opportunity" else reasons,
                "source": item.source,
                "title": item.title,
                "link": item.link,
                "summary": item.summary[:300],
                "published": item.published,
                "build_type": profile.build_type if item.mode == "opportunity" else None,
                "monetization": profile.monetization if item.mode == "opportunity" else None,
                "urgency": profile.urgency if item.mode == "opportunity" else None,
                "confidence": profile.confidence if item.mode == "opportunity" else None,
            }
        )
    return enriched


def render_report(mode: str, rows: list[dict]) -> str:
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [f"# {mode.title()} Radar Report", f"Generated: {now}", ""]
    if not rows:
        lines.append("No items found.")
        return "\n".join(lines)
    for row in sorted(rows, key=lambda r: r["score"], reverse=True)[:20]:
        lines.append(f"## {row['title']}")
        lines.append(f"- Score: {row['score']}")
        lines.append(f"- Source: {row['source']}")
        lines.append(f"- Link: {row['link']}")
        if row.get("build_type"):
            lines.append(f"- Best fit: {row['build_type']}")
        if row.get("monetization"):
            lines.append(f"- Monetization: {row['monetization']}")
        if row.get("confidence") is not None:
            lines.append(f"- Confidence: {row['confidence']}/100")
        if row["reasons"]:
            lines.append(f"- Signals: {', '.join(row['reasons'])}")
        if row["summary"]:
            lines.append(f"- Summary: {row['summary']}")
        lines.append("")
    return "\n".join(lines)


def render_action_summary(rows: list[dict]) -> str:
    opps = [row for row in rows if row["label"] == "opportunity"]
    tech = [row for row in rows if row["label"] == "tech"]
    top_opp = max(opps, key=lambda r: r["score"], default=None)
    top_tech = max(tech, key=lambda r: r["score"], default=None)
    lines = ["# Action Summary", ""]
    if top_opp:
        lines.append(f"- Best opportunity candidate: {top_opp['title']} ({top_opp['score']})")
        if top_opp.get("build_type"):
            lines.append(f"- Likely form: {top_opp['build_type']}")
        if top_opp.get("monetization"):
            lines.append(f"- Money path: {top_opp['monetization']}")
    if top_tech:
        lines.append(f"- Best tech signal: {top_tech['title']} ({top_tech['score']})")
    if not top_opp and not top_tech:
        lines.append("- No strong items yet.")
    return "\n".join(lines)


def build_notification(rows: list[dict], mode: str) -> str | None:
    strong = [row for row in rows if row["score"] >= DEFAULT_NOTIFY_SCORE]
    if not strong:
        return None
    top = sorted(strong, key=lambda r: r["score"], reverse=True)[:DEFAULT_TOP_ALERT_COUNT]
    lines = [f"{mode.title()} radar alert", ""]
    for row in top:
        lines.append(f"- {row['title']} ({row['score']})")
        if row.get("build_type"):
            lines.append(f"  fit: {row['build_type']} | {row.get('monetization', 'n/a')}")
        lines.append(f"  {row['link']}")
    return "\n".join(lines)


def build_daily_digest(rows: list[dict], mode: str) -> str | None:
    strong = sorted([row for row in rows if row["score"] >= DEFAULT_NOTIFY_SCORE], key=lambda r: r["score"], reverse=True)
    if not strong:
        return None
    top = strong[:5]
    lines = [f"{mode.title()} daily digest", ""]
    for row in top:
        lines.append(f"- {row['title']} ({row['score']})")
        if row.get("build_type"):
            lines.append(f"  fit: {row['build_type']} | {row.get('monetization', 'n/a')}")
    return "\n".join(lines)


def write_outputs(mode: str, report: str, rows: list[dict], state: dict[str, str]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    (OUT_DIR / f"{mode}-{stamp}.md").write_text(report, encoding="utf-8")
    (OUT_DIR / f"{mode}-{stamp}.json").write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    for row in rows:
        state[row["id"]] = stamp


def run_mode(mode: str) -> None:
    sources = load_sources()
    state = load_state()
    if mode == "both":
        combined: list[dict] = []
        for submode in ("opportunity", "tech"):
            items = collect(submode, sources)
            fresh = [item for item in items if hash_item(item) not in state]
            rows = enrich(fresh)
            report = render_report(submode, rows)
            write_outputs(submode, report, rows, state)
            combined.extend(rows)
            print(report)
            print()
            notification = build_notification(rows, submode)
            if notification and telegram_configured():
                send_telegram_message(notification)
        summary = render_action_summary(combined)
        (OUT_DIR / f"summary-{dt.datetime.now().strftime('%Y%m%d-%H%M%S')}.md").write_text(summary, encoding="utf-8")
        print(summary)
        if telegram_configured():
            top_notification = build_notification(combined, "combined")
            if top_notification:
                send_telegram_message(top_notification)
            daily_digest = build_daily_digest(combined, "combined")
            if daily_digest:
                (OUT_DIR / f"digest-{dt.datetime.now().strftime('%Y%m%d-%H%M%S')}.md").write_text(daily_digest, encoding="utf-8")
    else:
        items = collect(mode, sources)
        fresh = [item for item in items if hash_item(item) not in state]
        rows = enrich(fresh)
        report = render_report(mode, rows)
        write_outputs(mode, report, rows, state)
        print(report)
        notification = build_notification(rows, mode)
        if notification and telegram_configured():
            send_telegram_message(notification)
        digest = build_daily_digest(rows, mode)
        if digest:
            (OUT_DIR / f"digest-{dt.datetime.now().strftime('%Y%m%d-%H%M%S')}.md").write_text(digest, encoding="utf-8")
    save_state(state)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Opportunity and AI Radar")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run")
    run.add_argument("--mode", choices=["opportunity", "tech", "both"], default="both")
    run.add_argument("--reset-state", action="store_true", help="Clear prior seen-items state before running")
    args = parser.parse_args(argv)

    if args.command == "run":
        if args.reset_state and STATE_FILE.exists():
            STATE_FILE.unlink()
        run_mode(args.mode)
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
