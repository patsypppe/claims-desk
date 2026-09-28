"""Deterministic normalizers for PII and lookup values. All return None when the input is not valid."""
import re
from datetime import date

MONTHS = {name: i for i, name in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
     "november", "december"], start=1)}
MONTH_ALT = r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sept?(?:ember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
DASHES = "‐‑‒–—−"
_DASH_TABLE = str.maketrans({d: "-" for d in DASHES})


def unify_dashes(text: str) -> str:
    return text.translate(_DASH_TABLE)


def month_number(token: str) -> int | None:
    token = token.lower().rstrip(".")
    return next((num for name, num in MONTHS.items() if name.startswith(token[:3]) and len(token) >= 3), None)


def _year(raw: str, today: date) -> int:
    value = int(raw)
    if len(raw) == 2:
        return 1900 + value if value > today.year % 100 else 2000 + value
    return value


def _valid(y: int, m: int, d: int, today: date) -> str | None:
    try:
        parsed = date(y, m, d)
    except ValueError:
        return None
    return parsed.isoformat() if parsed <= today else None


def normalize_dob(raw: str, today: date) -> str | None:
    text = unify_dashes(raw.strip().lower())
    if m := re.search(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", text):
        return _valid(int(m[1]), int(m[2]), int(m[3]), today)
    if m := re.search(r"\b(\d{1,2})[/.-](\d{1,2})[/.-](\d{2}|\d{4})\b", text):
        return _valid(_year(m[3], today), int(m[1]), int(m[2]), today)
    if m := re.search(MONTH_ALT + r"\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})", text):
        return _valid(int(m[3]), month_number(m[1]), int(m[2]), today)
    if m := re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?" + MONTH_ALT + r"\.?,?\s+(\d{4})", text):
        return _valid(int(m[3]), month_number(m[2]), int(m[1]), today)
    return None


def normalize_phone(raw: str) -> str | None:
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 10:
        return f"+1{digits}"
    if len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"
    return None


def normalize_email(raw: str) -> str | None:
    value = raw.strip().lower()
    return value if re.fullmatch(r"[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}", value) else None


def normalize_name(raw: str) -> str:
    cleaned = "".join(ch for ch in raw.casefold() if ch.isalnum() or ch.isspace() or ch in "-'")
    return " ".join(cleaned.split())


def name_tokens(raw: str) -> frozenset[str]:
    return frozenset(normalize_name(raw).split())


def normalize_id_last4(raw: str) -> str | None:
    digits = re.sub(r"\s", "", raw)
    return digits if re.fullmatch(r"\d{4}", digits) else None


def normalize_claim_id(raw: str) -> str | None:
    m = re.search(r"\bcl\s*[-\s]?\s*(\d{4})\b", unify_dashes(raw), re.I)
    return f"CL-{m[1]}" if m else None


def normalize_policy(raw: str) -> str | None:
    m = re.search(r"\bpol\s*[-\s]?\s*(\d{3,})\b", unify_dashes(raw), re.I)
    return f"POL-{m[1]}" if m else None


def parse_month_year(text: str, today: date) -> tuple[int | None, int | None]:
    """Month/year hint for a CLAIM date (not a DOB). 'last <month>' resolves to the most recent one."""
    low = text.lower()
    m = re.search(r"\b(last\s+)?" + MONTH_ALT + r"\b(?:\s+(?:of\s+)?(\d{4}))?", low)
    if not m:
        return None, None
    month = month_number(m[2])
    if m[3]:
        return month, int(m[3])
    if m[1]:
        return month, today.year if month < today.month else today.year - 1
    return month, None
