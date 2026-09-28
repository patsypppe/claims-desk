"""Keyword lexicons and regexes for the deterministic extractor (the no-LLM path and LLM cross-check)."""
import re

from claims_agent.normalize import MONTH_ALT

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"(?<!\d)(?:\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}(?!\d)")
DATE_RES = (
    re.compile(r"\b\d{4}-\d{1,2}-\d{1,2}\b"),
    re.compile(r"\b\d{1,2}[/.-]\d{1,2}[/.-](?:\d{4}|\d{2})\b"),
    re.compile(MONTH_ALT + r"\.?\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4}", re.I),
    re.compile(r"\b\d{1,2}(?:st|nd|rd|th)?\s+(?:of\s+)?" + MONTH_ALT + r"\.?,?\s+\d{4}", re.I),
)
FOUR_DIGITS_RE = re.compile(r"(?<![\d-])\d{4}(?![\d-])")
ID_CUE_RE = re.compile(r"(ssn|social|last\s*(?:four|4)|national\s*id|\bid\b|ends?\s+(?:in|with))", re.I)
DOB_CUE_RE = re.compile(r"(dob|date of birth|birth\s*day|birthdate|born)", re.I)
NAME_CUE_RE = re.compile(
    r"\b(?i:my name is|my name's|name is|i am|i'm|this is|it's)\s+((?:[A-Z][a-zA-Z'-]+)(?:\s+[A-Z][a-zA-Z'-]+){0,3})")
NAME_STOPWORDS = frozenset({"The", "Not", "Calling", "Here", "Just", "So", "Really", "Very", "Sorry", "Fine", "Ok",
                            "Okay", "Yes", "No", "Hi", "Hello", "SSN", "DOB", "I", "My", "Your", "Policy", "SYSTEM"})
CORRECTION_RE = re.compile(r"\b(actually|i meant|correction|sorry,? (?:it'?s|my)|not .{1,30}, it'?s|wait)\b", re.I)
REFUSAL_RE = re.compile(r"(not (?:going to |gonna )?(?:give|giving|share|sharing|provide|providing)|"
                        r"won'?t (?:give|share|provide)|rather not|refuse|don'?t want to (?:give|share)|"
                        r"none of your business|not comfortable)", re.I)
REFUSE_ALL_RE = re.compile(r"(any (?:personal |of my )?(?:info|information|details)|anything personal)", re.I)
FIELD_WORDS = {
    "id_last4": re.compile(r"(ssn|social|national id|\bid\b|last four|last 4)", re.I),
    "dob": re.compile(r"(dob|date of birth|birthday|birth date)", re.I),
    "phone": re.compile(r"(phone|number|cell|mobile)", re.I),
    "email": re.compile(r"(e-?mail)", re.I),
    "name": re.compile(r"(my name)", re.I),
}
CASE_TYPES = {"healthcare": r"(healthcare|health care|medical|health|hospital|doctor|clinic|pathology)",
              "dental": r"(dental|dentist|teeth|tooth)", "auto": r"(auto|car|vehicle|accident|collision)"}
STATUSES = {"denied": r"(denied|denial|rejected|declined)", "closed": r"(closed|settled|completed)",
            "open": r"(open|pending|in progress)"}
DOCUMENTS = ("pathology report", "office note", "diagnosis report", "repair estimate", "accident photos",
             "scene photos")
OOS_RE = re.compile(r"(recipe|pasta|cook|python|javascript|write (?:some )?code|program|weather|vote|election|"
                    r"president|quantum|reinforcement learning|machine learning|joke|poem|song|sports?|football|"
                    r"stock|bitcoin|crypto|movie|capital of|homework|translate)", re.I)
INSURANCE_RE = re.compile(r"(claim|policy|insur|denied|denial|appeal|coverage|deductible|reimburs|payment|paid|"
                          r"document|report|verify|verification|premium|cl-?\s?\d{4}|email|summary)", re.I)
SMALL_TALK_RE = re.compile(r"^\s*(hi|hello|hey|good (?:morning|afternoon|evening)|thanks?|thank you|ok(?:ay)?)"
                           r"[\s!.,]*$", re.I)
INJECTION_RE = re.compile(r"(ignore (?:all |any |your |the )?(?:previous |prior )?(?:instructions|rules)|"
                          r"system\s*:|developer mode|dev mode|verified\s*=\s*true|phase\s*=|"
                          r"pretend (?:i'?m|i am|that i'?m) verified|already verified|verification already|"
                          r"skip (?:the )?verification|system prompt|you are now|override|jailbreak|"
                          r"authori[sz]ed you|previous agent verified|admin\s*:)", re.I)
TOOL_REQUEST_RE = re.compile(r"(call|run|use|invoke)\s+(?:the |your )?(?:claim\s+)?(lookup|search)", re.I)
HUMAN_RE = re.compile(r"(speak|talk|transfer|connect)\s+(?:me\s+)?(?:to|with)\s+(?:a |an |the |your )?"
                      r"(?:real |live |actual )?(human|person|representative|rep|agent|someone|supervisor|manager)|"
                      r"\b(human|real person|representative|operator)\b(?:,)?\s*please", re.I)
DONE_RE = re.compile(r"(that'?s (?:all|everything|it)|nothing else|no more questions|i'?m (?:all )?done|"
                     r"that is (?:all|everything)|i'?m good|all set)", re.I)
OTHER_EMAIL_RE = re.compile(r"(send|email|forward) (?:it|this|the summary)? ?to (?:my |a )?(other|different|"
                            r"another|son|wife|husband|work|[\w.+-]+@)", re.I)
YES_RE = re.compile(r"^\s*(yes|yeah|yep|sure|please do|please send|send it|go ahead|ok(?:ay)?|absolutely|"
                    r"of course|definitely)\b|\b(yes,? please|please email|email (?:it|me))\b", re.I)
NO_RE = re.compile(r"^\s*(no|nope|nah|don'?t|do not|skip|not now|no thanks?)\b|\b(no thanks|don'?t send|"
                   r"do not send|no need|skip it|actually no|changed my mind)\b", re.I)
HEDGE_RE = re.compile(r"\b(maybe|not sure|whatever|i guess|perhaps|i don'?t know|dunno|hmm)\b", re.I)
EMOTION_RES = (
    ("distrust", re.compile(r"(scam|don'?t trust|why do you need|suspicious|how do i know you)", re.I)),
    ("anger", re.compile(r"(ridiculous|absurd|unacceptable|furious|outrageous|useless|incompetent|!!)", re.I)),
    ("frustration", re.compile(r"(already told you|again\?|frustrat|how many times|annoying|this is taking)", re.I)),
    ("anxiety", re.compile(r"(worried|anxious|scared|stress|panic|can'?t afford|afraid|nervous)", re.I)),
    ("confusion", re.compile(r"(confus|don'?t understand|what do you mean|not sure what|lost me)", re.I)),
)
THIRD_PARTY_RE = re.compile(r"(on behalf of|(?:calling (?:for|about)|for) my (?:mother|mom|father|dad|wife|husband|"
                            r"son|daughter|parent|spouse)|i'?m (?:her|his) (\w+))", re.I)
RELATIONSHIP_RE = re.compile(r"\b(son|daughter|husband|wife|mother|father|mom|dad|brother|sister|spouse|partner|"
                             r"friend|caregiver)\b", re.I)
TOPIC_RULES = (
    ("appeal_question", r"appeal"),
    ("denial_question", r"why .*(denied|denial|rejected)|reason .*(denied|denial)"),
    ("document_submission", r"(submit|send|upload|document|paperwork|report|note|pdf|scan|photo|portal|fax)"),
    ("payment_question", r"(how much|pay|paid|payment|reimburs|amount|money)"),
    ("next_steps", r"(next step|what now|what should i do|what happens next|what do i do)"),
    ("status_inquiry", r"(status|what'?s happening|update on|where is my)"),
)
ATTRIBUTE_RULES = (
    ("provider_or_facility", r"(hospital|provider|facility|clinic|which doctor|who submitted)"),
    ("payment_date", r"(when .*(get paid|payment|paid|receive))"),
    ("deadline", r"(deadline|how long do i have|still appeal|too late)"),
    ("denial_reason", r"(why .*(denied|denial|rejected)|reason)"),
    ("amounts", r"(how much|amount|pay(?:ing|out)?\b|reimburs)"),
    ("documents", r"(what (?:do i need|documents)|which documents|what to send|need to send)"),
    ("status", r"(status)"),
)
