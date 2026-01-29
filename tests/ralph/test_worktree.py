"""
Tests for WorktreeManager class.

Tests git branch/worktree lifecycle following spec hierarchy.
"""

import subprocess
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.ralph import (
    WorktreeManager,
    BranchInfo,
    WorktreeInfo,
    MergeResult,
    SyncResult,
    GitError,
)


class TestWorktreeManagerInit:
    """Tests for WorktreeManager initialization."""

    def test_init_finds_repo_root(self):
        """WorktreeManager should find git repo root from cwd."""
        with patch.object(WorktreeManager, '_find_repo_root') as mock_find:
            mock_find.return_value = Path('/repo')
            mgr = WorktreeManager()
            assert mgr.repo_root == Path('/repo')

    def test_init_with_explicit_root(self):
        """WorktreeManager should use explicit repo root if provided."""
        mgr = WorktreeManager(repo_root=Path('/custom/repo'))
        assert mgr.repo_root == Path('/custom/repo')

    def test_init_sets_worktree_base(self):
        """WorktreeManager should set worktree base directory."""
        mgr = WorktreeManager(repo_root=Path('/repo'))
        assert mgr._worktree_base == Path('/repo/.worktrees')


class TestSpecPathToBranchName:
    """Tests for _spec_path_to_branch_name method."""

    def test_simple_spec_path(self):
        """Simple spec path converts to ralph/name branch."""
        mgr = WorktreeManager(repo_root=Path('/repo'))
        branch = mgr._spec_path_to_branch_name('calculator')
        assert branch == 'ralph/calculator'

    def test_nested_spec_path(self):
        """Nested spec path converts to ralph/parent/child branch."""
        mgr = WorktreeManager(repo_root=Path('/repo'))
        branch = mgr._spec_path_to_branch_name('calculator/parser')
        assert branch == 'ralph/calculator/parser'

    def test_full_spec_path_with_specs_active(self):
        """Full path with Specs/Active/ prefix is stripped."""
        mgr = WorktreeManager(repo_root=Path('/repo'))
        branch = mgr._spec_path_to_branch_name('Specs/Active/calculator/parser')
        assert branch == 'ralph/calculator/parser'

    def test_spec_path_with_spec_json(self):
        """spec.json suffix is removed from path."""
        mgr = WorktreeManager(repo_root=Path('/repo'))
        branch = mgr._spec_path_to_branch_name('Specs/Active/calculator/spec.json')
        assert branch == 'ralph/calculator'

    def test_empty_spec_path_raises(self):
        """Empty spec path raises GitError."""
        mgr = WorktreeManager(repo_root=Path('/repo'))
        with pytest.raises(GitError):
            mgr._spec_path_to_branch_name('Specs/Active/spec.json')


class TestCreateSpecBranch:
    """Tests for create_spec_branch method."""

    def test_creates_branch_from_parent(self):
        """Creates new branch from parent branch."""
        mgr = WorktreeManager(repo_root=Path('/repo'))

        with patch.object(mgr, '_branch_exists', return_value=False):
            with patch.object(mgr, '_run_git_no_check'):
                with patch.object(mgr, '_run_git') as mock_git:
                    with patch.object(mgr, '_get_current_commit', return_value='abc123'):
                        result = mgr.create_spec_branch('calculator', 'main')

        mock_git.assert_called_with('branch', 'ralph/calculator', 'main')
        assert result.name == 'ralph/calculator'
        assert result.commit == 'abc123'
        assert result.parent_branch == 'main'

    def test_returns_existing_branch_info(self):
        """Returns existing branch info if branch exists."""
        mgr = WorktreeManager(repo_root=Path('/repo'))

        with patch.object(mgr, '_branch_exists', return_value=True):
            with patch.object(mgr, '_get_current_commit', return_value='def456'):
                result = mgr.create_spec_branch('calculator', 'main')

        assert result.name == 'ralph/calculator'
        assert result.commit == 'def456'

    def test_raises_on_invalid_parent(self):
        """Raises GitError if parent branch doesn't exist."""
        mgr = WorktreeManager(repo_root=Path('/repo'))

        with patch.object(mgr, '_branch_exists', return_value=False):
            with patch.object(mgr, '_run_git_no_check'):
                with patch.object(mgr, '_run_git', side_effect=GitError('not a valid object name')):
                    with pytest.raises(GitError, match="does not exist"):
                        mgr.create_spec_branch('calculator', 'nonexistent')


class TestCreateWorktree:
    """Tests for create_worktree method."""

    def test_creates_worktree_for_branch(self):
        """Creates worktree in .worktrees directory."""
        mgr = WorktreeManager(repo_root=Path('/repo'))

        with patch.object(mgr, '_run_git_no_check'):
            with patch.object(mgr, '_list_worktrees', return_value=[]):
                with patch.object(mgr, '_branch_exists', return_value=True):
                    with patch.object(mgr, '_run_git') as mock_git:
                        with patch.object(mgr, '_get_current_commit', return_value='abc123'):
                            with patch.object(Path, 'mkdir'):
                                result = mgr.create_worktree('ralph/calculator')

        assert 'worktree' in mock_git.call_args[0]
        assert 'add' in mock_git.call_args[0]
        assert result.branch == 'ralph/calculator'

    def test_returns_existing_worktree(self):
        """Returns info if worktree already exists."""
        mgr = WorktreeManager(repo_root=Path('/repo'))

        existing = [
            {'path': '/repo/.worktrees/calculator', 'branch': 'refs/heads/ralph/calculator', 'head': 'abc123'}
        ]

        with patch.object(mgr, '_run_git_no_check'):
            with patch.object(mgr, '_list_worktrees', return_value=existing):
                result = mgr.create_worktree('ralph/calculator')

        assert result.path == '/repo/.worktrees/calculator'
        assert result.branch == 'ralph/calculator'

    def test_raises_if_branch_missing(self):
        """Raises GitError if branch doesn't exist."""
        mgr = WorktreeManager(repo_root=Path('/repo'))

        with patch.object(mgr, '_run_git_no_check'):
            with patch.object(mgr, '_list_worktrees', return_value=[]):
                with patch.object(mgr, '_branch_exists', return_value=False):
                    with pytest.raises(GitError, match="does not exist"):
                        mgr.create_worktree('ralph/missing')


class TestMergeUp:
    """Tests for merge_up method."""

    def test_merges_child_into_parent(self):
        """Successfully merges child branch into parent."""
        mgr = WorktreeManager(repo_root=Path('/repo'))

        worktrees = [
            {'path': '/repo/.worktrees/parent', 'branch': 'refs/heads/ralph/parent', 'head': 'abc123'}
        ]
        merge_result = MagicMock()
        merge_result.returncode = 0

        with patch.object(mgr, '_list_worktrees', return_value=worktrees):
            with patch.object(mgr, '_run_git_no_check', return_value=merge_result):
                with patch.object(mgr, '_get_current_commit', return_value='merged123'):
                    result = mgr.merge_up('ralph/child', 'ralph/parent')

        assert result.success is True
        assert result.commit == 'merged123'

    def test_returns_conflict_info_on_conflict(self):
        """Returns conflict info when merge has conflicts."""
        mgr = WorktreeManager(repo_root=Path('/repo'))

        worktrees = [
            {'path': '/repo/.worktrees/parent', 'branch': 'refs/heads/ralph/parent', 'head': 'abc123'}
        ]
        merge_result = MagicMock()
        merge_result.returncode = 1
        merge_result.stdout = 'CONFLICT (content): Merge conflict in file.py'
        merge_result.stderr = ''

        diff_result = MagicMock()
        diff_result.stdout = 'file.py\n'

        with patch.object(mgr, '_list_worktrees', return_value=worktrees):
            with patch.object(mgr, '_run_git_no_check', side_effect=[merge_result, diff_result, MagicMock()]):
                result = mgr.merge_up('ralph/child', 'ralph/parent')

        assert result.success is False
        assert result.conflict is True
        assert 'file.py' in result.conflict_files


class TestSyncFromParent:
    """Tests for sync_from_parent method."""

    def test_rebases_child_onto_parent(self):
        """Successfully rebases child branch onto parent."""
        mgr = WorktreeManager(repo_root=Path('/repo'))

        worktrees = [
            {'path': '/repo/.worktrees/child', 'branch': 'refs/heads/ralph/child', 'head': 'abc123'}
        ]
        rebase_result = MagicMock()
        rebase_result.returncode = 0

        with patch.object(mgr, '_list_worktrees', return_value=worktrees):
            with patch.object(mgr, '_run_git_no_check', return_value=rebase_result):
                result = mgr.sync_from_parent('ralph/child', 'ralph/parent')

        assert result.success is True

    def test_returns_conflict_info_on_conflict(self):
        """Returns conflict info when rebase has conflicts."""
        mgr = WorktreeManager(repo_root=Path('/repo'))

        worktrees = [
            {'path': '/repo/.worktrees/child', 'branch': 'refs/heads/ralph/child', 'head': 'abc123'}
        ]
        rebase_result = MagicMock()
        rebase_result.returncode = 1
        rebase_result.stdout = 'CONFLICT (content): Merge conflict in file.py'
        rebase_result.stderr = ''

        diff_result = MagicMock()
        diff_result.stdout = 'file.py\n'

        with patch.object(mgr, '_list_worktrees', return_value=worktrees):
            with patch.object(mgr, '_run_git_no_check', side_effect=[rebase_result, diff_result, MagicMock()]):
                result = mgr.sync_from_parent('ralph/child', 'ralph/parent')

        assert result.success is False
        assert result.conflict is True

    def test_returns_error_if_no_worktree(self):
        """Returns error if child has no worktree."""
        mgr = WorktreeManager(repo_root=Path('/repo'))

        head_result = MagicMock()
        head_result.returncode = 0
        head_result.stdout = 'main'  # Not the child branch

        with patch.object(mgr, '_list_worktrees', return_value=[]):
            with patch.object(mgr, '_run_git_no_check', return_value=head_result):
                result = mgr.sync_from_parent('ralph/child', 'ralph/parent')

        assert result.success is False
        assert 'Cannot find worktree' in result.message


class TestRollback:
    """Tests for rollback method."""

    def test_discards_changes_when_no_commit(self):
        """Discards all changes when to_commit is None."""
        mgr = WorktreeManager(repo_root=Path('/repo'))

        worktrees = [
            {'path': '/repo/.worktrees/test', 'branch': 'refs/heads/ralph/test', 'head': 'abc123'}
        ]

        with patch.object(mgr, '_list_worktrees', return_value=worktrees):
            with patch.object(mgr, '_run_git') as mock_git:
                mgr.rollback('ralph/test', None)

        # Should call checkout . and clean -fd
        calls = mock_git.call_args_list
        assert any('checkout' in str(c) for c in calls)
        assert any('clean' in str(c) for c in calls)

    def test_resets_to_commit(self):
        """Resets to specific commit when provided."""
        mgr = WorktreeManager(repo_root=Path('/repo'))

        worktrees = [
            {'path': '/repo/.worktrees/test', 'branch': 'refs/heads/ralph/test', 'head': 'abc123'}
        ]

        with patch.object(mgr, '_list_worktrees', return_value=worktrees):
            with patch.object(mgr, '_run_git') as mock_git:
                mgr.rollback('ralph/test', 'target123')

        mock_git.assert_called_with('reset', '--hard', 'target123', cwd=Path('/repo/.worktrees/test'))

    def test_raises_if_no_worktree(self):
        """Raises GitError if branch has no worktree."""
        mgr = WorktreeManager(repo_root=Path('/repo'))

        head_result = MagicMock()
        head_result.returncode = 0
        head_result.stdout = 'main'  # Not the target branch

        with patch.object(mgr, '_list_worktrees', return_value=[]):
            with patch.object(mgr, '_run_git_no_check', return_value=head_result):
                with pytest.raises(GitError, match="Cannot find worktree"):
                    mgr.rollback('ralph/missing', 'abc123')


class TestCleanup:
    """Tests for cleanup method."""

    def test_removes_worktree_and_branch(self):
        """Removes worktree and deletes branch."""
        mgr = WorktreeManager(repo_root=Path('/repo'))

        worktrees_before = [
            {'path': '/repo/.worktrees/calculator', 'branch': 'refs/heads/ralph/calculator', 'head': 'abc123'}
        ]
        worktrees_after = []  # Worktree removed

        call_count = [0]

        def mock_list_worktrees():
            call_count[0] += 1
            if call_count[0] <= 1:
                return worktrees_before
            return worktrees_after

        with patch.object(mgr, '_list_worktrees', side_effect=mock_list_worktrees):
            with patch.object(mgr, '_run_git_no_check') as mock_git:
                mgr.cleanup('calculator')

        # Should call worktree remove and branch -D
        calls = [str(c) for c in mock_git.call_args_list]
        assert any('worktree' in c and 'remove' in c for c in calls)
        assert any('branch' in c and '-D' in c for c in calls)


class TestGetWorktreePath:
    """Tests for get_worktree_path method."""

    def test_returns_path_if_exists(self):
        """Returns worktree path if it exists."""
        mgr = WorktreeManager(repo_root=Path('/repo'))

        worktrees = [
            {'path': '/repo/.worktrees/calculator', 'branch': 'refs/heads/ralph/calculator', 'head': 'abc123'}
        ]

        with patch.object(mgr, '_list_worktrees', return_value=worktrees):
            result = mgr.get_worktree_path('calculator')

        assert result == Path('/repo/.worktrees/calculator')

    def test_returns_none_if_not_exists(self):
        """Returns None if worktree doesn't exist."""
        mgr = WorktreeManager(repo_root=Path('/repo'))

        with patch.object(mgr, '_list_worktrees', return_value=[]):
            result = mgr.get_worktree_path('missing')

        assert result is None
