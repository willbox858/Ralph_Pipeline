"""
WorktreeManager - Git branch/worktree lifecycle following spec hierarchy.

Creates and manages git worktrees for isolated agent development.
Branch naming follows: ralph/{spec-hierarchy} convention.
"""

import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


class GitError(Exception):
    """Exception raised when a git command fails."""
    pass


@dataclass
class BranchInfo:
    """Information about a spec branch."""
    name: str
    commit: str
    spec_path: str
    parent_branch: str
    created_at: str


@dataclass
class WorktreeInfo:
    """Information about a worktree."""
    path: str
    branch: str
    commit: str
    spec_path: str


@dataclass
class MergeResult:
    """Result of merge operation."""
    success: bool
    commit: Optional[str] = None
    conflict: bool = False
    conflict_files: Optional[list[str]] = None
    message: str = ""


@dataclass
class SyncResult:
    """Result of sync/rebase operation."""
    success: bool
    conflict: bool = False
    conflict_files: Optional[list[str]] = None
    message: str = ""


class WorktreeManager:
    """
    Creates and manages git worktrees following spec hierarchy.

    Branch naming convention:
    - Root spec 'calculator': branch = 'ralph/calculator'
    - Child 'parser' of 'calculator': branch = 'ralph/calculator/parser'
    - Grandchild 'lexer': branch = 'ralph/calculator/parser/lexer'

    Worktrees are created in .worktrees/{spec_name} directory.
    """

    BRANCH_PREFIX = "ralph"
    WORKTREE_DIR = ".worktrees"

    def __init__(self, repo_root: Optional[Path] = None):
        """
        Initialize WorktreeManager.

        Args:
            repo_root: Path to git repository root. Defaults to finding it from cwd.
        """
        self.repo_root = repo_root or self._find_repo_root()
        self._worktree_base = self.repo_root / self.WORKTREE_DIR

    def _find_repo_root(self) -> Path:
        """Find the git repository root from current directory."""
        try:
            result = subprocess.run(
                ['git', 'rev-parse', '--show-toplevel'],
                capture_output=True,
                text=True,
                check=True
            )
            return Path(result.stdout.strip())
        except subprocess.CalledProcessError as e:
            raise GitError(f"Not in a git repository: {e.stderr}") from e

    def _run_git(self, *args: str, cwd: Optional[Path] = None) -> subprocess.CompletedProcess:
        """
        Run a git command with proper error handling.

        Args:
            *args: Git command arguments (without 'git' prefix)
            cwd: Working directory for command. Defaults to repo_root.

        Returns:
            CompletedProcess with stdout/stderr

        Raises:
            GitError: If command fails
        """
        cmd = ['git'] + list(args)
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True,
                cwd=str(cwd) if cwd else str(self.repo_root)
            )
            return result
        except subprocess.CalledProcessError as e:
            raise GitError(f"Git command failed: {' '.join(cmd)}\nstderr: {e.stderr}") from e

    def _run_git_no_check(self, *args: str, cwd: Optional[Path] = None) -> subprocess.CompletedProcess:
        """Run git command without raising on non-zero exit."""
        cmd = ['git'] + list(args)
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=str(cwd) if cwd else str(self.repo_root)
        )

    def _spec_path_to_branch_name(self, spec_path: str) -> str:
        """
        Convert spec path to branch name.

        Args:
            spec_path: Path like 'Specs/Active/calculator/parser' or just 'calculator/parser'

        Returns:
            Branch name like 'ralph/calculator/parser'
        """
        # Extract just the spec hierarchy part
        path = Path(spec_path)

        # Remove common prefixes like 'Specs/Active/'
        parts = path.parts
        if 'Specs' in parts:
            idx = parts.index('Specs')
            # Skip 'Specs' and 'Active' if present
            start = idx + 1
            if start < len(parts) and parts[start] == 'Active':
                start += 1
            parts = parts[start:]

        # Remove 'spec.json' if present
        if parts and parts[-1] == 'spec.json':
            parts = parts[:-1]

        if not parts:
            raise GitError(f"Cannot extract spec name from path: {spec_path}")

        # Join with / for branch name
        spec_name = '/'.join(parts)
        return f"{self.BRANCH_PREFIX}/{spec_name}"

    def _branch_exists(self, branch: str) -> bool:
        """Check if a branch exists."""
        result = self._run_git_no_check('branch', '--list', branch)
        return bool(result.stdout.strip())

    def _get_current_commit(self, ref: str = "HEAD") -> str:
        """Get the commit hash for a ref."""
        result = self._run_git('rev-parse', ref)
        return result.stdout.strip()

    def _get_spec_name_from_path(self, spec_path: str) -> str:
        """Extract just the spec name (last component) from spec path."""
        path = Path(spec_path)
        parts = path.parts

        # Remove spec.json if present
        if parts and parts[-1] == 'spec.json':
            parts = parts[:-1]

        return parts[-1] if parts else ""

    def create_spec_branch(self, spec_path: str, parent_branch: str) -> BranchInfo:
        """
        Create a branch for spec off parent branch.

        Args:
            spec_path: Path to the spec (e.g., 'Specs/Active/feature-x/parser')
            parent_branch: Branch to branch from (e.g., 'main' or 'ralph/feature-x')

        Returns:
            BranchInfo with branch details

        Raises:
            GitError: If branch creation fails
        """
        branch_name = self._spec_path_to_branch_name(spec_path)
        now = datetime.now(timezone.utc).isoformat()

        # Check if branch already exists
        if self._branch_exists(branch_name):
            # Return existing branch info
            commit = self._get_current_commit(branch_name)
            return BranchInfo(
                name=branch_name,
                commit=commit,
                spec_path=spec_path,
                parent_branch=parent_branch,
                created_at=now
            )

        # Prune stale worktrees first
        self._run_git_no_check('worktree', 'prune')

        # Create branch from parent
        try:
            self._run_git('branch', branch_name, parent_branch)
        except GitError as e:
            # If parent doesn't exist, try to be helpful
            if 'not a valid object name' in str(e).lower():
                raise GitError(f"Parent branch '{parent_branch}' does not exist") from e
            raise

        commit = self._get_current_commit(branch_name)

        return BranchInfo(
            name=branch_name,
            commit=commit,
            spec_path=spec_path,
            parent_branch=parent_branch,
            created_at=now
        )

    def create_worktree(self, branch: str) -> WorktreeInfo:
        """
        Create a worktree for agent to work in.

        Args:
            branch: Branch name (e.g., 'ralph/calculator/parser')

        Returns:
            WorktreeInfo with worktree details

        Raises:
            GitError: If worktree creation fails
        """
        # Determine worktree path from branch name
        # ralph/calculator/parser -> .worktrees/calculator-parser
        if branch.startswith(f"{self.BRANCH_PREFIX}/"):
            spec_part = branch[len(self.BRANCH_PREFIX) + 1:]
        else:
            spec_part = branch

        # Replace / with - for directory name
        worktree_name = spec_part.replace('/', '-')
        worktree_path = self._worktree_base / worktree_name

        # Prune stale worktrees first
        self._run_git_no_check('worktree', 'prune')

        # Check if worktree already exists
        existing = self._list_worktrees()
        for wt in existing:
            if wt.get('branch', '').endswith(branch) or wt.get('path') == str(worktree_path):
                # Already exists, return info
                return WorktreeInfo(
                    path=wt['path'],
                    branch=wt.get('branch', '').replace('refs/heads/', ''),
                    commit=wt.get('head', ''),
                    spec_path=spec_part
                )

        # Ensure base directory exists
        self._worktree_base.mkdir(parents=True, exist_ok=True)

        # Check if branch exists
        if not self._branch_exists(branch):
            raise GitError(f"Branch '{branch}' does not exist. Create it first with create_spec_branch()")

        # Create worktree - use forward slashes for git on Windows
        worktree_path_str = str(worktree_path).replace('\\', '/')

        self._run_git('worktree', 'add', worktree_path_str, branch)

        commit = self._get_current_commit(branch)

        return WorktreeInfo(
            path=str(worktree_path),
            branch=branch,
            commit=commit,
            spec_path=spec_part
        )

    def _list_worktrees(self) -> list[dict]:
        """
        List all worktrees in the repository.

        Returns:
            List of dicts with path, head, branch keys
        """
        result = self._run_git('worktree', 'list', '--porcelain')
        worktrees = []
        current: dict = {}

        for line in result.stdout.split('\n'):
            if not line:
                if current:
                    worktrees.append(current)
                    current = {}
            elif line.startswith('worktree '):
                current['path'] = line[9:]
            elif line.startswith('HEAD '):
                current['head'] = line[5:]
            elif line.startswith('branch '):
                current['branch'] = line[7:]
            elif line == 'detached':
                current['detached'] = True

        # Don't forget last entry
        if current:
            worktrees.append(current)

        return worktrees

    def merge_up(self, child_branch: str, parent_branch: str) -> MergeResult:
        """
        Merge verified child branch into parent branch.

        Does NOT auto-resolve conflicts. On conflict, aborts and returns conflict info.

        Args:
            child_branch: Branch to merge from
            parent_branch: Branch to merge into

        Returns:
            MergeResult with success status and conflict info if applicable
        """
        # Find or create parent worktree to do the merge
        parent_worktree = None
        worktrees = self._list_worktrees()

        for wt in worktrees:
            branch = wt.get('branch', '').replace('refs/heads/', '')
            if branch == parent_branch:
                parent_worktree = Path(wt['path'])
                break

        # If parent has no worktree, do merge in main repo if parent is checked out there
        # Otherwise we need to create a temporary worktree
        if parent_worktree is None:
            # Check if parent is current branch in main repo
            result = self._run_git_no_check('symbolic-ref', '--short', 'HEAD')
            if result.returncode == 0 and result.stdout.strip() == parent_branch:
                parent_worktree = self.repo_root
            else:
                # Create temporary worktree for parent
                temp_path = self._worktree_base / f"_merge-{parent_branch.replace('/', '-')}"
                temp_path_str = str(temp_path).replace('\\', '/')

                try:
                    self._run_git('worktree', 'add', temp_path_str, parent_branch)
                    parent_worktree = temp_path
                except GitError:
                    # Worktree may already exist
                    if temp_path.exists():
                        parent_worktree = temp_path
                    else:
                        return MergeResult(
                            success=False,
                            message=f"Could not access parent branch '{parent_branch}'"
                        )

        # Attempt merge
        merge_result = self._run_git_no_check(
            'merge', '--no-ff', child_branch, '-m', f'Merge {child_branch} into {parent_branch}',
            cwd=parent_worktree
        )

        if merge_result.returncode == 0:
            # Success
            commit = self._get_current_commit(f"{parent_branch}")
            return MergeResult(
                success=True,
                commit=commit,
                message=f"Merged {child_branch} into {parent_branch}"
            )

        # Check for conflicts
        if 'CONFLICT' in merge_result.stdout or 'conflict' in merge_result.stderr.lower():
            # Get list of conflicting files
            status_result = self._run_git_no_check('diff', '--name-only', '--diff-filter=U', cwd=parent_worktree)
            conflict_files = [f for f in status_result.stdout.strip().split('\n') if f]

            # Abort the merge
            self._run_git_no_check('merge', '--abort', cwd=parent_worktree)

            return MergeResult(
                success=False,
                conflict=True,
                conflict_files=conflict_files,
                message=f"Merge conflict in files: {', '.join(conflict_files)}"
            )

        # Some other failure
        return MergeResult(
            success=False,
            message=f"Merge failed: {merge_result.stderr}"
        )

    def sync_from_parent(self, child_branch: str, parent_branch: str) -> SyncResult:
        """
        Rebase child branch on parent (for getting shared type updates).

        Does NOT auto-resolve conflicts. On conflict, aborts and returns conflict info.

        Args:
            child_branch: Branch to rebase
            parent_branch: Branch to rebase onto

        Returns:
            SyncResult with success status and conflict info if applicable
        """
        # Find child worktree
        child_worktree = None
        worktrees = self._list_worktrees()

        for wt in worktrees:
            branch = wt.get('branch', '').replace('refs/heads/', '')
            if branch == child_branch:
                child_worktree = Path(wt['path'])
                break

        if child_worktree is None:
            # Check if child is current branch in main repo
            result = self._run_git_no_check('symbolic-ref', '--short', 'HEAD')
            if result.returncode == 0 and result.stdout.strip() == child_branch:
                child_worktree = self.repo_root
            else:
                return SyncResult(
                    success=False,
                    message=f"Cannot find worktree for branch '{child_branch}'"
                )

        # Attempt rebase
        rebase_result = self._run_git_no_check('rebase', parent_branch, cwd=child_worktree)

        if rebase_result.returncode == 0:
            return SyncResult(
                success=True,
                message=f"Rebased {child_branch} onto {parent_branch}"
            )

        # Check for conflicts
        if 'CONFLICT' in rebase_result.stdout or 'conflict' in rebase_result.stderr.lower():
            # Get list of conflicting files
            status_result = self._run_git_no_check('diff', '--name-only', '--diff-filter=U', cwd=child_worktree)
            conflict_files = [f for f in status_result.stdout.strip().split('\n') if f]

            # Abort the rebase
            self._run_git_no_check('rebase', '--abort', cwd=child_worktree)

            return SyncResult(
                success=False,
                conflict=True,
                conflict_files=conflict_files,
                message=f"Rebase conflict in files: {', '.join(conflict_files)}"
            )

        # Some other failure
        return SyncResult(
            success=False,
            message=f"Rebase failed: {rebase_result.stderr}"
        )

    def rollback(self, branch: str, to_commit: Optional[str] = None) -> None:
        """
        Reset branch to commit, or discard all changes if commit is None.

        Args:
            branch: Branch to rollback
            to_commit: Commit to reset to, or None to discard all uncommitted changes

        Raises:
            GitError: If rollback fails
        """
        # Find worktree for branch
        worktree_path = None
        worktrees = self._list_worktrees()

        for wt in worktrees:
            wt_branch = wt.get('branch', '').replace('refs/heads/', '')
            if wt_branch == branch:
                worktree_path = Path(wt['path'])
                break

        if worktree_path is None:
            # Check if branch is current in main repo
            result = self._run_git_no_check('symbolic-ref', '--short', 'HEAD')
            if result.returncode == 0 and result.stdout.strip() == branch:
                worktree_path = self.repo_root
            else:
                raise GitError(f"Cannot find worktree for branch '{branch}'")

        if to_commit is None:
            # Discard all uncommitted changes
            self._run_git('checkout', '.', cwd=worktree_path)
            self._run_git('clean', '-fd', cwd=worktree_path)
        else:
            # Reset to specific commit
            self._run_git('reset', '--hard', to_commit, cwd=worktree_path)

    def cleanup(self, spec_path: str) -> None:
        """
        Remove worktree and branch after spec completion.

        Args:
            spec_path: Path to the spec

        Raises:
            GitError: If cleanup fails
        """
        branch_name = self._spec_path_to_branch_name(spec_path)

        # Prune first
        self._run_git_no_check('worktree', 'prune')

        # Find and remove worktree
        worktrees = self._list_worktrees()
        for wt in worktrees:
            wt_branch = wt.get('branch', '').replace('refs/heads/', '')
            if wt_branch == branch_name:
                worktree_path = wt['path']
                # Remove worktree (--force handles uncommitted changes)
                self._run_git_no_check('worktree', 'remove', '--force', worktree_path)
                break

        # Prune again after removal
        self._run_git_no_check('worktree', 'prune')

        # Delete branch (only if not checked out anywhere)
        # Check if branch is in any worktree
        worktrees = self._list_worktrees()
        branch_in_use = False
        for wt in worktrees:
            if wt.get('branch', '').replace('refs/heads/', '') == branch_name:
                branch_in_use = True
                break

        if not branch_in_use:
            # Safe to delete branch
            self._run_git_no_check('branch', '-D', branch_name)

    def get_worktree_path(self, spec_path: str) -> Optional[Path]:
        """
        Get the worktree path for a spec, if it exists.

        Args:
            spec_path: Path to the spec

        Returns:
            Path to worktree, or None if not found
        """
        branch_name = self._spec_path_to_branch_name(spec_path)

        worktrees = self._list_worktrees()
        for wt in worktrees:
            wt_branch = wt.get('branch', '').replace('refs/heads/', '')
            if wt_branch == branch_name:
                return Path(wt['path'])

        return None
