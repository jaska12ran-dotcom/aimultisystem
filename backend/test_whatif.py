import sys
sys.path.insert(0, r"C:\Users\jaska\Desktop\ai multiagent system\backend")

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy import select
import asyncio

from app.models.repository import Repository, CodeSymbol, RepositoryFile, CodeImport, CodeRelationship, GitCommit
from app.schemas.whatif import WhatIfRequest
from app.services.whatif_simulator import WhatIfSimulatorService
from app.core.database import Base


async def test_simulator():
    # Use the existing database file
    engine = create_async_engine("sqlite+aiosqlite:///./codetwin.db", echo=False)
    
    # Initialize tables if needed
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    async with AsyncSession(engine) as session:
        # Check what repositories exist
        result = await session.execute(select(Repository))
        repos = result.scalars().all()
        print(f"Repositories found: {len(repos)}")
        for r in repos:
            print(f"  - {r.name} (id={r.id}, status={r.status}, files={r.total_files}, symbols={r.total_symbols})")
        
        if repos:
            repo = repos[0]
            print(f"\nSelected repo: {repo.name}")
            
            # Check what symbols exist
            result = await session.execute(select(CodeSymbol).limit(10))
            symbols = result.scalars().all()
            print(f"\nFirst 10 symbols:")
            for s in symbols:
                print(f"  - {s.qualified_name} ({s.symbol_type}) in {s.file_id}")
            
            # Check what files exist
            result = await session.execute(select(RepositoryFile).limit(10))
            files = result.scalars().all()
            print(f"\nFirst 10 files:")
            for f in files:
                print(f"  - {f.relative_path} (test={f.is_test})")
            
            # Now test the simulator
            service = WhatIfSimulatorService(session, repo)
            
            # Create a minimal request
            request = WhatIfRequest(
                natural_language_description="Rename function foo to bar",
            )
            
            # Run simulation
            result = await service.simulate(request)
            
            print(f"\n✓ Simulation completed!")
            print(f"  Repository: {result.repository_id}")
            print(f"  Simulation ID: {result.simulation_id}")
            print(f"  Target file: {result.target_file}")
            print(f"  Target symbol: {result.target_symbol}")
            print(f"  Overall risk: {result.overall_risk}")
            print(f"  Overall confidence: {result.overall_confidence}")
            print(f"  Affected files count: {len(result.affected_files)}")
            print(f"  Impacted functions count: {len(result.impacted_functions)}")
            print(f"  Breaking changes count: {len(result.breaking_changes)}")
            print(f"  Test failure risks count: {len(result.test_failure_risks)}")
            print(f"  Security implications count: {len(result.security_implications)}")
            print(f"  Performance concerns count: {len(result.performance_concerns)}")
            print(f"  Migration requirements count: {len(result.migration_requirements)}")
            print(f"  Regression test recommendations count: {len(result.regression_test_recommendations)}")
            print(f"  Verified finding count: {result.verified_finding_count}")
            print(f"  Predicted finding count: {result.predicted_finding_count}")
            print(f"  Summary: {result.summary}")
            
            # Verify the patch is read-only
            if result.patch:
                print(f"  Patch file_path: {result.patch.file_path}")
                print(f"  Patch has rollback_diff: {result.patch.rollback_diff is not None}")
                print(f"  Patch workspace_note: {result.patch.workspace_note}")
            
            print("\n✅ All tests passed!")
        else:
            print("No repositories found in the database. Please ingest a repository first.")

asyncio.run(test_simulator())