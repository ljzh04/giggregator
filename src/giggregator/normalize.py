"""Phase-0 rules pass: pure parsing/extraction functions (zero ML).

Iron rule 1 (AGENTS.md): never fabricate. Every parser keeps the raw text and returns a
confidence value; callers must not invent data beyond what these rules extract.
"""

from __future__ import annotations

import html as html_mod
import re
import unicodedata
from datetime import UTC, datetime

from . import config, models

# ---------------------------------------------------------------- helpers


def clean(text: str | None) -> str:
    """NFKC-normalize, unescape entities, collapse whitespace."""
    if not text:
        return ""
    t = html_mod.unescape(unicodedata.normalize("NFKC", str(text)))
    return re.sub(r"\s+", " ", t).strip()


def strip_html(html_text: str | None) -> str:
    """Cheap tag-stripper for HTML bodies (no full parser needed for flat text)."""
    if not html_text:
        return ""
    t = re.sub(r"<[^>]+>", " ", html_text)
    return clean(t)


def parse_dt(value: str | None) -> datetime | None:
    """Parse ISO-ish datetimes. Naive values are treated as UTC."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


def utcnow() -> datetime:
    return datetime.now(UTC)


# ---------------------------------------------------------------- pay parsing

_NUM_TOKEN = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(k\b)?", re.I)

_PERIOD_PATTERNS: list[tuple[str, str]] = [
    (models.PAY_YEARLY, r"(?:per|/|a|an)\s*(?:year|yr|annum)\b|\b(?:yearly|annual|year|yr)\b"),
    (models.PAY_MONTHLY, r"(?:per|/|a|an)\s*month\b|\bmonthly\b|\bmonth\b"),
    (models.PAY_WEEKLY, r"(?:per|/|a|an)\s*week\b|\bweekly\b"),
    (models.PAY_DAILY, r"(?:per|/|a|an)\s*day\b|\bdaily\b"),
    (
        models.PAY_PER_TASK,
        r"(?:per|/)\s*(?:gig|task|job|article|project|batch|piece|head|word|audio|video|post)\b",
    ),
    (models.PAY_HOURLY, r"(?:per|/)\s*(?:hr|hour)s?\b|\b(?:hr|hour)s?/|\ban hour\b"),
]


def _num(token: str, k_suffix: bool) -> float:
    t = token
    if k_suffix and t.count(",") == 1 and "." not in t:
        t = t.replace(",", ".")  # European decimal: 31,2k -> 31.2k (seen in Remotive data)
    else:
        t = t.replace(",", "")
    v = float(t)
    return v * 1000.0 if k_suffix else v


def _to_hourly(amount: float, kind: str) -> float | None:
    if kind == models.PAY_HOURLY:
        return amount
    if kind == models.PAY_DAILY:
        return amount / config.DAILY_TO_HOURS
    if kind == models.PAY_WEEKLY:
        return amount / config.WEEKLY_TO_HOURS
    if kind == models.PAY_MONTHLY:
        return amount / config.MONTHLY_TO_HOURS
    if kind == models.PAY_YEARLY:
        return amount / config.YEARLY_TO_HOURS
    return None  # per_task / unknown: needs task-hours estimate (phase 2)


def parse_pay(
    text: str | None,
    *,
    default_currency: str | None = None,
    default_period: str | None = None,
    fx: float = config.USD_PHP_FALLBACK,
) -> models.PayInfo:
    """Parse a raw pay string into normalized hourly-equivalent PHP.

    Confidence penalties: -0.15 currency inferred from source convention, -0.30 period
    inferred from source convention, -0.10 value is a range. Unknown/negotiable -> conf 0.
    """
    t = clean(text)
    low = t.lower()
    if not t:
        return models.PayInfo()
    if re.search(r"\bnegotiable\b|\bn/?a\b|not disclosed|to be discussed|\btbd\b", low):
        return models.PayInfo(raw_text=t, confidence=0.0)

    confidence = 0.8
    if "$" in t or "usd" in low:
        currency = "USD"
    elif "₱" in t or "php" in low or "peso" in low:
        currency = "PHP"
    else:
        currency = default_currency
        if currency:
            confidence -= 0.15

    kind: str | None = None
    for candidate, pattern in _PERIOD_PATTERNS:
        if re.search(pattern, low):
            kind = candidate
            break
    if kind is None:
        kind = default_period
        if kind:
            confidence -= 0.30
    if kind is None:
        kind = models.PAY_UNKNOWN

    tokens = _NUM_TOKEN.findall(low)
    if not tokens:
        return models.PayInfo(kind=kind, raw_text=t, currency=currency, confidence=0.0)
    values = [_num(n, bool(k)) for n, k in tokens]

    if len(values) >= 2 and re.search(
        r"\d[\d,]*\s*k?\s*(?:-|–|—|to)\s*(?:\$|₱|\b(?:usd|php|peso)s?\b)?\s*\d", low
    ):
        amount = (min(values) + max(values)) / 2.0
        confidence -= 0.10
    else:
        amount = values[0]

    hourly = _to_hourly(amount, kind)
    if hourly is not None and currency == "USD":
        hourly *= fx

    return models.PayInfo(
        kind=kind,
        raw_text=t,
        hourly_equiv_php=hourly,
        currency=currency,
        confidence=max(0.0, min(1.0, confidence)),
    )


# ---------------------------------------------------------------- requirements

_DEVICE_MOBILE = re.compile(r"mobile[ -]only|smartphone|phone only|just (?:a |your )?phone", re.I)
_DEVICE_PC = re.compile(r"\b(?:laptop|pc|computer|desktop)\b", re.I)
_INTERNET_STABLE = re.compile(
    r"stable (?:internet|connection)|fast internet|\b\d+\s*mbps|reliable internet", re.I
)
_HOURS_FLEX = re.compile(
    r"flexible|set your own (?:hours|schedule)|own time|anytime|choose your (?:hours|schedule)",
    re.I,
)
_HOURS_OWN = re.compile(r"set your own|own time|own hours|choose your", re.I)
_HOURS_FIXED = re.compile(r"\bshift\b|graveyard|night shift|day shift|\bus hours\b|rotating", re.I)
_COMMS_LIVE = re.compile(
    r"video (?:call|interview)|webcam|on cam|camera|live interview|zoom|google meet", re.I
)
_MIN_HOURS_WEEK = re.compile(r"(\d{1,2})\s*(?:hours?|hrs?)\s*(?:per|/|a)\s*(?:week|wk)\b", re.I)
_FULLTIME_HINT = re.compile(r"full[- ]?time", re.I)


def extract_requirements(text: str) -> models.Requirements:
    low = clean(text).lower()
    req = models.Requirements()
    if _DEVICE_MOBILE.search(low):
        req.device = models.DEVICE_MOBILE
    elif _DEVICE_PC.search(low):
        req.device = models.DEVICE_PC
    if _INTERNET_STABLE.search(low):
        req.internet = models.INTERNET_STABLE
    if _HOURS_OWN.search(low):
        req.hours = models.HOURS_FLEX
    elif _HOURS_FIXED.search(low):
        req.hours = models.HOURS_FIXED
    elif _HOURS_FLEX.search(low):
        req.hours = models.HOURS_FLEX
    m = _MIN_HOURS_WEEK.search(low)
    if m:
        req.min_hours_per_week = int(m.group(1))
    elif _FULLTIME_HINT.search(low):
        req.min_hours_per_week = 40
    if _COMMS_LIVE.search(low):
        req.comms = models.COMMS_LIVE
    return req


# ---------------------------------------------------------------- categorization

CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "customer_support": [
        "customer service",
        "customer support",
        "chat support",
        "csr",
        "help desk",
        "call center",
        "bpo",
        "support agent",
        "technical support",
    ],
    "va_admin": [
        "virtual assistant",
        "personal assistant",
        "executive assistant",
        "admin assistant",
        "administrative assistant",
        "appointment setting",
        "email management",
    ],
    "data_entry": ["data entry", "encoding", "encoder", "typing", "encode"],
    "transcription": ["transcription", "transcriber", "captioning", "subtitle", "captions"],
    "ai_training": [
        "ai training",
        "ai trainer",
        "data annotation",
        "annotat",
        "labeling",
        "labelling",
        "rlhf",
        "content moderation",
        "llm",
        "ai model evaluation",
    ],
    "online_tutoring": ["tutor", "teach", "teacher", "teaching", "esl", "lesson", "english online"],
    "content_writing": [
        "content writer",
        "writer",
        "writing",
        "copywriting",
        "blogger",
        "blog",
        "proofread",
        "editor",
        "article",
    ],
    "translation": ["translat", "interpreter"],
    "dev": [
        "developer",
        "programmer",
        "software engineer",
        "full stack",
        "full-stack",
        "backend",
        "frontend",
        "front-end",
        "web developer",
        "python",
        "javascript",
        "react",
        "laravel",
        "node",
    ],
    "design": [
        "designer",
        "graphic design",
        "ui design",
        "ux",
        "figma",
        "canva",
        "photoshop",
        "illustrator",
        "video editor",
        "video editing",
        "motion graphics",
    ],
    "social_media": [
        "social media",
        "smm",
        "tiktok",
        "instagram",
        "facebook ads",
        "community manager",
        "seo specialist",
        "digital marketing",
        "content creator",
    ],
    "qa_testing": ["qa", "tester", "test cases", "quality assurance", "manual testing", "bug"],
    "microtasks": [
        "survey",
        "microtask",
        "micro task",
        "small task",
        "easy task",
        "raket",
        "sideline",
    ],
    "sales_marketing": [
        "sales",
        "lead generation",
        "telemarketing",
        "affiliate",
        "telesales",
        "cold call",
        "marketing specialist",
    ],
}


def categorize(title: str, body: str = "") -> str:
    """Keyword scoring; title matches weigh double. Falls back to 'other'."""
    t_low = clean(title).lower()
    b_low = clean(body).lower()
    best, best_score = "other", 0
    for category, keywords in CATEGORY_KEYWORDS.items():
        score = 0
        for kw in keywords:
            pattern = r"\b" + re.escape(kw) + r"\b"
            weight = 1 + len(kw) // 4  # longer phrases are more specific
            if re.search(pattern, t_low):
                score += 2 * weight
            if re.search(pattern, b_low):
                score += 1 * weight
        if score > best_score:
            best, best_score = category, score
    return best


_SKILL_KEYWORDS: dict[str, str] = {
    "python": r"\bpython\b",
    "javascript": r"\bjavascript\b|\bjs\b",
    "typescript": r"\btypescript\b",
    "react": r"\breact\b",
    "node": r"\bnode(?:\.?js)?\b",
    "php": r"\bphp\b",
    "wordpress": r"wordpress",
    "shopify": r"shopify",
    "seo": r"\bseo\b",
    "canva": r"canva",
    "figma": r"figma",
    "photoshop": r"photoshop",
    "excel": r"\bexcel\b",
    "google_sheets": r"google sheets",
    "quickbooks": r"quickbooks",
    "crm": r"\bcrm\b",
    "hubspot": r"hubspot",
    "salesforce": r"salesforce",
    "english": r"\benglish\b",
    "communication": r"communica",
    "writing": r"writing|copywriting",
    "video_editing": r"video edit",
    "customer_service": r"customer (?:service|support)",
    "data_entry": r"data entry|encoding",
    "chatgpt": r"chat ?gpt",
    "ai_tools": r"\bai (?:tools|automation)|generative ai|\bai\b",
    "social_media": r"social media",
    "teaching": r"teach|tutor",
    "bookkeeping": r"bookkeep",
    "lead_gen": r"lead gen|prospecting",
    "go_high_level": r"go ?high ?level|\bghl\b",
}


def extract_tags(text: str) -> list[str]:
    low = clean(text).lower()
    return sorted({tag for tag, pattern in _SKILL_KEYWORDS.items() if re.search(pattern, low)})


_NO_EXPERIENCE = re.compile(
    r"no experience|entry[- ]level|no prior|fresh ?grad|beginners? (?:welcome|friendly)|"
    r"no experience required|undergrad",
    re.I,
)


def is_no_experience_friendly(text: str) -> bool:
    return bool(_NO_EXPERIENCE.search(clean(text)))


# ---------------------------------------------------------------- payout cadence

_PAYOUT_INSTANT = re.compile(r"gcash|instant(?:ly)?\s+p(?:ay|aid)|same[- ]day\s+pay", re.I)
_PAYOUT_DAILY = re.compile(r"paid\s+daily|daily\s+payout|payout\s+daily|daily\s+pay", re.I)
_PAYOUT_WEEKLY = re.compile(r"weekly\s+(?:payout|pay)|paid\s+weekly|pay\s+weekly", re.I)


def payout_cadence(text: str, pay_kind: str) -> str:
    low = clean(text).lower()
    if _PAYOUT_INSTANT.search(low):
        return models.PAYOUT_INSTANT
    if _PAYOUT_DAILY.search(low):
        return models.PAYOUT_DAILY
    if _PAYOUT_WEEKLY.search(low):
        return models.PAYOUT_WEEKLY
    if pay_kind == models.PAY_PER_TASK:
        return models.PAYOUT_PER_TASK
    if pay_kind in (models.PAY_MONTHLY, models.PAY_YEARLY):
        return models.PAYOUT_MONTHLY
    return models.PAYOUT_UNKNOWN


# ---------------------------------------------------------------- scam signals

_FEE_REQUIRED = re.compile(
    r"(?:registration|training|application|processing|membership|admin)\s*fee"
    r"|pay[^.]{0,30}(?:fee|deposit)"
    r"|fee[^.]{0,30}to (?:start|apply|begin|join)"
    r"|\bdeposit\b[^.]{0,40}(?:start|training|equipment)"
    r"|invest(?:ment)?\s+(?:first|required|to start)",
    re.I,
)


# Soft signals -> downrank (score.trust_factor). The classic "no company + text-only
# contact" scammer shape from the scam layer: a personal contact vector with no employer
# name behind it. Fires only when the company name is also withheld, so a named employer
# advertising "email us at careers@co.com" is NOT penalized.
_DIRECT_CONTACT = re.compile(
    r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"  # bare email
    r"|wa\.me/|whatsapp\.com/"
    r"|t\.me/|tg://"
    r"|discord\.gg/|discordapp\.com/"
    r"|\b\+?63\s?9\d{9}\b"  # PH mobile
    r"|call/text|call or text|sms me",
    re.I,
)
# Company field placeholders that mean the employer name was withheld.
_COMPANY_PLACEHOLDER = re.compile(
    r"^(?:n/?a|tbd|to be discussed|anon(?:ymous)?|confidential|self[-\s]employed|freelancer)$",
    re.I,
)


def _company_known(company: str) -> bool:
    """True when the listing carries a real employer name (not withheld/placeholder)."""
    c = clean(company)
    return bool(c) and not _COMPANY_PLACEHOLDER.match(c)


def scam_flags(text: str, *, company: str = "") -> list[str]:
    """Hard signals -> auto-exclude; soft signals -> downrank (score.trust_factor).

    Hard flags (fee_required) force status=flagged in enrich(); soft flags (no_company)
    only downrank via trust_factor and never exclude on their own. ``company`` is needed
    because "no company + text-only contact" is a conjunction, not merely the presence of
    a contact vector.
    """
    low = clean(text)
    flags: list[str] = []
    if _FEE_REQUIRED.search(low):
        flags.append("fee_required")
    if _DIRECT_CONTACT.search(low) and not _company_known(company):
        flags.append("no_company")
    return flags
