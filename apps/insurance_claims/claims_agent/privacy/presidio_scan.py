"""Optional Presidio-based PII scanner (MIT). Lazily built once; absent libraries/models => feature off."""
import logging
from functools import lru_cache

log = logging.getLogger(__name__)
ENTITIES = ["PHONE_NUMBER", "EMAIL_ADDRESS", "US_SSN", "CLAIM_ID", "POLICY_NUMBER"]


class PresidioScanner:
    def __init__(self, analyzer) -> None:
        self._analyzer = analyzer

    @staticmethod
    def try_create() -> "PresidioScanner | None":
        return _build()

    def scan(self, text: str) -> list[tuple[str, str]]:
        hits = self._analyzer.analyze(text=text, language="en", entities=ENTITIES, score_threshold=0.35)
        return [(h.entity_type, text[h.start:h.end]) for h in hits]


@lru_cache(maxsize=1)
def _build() -> PresidioScanner | None:
    try:
        from presidio_analyzer import AnalyzerEngine, Pattern, PatternRecognizer
        from presidio_analyzer.nlp_engine import NlpEngineProvider

        nlp = NlpEngineProvider(nlp_configuration={
            "nlp_engine_name": "spacy", "models": [{"lang_code": "en", "model_name": "en_core_web_sm"}]}).create_engine()
        analyzer = AnalyzerEngine(nlp_engine=nlp, supported_languages=["en"])
        analyzer.registry.add_recognizer(PatternRecognizer(
            supported_entity="CLAIM_ID", patterns=[Pattern("claim", r"\bCL[-\s]?\d{4,}\b", 0.8)], context=["claim"]))
        analyzer.registry.add_recognizer(PatternRecognizer(
            supported_entity="POLICY_NUMBER", patterns=[Pattern("policy", r"\bPOL[-\s]?\d{3,}\b", 0.8)],
            context=["policy"]))
        return PresidioScanner(analyzer)
    except Exception as exc:  # optional dependency: missing package or spaCy model disables the feature
        log.warning("Presidio scanner unavailable (%s); continuing with regex-only checks", type(exc).__name__)
        return None
