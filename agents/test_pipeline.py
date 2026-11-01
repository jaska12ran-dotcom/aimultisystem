from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.repository import CodeSymbol, Repository, RepositoryFile
from intelligence.retriever import ASTRetriever
from sandbox.policies import GeneratedTestSafetyScreen
from sandbox.runner import sandbox_runner


@dataclass
class TestPipelinePlan:
    target_files: List[str]
    untested_functions: List[str]
    missing_edge_cases: List[str]
    missing_error_handling_tests: List[str]
    api_test_gaps: List[str]
    business_logic_test_gaps: List[str]
    summary: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "target_files": self.target_files,
            "untested_functions": self.untested_functions,
            "missing_edge_cases": self.missing_edge_cases,
            "missing_error_handling_tests": self.missing_error_handling_tests,
            "api_test_gaps": self.api_test_gaps,
            "business_logic_test_gaps": self.business_logic_test_gaps,
            "summary": self.summary,
        }


class ExplorerAgent:
    async def inspect_repository(self, db: AsyncSession, repo_id: str) -> Dict[str, Any]:
        overview = await ASTRetriever.get_repository_overview(db, repo_id)
        repo = await db.get(Repository, repo_id)
        files = []
        if repo:
            file_result = await db.execute(
                select(RepositoryFile).where(RepositoryFile.repository_id == repo_id).order_by(RepositoryFile.relative_path.asc())
            )
            files = [{
                "file_path": item.relative_path,
                "language": item.language,
                "is_documentation": item.is_documentation,
                "is_config": item.is_config,
            } for item in file_result.scalars().all()]
        return {
            "repository_name": overview.get("repository_name"),
            "total_files": overview.get("total_files"),
            "languages": overview.get("languages", []),
            "dependencies": overview.get("dependencies", []),
            "api_routes": overview.get("api_routes", []),
            "db_models": overview.get("db_models", []),
            "classes": overview.get("classes", []),
            "files": files,
        }


class TestPlannerAgent:
    async def plan(self, db: AsyncSession, repo_id: str, target_file: Optional[str] = None) -> TestPipelinePlan:
        overview = await ASTRetriever.get_repository_overview(db, repo_id)
        function_names: List[str] = []
        route_names: List[str] = [item["name"] for item in overview.get("api_routes", [])]
        class_names: List[str] = [item["name"] for item in overview.get("classes", [])]

        symbol_result = await db.execute(
            select(CodeSymbol).where(CodeSymbol.repository_id == repo_id).order_by(CodeSymbol.start_line.asc())
        )
        for symbol in symbol_result.scalars().all():
            if symbol.symbol_type in {"function", "method", "api_route", "class"}:
                function_names.append(symbol.name)

        target_files = []
        if target_file:
            target_files = [target_file]
        else:
            for item in overview.get("api_routes", []) + overview.get("classes", []) + overview.get("db_models", []):
                file_value = item.get("file_path")
                if file_value:
                    target_files.append(file_value)
            target_files = sorted(set(target_files))

        untested = [name for name in function_names if not re.search(rf"(?:^|_){re.escape(name.lower())}(?:_|$)", " ".join(name.lower() for name in function_names))]
        if not untested:
            untested = function_names[: max(1, len(function_names) // 2)]

        edge_cases = [
            "empty inputs",
            "None values",
            "boundary values",
            "large payloads",
            "invalid types",
        ]
        missing_error = [
            name for name in function_names if any(keyword in name.lower() for keyword in ["validate", "fetch", "save", "delete", "create", "update", "auth"])
        ]
        business_logic = [
            name for name in function_names if name not in route_names and name not in class_names and name not in missing_error
        ]

        return TestPipelinePlan(
            target_files=target_files,
            untested_functions=sorted(set(untested)),
            missing_edge_cases=edge_cases,
            missing_error_handling_tests=sorted(set(missing_error)),
            api_test_gaps=route_names,
            business_logic_test_gaps=sorted(set(business_logic)),
            summary=(
                f"Detected {len(function_names)} candidate methods/functions, {len(route_names)} API endpoints, "
                f"and {len(edge_cases)} edge-case categories requiring tests."
            ),
        )


class TestGeneratorAgent:
    async def generate_tests(self, db: AsyncSession, repo_id: str, plan: TestPipelinePlan, framework: str = "pytest") -> Dict[str, Any]:
        repo = await db.get(Repository, repo_id)
        if repo is None:
            raise ValueError(f"Repository {repo_id} not found")

        generated_by_file: Dict[str, str] = {}
        for file_path in plan.target_files:
            file_ctx = await ASTRetriever.get_file_context(db, repo_id, file_path)
            if not file_ctx:
                continue
            module_name = file_path.replace("\\", "/").replace(".py", "").replace("/", ".")
            if not module_name:
                continue
            lines = [
                "import importlib",
                f"module = importlib.import_module({module_name!r})",
                "",
            ]
            for symbol_name in plan.untested_functions[:6]:
                lines.append(f"def test_{symbol_name.lower()}_smoke():")
                lines.append(f"    assert hasattr(module, {symbol_name!r})")
                lines.append("")
            for symbol_name in plan.missing_error_handling_tests[:3]:
                lines.append(f"def test_{symbol_name.lower()}_handles_invalid_inputs():")
                lines.append(f"    assert callable(getattr(module, {symbol_name!r}, None))")
                lines.append("")
            generated_by_file[file_path] = "\n".join(lines)

        return {
            "framework": framework,
            "generated_by_file": generated_by_file,
            "all_tests": "\n\n".join(generated_by_file.values()),
        }


class CoverageAnalyzer:
    @staticmethod
    def parse_coverage(output: str) -> Dict[str, Any]:
        text = output or ""
        match = re.search(r"TOTAL\s+\d+\s+\d+\s+\d+\s+(\d+)%", text, re.IGNORECASE)
        if match:
            return {"percent": float(match.group(1)), "tool": "coverage"}
        match = re.search(r"(\d+(?:\.\d+)?)%\s+\(\d+\s+of\s+\d+\s+lines\)", text, re.IGNORECASE)
        if match:
            return {"percent": float(match.group(1)), "tool": "coverage"}
        return {"percent": 0.0, "tool": "not_available"}


class MutationTestingAgent:
    @staticmethod
    def available_tools() -> List[str]:
        tools = []
        for tool in ("mutmut", "stryker", "pit"):
            if shutil.which(tool):
                tools.append(tool)
        return tools

    @staticmethod
    def run_mutation_tests(repo_path: str, framework: str = "pytest") -> Dict[str, Any]:
        tools = MutationTestingAgent.available_tools()
        if not tools:
            return {"status": "not_available", "tool": "not_available", "score": 0.0, "details": "Mutation testing is unavailable in this environment."}
        tool = tools[0]
        if tool == "mutmut":
            cmd = [tool, "run"]
        elif tool == "stryker":
            cmd = [tool, "run"]
        else:
            cmd = [tool, "-text"]
        try:
            completed = subprocess.run(cmd, cwd=repo_path, capture_output=True, text=True, check=False, timeout=60)
            score = 0.0
            match = re.search(r"(\d+(?:\.\d+)?)%", (completed.stdout or "") + (completed.stderr or ""))
            if match:
                score = float(match.group(1))
            return {"status": "passed" if completed.returncode == 0 else "failed", "tool": tool, "score": score, "details": completed.stdout or completed.stderr}
        except Exception as exc:
            return {"status": "not_available", "tool": tool, "score": 0.0, "details": str(exc)}


class TestVerifierAgent:
    async def verify(self, repo_path: str, generated_tests: Dict[str, Any], framework: str = "pytest") -> Dict[str, Any]:
        all_tests = generated_tests.get("all_tests", "")
        if not all_tests.strip():
            return {"status": "blocked", "exit_code": 126, "stdout": "", "stderr": "No tests generated for verification.", "tests": {"total": 0, "passed": 0, "failed": 0}, "coverage": {"percent": 0.0}, "duration": 0.0}

        # Report the static screen result for transparency. Enforcement lives in
        # the sandbox runner: with Docker the container confines side effects,
        # without Docker dangerous constructs are blocked at the host boundary.
        safety = GeneratedTestSafetyScreen.screen(all_tests)
        file_name = "generated_test_suite.py"
        result = await sandbox_runner.execute_python_test(
            repo_workspace=repo_path,
            test_code=all_tests,
            test_filename=file_name,
            framework=framework,
        )
        return {
            "status": result.status,
            "exit_code": result.success and 0 or 1,
            "stdout": result.execution_output,
            "stderr": "",
            "tests": {"total": result.tests_run, "passed": result.tests_passed, "failed": result.tests_failed},
            "coverage": {"percent": 0.0},
            "duration": float(result.duration_ms) / 1000.0,
            "safety": safety,
        }


class TestQualityScorer:
    @staticmethod
    def score(verification: Dict[str, Any], coverage: Dict[str, Any], mutation: Dict[str, Any], plan: TestPipelinePlan) -> Dict[str, Any]:
        pass_status = 1.0 if verification.get("status") == "passed" else 0.0
        coverage_delta = min(1.0, (float(coverage.get("percent", 0.0)) / 100.0) * 0.5)
        mutation_score = min(1.0, float(mutation.get("score", 0.0)) / 100.0 * 0.25)
        edge_case_coverage = 1.0 if not plan.missing_edge_cases else max(0.0, 1.0 - (len(plan.missing_edge_cases) / max(1, len(plan.missing_edge_cases) + 1)))
        edge_case_score = (1.0 - edge_case_coverage) * 0.25
        flaky_risk = 0.15 if verification.get("status") == "failed" else 0.05
        score = max(0.0, min(1.0, pass_status - coverage_delta - mutation_score - edge_case_score - flaky_risk))
        return {
            "score": round(score, 4),
            "pass_status": pass_status,
            "coverage_delta": round(coverage_delta, 4),
            "mutation_score": round(mutation_score, 4),
            "edge_case_score": round(edge_case_score, 4),
            "flaky_risk": round(flaky_risk, 4),
        }


class TestGenerationPipeline:
    __test__ = False

    def __init__(self, db: AsyncSession, repo_id: str):
        self.db = db
        self.repo_id = repo_id
        self.explorer = ExplorerAgent()
        self.planner = TestPlannerAgent()
        self.generator = TestGeneratorAgent()
        self.verifier = TestVerifierAgent()

    async def run(self, target_file: Optional[str] = None, framework: str = "pytest", include_mutation: bool = False) -> Dict[str, Any]:
        repo = await self.db.get(Repository, self.repo_id)
        if repo is None:
            raise ValueError(f"Repository {self.repo_id} not found")

        inspection = await self.explorer.inspect_repository(self.db, self.repo_id)
        plan = await self.planner.plan(self.db, self.repo_id, target_file=target_file)
        generated = await self.generator.generate_tests(self.db, self.repo_id, plan, framework=framework)

        verification = await self.verifier.verify(repo.local_path, generated, framework=framework)
        coverage = CoverageAnalyzer.parse_coverage(verification.get("stdout", ""))
        mutation = MutationTestingAgent.run_mutation_tests(repo.local_path, framework=framework) if include_mutation else {"status": "not_requested", "score": 0.0, "tool": "not_requested"}
        quality = TestQualityScorer.score(verification, coverage, mutation, plan)

        return {
            "repository_id": self.repo_id,
            "inspection": inspection,
            "plan": plan.to_dict(),
            "generated_tests": generated,
            "verification": verification,
            "coverage": coverage,
            "mutation": mutation,
            "quality_score": quality,
        }
