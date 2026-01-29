# Project Style Guide

This document defines conventions for AI agents working on this project.
Update as preferences evolve—agents will follow the latest version.

---

## Code Style

### Language: C#

**Naming:**
- PascalCase for public members, types, methods
- _camelCase for private fields (with underscore prefix)
- Interfaces prefixed with `I` (e.g., `ICalculator`)

**Formatting:**
- Allman brace style (braces on new lines)
- 4-space indentation
- Max line length: 120 characters

**Preferences:**
- Prefer expression-bodied members for single-line getters
- Use `var` only when type is obvious from right-hand side
- Prefer `readonly` for fields that don't change after construction
- Use records for pure data types, classes for behavior

**Example:**
```csharp
public class BasicAttack : IAttack
{
    private readonly IDamageCalculator _damageCalculator;
    
    public string Name => "Basic Attack";
    
    public BasicAttack(IDamageCalculator damageCalculator)
    {
        _damageCalculator = damageCalculator;
    }
    
    public DamageResult Execute(ICombatant attacker, ICombatant target)
    {
        var damage = _damageCalculator.Calculate(attacker, target);
        return new DamageResult(damage, DamageType.Physical);
    }
}
```

---

## Architecture Style

**General Principles:**
- Prefer composition over inheritance
- Depend on abstractions (interfaces), not concretions
- Single responsibility—one reason to change per class
- Keep classes small (<200 lines preferred)

**Decomposition:**
- Err toward smaller, more focused specs (more leaves)
- If a component does 2 distinct things, split it
- Shared types go in `shared/` child, not duplicated

**Interface Design:**
- Interfaces should be focused (Interface Segregation)
- Prefer `IVerbNoun` naming (e.g., `ICalculateDamage`, `IParseExpression`)
- Methods should do one thing

**Dependency Management:**
- Constructor injection for required dependencies
- No service locators or static access
- Avoid circular dependencies between siblings

---

## Testing Style

**Naming:**
- Test classes: `{ClassName}Tests`
- Test methods: `{Method}_{Scenario}_{Expected}`
- Example: `Calculate_DivideByZero_ThrowsException`

**Structure:**
- Arrange / Act / Assert pattern
- One assertion per test (conceptually)
- Use descriptive variable names in tests

**Coverage:**
- Every acceptance criterion = at least one test
- Edge cases should have explicit tests
- Happy path + error paths

---

## Documentation Style

**Code Comments:**
- Public APIs get XML docs
- Complex algorithms get inline explanations
- Don't comment obvious code

**Agent Messages:**
- Format: `[component] action: brief description`
- Example: `[Parser] feat: add support for negative numbers`

---

## Console Output

**ASCII Only:**
- Use only base ASCII characters in console output (codes 0-127)
- Avoid Unicode symbols like `✓`, `✗`, `→`, `•`, etc.
- Windows terminals often have encoding issues with non-ASCII
- Use ASCII alternatives: `[OK]`, `[X]`, `->`, `-`, `*`

**Good:**
```python
print("[OK] Task completed")
print("[  ] Task pending")
print("  -> Next step")
```

**Bad:**
```python
print("✓ Task completed")   # Windows encoding error
print("○ Task pending")      # Won't display correctly
print("  → Next step")       # Breaks on cp1252
```

---

## Anti-Patterns to Avoid

- God classes (>500 lines, does everything)
- Primitive obsession (use domain types)
- Stringly-typed code (use enums/types)
- Deep inheritance hierarchies (max 2 levels)
- Public fields (use properties)
- Magic numbers (use named constants)
- Unicode symbols in console output (encoding issues)

---

## Project-Specific Conventions

<!-- Add your project-specific rules here -->

- Domain models live in `src/Domain/`
- Infrastructure in `src/Infrastructure/`
- Tests mirror source structure in `tests/`

---

*Last updated: 2026-01-28*
