"""
Basic tests for the Ralph pipeline.
"""

import pytest
from pathlib import Path
import tempfile
import json


class TestPhase:
    """Tests for phase transitions."""
    
    def test_phase_transitions(self):
        from ralph.core.phase import Phase, can_transition
        
        # Valid transitions
        assert can_transition(Phase.DRAFT, Phase.READY)
        assert can_transition(Phase.READY, Phase.ARCHITECTURE)
        assert can_transition(Phase.ARCHITECTURE, Phase.AWAITING_ARCH_APPROVAL)
        
        # Invalid transitions
        assert not can_transition(Phase.DRAFT, Phase.IMPLEMENTATION)
        assert not can_transition(Phase.COMPLETE, Phase.ARCHITECTURE)
    
    def test_approval_phases(self):
        from ralph.core.phase import Phase, is_approval_phase
        
        assert is_approval_phase(Phase.AWAITING_ARCH_APPROVAL)
        assert is_approval_phase(Phase.AWAITING_IMPL_APPROVAL)
        assert not is_approval_phase(Phase.ARCHITECTURE)


class TestSpec:
    """Tests for spec types."""
    
    def test_spec_creation(self):
        from ralph.core.spec import create_spec, TechStack
        
        tech = TechStack(language="Python")
        spec = create_spec(
            name="test-feature",
            problem="Test problem",
            success_criteria="It works",
            tech_stack=tech,
        )
        
        assert spec.name == "test-feature"
        assert spec.problem == "Test problem"
        assert spec.get_effective_tech_stack().language == "Python"
    
    def test_spec_serialization(self):
        from ralph.core.spec import Spec, Phase
        
        spec = Spec(name="test", problem="testing")
        data = spec.to_dict()
        
        assert data["name"] == "test"
        assert data["phase"] == "draft"
        
        # Round-trip
        spec2 = Spec.from_dict(data)
        assert spec2.name == spec.name
        assert spec2.phase == spec.phase


class TestMessage:
    """Tests for message types."""
    
    def test_message_creation(self):
        from ralph.core.message import Message, MessageType
        
        msg = Message(
            from_id="spec-1",
            to_id="orchestrator",
            type=MessageType.PHASE_COMPLETE,
            payload={"phase": "architecture", "success": True},
        )
        
        assert msg.from_id == "spec-1"
        assert msg.type == MessageType.PHASE_COMPLETE
    
    def test_message_serialization(self):
        from ralph.core.message import Message, MessageType, MessageStatus
        
        msg = Message(
            from_id="test",
            to_id="orch",
            type=MessageType.ERROR_REPORT,
        )
        
        data = msg.to_dict()
        msg2 = Message.from_dict(data)
        
        assert msg2.from_id == msg.from_id
        assert msg2.type == msg.type


class TestToolRegistry:
    """Tests for tool registry."""
    
    def test_preset_loading(self):
        from ralph.tools.registry import get_tool_registry, reset_registry
        
        reset_registry()
        registry = get_tool_registry()
        
        # Check built-in presets
        assert registry.get_preset("python") is not None
        assert registry.get_preset("unity") is not None
        assert registry.get_preset("unknown") is None
    
    def test_tools_for_role(self):
        from ralph.tools.registry import get_tool_registry, reset_registry
        
        reset_registry()
        registry = get_tool_registry()
        
        # Implementer should have write access
        impl_tools = registry.get_tools_for_role("implementer", "python")
        assert "Write" in impl_tools["builtin_tools"]
        
        # Proposer should NOT have write access
        prop_tools = registry.get_tools_for_role("proposer", "python")
        assert "Write" not in prop_tools["builtin_tools"]
    
    def test_unity_mcp(self):
        from ralph.tools.registry import get_tool_registry, reset_registry
        
        reset_registry()
        registry = get_tool_registry()
        
        unity_preset = registry.get_preset("unity")
        assert unity_preset is not None
        assert len(unity_preset.mcp_servers) > 0
        assert unity_preset.mcp_servers[0].name == "unity"


class TestScopeEnforcement:
    """Tests for scope enforcement."""
    
    def test_path_allowed(self):
        from ralph.hooks.scope import is_path_allowed
        
        allowed = ["src/feature/", "tests/"]
        
        ok, _ = is_path_allowed("src/feature/main.py", allowed)
        assert ok
        
        ok, _ = is_path_allowed("src/other/file.py", allowed)
        assert not ok
    
    def test_tool_allowed(self):
        from ralph.hooks.scope import is_tool_allowed
        
        allowed = ["Read", "Write", "Bash"]
        
        ok, _ = is_tool_allowed("Read", allowed)
        assert ok
        
        ok, _ = is_tool_allowed("Task", allowed)
        assert not ok


class TestSpecStore:
    """Tests for spec persistence."""
    
    def test_save_and_load(self):
        from ralph.core.spec import Spec
        from ralph.orchestrator.spec_store import SpecStore
        
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SpecStore(Path(tmpdir))
            
            spec = Spec(name="test-spec", problem="Test problem")
            store.save(spec)
            
            loaded = store.get(spec.id)
            assert loaded is not None
            assert loaded.name == "test-spec"
    
    def test_list_by_phase(self):
        from ralph.core.spec import Spec
        from ralph.core.phase import Phase
        from ralph.orchestrator.spec_store import SpecStore
        
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SpecStore(Path(tmpdir))
            
            spec1 = Spec(name="spec1", phase=Phase.ARCHITECTURE)
            spec2 = Spec(name="spec2", phase=Phase.IMPLEMENTATION)
            
            store.save(spec1)
            store.save(spec2)
            
            arch_specs = store.list_by_phase(Phase.ARCHITECTURE)
            assert len(arch_specs) == 1
            assert arch_specs[0].name == "spec1"


class TestStateMachine:
    """Tests for state machine."""
    
    def test_valid_transition(self):
        from ralph.core.spec import Spec
        from ralph.core.phase import Phase
        from ralph.orchestrator.state_machine import StateMachine
        
        sm = StateMachine()
        spec = Spec(name="test", phase=Phase.DRAFT)
        
        result = sm.transition(spec, Phase.READY, "test")
        assert result.success
        assert spec.phase == Phase.READY
    
    def test_invalid_transition(self):
        from ralph.core.spec import Spec
        from ralph.core.phase import Phase
        from ralph.orchestrator.state_machine import StateMachine
        
        sm = StateMachine()
        spec = Spec(name="test", phase=Phase.DRAFT)
        
        result = sm.transition(spec, Phase.IMPLEMENTATION, "test")
        assert not result.success
        assert spec.phase == Phase.DRAFT  # Unchanged


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
