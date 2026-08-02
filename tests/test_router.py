from skillcell.router import default_router


def test_refactor_goal_routes_to_refactor_surgeon():
    assert default_router("refactor the parser module") == "refactor-surgeon"


def test_audit_goal_routes_to_code_audit():
    assert default_router("audit this codebase for dead code") == "code-audit"


def test_existing_rules_take_precedence():
    # firmware rule exists and matches; order of rules means firmware wins
    assert default_router("audit router firmware image") == "firmware-pentest"


def test_generalist_fallback_unchanged():
    assert default_router("write a haiku") == "generalist"


def test_routing_is_deterministic():
    # same goal returns same route, called twice
    result_1 = default_router("refactor and audit the loop")
    result_2 = default_router("refactor and audit the loop")
    assert result_1 == result_2
