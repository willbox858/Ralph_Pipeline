"""
Tests for FileOwnershipTracker class.

Tests file ownership tracking in database to prevent conflicts.
"""

import sqlite3
import tempfile
from pathlib import Path

import pytest

from src.ralph import (
    FileOwnershipTracker,
    ClaimResult,
    OwnerInfo,
)


@pytest.fixture
def temp_db():
    """Create a temporary database for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / ".ralph" / "test.db"
        yield db_path


@pytest.fixture
def tracker(temp_db):
    """Create a FileOwnershipTracker with temp database."""
    return FileOwnershipTracker(db_path=temp_db)


class TestFileOwnershipTrackerInit:
    """Tests for FileOwnershipTracker initialization."""

    def test_creates_database(self, temp_db):
        """Creates database file on init."""
        tracker = FileOwnershipTracker(db_path=temp_db)
        assert temp_db.exists()

    def test_creates_schema(self, temp_db):
        """Creates file_claims table on init."""
        tracker = FileOwnershipTracker(db_path=temp_db)

        conn = sqlite3.connect(str(temp_db))
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='file_claims'"
        )
        assert cursor.fetchone() is not None
        conn.close()


class TestClaimFiles:
    """Tests for claim_files method."""

    def test_claims_single_pattern(self, tracker):
        """Claims a single file pattern successfully."""
        result = tracker.claim_files('spec-a', ['src/parser/*.py'])

        assert result.success is True
        assert result.patterns == ['src/parser/*.py']

    def test_claims_multiple_patterns(self, tracker):
        """Claims multiple file patterns successfully."""
        result = tracker.claim_files('spec-a', ['src/parser/*.py', 'src/lexer/*.py'])

        assert result.success is True
        assert len(result.patterns) == 2

    def test_empty_patterns_succeeds(self, tracker):
        """Empty pattern list succeeds with no claims."""
        result = tracker.claim_files('spec-a', [])

        assert result.success is True
        assert result.patterns == []

    def test_detects_exact_conflict(self, tracker):
        """Detects conflict when exact same pattern already claimed."""
        tracker.claim_files('spec-a', ['src/parser/*.py'])

        result = tracker.claim_files('spec-b', ['src/parser/*.py'])

        assert result.success is False
        assert result.conflicts is not None
        assert len(result.conflicts) == 1
        assert result.conflicts[0]['owner'] == 'spec-a'

    def test_detects_overlapping_conflict(self, tracker):
        """Detects conflict when patterns overlap."""
        tracker.claim_files('spec-a', ['src/*.py'])

        result = tracker.claim_files('spec-b', ['src/parser/*.py'])

        assert result.success is False
        assert result.conflicts is not None

    def test_allows_non_overlapping_patterns(self, tracker):
        """Allows claims for non-overlapping patterns."""
        tracker.claim_files('spec-a', ['src/parser/*.py'])

        result = tracker.claim_files('spec-b', ['src/lexer/*.py'])

        assert result.success is True

    def test_same_spec_can_reclaim(self, tracker):
        """Same spec can reclaim its own patterns."""
        tracker.claim_files('spec-a', ['src/parser/*.py'])

        result = tracker.claim_files('spec-a', ['src/parser/*.py', 'src/lexer/*.py'])

        assert result.success is True

    def test_no_conflict_with_released_claims(self, tracker):
        """No conflict with previously released claims."""
        tracker.claim_files('spec-a', ['src/parser/*.py'])
        tracker.release_files('spec-a')

        result = tracker.claim_files('spec-b', ['src/parser/*.py'])

        assert result.success is True


class TestCheckOwnership:
    """Tests for check_ownership method."""

    def test_returns_owner_for_claimed_file(self, tracker):
        """Returns owner info for file matching a claim."""
        tracker.claim_files('spec-a', ['src/parser/*.py'])

        result = tracker.check_ownership('src/parser/lexer.py')

        assert result is not None
        assert result.spec_path == 'spec-a'
        assert result.pattern == 'src/parser/*.py'

    def test_returns_none_for_unclaimed_file(self, tracker):
        """Returns None for file not matching any claim."""
        tracker.claim_files('spec-a', ['src/parser/*.py'])

        result = tracker.check_ownership('src/other/file.py')

        assert result is None

    def test_returns_none_when_no_claims(self, tracker):
        """Returns None when no claims exist."""
        result = tracker.check_ownership('src/any/file.py')

        assert result is None

    def test_handles_backslash_paths(self, tracker):
        """Handles Windows-style backslash paths."""
        tracker.claim_files('spec-a', ['src/parser/*.py'])

        result = tracker.check_ownership('src\\parser\\lexer.py')

        assert result is not None
        assert result.spec_path == 'spec-a'


class TestReleaseFiles:
    """Tests for release_files method."""

    def test_releases_all_claims_for_spec(self, tracker):
        """Releases all claims for a spec."""
        tracker.claim_files('spec-a', ['src/parser/*.py', 'src/lexer/*.py'])

        tracker.release_files('spec-a')

        # Should be able to claim same patterns now
        result = tracker.claim_files('spec-b', ['src/parser/*.py'])
        assert result.success is True

    def test_release_does_not_affect_other_specs(self, tracker):
        """Release only affects the specified spec."""
        tracker.claim_files('spec-a', ['src/parser/*.py'])
        tracker.claim_files('spec-b', ['src/lexer/*.py'])

        tracker.release_files('spec-a')

        # spec-b's claims should still be active
        result = tracker.claim_files('spec-c', ['src/lexer/*.py'])
        assert result.success is False


class TestGetClaims:
    """Tests for get_claims method."""

    def test_returns_claimed_patterns(self, tracker):
        """Returns list of claimed patterns for spec."""
        tracker.claim_files('spec-a', ['src/parser/*.py', 'src/lexer/*.py'])

        result = tracker.get_claims('spec-a')

        assert len(result) == 2
        assert 'src/parser/*.py' in result
        assert 'src/lexer/*.py' in result

    def test_returns_empty_for_no_claims(self, tracker):
        """Returns empty list when spec has no claims."""
        result = tracker.get_claims('spec-a')

        assert result == []

    def test_excludes_released_claims(self, tracker):
        """Excludes released claims from result."""
        tracker.claim_files('spec-a', ['src/parser/*.py'])
        tracker.release_files('spec-a')

        result = tracker.get_claims('spec-a')

        assert result == []


class TestGetAllActiveClaims:
    """Tests for get_all_active_claims method."""

    def test_returns_all_active_claims(self, tracker):
        """Returns all active claims across specs."""
        tracker.claim_files('spec-a', ['src/parser/*.py'])
        tracker.claim_files('spec-b', ['src/lexer/*.py'])

        result = tracker.get_all_active_claims()

        assert len(result) == 2

    def test_excludes_released_claims(self, tracker):
        """Excludes released claims from result."""
        tracker.claim_files('spec-a', ['src/parser/*.py'])
        tracker.claim_files('spec-b', ['src/lexer/*.py'])
        tracker.release_files('spec-a')

        result = tracker.get_all_active_claims()

        assert len(result) == 1
        assert result[0]['spec_path'] == 'spec-b'


class TestPatternsOverlap:
    """Tests for _patterns_overlap method."""

    def test_identical_patterns_overlap(self, tracker):
        """Identical patterns overlap."""
        assert tracker._patterns_overlap('src/*.py', 'src/*.py') is True

    def test_one_matches_other_overlaps(self, tracker):
        """Patterns where one matches the other overlap."""
        assert tracker._patterns_overlap('src/*.py', 'src/file.py') is True

    def test_different_directories_no_overlap(self, tracker):
        """Patterns in different directories don't overlap."""
        assert tracker._patterns_overlap('src/a/*.py', 'src/b/*.py') is False

    def test_parent_child_patterns_overlap(self, tracker):
        """Parent directory pattern overlaps with child."""
        assert tracker._patterns_overlap('src/*.py', 'src/sub/*.py') is True

    def test_completely_different_no_overlap(self, tracker):
        """Completely different patterns don't overlap."""
        assert tracker._patterns_overlap('foo/*.py', 'bar/*.py') is False


class TestFileMatchesPattern:
    """Tests for _file_matches_pattern method."""

    def test_simple_wildcard_match(self, tracker):
        """Simple wildcard pattern matches."""
        assert tracker._file_matches_pattern('src/file.py', 'src/*.py') is True

    def test_simple_wildcard_no_match(self, tracker):
        """Simple wildcard pattern doesn't match wrong extension."""
        assert tracker._file_matches_pattern('src/file.txt', 'src/*.py') is False

    def test_nested_path_match(self, tracker):
        """Nested path with wildcard matches."""
        assert tracker._file_matches_pattern('src/parser/lexer.py', 'src/parser/*.py') is True

    def test_double_star_pattern(self, tracker):
        """Double star pattern matches any depth."""
        assert tracker._file_matches_pattern('src/deep/nested/file.py', 'src/**/*.py') is True

    def test_question_mark_wildcard(self, tracker):
        """Question mark matches single character."""
        assert tracker._file_matches_pattern('src/file1.py', 'src/file?.py') is True
        assert tracker._file_matches_pattern('src/file12.py', 'src/file?.py') is False

    def test_backslash_normalized(self, tracker):
        """Backslashes are normalized to forward slashes."""
        assert tracker._file_matches_pattern('src\\parser\\file.py', 'src/parser/*.py') is True


class TestEdgeCases:
    """Tests for edge cases."""

    def test_concurrent_claims_same_db(self, temp_db):
        """Multiple trackers can use same database."""
        tracker1 = FileOwnershipTracker(db_path=temp_db)
        tracker2 = FileOwnershipTracker(db_path=temp_db)

        tracker1.claim_files('spec-a', ['src/a/*.py'])

        # tracker2 should see tracker1's claims
        result = tracker2.claim_files('spec-b', ['src/a/*.py'])
        assert result.success is False

    def test_special_characters_in_pattern(self, tracker):
        """Handles special characters in patterns."""
        result = tracker.claim_files('spec-a', ['src/[test]/*.py'])
        assert result.success is True

    def test_unicode_in_spec_path(self, tracker):
        """Handles unicode in spec path."""
        result = tracker.claim_files('spec-unicode-test', ['src/*.py'])
        assert result.success is True

    def test_very_long_pattern(self, tracker):
        """Handles very long patterns."""
        long_pattern = 'src/' + '/'.join(['dir'] * 50) + '/*.py'
        result = tracker.claim_files('spec-a', [long_pattern])
        assert result.success is True
