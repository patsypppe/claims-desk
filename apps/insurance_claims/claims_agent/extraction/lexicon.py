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
ID_WORD_RE = re.compile(r"(ssn|social|last\s*(?:four|4)|national\s*id|\bid\b)", re.I)
ENDS_RE = re.compile(r"ends?\s+(?:in|with)", re.I)
PHONE_WORD_RE = re.compile(r"(phone|number|cell|mobile)", re.I)
DOB_CUE_RE = re.compile(r"(dob|date of birth|birth\s*day|birthdate|born)", re.I)
NAME_CUE_RE = re.compile(
    r"\b(?i:my name is|my name's|name is|i am|i'm|this is|it's|that's|thats)\s+((?:[A-Z][a-zA-Z'-]+)(?:\s+[A-Z][a-zA-Z'-]+){0,3})")
LEADING_NAME_RE = re.compile(r"(?:^|[.!?:]\s+)([A-Z][a-z'-]+(?:\s+[A-Z][a-z'-]+){1,3})(?:\s*[,.;]|\s+(?=[^\w\s]))")
FILLER_WORDS = frozenset({"hold", "on", "one", "sec", "second", "moment", "minute", "hi", "hello", "hey", "there",
                          "wait", "a", "ok", "okay", "yes", "no", "sure", "thanks", "thank", "you", "um", "uh", "hmm",
                          "please", "just", "what", "why", "sorry", "fine", "good", "morning", "afternoon", "idk"})
NAME_STOPWORDS = frozenset({"Healthcare", "Claim", "Dental", "Auto", "Hello", "Thanks", "Thank", "The", "Not", "Calling", "Here", "Just", "So", "Really", "Very", "Sorry", "Fine", "Ok",
                            "Okay", "Yes", "No", "Hi", "Hello", "SSN", "DOB", "I", "My", "Your", "Policy", "SYSTEM"})
CORRECTION_RE = re.compile(r"\b(actually|i meant|correction|sorry,? (?:it'?s|my)|not .{1,30}, it'?s|wait)\b", re.I)
REFUSAL_RE = re.compile(r"(not (?:going to |gonna )?(?:give|giving|share|sharing|provide|providing)|"
                        r"won'?t (?:give|share|provide)|rather not|refuse|don'?t want to (?:give|share)|"
                        r"none of your business|not comfortable|forgot|forgotten|don'?t remember|do not remember|"
                        r"can'?t remember|don'?t know (?:my|it))", re.I)
REFUSE_ALL_RE = re.compile(r"(any (?:personal |of my )?(?:info|information|details)|anything personal)", re.I)
FIELD_WORDS = {
    "id_last4": re.compile(r"(ssn|social|national id|\bid\b|last four|last 4)", re.I),
    "dob": re.compile(r"(dob|date of birth|birthday|birth date)", re.I),
    "phone": re.compile(r"(phone|cell|mobile)", re.I),
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
YES_RE = re.compile(r"^\s*(yes|yeah|yep|sure|please do|please send|send it|go ahead|absolutely|"
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
THIRD_PARTY_RE = re.compile(r"(\bi'?m\s+(?:\w+\s+){1,3}?\w+'s\s+(?:husband|wife|son|daughter|mother|father|partner|"
                            r"brother|sister|friend|caregiver|spouse)\b|on behalf of|(?:calling (?:for|about)|for) my (?:mother|mom|father|dad|wife|husband|"
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
SUBJECT_RE = re.compile(r"(?i:on behalf of|calling for|calling about|for)\s+(?i:my\s+\w+[,]?\s+)?"
                        r"([A-Z][a-zA-Z'-]+\s+[A-Z][a-zA-Z'-]+)")
SELF_RELATION_RE = re.compile(r"\bi'?m (?:her|his|their) (\w+)|\bi'?m\s+(?:\w+\s+){1,3}?\w+'s\s+(\w+)", re.I)
SUBJECT_RELATION_RE = re.compile(r"\bmy (mother|mom|mum|father|dad|parent|wife|husband|spouse|son|daughter)\b", re.I)
SUBJECT_NAME_RE = re.compile(r"\b(?i:her|his|their) name is ([A-Z][a-zA-Z'-]+\s+[A-Z][a-zA-Z'-]+)")
REPEAT_RE = re.compile(r"^\W*(?:sorry[,.]?\s*|um+[,.]?\s*)?(?:(?:can|could) you |please )?(?:repeat that|say that "
                       r"again|come again|pardon(?: me)?)\b|^\W*(?:sorry[,.]?\s*)?(?:i )?didn'?t (?:quite )?catch that",
                       re.I)
START_OVER_RE = re.compile(r"^\W*(?:actually[,.]?\s*|ok(?:ay)?[,.]?\s*|so[,.]?\s*)?(?:(?:let'?s|can we|could we|"
                           r"i(?:'d)? (?:want|like) to|please)\s+)?(?:start (?:over|again|fresh)|begin again|restart)\b",
                           re.I)
SKIP_RE = re.compile(r"^\W*(?:(?:can|could) we |let'?s |please |i'?d like to )?(?:skip (?:this|that|it)(?: one| "
                     r"question)?|next question|pass on (?:this|that))\b", re.I)
CRISIS_RE = re.compile(r"(kill(?:ing)? myself|end it all|end my life|suicid|(?:don'?t|no) see (?:the|any) point in "
                       r"living|no point (?:in )?living|want to die|take my (?:own )?life|hurt(?:ing)? myself|"
                       r"can'?t go on|better off dead)", re.I)
THREAT_RE = re.compile(r"(make you (?:all )?pay|come (?:down )?to your office|i'?ll (?:hurt|find|get) you|you'?ll regret|"
                       r"i know where you|watch your back|burn (?:it|the place) down)", re.I)
READBACK_RE = re.compile(r"(read (?:me )?back|what(?:'?s| is) my (?:full )?(?:ssn|social|phone(?: number)?|email|date of "
                         r"birth|dob|address)|what (?:date of birth|dob|phone(?: number)?|email(?: address)?|ssn|social) "
                         r"do you have|full (?:ssn|social|phone number)|tell me my (?:ssn|social|dob|date of birth|phone))",
                         re.I)
POSSESSIVE_REL_RE = re.compile(r"\bi'?m\s+(?:[A-Z][a-zA-Z'-]+\s+){1,3}?[A-Z][a-zA-Z-]*'s\s+(husband|wife|son|daughter|mother|"
                               r"father|partner|brother|sister|friend|caregiver|spouse)\b")
SPELLED_RE = re.compile(r"\b([A-Za-z](?:[-\s][A-Za-z]){2,})\b")
TYPE_SUPPORT = {
    "auto": re.compile(r"\b(auto|car|vehicle|truck|accident|crash|collision|repair|bumper|windshield|motor)", re.I),
    "healthcare": re.compile(r"\b(health|medical|doctor|hospital|clinic|surg|mri|scan|x-?ray|lab|patholog|prescri|"
                             r"therap|er\b|emergency room|physician|treatment)", re.I),
    "dental": re.compile(r"\b(dental|dentist|tooth|teeth|orthodont|cavity|root canal|crown|filling)", re.I),
}
