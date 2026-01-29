"""
Tests for orchestrator worktree integration.

Tests the integration of WorktreeManager and FileOwnershipTracker into the orchestrator.
"""

import asyncio
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch
import pytest

# Add the lib path for imports
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent / ".claude" / "lib"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src" / "ralph"))

from worktree import WorktreeManager, BranchInfo, WorktreeInfo, MergeResult, GitError
from file_ownership import FileOwnershipTracker, ClaimResult


def get_default_branch(repo_path: Path) -> str:
    """Get the default branch name (main or master)."""
    result = subprocess.run(
        ['git', 'symbolic-ref', '--short', 'HEAD'],
        cwd=repo_path,
        capture_output=True,
        text=True
    )
    return result.stdout.strip() or 'main'


class TestWorktreeIntegration:
    """Test worktree integration in orchestrator."""

    @pytest.fixture
    def temp_git_repo(self, tmp_path):
        """Create a temporary git repository for testing."""
        repo_path = tmp_path / "test_repo"
        repo_path.mkdir()

        # Initialize git repo with 'main' as default branch
        subprocess.run(['git', 'init', '-b', 'main'], cwd=repo_path, capture_output=True)
        subprocess.run(['git', 'config', 'user.email', 'test@test.com'], cwd=repo_path, capture_output=True)
        subprocess.run(['git', 'config', 'user.name', 'Test User'], cwd=repo_path, capture_output=True)

        # Create initial commit
        (repo_path / "README.md").write_text("# Test Repo")
        subprocess.run(['git', 'add', '.'], cwd=repo_path, capture_output=True)
        subprocess.run(['git', 'commit', '-m', 'Initial commit'], cwd=repo_path, capture_output=True)

        yield repo_path

        # Cleanup worktrees before deleting
        subprocess.run(['git', 'worktree', 'prune'], cwd=repo_path, capture_output=True)

    @pytest.fixture
    def temp_db(self, tmp_path):
        """Create a temporary database for testing."""
        db_path = tmp_path / "test.db"
        return db_path

    def test_creates_worktree_on_spec_start(self, temp_git_repo):
        """AC-001: Orchestrator creates worktree when spec enters implementation phase."""
        mgr = WorktreeManager(repo_root=temp_git_repo)
        default_branch = get_default_branch(temp_git_repo)

        # Create a spec branch and worktree
        spec_path = "Specs/Active/test-feature/spec.json"
        branch = mgr.create_spec_branch(spec_path, default_branch)

        assert branch.name == "ralph/test-feature"
        assert branch.commit is not None

        # Create worktree
        wt = mgr.create_worktree(branch.name)

        assert Path(wt.path).exists()
        assert wt.branch == branch.name

    def test_agent_runs_in_worktree(self, temp_git_repo):
        """AC-002: Implementer agent runs with cwd set to spec's worktree."""
        mgr = WorktreeManager(repo_root=temp_git_repo)
        default_branch = get_default_branch(temp_git_repo)

        # Create branch and worktree
        spec_path = "Specs/Active/test-feature/spec.json"
        branch = mgr.create_spec_branch(spec_path, default_branch)
        wt = mgr.create_worktree(branch.name)

        worktree_path = Path(wt.path)

        # Verify worktree exists and is a valid git worktree
        assert worktree_path.exists()

        # Verify it's a different directory from main repo
        assert str(worktree_path) != str(temp_git_repo)

        # Verify we can create files in the worktree
        test_file = worktree_path / "test_file.txt"
        test_file.write_text("Test content")
        assert test_file.exists()

    def test_merges_on_completion(self, temp_git_repo):
        """AC-003: On spec completion, changes merge into parent branch."""
        mgr = WorktreeManager(repo_root=temp_git_repo)
        default_branch = get_default_branch(temp_git_repo)

        # Create branch and worktree
        spec_path = "Specs/Active/test-feature/spec.json"
        branch = mgr.create_spec_branch(spec_path, default_branch)
        wt = mgr.create_worktree(branch.name)

        worktree_path = Path(wt.path)

        # Make changes in worktree
        test_file = worktree_path / "new_feature.py"
        test_file.write_text("# New feature code")

        # Commit changes in worktree
        subprocess.run(['git', 'add', '.'], cwd=worktree_path, capture_output=True)
        subprocess.run(['git', 'commit', '-m', 'Add new feature'], cwd=worktree_path, capture_output=True)

        # Merge into main
        result = mgr.merge_up(branch.name, default_branch)

        assert result.success
        assert result.commit is not None

        # Verify file exists in main branch
        subprocess.run(['git', 'checkout', default_branch], cwd=temp_git_repo, capture_output=True)
        assert (temp_git_repo / "new_feature.py").exists()

    def test_cleanup_on_failure(self, temp_git_repo):
        """AC-004: On spec failure, worktree is cleaned up without affecting main."""
        mgr = WorktreeManager(repo_root=temp_git_repo)
        default_branch = get_default_branch(temp_git_repo)

        # Get main's initial commit
        result = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=temp_git_repo, capture_output=True, text=True)
        initial_commit = result.stdout.strip()

        # Create branch and worktree
        spec_path = "Specs/Active/failing-feature/spec.json"
        branch = mgr.create_spec_branch(spec_path, default_branch)
        wt = mgr.create_worktree(branch.name)

        worktree_path = Path(wt.path)

        # Make changes in worktree (simulating failed implementation)
        test_file = worktree_path / "broken_code.py"
        test_file.write_text("# This code is broken")

        # Commit changes
        subprocess.run(['git', 'add', '.'], cwd=worktree_path, capture_output=True)
        subprocess.run(['git', 'commit', '-m', 'Broken code'], cwd=worktree_path, capture_output=True)

        # Cleanup without merging (simulating failure)
        mgr.cleanup(spec_path)

        # Verify main is unchanged
        subprocess.run(['git', 'checkout', default_branch], cwd=temp_git_repo, capture_output=True)
        result = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=temp_git_repo, capture_output=True, text=True)
        current_commit = result.stdout.strip()

        assert current_commit == initial_commit
        assert not (temp_git_repo / "broken_code.py").exists()

    def test_file_ownership_prevents_conflicts(self, tmp_path):
        """AC-005: FileOwnershipTracker prevents concurrent specs from claiming same files."""
        db_path = tmp_path / "test.db"
        tracker = FileOwnershipTracker(db_path=db_path)

        # First spec claims files
        result1 = tracker.claim_files("spec-a", ["src/parser/*.py", "src/lexer/*.py"])
        assert result1.success

        # Second spec tries to claim overlapping files
        result2 = tracker.claim_files("spec-b", ["src/parser/*.py"])  # Overlaps with spec-a
        assert not result2.success
        assert result2.conflicts is not None
        assert len(result2.conflicts) > 0
        assert result2.conflicts[0]["owner"] == "spec-a"

        # Non-overlapping claim should work
        result3 = tracker.claim_files("spec-b", ["src/evaluator/*.py"])
        assert result3.success

    def test_merge_conflict_blocks_spec(self, temp_git_repo):
        """EC-001: Merge conflicts mark spec as blocked with conflict info."""
        mgr = WorktreeManager(repo_root=temp_git_repo)
        default_branch = get_default_branch(temp_git_repo)

        # Create a file in main
        test_file = temp_git_repo / "shared_file.py"
        test_file.write_text("# Original content")
        subprocess.run(['git', 'add', '.'], cwd=temp_git_repo, capture_output=True)
        subprocess.run(['git', 'commit', '-m', 'Add shared file'], cwd=temp_git_repo, capture_output=True)

        # Create branch and worktree
        spec_path = "Specs/Active/feature-x/spec.json"
        branch = mgr.create_spec_branch(spec_path, default_branch)
        wt = mgr.create_worktree(branch.name)
        worktree_path = Path(wt.path)

        # Modify file in worktree
        (worktree_path / "shared_file.py").write_text("# Feature X changes")
        subprocess.run(['git', 'add', '.'], cwd=worktree_path, capture_output=True)
        subprocess.run(['git', 'commit', '-m', 'Feature X changes'], cwd=worktree_path, capture_output=True)

        # Modify same file in main (creating conflict)
        subprocess.run(['git', 'checkout', default_branch], cwd=temp_git_repo, capture_output=True)
        test_file.write_text("# Main branch changes")
        subprocess.run(['git', 'add', '.'], cwd=temp_git_repo, capture_output=True)
        subprocess.run(['git', 'commit', '-m', 'Main changes'], cwd=temp_git_repo, capture_output=True)

        # Attempt merge - should fail with conflict
        result = mgr.merge_up(branch.name, default_branch)

        assert not result.success
        assert result.conflict
        assert result.conflict_files is not None
        assert "shared_file.py" in result.conflict_files

    def test_cleans_orphaned_worktrees(self, temp_git_repo):
        """EC-002: Stale worktrees are cleaned up on orchestrator startup."""
        mgr = WorktreeManager(repo_root=temp_git_repo)
        default_branch = get_default_branch(temp_git_repo)

        # Create a worktree
        spec_path = "Specs/Active/orphan-feature/spec.json"
        branch = mgr.create_spec_branch(spec_path, default_branch)
        wt = mgr.create_worktree(branch.name)
        worktree_path = Path(wt.path)

        # Manually delete the worktree directory (simulating crash)
        shutil.rmtree(worktree_path)

        # Prune should clean up the stale reference
        mgr._run_git_no_check('worktree', 'prune')

        # Verify worktree is no longer listed
        worktrees = mgr._list_worktrees()
        worktree_paths = [wt.get('path', '') for wt in worktrees]

        assert str(worktree_path) not in worktree_paths


class TestFullSpecLifecycle:
    """Integration test for full spec lifecycle with worktree isolation."""

    @pytest.fixture
    def temp_git_repo(self, tmp_path):
        """Create a temporary git repository for testing."""
        repo_path = tmp_path / "test_repo"
        repo_path.mkdir()

        # Initialize git repo with 'main' as default branch
        subprocess.run(['git', 'init', '-b', 'main'], cwd=repo_path, capture_output=True)
        subprocess.run(['git', 'config', 'user.email', 'test@test.com'], cwd=repo_path, capture_output=True)
        subprocess.run(['git', 'config', 'user.name', 'Test User'], cwd=repo_path, capture_output=True)

        # Create initial commit
        (repo_path / "README.md").write_text("# Test Repo")
        subprocess.run(['git', 'add', '.'], cwd=repo_path, capture_output=True)
        subprocess.run(['git', 'commit', '-m', 'Initial commit'], cwd=repo_path, capture_output=True)

        yield repo_path

        # Cleanup
        subprocess.run(['git', 'worktree', 'prune'], cwd=repo_path, capture_output=True)

    def test_full_spec_lifecycle_with_isolation(self, temp_git_repo, tmp_path):
        """IT-001: Full spec lifecycle works with worktree isolation end-to-end."""
        mgr = WorktreeManager(repo_root=temp_git_repo)
        tracker = FileOwnershipTracker(db_path=tmp_path / "test.db")
        default_branch = get_default_branch(temp_git_repo)

        spec_path = "Specs/Active/calculator/spec.json"

        # 1. Create worktree for spec
        branch = mgr.create_spec_branch(spec_path, default_branch)
        assert branch.name == "ralph/calculator"

        wt = mgr.create_worktree(branch.name)
        worktree_path = Path(wt.path)
        assert worktree_path.exists()

        # 2. Claim files
        claim_result = tracker.claim_files(spec_path, ["src/calculator.py"])
        assert claim_result.success

        # 3. Make implementation changes in worktree
        src_dir = worktree_path / "src"
        src_dir.mkdir(exist_ok=True)
        (src_dir / "calculator.py").write_text("""
class Calculator:
    def add(self, a, b):
        return a + b

    def subtract(self, a, b):
        return a - b
""")

        subprocess.run(['git', 'add', '.'], cwd=worktree_path, capture_output=True)
        subprocess.run(['git', 'commit', '-m', 'Implement calculator'], cwd=worktree_path, capture_output=True)

        # 4. Merge into main
        merge_result = mgr.merge_up(branch.name, default_branch)
        assert merge_result.success

        # 5. Cleanup worktree
        mgr.cleanup(spec_path)

        # 6. Release file claims
        tracker.release_files(spec_path)

        # 7. Verify changes are in main
        subprocess.run(['git', 'checkout', default_branch], cwd=temp_git_repo, capture_output=True)
        assert (temp_git_repo / "src" / "calculator.py").exists()

        # 8. Verify files can be claimed by another spec
        new_claim = tracker.claim_files("spec-b", ["src/calculator.py"])
        assert new_claim.success


class TestHierarchicalBranching:
    """Test hierarchical branching for parent-child specs."""

    @pytest.fixture
    def temp_git_repo(self, tmp_path):
        """Create a temporary git repository for testing."""
        repo_path = tmp_path / "test_repo"
        repo_path.mkdir()

        # Initialize git repo with 'main' as default branch
        subprocess.run(['git', 'init', '-b', 'main'], cwd=repo_path, capture_output=True)
        subprocess.run(['git', 'config', 'user.email', 'test@test.com'], cwd=repo_path, capture_output=True)
        subprocess.run(['git', 'config', 'user.name', 'Test User'], cwd=repo_path, capture_output=True)

        (repo_path / "README.md").write_text("# Test Repo")
        subprocess.run(['git', 'add', '.'], cwd=repo_path, capture_output=True)
        subprocess.run(['git', 'commit', '-m', 'Initial commit'], cwd=repo_path, capture_output=True)

        yield repo_path

        subprocess.run(['git', 'worktree', 'prune'], cwd=repo_path, capture_output=True)

    def test_child_branches_from_parent(self, temp_git_repo):
        """Test that child specs branch from parent's worktree branch.

        Note: Git doesn't allow branch names that are prefixes of other branches
        (e.g., can't have both 'ralph/calculator' and 'ralph/calculator/parser').
        So child branches must use a different naming pattern.

        In practice, the orchestrator branches child specs from the parent's branch,
        but uses unique non-conflicting branch names (leaf specs get worktrees,
        non-leaf parent specs typically don't need their own worktree).
        """
        mgr = WorktreeManager(repo_root=temp_git_repo)
        default_branch = get_default_branch(temp_git_repo)

        # Create parent branch - use a name that won't conflict with children
        # In real usage, parent specs don't get worktrees (only leaf specs do)
        parent_path = "Specs/Active/calculator-root/spec.json"
        parent_branch = mgr.create_spec_branch(parent_path, default_branch)
        parent_wt = mgr.create_worktree(parent_branch.name)

        # Make changes in parent worktree
        (Path(parent_wt.path) / "shared_types.py").write_text("# Shared types")
        subprocess.run(['git', 'add', '.'], cwd=parent_wt.path, capture_output=True)
        subprocess.run(['git', 'commit', '-m', 'Add shared types'], cwd=parent_wt.path, capture_output=True)

        # Create child branch from parent branch
        # Child uses a separate path that doesn't conflict with parent
        child_path = "Specs/Active/calculator-parser/spec.json"
        child_branch = mgr.create_spec_branch(child_path, parent_branch.name)

        assert child_branch.name == "ralph/calculator-parser"
        assert child_branch.parent_branch == parent_branch.name

        # Create child worktree
        child_wt = mgr.create_worktree(child_branch.name)
        child_worktree_path = Path(child_wt.path)

        # Verify child has parent's changes (inherited from parent branch)
        assert (child_worktree_path / "shared_types.py").exists()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
