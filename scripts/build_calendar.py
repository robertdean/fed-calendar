#!/usr/bin/env python3
"""Build subscribable .ics calendars from the Federal Reserve's public pages.

Outputs (served by GitHub Pages from docs/):
  docs/fomc.ics   FOMC meetings, from the FOMC meeting calendar page
  docs/board.ics  Board of Governors meetings, from the Board meetings RSS feed

State (committed so history survives after items drop off the RSS feed):
  data/fomc_meetings.json
  data/board_meetings.json

If the FOMC schedule changed since the last run, a summary is written to
changes.md, which the workflow turns into a GitHub issue (GitHub emails you).

Standard library only. Exits non-zero if the page can't be read or parsed,
so a broken run fails loudly instead of publishing an empty calendar.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path
from zoneinfo import ZoneInfo

FOMC_URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
BOARD_RSS_URL = "https://www.federalreserve.gov/feeds/boardmeetings.xml"
USER_AGENT = "fed-calendar-ics/1.0 (personal calendar feed; GitHub Actions)"

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
DATA = ROOT / "data"
CHANGES_FILE = ROOT / "changes.md"

ET_ZONE = ZoneInfo("America/New_York")
UID_DOMAIN = "fed-calendar.github.io"

MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july",
     "august", "september", "october", "november", "december"], start=1)}


def month_num(name: str) -> int:
    key = name.strip().lower()
    for full, n in MONTHS.items():
        if full.startswith(key[:3]):
            return n
    raise ValueError(f"Unknown month: {name!r}")


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8-sig", errors="replace")


# ---------------------------------------------------------------- FOMC page

class _TextLines(HTMLParser):
    """Flatten HTML to text, putting block-level elements on their own lines."""

    BLOCK = {"div", "p", "br", "li", "tr", "td", "th", "h1", "h2", "h3", "h4",
             "h5", "h6", "section", "article", "header", "footer", "ul", "ol",
             "table"}
    SKIP = {"script", "style", "noscript"}

    def __init__(self):
        super().__init__()
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP:
            self._skip = max(0, self._skip - 1)
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)

    def lines(self) -> list[str]:
        text = "".join(self.parts).replace("\xa0", " ")
        return [re.sub(r"\s+", " ", l).strip() for l in text.split("\n") if l.strip()]


YEAR_RE = re.compile(r"^(\d{4}) FOMC Meetings$", re.I)
MONTH_RE = re.compile(
    r"^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?"
    r"(?:\s*/\s*(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?)?$", re.I)
DATE_RE = re.compile(r"^(\d{1,2})(?:\s*[-–]\s*(\d{1,2}))?\s*(\*)?\s*(?:\((.+?)\))?\s*(\*)?$")
NOTE_RE = re.compile(
    r"meeting is scheduled for (\w+) (\d{1,2})\s*[-–]\s*(\d{1,2}), (\d{4})", re.I)


def parse_fomc(html: str) -> list[dict]:
    p = _TextLines()
    p.feed(html)
    lines = p.lines()

    meetings: list[dict] = []
    year = None
    i = 0
    while i < len(lines):
        line = lines[i]
        y = YEAR_RE.match(line)
        if y:
            year = int(y.group(1))
            i += 1
            continue
        m = MONTH_RE.match(line)
        if year and m and i + 1 < len(lines):
            d = DATE_RE.match(lines[i + 1])
            if d:
                m1 = month_num(m.group(1))
                m2 = month_num(m.group(2)) if m.group(2) else m1
                day1 = int(d.group(1))
                day2 = int(d.group(2)) if d.group(2) else day1
                start = dt.date(year, m1, day1)
                end = dt.date(year, m2 if d.group(2) else m1, day2)
                if end < start:  # e.g. "Dec/Jan 31-1"
                    end = dt.date(year + 1, m2, day2)
                note = (d.group(4) or "").strip().lower()
                meetings.append({
                    "year": year,
                    "label": line,
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                    "sep": bool(d.group(3) or d.group(5)),
                    "kind": note or "scheduled",
                })
                i += 2
                continue
        i += 1

    # "A two-day meeting is scheduled for January 25-26, 2028."
    for n in NOTE_RE.finditer(" ".join(lines)):
        mo, d1, d2, yr = month_num(n.group(1)), int(n.group(2)), int(n.group(3)), int(n.group(4))
        start = dt.date(yr, mo, d1).isoformat()
        if not any(x["start"] == start for x in meetings):
            meetings.append({"year": yr, "label": n.group(1), "start": start,
                             "end": dt.date(yr, mo, d2).isoformat(), "sep": False,
                             "kind": "scheduled"})

    for mt in meetings:
        mt["uid"] = fomc_uid(mt)
    meetings.sort(key=lambda x: x["start"])
    return meetings


def fomc_uid(mt: dict) -> str:
    # Scheduled meetings are keyed by year + starting month so a meeting that
    # moves within its month updates in place instead of duplicating.
    if mt["kind"] == "scheduled":
        mon = dt.date.fromisoformat(mt["start"]).strftime("%b").lower()
        return f"fomc-{mt['year']}-{mon}@{UID_DOMAIN}"
    slug = re.sub(r"[^a-z0-9]+", "-", mt["kind"]).strip("-")
    return f"fomc-{mt['start']}-{slug}@{UID_DOMAIN}"


def validate_fomc(meetings: list[dict], today: dt.date) -> None:
    this_year = [m for m in meetings if m["year"] == today.year and m["kind"] == "scheduled"]
    if len(this_year) < 8:
        sys.exit(f"ERROR: found {len(this_year)} scheduled FOMC meetings for {today.year} "
                 f"(expected 8). The Fed page layout may have changed; not publishing.")


def diff_fomc(old: list[dict], new: list[dict]) -> list[str]:
    def fmt(m):
        s, e = dt.date.fromisoformat(m["start"]), dt.date.fromisoformat(m["end"])
        span = s.strftime("%b %-d") + (f"–{e.strftime('%b %-d') if e.month != s.month else e.day}"
                                       if e != s else "")
        extra = "" if m["kind"] == "scheduled" else f" ({m['kind']})"
        return f"{span}, {s.year}{extra}"

    o = {m["uid"]: m for m in old}
    n = {m["uid"]: m for m in new}
    out = []
    for uid in n.keys() - o.keys():
        out.append(f"- **Added:** {fmt(n[uid])}")
    for uid in o.keys() - n.keys():
        out.append(f"- **Removed:** {fmt(o[uid])}")
    for uid in o.keys() & n.keys():
        a, b = o[uid], n[uid]
        if (a["start"], a["end"]) != (b["start"], b["end"]):
            out.append(f"- **Moved:** {fmt(a)} → {fmt(b)}")
        elif a["sep"] != b["sep"]:
            out.append(f"- **Projections changed:** {fmt(b)} now "
                       f"{'has' if b['sep'] else 'has no'} a Summary of Economic Projections")
    return sorted(out)


# ------------------------------------------------------- Board meetings RSS

BOARD_TIME_RE = re.compile(
    r"(will be|was) held at ([\d:]+\s*[ap]\.m\.) on ([A-Z][a-z]+ \d{1,2}, \d{4})"
    r"(?: and continued at ([\d:]+\s*[ap]\.m\.) on ([A-Z][a-z]+ \d{1,2}, \d{4}))?")
MATTER_RE = re.compile(r"Matter\(s\) considered:\s*(.+)", re.S)


def _to_dt(time_s: str, date_s: str) -> dt.datetime:
    t = time_s.replace(".", "").replace(" ", "").upper()  # "10:00AM"
    naive = dt.datetime.strptime(f"{date_s} {t}", "%B %d, %Y %I:%M%p")
    return naive.replace(tzinfo=ET_ZONE)


def parse_board(xml_text: str) -> list[dict]:
    root = ET.fromstring(xml_text.lstrip("\ufeff"))
    items = []
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        link = (it.findtext("link") or "").strip()
        desc = re.sub(r"\s+", " ", it.findtext("description") or "").strip()
        pub = (it.findtext("pubDate") or "").strip()
        m = BOARD_TIME_RE.search(desc)
        if not (link and m):
            continue
        matter = MATTER_RE.search(desc)
        sessions = [_to_dt(m.group(2), m.group(3))]
        if m.group(4):
            sessions.append(_to_dt(m.group(4), m.group(5)))
        try:
            pub_dt = dt.datetime.strptime(pub, "%a, %d %b %Y %H:%M:%S %Z")
        except ValueError:
            pub_dt = dt.datetime.min
        items.append({
            "link": link,
            "held": not title.lower().startswith("advance") and m.group(1) == "was",
            "sessions": [s.isoformat() for s in sessions],
            "matter": (matter.group(1).strip() if matter else "").rstrip(),
            "pub": pub_dt,
        })
    items.sort(key=lambda x: x["pub"])
    return items


def merge_board(state: dict, items: list[dict]) -> dict:
    for it in items:
        key = it["link"]
        cur = state.get(key)
        if cur is None:
            cur = {"link": key, "matter": it["matter"], "status": "announced",
                   "sessions": it["sessions"], "announced_sessions": None}
            state[key] = cur
        if it["held"]:
            if cur["status"] != "held" and cur["sessions"] != it["sessions"]:
                cur["announced_sessions"] = cur["sessions"]
            cur["status"] = "held"
            cur["sessions"] = it["sessions"]
        elif cur["status"] != "held":
            if cur["sessions"] != it["sessions"]:
                cur["announced_sessions"] = cur["announced_sessions"] or cur["sessions"]
            cur["sessions"] = it["sessions"]
        cur["matter"] = it["matter"] or cur["matter"]
    return state


# --------------------------------------------------------------------- ICS

def esc(text: str) -> str:
    return (text.replace("\\", "\\\\").replace(";", "\\;")
            .replace(",", "\\,").replace("\n", "\\n"))


def fold(line: str) -> str:
    out, cur = [], b""
    for ch in line:
        b = ch.encode("utf-8")
        if len(cur) + len(b) > (75 if not out else 74):
            out.append(cur.decode("utf-8"))
            cur = b""
        cur += b
    out.append(cur.decode("utf-8"))
    return "\r\n ".join(out)


def calendar(name: str, desc: str, events: list[list[str]], stamp: str) -> str:
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0",
             "PRODID:-//fed-calendar//Federal Reserve meetings//EN",
             "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
             f"X-WR-CALNAME:{esc(name)}", f"X-WR-CALDESC:{esc(desc)}",
             "X-WR-TIMEZONE:America/New_York",
             "REFRESH-INTERVAL;VALUE=DURATION:PT12H",
             "X-PUBLISHED-TTL:PT12H"]
    for ev in events:
        lines += ["BEGIN:VEVENT", f"DTSTAMP:{stamp}"] + ev + ["END:VEVENT"]
    lines.append("END:VCALENDAR")
    return "\r\n".join(fold(l) for l in lines) + "\r\n"


def fomc_events(meetings: list[dict]) -> list[list[str]]:
    evs = []
    for m in meetings:
        start = dt.date.fromisoformat(m["start"])
        end = dt.date.fromisoformat(m["end"]) + dt.timedelta(days=1)  # exclusive
        if m["kind"] == "scheduled":
            summary = "FOMC meeting" + (" (with projections)" if m["sep"] else "")
            desc = ("Policy statement at 2:00 p.m. ET on the final day, "
                    "press conference at 2:30 p.m. ET.")
            if m["sep"]:
                desc += " Includes a Summary of Economic Projections."
            desc += (" Dates are tentative until confirmed at the meeting immediately "
                     "preceding.")
        else:
            summary = f"FOMC {m['kind']}"
            desc = f"FOMC {m['kind']}."
        desc += f"\n\nSource: {FOMC_URL}"
        evs.append([f"UID:{m['uid']}",
                    f"DTSTART;VALUE=DATE:{start:%Y%m%d}",
                    f"DTEND;VALUE=DATE:{end:%Y%m%d}",
                    f"SUMMARY:{esc(summary)}",
                    f"DESCRIPTION:{esc(desc)}",
                    f"URL:{FOMC_URL}",
                    "TRANSP:TRANSPARENT"])
    return evs


def board_events(state: dict) -> list[list[str]]:
    evs = []
    for key in sorted(state, key=lambda k: state[k]["sessions"][0]):
        b = state[key]
        base = hashlib.sha1(key.encode()).hexdigest()[:12]
        matter = b["matter"] or "Board of Governors meeting"
        for idx, s in enumerate(b["sessions"]):
            start = dt.datetime.fromisoformat(s).astimezone(dt.timezone.utc)
            end = start + dt.timedelta(hours=1)
            desc = f"Closed meeting of the Board of Governors. Matter(s) considered: {matter}"
            if idx:
                desc += " (continued session)"
            if b["status"] != "held":
                desc += "\n\nAnnounced; not yet confirmed as held."
            if b.get("announced_sessions"):
                orig = dt.datetime.fromisoformat(b["announced_sessions"][0])
                desc += (f"\n\nOriginally announced for "
                         f"{orig.strftime('%-I:%M %p ET on %B %-d, %Y')}.")
            desc += "\nEnd time is not published; shown as one hour."
            desc += f"\n\nNotice: {key}"
            evs.append([f"UID:board-{base}-{idx + 1}@{UID_DOMAIN}",
                        f"DTSTART:{start:%Y%m%dT%H%M%SZ}",
                        f"DTEND:{end:%Y%m%dT%H%M%SZ}",
                        f"SUMMARY:{esc('Fed Board: ' + short_matter(matter))}",
                        f"DESCRIPTION:{esc(desc)}",
                        f"URL:{key}",
                        "TRANSP:TRANSPARENT"])
    return evs


def short_matter(matter: str) -> str:
    low = matter.lower()
    if "discount rate" in low:
        return "discount rate review"
    if "monetary policy" in low:
        return "monetary policy discussion"
    if "financial markets" in low:
        return "financial markets briefing"
    return matter[:60]


def write_if_changed(path: Path, content: str) -> bool:
    """Write the file only if something other than DTSTAMP changed."""
    def norm(s): return re.sub(r"DTSTAMP:\S+", "DTSTAMP:", s)
    if path.exists():
        with path.open(encoding="utf-8", newline="") as f:
            if norm(f.read()) == norm(content):
                return False
    path.write_text(content, encoding="utf-8", newline="")
    return True


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def main() -> None:
    DOCS.mkdir(exist_ok=True)
    DATA.mkdir(exist_ok=True)
    CHANGES_FILE.unlink(missing_ok=True)
    now = dt.datetime.now(dt.timezone.utc)
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    today = now.astimezone(ET_ZONE).date()

    fomc_html = Path(sys.argv[1]).read_text() if len(sys.argv) > 1 else fetch(FOMC_URL)
    meetings = parse_fomc(fomc_html)
    validate_fomc(meetings, today)

    fomc_state = DATA / "fomc_meetings.json"
    old = load_json(fomc_state, None)
    if old is not None:
        changes = diff_fomc(old, meetings)
        if changes:
            CHANGES_FILE.write_text(
                "The Federal Reserve's FOMC meeting calendar changed:\n\n"
                + "\n".join(changes)
                + f"\n\nSource: {FOMC_URL}\n", encoding="utf-8")
            print("FOMC schedule changes:\n" + "\n".join(changes))
    fomc_state.write_text(json.dumps(meetings, indent=2) + "\n", encoding="utf-8")

    changed = write_if_changed(DOCS / "fomc.ics", calendar(
        "FOMC meetings",
        "Federal Open Market Committee meetings, from federalreserve.gov. Updated daily.",
        fomc_events(meetings), stamp))
    print(f"fomc.ics: {len(meetings)} events, {'updated' if changed else 'unchanged'}")

    board_xml = Path(sys.argv[2]).read_text() if len(sys.argv) > 2 else fetch(BOARD_RSS_URL)
    board_state_path = DATA / "board_meetings.json"
    board_state = merge_board(load_json(board_state_path, {}), parse_board(board_xml))
    board_state_path.write_text(json.dumps(board_state, indent=2) + "\n", encoding="utf-8")
    changed = write_if_changed(DOCS / "board.ics", calendar(
        "Fed Board meetings",
        "Federal Reserve Board of Governors meetings, from the Board's Sunshine Act notices.",
        board_events(board_state), stamp))
    print(f"board.ics: {len(board_state)} meetings, {'updated' if changed else 'unchanged'}")

    (DOCS / "status.json").write_text(json.dumps({
        "last_checked": now.isoformat(timespec="seconds"),
        "fomc_meetings": len(meetings),
        "board_meetings": len(board_state),
    }, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
