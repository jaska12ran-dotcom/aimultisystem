"""Complete import and runtime test for all CodeTwin modules."""
import sys, os
sys.path.insert(0, 'backend')
os.environ.setdefault('DATABASE_URL', 'sqlite+aiosqlite:///./codetwin.db')

errors = []

def try_import(name, code):
    try:
        exec(code, {})
        print(f'  OK  {name}')
    except Exception as e:
        msg = str(e)
        print(f'  ERR {name}: {type(e).__name__}: {msg[:150]}')
        errors.append((name, msg))

print('\n=== Schemas ===')
try_import('schemas.agent',        'from app.schemas.agent import *')
try_import('schemas.impact',       'from app.schemas.impact import *')
try_import('schemas.git_history',  'from app.schemas.git_history import *')
try_import('schemas.technical_debt','from app.schemas.technical_debt import *')
try_import('schemas.test_intel',   'from app.schemas.test_intelligence import *')
try_import('schemas.dev_know',     'from app.schemas.developer_knowledge import *')
try_import('schemas.repository',   'from app.schemas.repository import *')
try_import('schemas.whatif',       'from app.schemas.whatif import *')

print('\n=== Models ===')
try_import('models.repository',  'from app.models.repository import Repository, RepositoryFile, CodeSymbol, GitCommit')
try_import('models.artifact',    'from app.models.agent_artifact import GeneratedDoc, GeneratedTestSuite, AgentChatMessage')

print('\n=== Services ===')
try_import('rag.service',          'from app.services.rag.service import EmbeddingService, VectorSearchService, RepositoryIndexer, RepositoryRetriever')
try_import('change_impact',        'from app.services.change_impact import ChangeImpactService')
try_import('git_history',          'from app.services.git_history import GitHistoryService')
try_import('technical_debt',       'from app.services.technical_debt import TechnicalDebtService')
try_import('developer_knowledge',  'from app.services.developer_knowledge import DeveloperKnowledgeService')
try_import('production_readiness', 'from app.services.production_readiness import ProductionReadinessService')
try_import('pr_description',       'from app.services.pr_description import PRDescriptionService')
try_import('breaking_change',      'from app.services.breaking_change import BreakingChangeService')
try_import('sensitive_data_flow',  'from app.services.sensitive_data_flow import SensitiveDataFlowService')
try_import('test_intelligence',    'from app.services.test_intelligence import TestIntelligenceService')

print('\n=== Agents ===')
try_import('doc_agent',            'from agents.documentation_agent import DocumentationAgent, DocumentationDriftDetector')
try_import('security_agent',       'from agents.security_agent import SecurityAgent')
try_import('test_pipeline',        'from agents.test_pipeline import TestGenerationPipeline, MutationTestingAgent')
try_import('qa_agent',             'from agents.qa_agent import QAAgent')
try_import('test_agent',           'from agents.test_agent import TestAgent')
try_import('self_healing',         'from agents.self_healing_agent import SelfHealingAgent, HealingDiagnosis')
try_import('bug_detective',        'from agents.bug_detective import BugDetectiveAgent')
try_import('orchestrator',         'from agents.orchestrator import OrchestratorAgent, _classify_intent')

print('\n=== API Endpoints ===')
try_import('endpoints.health',     'import app.api.v1.endpoints.health')
try_import('endpoints.repos',      'import app.api.v1.endpoints.repositories')
try_import('endpoints.twin',       'import app.api.v1.endpoints.twin')
try_import('endpoints.agents',     'import app.api.v1.endpoints.agents')
try_import('router',               'import app.api.v1.router')
try_import('main_app',             'import app.main')

print('\n=== Training Scripts ===')
try_import('prepare_csn',          'import training.prepare_codesearchnet')
try_import('train_embedding',      'import training.train_embedding')
try_import('evaluate_embedding',   'import training.evaluate_embedding')
try_import('data_utils',           'import training.data_utils')

print('\n' + '='*50)
if errors:
    print(f'FAILED: {len(errors)} error(s):')
    for n, e in errors:
        print(f'  - {n}: {e[:200]}')
    sys.exit(1)
else:
    print(f'ALL IMPORTS PASSED ({sum(1 for _ in range(1))} checks)')
    sys.exit(0)
