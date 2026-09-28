from claims_agent.audit import AuditEvent


def test_pii_captured_event_never_contains_raw_value():
    ev = AuditEvent.pii_captured(field="id_last4", value="4472", turn=1)
    assert "4472" not in ev.model_dump_json() and ev.detail["masked"] == "**72"


def test_tool_event_shape():
    ev = AuditEvent.tool(kind="tool_called", tool="verify_identity", phase="VERIFY_ID", consent="NOT_OFFERED", turn=2)
    assert ev.detail == {"tool": "verify_identity", "phase": "VERIFY_ID", "consent": "NOT_OFFERED"}
