"""
Schema validation for the Ralph pipeline.

Validates specs, messages, and configs against JSON schemas.
"""

from typing import Dict, Any, List, Optional, Tuple
from pathlib import Path
import json

try:
    import jsonschema
    HAS_JSONSCHEMA = True
except ImportError:
    HAS_JSONSCHEMA = False


class ValidationError:
    """A single validation error."""
    
    def __init__(self, path: str, message: str):
        self.path = path
        self.message = message
    
    def __str__(self) -> str:
        return f"{self.path}: {self.message}"


class Validator:
    """
    Validates data against JSON schemas.
    
    Loads schemas from the schemas directory and caches them.
    """
    
    def __init__(self, schemas_dir: Optional[Path] = None):
        self.schemas_dir = schemas_dir
        self._schemas: Dict[str, Dict] = {}
        
        # Load built-in schemas
        self._load_builtin_schemas()
        
        # Load schemas from directory
        if schemas_dir and schemas_dir.exists():
            self._load_schemas_from_dir(schemas_dir)
    
    def _load_builtin_schemas(self) -> None:
        """Load built-in schemas."""
        # Minimal spec schema
        self._schemas["spec"] = {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "required": ["name"],
            "properties": {
                "id": {"type": "string"},
                "name": {"type": "string", "minLength": 1},
                "parent_id": {"type": ["string", "null"]},
                "phase": {"type": "string"},
                "is_leaf": {"type": ["boolean", "null"]},
                "problem": {"type": "string"},
                "success_criteria": {"type": "string"},
                "context": {"type": "string"},
                "provides": {"type": "array"},
                "requires": {"type": "array"},
                "shared_types": {"type": "array"},
                "classes": {"type": "array"},
                "children": {"type": "array"},
                "acceptance_criteria": {"type": "array"},
                "constraints": {"type": ["object", "null"]},
                "iteration": {"type": "integer", "minimum": 0},
                "max_iterations": {"type": "integer", "minimum": 1},
            },
        }
        
        # Message schema
        self._schemas["message"] = {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "required": ["type"],
            "properties": {
                "id": {"type": "string"},
                "from_id": {"type": "string"},
                "to_id": {"type": "string"},
                "spec_id": {"type": "string"},
                "type": {"type": "string"},
                "payload": {"type": "object"},
                "priority": {"type": "string"},
                "status": {"type": "string"},
            },
        }
        
        # Project config schema
        self._schemas["project_config"] = {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "required": ["name", "tech_stack"],
            "properties": {
                "name": {"type": "string"},
                "tech_stack": {
                    "type": "object",
                    "required": ["language"],
                    "properties": {
                        "language": {"type": "string"},
                        "runtime": {"type": "string"},
                        "frameworks": {"type": "array", "items": {"type": "string"}},
                        "test_framework": {"type": "string"},
                        "build_command": {"type": "string"},
                        "test_command": {"type": "string"},
                        "mcp_tools": {"type": "array", "items": {"type": "string"}},
                    },
                },
                "mcp_servers": {"type": "array"},
                "specs_dir": {"type": "string"},
                "source_dir": {"type": "string"},
                "max_iterations": {"type": "integer", "minimum": 1},
            },
        }
    
    def _load_schemas_from_dir(self, schemas_dir: Path) -> None:
        """Load schemas from a directory."""
        for schema_file in schemas_dir.glob("*.schema.json"):
            try:
                schema_name = schema_file.stem.replace(".schema", "")
                with open(schema_file, "r", encoding="utf-8") as f:
                    self._schemas[schema_name] = json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                print(f"Failed to load schema {schema_file}: {e}")
    
    def validate(
        self,
        data: Dict[str, Any],
        schema_name: str,
    ) -> Tuple[bool, List[ValidationError]]:
        """
        Validate data against a schema.
        
        Args:
            data: The data to validate
            schema_name: Name of the schema to use
            
        Returns:
            (is_valid, errors)
        """
        schema = self._schemas.get(schema_name)
        if not schema:
            return False, [ValidationError("", f"Unknown schema: {schema_name}")]
        
        if not HAS_JSONSCHEMA:
            # Can't validate without jsonschema, assume valid
            return True, []
        
        errors = []
        
        try:
            jsonschema.validate(data, schema)
        except jsonschema.ValidationError as e:
            path = ".".join(str(p) for p in e.absolute_path) or "root"
            errors.append(ValidationError(path, e.message))
        except jsonschema.SchemaError as e:
            errors.append(ValidationError("schema", f"Invalid schema: {e.message}"))
        
        return len(errors) == 0, errors
    
    def validate_spec(self, spec_data: Dict[str, Any]) -> Tuple[bool, List[ValidationError]]:
        """Validate spec data."""
        return self.validate(spec_data, "spec")
    
    def validate_message(self, message_data: Dict[str, Any]) -> Tuple[bool, List[ValidationError]]:
        """Validate message data."""
        return self.validate(message_data, "message")
    
    def validate_config(self, config_data: Dict[str, Any]) -> Tuple[bool, List[ValidationError]]:
        """Validate project config data."""
        return self.validate(config_data, "project_config")
    
    def get_schema(self, schema_name: str) -> Optional[Dict]:
        """Get a schema by name."""
        return self._schemas.get(schema_name)
    
    def list_schemas(self) -> List[str]:
        """List available schema names."""
        return list(self._schemas.keys())


# Global validator instance
_validator: Optional[Validator] = None


def get_validator(schemas_dir: Optional[Path] = None) -> Validator:
    """Get the global validator instance."""
    global _validator
    if _validator is None:
        _validator = Validator(schemas_dir)
    return _validator


def validate_spec(spec_data: Dict[str, Any]) -> Tuple[bool, List[ValidationError]]:
    """Convenience function to validate spec data."""
    return get_validator().validate_spec(spec_data)


def validate_message(message_data: Dict[str, Any]) -> Tuple[bool, List[ValidationError]]:
    """Convenience function to validate message data."""
    return get_validator().validate_message(message_data)


def validate_config(config_data: Dict[str, Any]) -> Tuple[bool, List[ValidationError]]:
    """Convenience function to validate config data."""
    return get_validator().validate_config(config_data)
