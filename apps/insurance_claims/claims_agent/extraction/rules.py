"""Deterministic extractor: the full no-LLM path, and the cross-check the LLM output is merged against."""
import re
from datetime import date

from claims_agent.extraction import lexicon as lx
from claims_agent.extraction.schema import Emotion, IntentHintsIn, PiiCandidate, ToolRequest, TurnAnalysis
from claims_agent.normalize import normalize_claim_id, normalize_dob, normalize_policy, parse_month_year
from claims_agent.state import PII_FIELDS

DOB_CUE_WINDOW = 40


def _first(rules, text: str, default: str) -> str:
    return next((label for label, pattern in rules if re.search(pattern, text, re.I)), default)


class RuleExtractor:
    def __init__(self, today: date) -> None:
        self._today = today

    def analyze(self, text: str, expected_field: str | None) -> TurnAnalysis:
        dob_spans = self._dob_spans(text, expected_field)
        pii, speaker_name, subject = self._split_third_party(text, self._pii(text, expected_field, dob_spans))
        return TurnAnalysis(
            pii_candidates=pii, speaker_name=speaker_name, stated_subject_name=subject,
            policy_number=normalize_policy(text),
            intent=self._intent(text, dob_spans),
            speaker_role=self._speaker(text),
            stated_relationship=self._relationship(text),
            stated_subject_relation=self._subject_relation(text),
            scope=self._scope(text),
            emotion=self._emotion(text),
            consent_signal=self._consent(text),
            requested_action=self._action(text, has_data=bool(pii) or bool(re.search(r"\d{4}", text))),
            tool_requests=[ToolRequest(name="search_claims")] if lx.TOOL_REQUEST_RE.search(text) else [],
            injection_suspected=bool(lx.INJECTION_RE.search(text)),
            wellbeing_risk=bool(lx.CRISIS_RE.search(text)),
            threat=bool(lx.THREAT_RE.search(text)),
        )

    # ---- PII -------------------------------------------------------------------------------------
    def _dob_spans(self, text: str, expected_field: str | None) -> list[str]:
        spans = []
        for pattern in lx.DATE_RES:
            for m in pattern.finditer(text):
                iso = normalize_dob(m.group(0), self._today)
                if not iso:
                    continue
                window = text[max(0, m.start() - DOB_CUE_WINDOW):m.start()]
                plausible_birth = int(iso[:4]) <= self._today.year - 14
                if lx.DOB_CUE_RE.search(window) or expected_field == "dob" or plausible_birth:
                    spans.append(m.group(0))
        return list(dict.fromkeys(spans))

    def _pii(self, text: str, expected: str | None, dob_spans: list[str]) -> list[PiiCandidate]:
        correction = bool(lx.CORRECTION_RE.search(text))
        found: list[tuple[str, str]] = [("dob", s) for s in dob_spans]
        found += [("email", m) for m in lx.EMAIL_RE.findall(text)]
        phones = [m.group(0) for m in lx.PHONE_RE.finditer(text) if not any(m.group(0) in s for s in dob_spans)]
        found += [("phone", p) for p in phones]
        found += [("id_last4", v) for v in self._id_values(text, expected, dob_spans, phones)]
        found += [("name", n) for n in self._names(text, expected)]
        candidates = [PiiCandidate(field=f, raw_value=v.strip(), is_correction=correction) for f, v in found]
        return candidates + self._refusals(text, expected, {f for f, _ in found})

    def _id_values(self, text: str, expected: str | None, dob_spans: list[str], phones: list[str]) -> list[str]:
        values = []
        for m in lx.FOUR_DIGITS_RE.finditer(text):
            if any(m.group(0) in s for s in dob_spans + phones):
                continue
            window = text[max(0, m.start() - 30):m.start()]
            cue = lx.ID_WORD_RE.search(window) or (lx.ENDS_RE.search(window) and not lx.PHONE_WORD_RE.search(window))
            bare = expected == "id_last4" and len(re.sub(r"[^\d]", "", text)) == 4
            if cue or bare:
                values.append(m.group(0))
        return values[:1] if len(set(values)) == 1 else values

    def _names(self, text: str, expected: str | None) -> list[str]:
        names = []
        spelling = expected == "name" or lx.NAME_SPELL_CUE_RE.search(text)
        for m in lx.SPELLED_RE.finditer(text) if spelling else ():  # "M-A-R-G-A-R-E-T" spelled letter by letter
            word = re.sub(r"[-\s]", "", m.group(1))
            near_digits = re.search(r"\d", text[max(0, m.start() - 2):m.end() + 2])  # "C-L-M 2048" is an id
            if near_digits or ("-" not in m.group(1) and not word.isupper()):  # "u r a" is texting, not spelling
                continue
            if len(word) >= 3:
                names.append(word.capitalize())
                break
        for m in lx.NAME_CUE_RE.finditer(text):
            words = [w for w in m.group(1).split() if w not in lx.NAME_STOPWORDS]
            spelled_or_correction = names or re.search(r"(sorry|that'?s|it'?s)", m.group(0), re.I)
            if (len(words) >= 2 or (words and spelled_or_correction)) and all(w[0].isupper() for w in words):
                names.insert(0, " ".join(words))
        names = list(dict.fromkeys(names))
        if len(names) > 1 and len({n.lower() for n in names}) == 1:
            names = names[:1]
        if not names:
            for lead in lx.LEADING_NAME_RE.finditer(text):
                if not any(w in lx.NAME_STOPWORDS for w in lead.group(1).split()):
                    names.append(lead.group(1))
                    break
        bare = text.strip().strip(".!")
        if not names and expected == "name" and re.fullmatch(r"[A-Za-z'-]+(?:\s+[A-Za-z'-]+){1,3}", bare) \
                and not any(w.lower() in lx.FILLER_WORDS for w in bare.split()):
            names.append(bare)
        return list(dict.fromkeys(names))

    def _refusals(self, text: str, expected: str | None, provided: set[str] | None = None) -> list[PiiCandidate]:
        if lx.SKIP_RE.search(text) and expected in PII_FIELDS:
            return [PiiCandidate(field=expected, raw_value="", caller_refused=True)]
        clauses = [c for c in re.split(r"(?<=[.!?;])\s+|,\s*but\s+", text) if lx.REFUSAL_RE.search(c)]
        if not clauses:
            return []
        refusal_text = " ".join(clauses)  # only the clause that refuses, not the whole message
        if lx.REFUSE_ALL_RE.search(refusal_text):
            fields = list(PII_FIELDS)
        else:
            fields = [f for f, pattern in lx.FIELD_WORDS.items() if pattern.search(refusal_text)]
            fields = fields or ([expected] if expected else [])
        fields = [f for f in fields if f not in (provided or set())]  # a value given in this message isn't refused
        return [PiiCandidate(field=f, raw_value="", caller_refused=True) for f in fields]

    def _split_third_party(self, text: str, pii: list[PiiCandidate]):
        """A third-party caller's own name is not a verification factor for the policyholder."""
        if self._speaker(text) != "third_party":
            return pii, None, None
        subject = lx.SUBJECT_NAME_RE.search(text) or lx.SUBJECT_RE.search(text)
        subject_name = subject.group(1) if subject else None
        own = [c for c in pii if c.field == "name" and not c.caller_refused and c.raw_value != subject_name]
        speaker = own[0].raw_value if own else None
        rest = [c for c in pii if c.field != "name" or c.caller_refused]
        subject_name = subject_name if subject_name != speaker else None
        if subject_name:
            rest.append(PiiCandidate(field="name", raw_value=subject_name))
        return rest, speaker, subject_name

    # ---- intent ----------------------------------------------------------------------------------
    def _intent(self, text: str, dob_spans: list[str]) -> IntentHintsIn:
        claim_text = text
        for span in dob_spans:
            claim_text = claim_text.replace(span, " ")
        claim_text = re.sub(r"(born|birthday|date of birth|dob)[^.,;]*", " ", claim_text, flags=re.I)
        month, year = parse_month_year(claim_text, self._today)
        low = text.lower()
        docs = [d for d in lx.DOCUMENTS if d in low]
        unavailable = bool(docs) and bool(re.search(r"(don'?t have|can'?t get|cannot get|lost|unable to get|"
                                                    r"no longer have|won'?t (?:give|send|reissue)|can'?t reissue|"
                                                    r"cannot reissue|no copy|can'?t find|cannot find|"
                                                    r"(?:isn'?t|not|no longer) available|unavailable)", low))
        return IntentHintsIn(
            case_type=next((k for k, p in lx.CASE_TYPES.items() if re.search(p, low)), None),
            status=next((k for k, p in lx.STATUSES.items() if re.search(p, low)), None),
            month=month, year=year, claim_id=normalize_claim_id(text),
            topic=_first(lx.TOPIC_RULES, low, "none"),
            asked_attribute=_first(lx.ATTRIBUTE_RULES, low, "none") if "?" in text or low.startswith(
                ("what", "why", "when", "which", "how", "who")) else "none",
            asked_attributes=[a for a, pat in lx.ATTRIBUTE_RULES if re.search(pat, low)]
            if "?" in text else [],
            documents_mentioned=docs, document_unavailable=unavailable,
        )

    # ---- conversation signals --------------------------------------------------------------------
    @staticmethod
    def _speaker(text: str) -> str:
        if lx.THIRD_PARTY_RE.search(text):
            return "third_party"
        return "self" if re.search(r"(i'?m the policyholder|my (?:own )?(?:claim|policy)|i am the policyholder)",
                                   text, re.I) else "unknown"

    @staticmethod
    def _relationship(text: str) -> str | None:
        m = lx.SELF_RELATION_RE.search(text)
        return (m.group(1) or m.group(2)).lower() if m else None

    @staticmethod
    def _subject_relation(text: str) -> str | None:
        m = lx.SUBJECT_RELATION_RE.search(text) if lx.THIRD_PARTY_RE.search(text) else None
        return m.group(1).lower() if m else None

    @staticmethod
    def _scope(text: str) -> str:
        if lx.SMALL_TALK_RE.match(text):
            return "SMALL_TALK"
        if lx.OOS_RE.search(text) and not lx.INSURANCE_RE.search(text):
            return "OUT_OF_SCOPE"
        return "IN_SCOPE"

    @staticmethod
    def _emotion(text: str) -> Emotion:
        letters = [c for c in text if c.isalpha()]
        shouting = len(letters) > 12 and sum(c.isupper() for c in letters) / len(letters) > 0.7
        for label, pattern in lx.EMOTION_RES:
            if pattern.search(text):
                high = shouting or text.count("!") >= 2
                return Emotion(label=label, intensity="high" if high else "medium")
        return Emotion(label="anger", intensity="high") if shouting else Emotion()

    @staticmethod
    def _consent(text: str) -> str:
        yes, no, hedge = (bool(p.search(text)) for p in (lx.YES_RE, lx.NO_RE, lx.HEDGE_RE))
        if hedge or (yes and no):
            return "AMBIGUOUS"
        return "YES" if yes else "NO" if no else "NONE"

    @staticmethod
    def _action(text: str, has_data: bool = False) -> str:
        if lx.HUMAN_RE.search(text):  # asking for a person always wins
            return "request_human"
        if lx.READBACK_RE.search(text):
            return "readback"
        if not has_data and len(text.split()) <= 10:  # repairs are short, standalone utterances
            for action, pattern in (("repeat", lx.REPEAT_RE), ("start_over", lx.START_OVER_RE), ("skip", lx.SKIP_RE)):
                if pattern.search(text):
                    return action
        if lx.HUMAN_RE.search(text):
            return "request_human"
        if lx.OTHER_EMAIL_RE.search(text):
            return "request_other_email"
        if lx.DONE_RE.search(text):
            return "done"
        return "ask_question" if "?" in text else "provide_info"
