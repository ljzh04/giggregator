"""Pay extraction across the whole listing: structured pay field first, body scan fallback.

Kept separate from normalize.parse_pay so adapters pass their source-specific conventions
(default currency / period) and the body-scan fallback stays in one place.
"""

from __future__ import annotations

import re

from . import config, models, normalize


def _guess_onlinejobs_currency(text: str) -> str | None:
    """OnlineJobs pay column is unit-ambiguous: '$' marked = USD, bare = PH context.

    Heuristic per fixture corpus: bare numbers under ~20 are USD hourly VA rates;
    20+ are PHP. Confidence is already penalized for inferred currency in parse_pay.
    """
    low = normalize.clean(text).lower()
    if "$" in low or "usd" in low or "₱" in low or "php" in low or "peso" in low:
        return None  # explicit; parse_pay handles it
    m = re.search(r"\d", low)
    if not m:
        return None
    return "USD" if m.group() and re.search(r"\b\d{1,2}(\.\d+)?\b", low) else "PHP"


_EXPLICIT_PERIOD = re.compile(
    r"per\s*(?:hour|hr|month|week|day|gig|task|year)|/hr|/hour|/month|/week|/day|/gig|/task"
    r"|monthly|weekly|yearly|annual",
    re.I,
)
_FIRST_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _onlinejobs_defaults(pay_raw: str) -> tuple[str | None, str | None]:
    """(currency, default_period) for an OnlineJobs pay string.

    Documented conventions (fixture MANIFEST.md): explicit $/Php markers set currency;
    bare numbers are magnitude-guessed (<20 -> USD hourly VA rate, else PHP). Period:
    explicit markers left to parse_pay; otherwise PH postings are monthly salaries when
    the value >= 100, hourly piece rates below that.
    """
    low = normalize.clean(pay_raw).lower()
    if re.search(r"\$|usd", low):
        currency = "USD"
    elif re.search(r"₱|php|peso", low):
        currency = "PHP"
    else:
        m = _FIRST_NUMBER.search(low)
        first = float(m.group().replace(",", "")) if m else 0.0
        currency = "USD" if first < 20 else "PHP"
    m = _FIRST_NUMBER.search(low)
    first = float(m.group().replace(",", "")) if m else 0.0
    period = None if _EXPLICIT_PERIOD.search(low) else ("monthly" if first >= 100 else "hourly")
    return currency, period


def pay_from_listing(raw: models.RawListing, *, fx: float = config.USD_PHP_FALLBACK) -> models.PayInfo:
    default_currency = None
    default_period = None
    pay_raw = raw.pay_raw

    if raw.source_id == "onlinejobs_ph" and pay_raw:
        default_currency, default_period = _onlinejobs_defaults(pay_raw)
    elif raw.source_id == "remotive":
        default_currency = "USD"
        default_period = "yearly"  # salary field is annual k-notation in practice
    elif raw.source_id in ("jobicy", "arbeitnow"):
        default_currency = "USD"
        default_period = "yearly"

    if pay_raw:
        info = normalize.parse_pay(
            pay_raw, default_currency=default_currency, default_period=default_period, fx=fx
        )
        if info.hourly_equiv_php is not None or info.kind != models.PAY_UNKNOWN:
            return info

    # fallback: scan the body for an embedded pay sentence
    body = normalize.clean(raw.body)
    if body:
        window = _pay_window(body)
        if window:
            info = normalize.parse_pay(
                window, default_currency=default_currency, default_period=None, fx=fx
            )
            info.confidence = max(0.0, info.confidence - 0.10)  # body-scan penalty
            if info.hourly_equiv_php is not None and 15.0 <= info.hourly_equiv_php <= 7500.0:
                return info  # sanity clamp: outside this band it's almost certainly
            # a false positive (traffic stats, funding numbers, etc.) — treat as unknown
    return normalize.parse_pay(None)


def _pay_window(body: str, max_chars: int = 4000) -> str | None:
    """Find a pay-ish sentence: must contain a currency marker or salary/hourly phrasing.

    Bare 'per month'/'per week' sentences are NOT enough (traffic-count sentences in
    company blurbs false-positive otherwise — seen live in the jobicy fixture corpus).
    """
    pattern = re.compile(
        r"[^.!?\n]{0,80}(?:\$|₱|\bUSD\b|\bPHP\b|\bpeso|\b/hr\b|\bper hour\b|\bper hr\b"
        r"|\bhourly\b|\bsalary\b|\bpay\b)[^.!?\n]{0,120}",
        re.I,
    )
    m = pattern.search(body[:max_chars])
    return m.group(0).strip() if m else None
