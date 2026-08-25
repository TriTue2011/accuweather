"""Official hazardous-weather bulletins from Việt Nam's national forecast centre.

Windy answers "where is the storm and where is it going"; this answers "what has
the authority actually issued". The two are complementary and occasionally
disagree, which is itself worth seeing: Windy names storms internationally
(Kajiki) while Việt Nam numbers them by basin entry (bão số 4), and only the
NCHMF bulletin carries the official numbering, the official wording, and
warnings — floods, cold surges, heat, sea state — that a cyclone feed knows
nothing about.

The page has no API. It is a plain server-rendered list, scraped the same way
the AccuWeather pages are, and a change to its markup empties these sensors
without touching anything else.
"""
from __future__ import annotations

import logging
import re
import unicodedata
from html import unescape
from datetime import datetime, timedelta, timezone
from time import monotonic
from typing import Any

from .fetcher import HtmlFetcher

_LOGGER = logging.getLogger(__name__)

NCHMF_URL = "https://www.nchmf.gov.vn/kttv/vi-VN/1/thoi-tiet-nguy-hiem-5-15.html"

# Bulletins are issued hourly at the most, and this is a government site serving
# the whole country. Fifteen minutes is frequent enough to catch a new warning
# and light enough to be a good guest.
CACHE_TTL = 900.0

# The page stamps its bulletins in Vietnam time without saying so.
VIETNAM_TZ = timezone(timedelta(hours=7))

# A bulletin issued within this window is current news rather than archive: the
# page keeps months of old entries below the fresh ones.
RECENT_HOURS = 24

# The bulletin body, on the page the list links to. The list itself carries only
# headlines, and a headline like "TIN BÃO TRÊN BIỂN ĐÔNG" says nothing about
# where the storm is or how strong it has become.
_BODY_OPEN = '<div class="text-content-news">'

# Where the bulletin text ends and the page furniture begins: a PDF link, share
# buttons, a list of other bulletins.
_BODY_STOP = ("Chi tiết tin", "Tin mới", "Tin cùng chuyên mục")

# Forecast tables flatten into an unreadable run of numbers, so they are marked
# rather than inlined. The prose around them carries the situation itself.
_TABLE_MARK = "[bảng]"

# The summary is what the sensor reads out, and Home Assistant refuses a state
# longer than 255 characters — it drops the entity rather than truncating. So
# this is that limit, not a display preference. The rest stays in `content`.
SUMMARY_MAX = 255

# A cap on the stored body. Attributes are written to the recorder every time
# they change, and nobody reads a five-page warning off a dashboard tile.
CONTENT_MAX = 3000

# The official PDF of the bulletin, when the page links one.
_PDF = re.compile(r'href="([^"]+\.pdf)"', re.IGNORECASE)

# One list entry: the link, its title, and the issue time in the trailing span.
_ENTRY = re.compile(
    r'<div class="text-weather-location[^"]*">\s*<a href="([^"]+)">(.*?)'
    r'<span[^>]*>\s*\(\s*([^)]+?)\s*\)\s*</span>\s*</a>',
    re.S,
)
_TAGS = re.compile(r"<[^>]+>")

# The official Vietnamese storm number, which Windy never carries.
_STORM_NUMBER = re.compile(r"bão\s+số\s+(\d+)", re.IGNORECASE)

# What kind of warning it is, so an automation can act on storms alone. Checked
# in order: a sea-state bulletin mentions rain too, and a storm bulletin
# mentions the sea, so the more specific heading has to win.
_CATEGORIES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("bão", ("BÃO", "ÁP THẤP NHIỆT ĐỚI")),
    ("lũ", ("LŨ", "NGẬP LỤT", "SẠT LỞ", "LŨ QUÉT")),
    ("biển", ("TRÊN BIỂN", "SÓNG LỚN", "TRIỀU CƯỜNG", "GIÓ MẠNH")),
    ("mưa", ("MƯA", "DÔNG", "LỐC", "SÉT", "MƯA ĐÁ")),
    ("nắng nóng", ("NẮNG NÓNG",)),
    ("rét", ("RÉT", "GIÓ MÙA ĐÔNG BẮC", "SƯƠNG MUỐI", "BĂNG GIÁ")),
)

EMPTY: dict[str, Any] = {
    "available": False,
    "count": 0,
    "recent_count": 0,
    "bulletins": [],
    "latest": None,
    "source": NCHMF_URL,
}

_HEADERS = {
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "vi-VN,vi;q=0.9",
}

_CACHE: tuple[float, dict[str, Any]] | None = None


def _clean(raw: str) -> str:
    """Strip the markup out of a title, squeeze its whitespace, normalise it.

    The page mixes Unicode normalisation forms — some titles carry precomposed
    Vietnamese letters and others carry the same letters as a base plus a
    combining mark, sometimes inside one headline. Left alone, "BÃO" typed one
    way does not match "BÃO" typed the other, and every keyword test below
    silently fails on the bulletins that matter most.
    """
    text = re.sub(r"\s+", " ", unescape(_TAGS.sub("", raw))).strip()
    return unicodedata.normalize("NFC", text)


def _clean_multiline(raw: str) -> str:
    """Unescape and normalise a block of text, keeping its line breaks."""
    return unicodedata.normalize("NFC", unescape(raw))


def _issued(raw: str) -> tuple[str | None, float | None]:
    """Parse a "25/08/2026 11:00" stamp into ISO text and an age in hours."""
    try:
        stamp = datetime.strptime(raw.strip(), "%d/%m/%Y %H:%M")
    except (TypeError, ValueError):
        return None, None
    stamp = stamp.replace(tzinfo=VIETNAM_TZ)
    age = (datetime.now(timezone.utc) - stamp).total_seconds() / 3600
    return stamp.isoformat(), round(age, 1)


def _category(title: str) -> str:
    """Which kind of hazard a bulletin is about."""
    upper = title.upper()
    for name, keywords in _CATEGORIES:
        if any(word in upper for word in keywords):
            return name
    return "khác"


def _shorten(text: str, limit: int) -> str:
    """Cut to `limit` characters on a word boundary, marking the cut."""
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0].rstrip(" ,;:.")
    return f"{cut}…"


def _summarise(text: str, limit: int) -> str:
    """Cut to whole sentences, so the summary never trails off mid-heading.

    A bulletin's opening paragraph is often shorter than the limit, and a plain
    character cut then drags in the start of the next section heading. Ending
    on the last full stop reads as a finished thought instead.
    """
    if len(text) <= limit:
        return text
    window = text[:limit]
    # Bulletins number their sections "1.", "2.", "3.", and the dot after a bare
    # number is not the end of a sentence — cutting there leaves the summary
    # trailing off on a section number that says nothing.
    end = -1
    for match in re.finditer(r"\.(?=[ \n])", window):
        if re.search(r"(?:^|[ \n])\d{1,2}$", window[: match.start()]):
            continue
        end = match.start()
    # Only if a sentence actually ends late enough to be worth reading; a very
    # early full stop would throw away most of what was asked for.
    if end >= limit // 2:
        return window[: end + 1]
    return _shorten(text, limit)


def parse_content(page: str) -> dict[str, Any]:
    """The body of one bulletin: a short summary, the full text, the PDF link.

    Returns empty strings when the body cannot be found, so a page that changes
    shape costs the summary and nothing else.
    """
    start = page.find(_BODY_OPEN)
    if start < 0:
        return {"summary": "", "content": "", "pdf_url": None}

    body = page[start:]
    pdf = _PDF.search(body)
    body = re.sub(r"<table.*?</table>", f"\n{_TABLE_MARK}\n", body, flags=re.S | re.I)
    body = re.sub(r"<(script|style|iframe).*?</\1>", " ", body, flags=re.S | re.I)
    # Block ends become line breaks before the tags go, so sentences that sat in
    # separate paragraphs do not run together into one.
    body = re.sub(r"<br\s*/?>|</p>|</div>|</h\d>", "\n", body, flags=re.I)
    body = _clean_multiline(_TAGS.sub("", body))

    lines: list[str] = []
    for raw in body.split("\n"):
        line = re.sub(r"\s+", " ", raw).strip()
        if not line:
            continue
        if any(line.startswith(stop) for stop in _BODY_STOP):
            break
        lines.append(line)

    prose = [line for line in lines if line != _TABLE_MARK]
    return {
        "summary": _summarise(" ".join(prose), SUMMARY_MAX),
        "content": _shorten("\n".join(lines), CONTENT_MAX),
        "pdf_url": pdf.group(1) if pdf else None,
    }


def parse_bulletins(page: str) -> list[dict[str, Any]]:
    """Every bulletin on the page, newest first as the page itself orders them."""
    bulletins: list[dict[str, Any]] = []
    for url, title_html, stamp in _ENTRY.findall(page):
        title = _clean(title_html)
        if not title:
            continue
        issued, age_hours = _issued(stamp)
        number = _STORM_NUMBER.search(title)
        bulletins.append(
            {
                "title": title,
                "url": url,
                "issued": issued,
                "issued_text": stamp.strip(),
                "age_hours": age_hours,
                "category": _category(title),
                # None on everything except a storm bulletin.
                "storm_number": int(number.group(1)) if number else None,
            }
        )
    return bulletins


async def _add_content(fetcher: HtmlFetcher, bulletin: dict[str, Any]) -> None:
    """Attach the bulletin body to its list entry, in place.

    Failure is quiet and partial on purpose: the headline, the issue time and
    the link are already known and worth showing on their own, so a body that
    cannot be read leaves empty strings rather than losing the bulletin.
    """
    bulletin.setdefault("summary", "")
    bulletin.setdefault("content", "")
    bulletin.setdefault("pdf_url", None)

    url = bulletin.get("url")
    if not url:
        return
    try:
        status, page = await fetcher.get_text(url, _HEADERS)
    except Exception as err:  # noqa: BLE001 - the list is worth keeping
        _LOGGER.debug("NCHMF bulletin body failed: %s: %s", type(err).__name__, err)
        return
    if status != 200 or not page:
        _LOGGER.debug("NCHMF bulletin body returned HTTP %s", status)
        return

    content = parse_content(page)
    if not content["content"]:
        _LOGGER.debug(
            "NCHMF bulletin fetched but no body parsed — the markup has "
            "probably changed"
        )
    bulletin.update(content)


async def get_bulletins(fetcher: HtmlFetcher) -> dict[str, Any]:
    """Fetch and parse the hazardous-weather list.

    Cached process-wide: the bulletins are national, so a second configured
    location must not mean a second request. `available` is False when the page
    could not be read or its markup no longer parses, which is the caller's cue
    to keep showing whatever it had.
    """
    global _CACHE  # noqa: PLW0603 - one page shared by every config entry

    if _CACHE and (monotonic() - _CACHE[0]) < CACHE_TTL:
        return _CACHE[1]

    result = dict(EMPTY)
    try:
        status, page = await fetcher.get_text(NCHMF_URL, _HEADERS)
        if status != 200 or not page:
            _LOGGER.debug("NCHMF returned HTTP %s", status)
        else:
            bulletins = parse_bulletins(page)
            if not bulletins:
                _LOGGER.debug(
                    "NCHMF page fetched but no bulletins parsed — the markup has "
                    "probably changed"
                )
            else:
                # Only the newest bulletin's body is fetched. Ten more requests
                # per update on a government site would be rude, and nobody
                # reads the body of an archived warning off a dashboard.
                await _add_content(fetcher, bulletins[0])
                result = {
                    "available": True,
                    "count": len(bulletins),
                    # How many are current rather than archive, which is what
                    # tells a quiet week from an active one.
                    "recent_count": sum(
                        1
                        for item in bulletins
                        if item["age_hours"] is not None
                        and item["age_hours"] <= RECENT_HOURS
                    ),
                    "bulletins": bulletins,
                    "latest": bulletins[0],
                    "source": NCHMF_URL,
                }
    except Exception as err:  # noqa: BLE001 - never break the update for this
        _LOGGER.debug("NCHMF unavailable: %s: %s", type(err).__name__, err)

    # Failures are cached too, briefly, so a broken page is not retried once per
    # location on every cycle.
    _CACHE = (monotonic(), result)
    return result
