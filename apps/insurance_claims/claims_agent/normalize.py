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
    return _dateparser_dob(raw, today)


def _dateparser_dob(raw: str, today: date) -> str | None:
    """Fallback for spelled-out forms ("the fifteenth of March, 1985"). US order; all parts required."""
    if not re.search(r"\d{4}", raw):
        return None
    import dateparser

    parsed = dateparser.parse(raw, languages=["en"], settings={
        "DATE_ORDER": "MDY", "STRICT_PARSING": True, "REQUIRE_PARTS": ["day", "month", "year"],
        "PREFER_DATES_FROM": "past"})
    return _valid(parsed.year, parsed.month, parsed.day, today) if parsed else None


def normalize_phone(raw: str) -> str | None:
    """E.164 for valid North American numbers only (the fixture market); libphonenumber validates area codes."""
    import phonenumbers

    try:
        number = phonenumbers.parse(raw, "US")
    except phonenumbers.NumberParseException:
        return None
    if number.country_code != 1 or not phonenumbers.is_valid_number(number):
        return None
    return phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.E164)


def normalize_email(raw: str) -> str | None:
    from email_validator import EmailNotValidError, validate_email

    try:
        return validate_email(raw.strip(), check_deliverability=False).normalized.lower()
    except EmailNotValidError:
        return None


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


def _is_month_may(text: str, start: int, end: int) -> bool:
    """'may' is a month only when written 'May' or followed by a day/year (not the verb 'I may need')."""
    word = text[start:end]
    following = text[end:end + 6]
    return word == "May" or bool(re.match(r"\s+\d", following))


def _bare_year(text: str, today: date) -> int | None:
    m = re.search(r"\b(?:from|in|of|the one from|filed in|year)\s+(20\d{2})\b|^\s*(20\d{2})\s*[.!?]?\s*$", text, re.I)
    year = int(m[1] or m[2]) if m else None
    return year if year and year <= today.year else None


def parse_month_year(text: str, today: date) -> tuple[int | None, int | None]:
    """Month/year hint for a CLAIM date (not a DOB). 'last <month>' resolves to the most recent one."""
    low = text.lower()
    m = None
    for candidate in re.finditer(r"\b(last\s+)?" + MONTH_ALT + r"\b(?:\s+(?:of\s+)?(\d{4}))?", low):
        if candidate[2] == "may" and not _is_month_may(text, candidate.start(2), candidate.end(2)):
            continue
        m = candidate
        break
    if not m:
        return None, _bare_year(text, today)
    month = month_number(m[2])
    if m[3]:
        return month, int(m[3])
    if m[1]:
        return month, today.year if month < today.month else today.year - 1
    return month, None
