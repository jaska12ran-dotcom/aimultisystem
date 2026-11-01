"""Full logic test suite for all CodeTwin modules."""
import sys, os, math
sys.path.insert(0, 'backend')
os.environ.setdefault('DATABASE_URL', 'sqlite+aiosqlite:///./codetwin.db')

errors = []

def check(label, fn):
    try:
        fn()
        print(f'  PASS  {label}')
    except Exception as e:
        print(f'  FAIL  {label}: {type(e).__name__}: {e}')
        errors.append(label)

# ── 1. Self-healing agent ─────────────────────────────────────────────────────
from agents.self_healing_agent import HealingDiagnosis, SelfHealingAgent, _RE_IMPORT_ERR, _RE_IMPORT_ERR_UNQUOTED

def t_healing_import():
    d = HealingDiagnosis("ModuleNotFoundError: No module named myapp")
    assert d.has_failures, f"has_failures=False, import_errors={d.import_errors}"
    assert d.import_errors, "no import_errors captured"
    assert "import_error" in d.categories

def t_healing_assertion():
    d = HealingDiagnosis("AssertionError: assert x == 42")
    assert d.has_failures
    assert "assertion_error" in d.categories

def t_healing_quoted():
    d = HealingDiagnosis("ModuleNotFoundError: No module named 'myapp.utils'")
    assert d.has_failures
    assert any("myapp" in e for e in d.import_errors), d.import_errors

def t_healing_name_error():
    d = HealingDiagnosis("NameError: name 'foo_func' is not defined")
    assert d.has_failures
    assert "foo_func" in d.name_errors

check("HealingDiagnosis: unquoted ModuleNotFoundError", t_healing_import)
check("HealingDiagnosis: AssertionError detection", t_healing_assertion)
check("HealingDiagnosis: quoted module name", t_healing_quoted)
check("HealingDiagnosis: NameError detection", t_healing_name_error)

# ── 2. Bug detective ──────────────────────────────────────────────────────────
from agents.bug_detective import (
    _extract_stack_files, _extract_error_types, BugDetectiveAgent,
    _normalize, _INTENT_KEYWORDS  # re-using normalize
)

def t_stack_python():
    files = _extract_stack_files('File "app/views.py", line 45, in handle_request')
    assert files and files[0][0] == 'app/views.py' and files[0][1] == 45

def t_stack_js():
    files = _extract_stack_files('at Object.login (src/auth.js:23:5)')
    assert files and 'src/auth.js' in files[0][0]

def t_bug_agent_instantiates():
    agent = BugDetectiveAgent()
    terms = agent._extract_search_terms("TypeError in login function at line 42")
    assert "TypeError" in terms or "login" in terms

check("BugDetective: Python stack trace parsing", t_stack_python)
check("BugDetective: JS stack trace parsing", t_stack_js)
check("BugDetective: search term extraction", t_bug_agent_instantiates)

# ── 3. Orchestrator ───────────────────────────────────────────────────────────
from agents.orchestrator import _classify_intent, OrchestratorAgent

def t_intents():
    cases = {
        "my app crashes with TypeError": "bug",
        "production readiness score": "readiness",
        "fix my failing test": "heal_test",
        "generate pr description for my branch": "pr",
        "security vulnerability found": "security",
        "what is the change impact": "impact",
        "why does this code exist": "history",
        "show me technical debt": "debt",
        "I am new to the codebase": "onboarding",
        "detect breaking changes": "breaking",
        "sensitive data flow password": "sensitive",
        "generate docs for my module": "docs",
    }
    for query, expected in cases.items():
        got = _classify_intent(query)
        assert got == expected, f"query={query!r} expected={expected} got={got}"

check("Orchestrator: intent classification (12 intents)", t_intents)

# ── 4. Breaking change service ────────────────────────────────────────────────
from app.services.breaking_change import (
    _parse_params, _has_default, _extract_return_type, BreakingChangeService
)

def t_parse_params_basic():
    p = _parse_params("def foo(self, a: int, b: str)")
    assert "a" in p and "b" in p and "self" not in p

def t_parse_params_defaults():
    p = _parse_params("def foo(a, b=None, *args, **kwargs)")
    assert "a" in p and "b" in p
    assert "args" not in p and "kwargs" not in p

def t_has_default():
    assert _has_default("def foo(b: str = 'x')", "b")
    assert not _has_default("def foo(a: int)", "a")

def t_return_type():
    assert _extract_return_type("def foo() -> bool") == "bool"
    assert _extract_return_type("def foo() -> Optional[str]") == "Optional[str]"
    assert _extract_return_type("def foo()") is None

check("BreakingChange: parameter parsing (basic)", t_parse_params_basic)
check("BreakingChange: parameter parsing (defaults/varargs)", t_parse_params_defaults)
check("BreakingChange: default detection", t_has_default)
check("BreakingChange: return type extraction", t_return_type)

# ── 5. Sensitive data flow ────────────────────────────────────────────────────
from app.services.sensitive_data_flow import (
    _is_source, _is_sink, _term_in, SENSITIVE_SOURCES, SENSITIVE_SINKS, SensitiveDataFlowService
)
from types import SimpleNamespace

def t_source_detection():
    assert _is_source(SimpleNamespace(name="get_password", qualified_name="auth.get_password", docstring=None, parameters=[]))
    assert _is_source(SimpleNamespace(name="process", qualified_name="handler", docstring=None,
                                       parameters=[{"name": "token"}, {"name": "user_id"}]))
    assert not _is_source(SimpleNamespace(name="render_page", qualified_name="views.render", docstring=None, parameters=[]))

def t_sink_detection():
    assert _is_sink(SimpleNamespace(name="log_error", qualified_name="logger.log_error", docstring=None, parameters=[]))
    assert _is_sink(SimpleNamespace(name="send_response", qualified_name="http.send_response", docstring=None, parameters=[]))
    assert not _is_sink(SimpleNamespace(name="calculate_sum", qualified_name="math.calculate_sum", docstring=None, parameters=[]))

check("SensitiveDataFlow: source detection", t_source_detection)
check("SensitiveDataFlow: sink detection", t_sink_detection)

# ── 6. Production readiness ───────────────────────────────────────────────────
from app.services.production_readiness import _letter, ProductionReadinessService

def t_letter_grades():
    assert _letter(90) == "A"
    assert _letter(85) == "A"
    assert _letter(84) == "B"
    assert _letter(70) == "B"
    assert _letter(69) == "C"
    assert _letter(55) == "C"
    assert _letter(54) == "D"
    assert _letter(40) == "D"
    assert _letter(39) == "F"
    assert _letter(0) == "F"

check("ProductionReadiness: letter grade boundaries", t_letter_grades)

# ── 7. EmbeddingService ───────────────────────────────────────────────────────
from app.services.rag.service import EmbeddingService, _get_embedder, _HashEmbedder

def t_embedding_single():
    emb = EmbeddingService.generate_embedding("def authenticate_user(token: str) -> bool:")
    assert len(emb) == 384
    norm = math.sqrt(sum(v * v for v in emb))
    assert abs(norm - 1.0) < 1e-5, f"not unit-norm: {norm}"

def t_embedding_batch():
    texts = ["login", "password hash", "def compute_checksum(data):"]
    batch = EmbeddingService.generate_embeddings_batch(texts)
    assert len(batch) == 3
    for emb in batch:
        assert len(emb) == 384
        norm = math.sqrt(sum(v * v for v in emb))
        assert abs(norm - 1.0) < 1e-5

def t_cosine_similarity():
    a = EmbeddingService.generate_embedding("authenticate user with token")
    b = EmbeddingService.generate_embedding("authenticate user with token")
    c = EmbeddingService.generate_embedding("completely unrelated xyz 12345")
    same = EmbeddingService.cosine_similarity(a, b)
    diff = EmbeddingService.cosine_similarity(a, c)
    assert abs(same - 1.0) < 1e-5, f"identical texts should score 1.0, got {same}"
    assert diff < same, f"unrelated text should score lower, diff={diff}, same={same}"

def t_embedding_empty():
    emb = EmbeddingService.generate_embedding("")
    assert len(emb) == 384
    assert all(v == 0.0 for v in emb), "empty text should give zero vector"

check("EmbeddingService: single embedding (unit-norm)", t_embedding_single)
check("EmbeddingService: batch embedding", t_embedding_batch)
check("EmbeddingService: cosine similarity ordering", t_cosine_similarity)
check("EmbeddingService: empty text gives zero vector", t_embedding_empty)

# ── 8. Schemas (Pydantic) ─────────────────────────────────────────────────────
from app.schemas.agent import (
    SelfHealRequest, SelfHealResponse,
    BugInvestigateRequest, BugInvestigationResult,
    ProductionReadinessResult, ReadinessDimensionResponse,
    PRDescribeRequest, PRDescribeResponse,
    BreakingChangeRequest, BreakingChangeResult,
    SensitiveDataFlowResult,
    OrchestratorRequest, OrchestratorResult, OrchestratorStepResponse,
    DocGenerateRequest, ChatRequest, SecurityAnalysisResponse,
)

def t_schemas():
    r = SelfHealRequest(test_code="def test(): pass", execution_output="AssertionError: assert x == 1")
    assert r.framework == "pytest" and r.max_passes == 3

    b = BugInvestigateRequest(bug_description="NullPointerException in UserService")
    assert not b.generate_mre and b.stack_trace is None

    o = OrchestratorRequest(query="what is the production readiness score")
    assert o.changed_files == []

    p = PRDescribeRequest(changed_files=["src/auth.py", "src/models.py"])
    assert p.diff is None

    bc = BreakingChangeRequest(diff="- def login(user):\n+ def login(user, token=None):")
    assert bc.previous_snapshot is None

    d = ReadinessDimensionResponse(name="security", score=72.5, weight=0.35, grade="B")
    assert d.findings == []

check("Schemas: Pydantic model instantiation and defaults", t_schemas)

# ── 9. Technical debt dead-code (non-placeholder) ─────────────────────────────
from app.services.technical_debt import TechnicalDebtService

def t_dead_code_empty():
    svc = TechnicalDebtService.__new__(TechnicalDebtService)
    svc._relationships_cache = []
    result = svc._dead_code_signals([], [])
    assert result == [], f"expected [] with no symbols, got {result}"

def t_dead_code_unreferenced():
    from app.models.repository import CodeSymbol, RepositoryFile
    svc = TechnicalDebtService.__new__(TechnicalDebtService)
    sym = SimpleNamespace(
        id="s1", name="orphan_func", qualified_name="mod.orphan_func",
        symbol_type="function", is_exported=True, start_line=10,
        file_id="f1", complexity_score=1
    )
    f = SimpleNamespace(id="f1", relative_path="mod.py", is_test=False, is_config=False)
    svc._relationships_cache = []   # no relationships → sym is unreferenced
    findings = svc._dead_code_signals([sym], [f])
    assert len(findings) == 1
    assert findings[0].category == "potential_dead_code"
    assert findings[0].measured == True

check("TechnicalDebt: dead code with empty relationships", t_dead_code_empty)
check("TechnicalDebt: unreferenced symbol flagged", t_dead_code_unreferenced)

# ── 10. PR Description service ────────────────────────────────────────────────
from app.services.pr_description import PRDescriptionService

def t_pr_title_branch():
    svc = PRDescriptionService.__new__(PRDescriptionService)
    svc.llm = None
    title = asyncio_run(svc._suggest_title([], [], None, "feature/add-user-auth"))
    assert "add" in title.lower() or "feature" in title.lower() or "user" in title.lower()

def asyncio_run(coro):
    import asyncio
    return asyncio.get_event_loop().run_until_complete(coro)

check("PRDescription: title from branch name", t_pr_title_branch)

# ─────────────────────────────────────────────────────────────────────────────
print()
print("=" * 55)
if errors:
    print(f"FAILED: {len(errors)} test(s):")
    for e in errors:
        print(f"  - {e}")
    sys.exit(1)
else:
    print(f"ALL TESTS PASSED")
    sys.exit(0)
