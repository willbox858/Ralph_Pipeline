"""
Spec Store for the Ralph pipeline.

Handles persistence, retrieval, and management of specs.
Uses JSON files for human-readable, diffable storage.
"""

from typing import Optional, List, Dict
from pathlib import Path
import json
import shutil
from datetime import datetime, timezone

from ..core.spec import Spec, ChildRef, create_child_spec
from ..core.phase import Phase


class SpecStore:
    """
    Manages spec storage and retrieval.
    
    Specs are stored as JSON files in the specs directory.
    Structure:
        specs_dir/
        └── {spec_name}/
            ├── spec.json
            ├── research.json (optional)
            ├── architecture.json (optional)
            └── children/
                └── {child_name}/
                    └── spec.json
    """
    
    def __init__(self, specs_dir: Path):
        """
        Initialize the spec store.
        
        Args:
            specs_dir: Base directory for specs (e.g., Specs/Active)
        """
        self.specs_dir = specs_dir
        self.specs_dir.mkdir(parents=True, exist_ok=True)
        
        # In-memory cache
        self._cache: Dict[str, Spec] = {}
    
    def save(self, spec: Spec) -> Path:
        """
        Save a spec to disk.
        
        Args:
            spec: The spec to save
            
        Returns:
            Path to the saved spec.json
        """
        # Determine directory
        if spec.spec_dir:
            spec_dir = Path(spec.spec_dir)
        else:
            spec_dir = self.specs_dir / spec.name
        
        spec_dir.mkdir(parents=True, exist_ok=True)
        spec.spec_dir = str(spec_dir)
        
        # Update timestamp
        spec.touch()
        
        # Save to file
        spec_file = spec_dir / "spec.json"
        spec_file.write_text(
            json.dumps(spec.to_dict(), indent=2),
            encoding="utf-8"
        )
        
        # Update cache
        self._cache[spec.id] = spec
        
        return spec_file
    
    def load(self, spec_path: Path) -> Optional[Spec]:
        """
        Load a spec from disk.
        
        Args:
            spec_path: Path to spec.json or spec directory
            
        Returns:
            Loaded Spec, or None if not found
        """
        # Handle both file and directory paths
        if spec_path.is_dir():
            spec_file = spec_path / "spec.json"
        else:
            spec_file = spec_path
            spec_path = spec_file.parent
        
        if not spec_file.exists():
            return None
        
        try:
            data = json.loads(spec_file.read_text(encoding="utf-8"))
            spec = Spec.from_dict(data)
            spec.spec_dir = str(spec_path)
            
            # Update cache
            self._cache[spec.id] = spec
            
            return spec
        except (json.JSONDecodeError, KeyError) as e:
            print(f"Failed to load spec from {spec_file}: {e}")
            return None
    
    def get(self, spec_id: str) -> Optional[Spec]:
        """
        Get a spec by ID (from cache or disk).
        
        Args:
            spec_id: The spec ID
            
        Returns:
            Spec if found, None otherwise
        """
        # Check cache first
        if spec_id in self._cache:
            return self._cache[spec_id]
        
        # Search for spec file
        for spec_dir in self.specs_dir.rglob("spec.json"):
            spec = self.load(spec_dir)
            if spec and spec.id == spec_id:
                return spec
        
        return None
    
    def get_by_name(self, name: str) -> Optional[Spec]:
        """
        Get a spec by name.
        
        Args:
            name: The spec name
            
        Returns:
            Spec if found, None otherwise
        """
        # Check cache
        for spec in self._cache.values():
            if spec.name == name:
                return spec
        
        # Check directory
        spec_dir = self.specs_dir / name
        if spec_dir.exists():
            return self.load(spec_dir)
        
        return None
    
    def list_all(self) -> List[Spec]:
        """
        List all specs in the store.
        
        Returns:
            List of all specs
        """
        specs = []
        
        for spec_file in self.specs_dir.rglob("spec.json"):
            spec = self.load(spec_file)
            if spec:
                specs.append(spec)
        
        return specs
    
    def list_by_phase(self, phase: Phase) -> List[Spec]:
        """List specs in a specific phase."""
        return [s for s in self.list_all() if s.phase == phase]
    
    def list_children(self, parent_id: str) -> List[Spec]:
        """List child specs of a parent."""
        return [s for s in self.list_all() if s.parent_id == parent_id]
    
    def list_roots(self) -> List[Spec]:
        """List root specs (no parent)."""
        return [s for s in self.list_all() if s.parent_id is None]
    
    def delete(self, spec_id: str) -> bool:
        """
        Delete a spec and its directory.
        
        Args:
            spec_id: The spec ID to delete
            
        Returns:
            True if deleted, False if not found
        """
        spec = self.get(spec_id)
        if not spec or not spec.spec_dir:
            return False
        
        spec_dir = Path(spec.spec_dir)
        if spec_dir.exists():
            shutil.rmtree(spec_dir)
        
        # Remove from cache
        self._cache.pop(spec_id, None)
        
        return True
    
    def create_children(self, parent: Spec) -> List[Spec]:
        """
        Create child spec directories from parent's children list.
        
        Args:
            parent: Parent spec with children defined
            
        Returns:
            List of created child specs
        """
        if not parent.spec_dir:
            raise ValueError("Parent spec must have spec_dir set")
        
        parent_dir = Path(parent.spec_dir)
        children_dir = parent_dir / "children"
        children_dir.mkdir(exist_ok=True)
        
        created = []
        
        for child_ref in parent.children:
            # Create child spec from reference
            child_spec = create_child_spec(parent, child_ref)
            child_spec.spec_dir = str(children_dir / child_ref.name)
            
            # Save child
            self.save(child_spec)
            created.append(child_spec)
        
        return created
    
    def get_siblings(self, spec: Spec) -> List[Spec]:
        """
        Get sibling specs (same parent).
        
        Args:
            spec: The spec to find siblings for
            
        Returns:
            List of sibling specs (excluding the spec itself)
        """
        if not spec.parent_id:
            return []
        
        siblings = self.list_children(spec.parent_id)
        return [s for s in siblings if s.id != spec.id]
    
    def get_parent(self, spec: Spec) -> Optional[Spec]:
        """
        Get parent spec.
        
        Args:
            spec: The spec to find parent for
            
        Returns:
            Parent spec if exists, None otherwise
        """
        if not spec.parent_id:
            return None
        return self.get(spec.parent_id)
    
    def refresh_cache(self) -> None:
        """Clear cache and reload all specs."""
        self._cache.clear()
        self.list_all()  # This repopulates the cache
    
    def get_stats(self) -> Dict[str, any]:
        """Get statistics about stored specs."""
        specs = self.list_all()
        
        by_phase = {}
        for spec in specs:
            phase = spec.phase.value
            by_phase[phase] = by_phase.get(phase, 0) + 1
        
        return {
            "total": len(specs),
            "by_phase": by_phase,
            "roots": len([s for s in specs if s.parent_id is None]),
            "leaves": len([s for s in specs if s.is_leaf is True]),
        }
