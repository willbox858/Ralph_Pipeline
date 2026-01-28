# Create New Ralph Spec

Create a new spec for a feature to be built by Ralph.

## Arguments

This command accepts a feature name:
```
/spec calculator
/spec "user authentication"
```

## What This Does

1. Creates the directory structure
2. Copies the spec template
3. Opens for editing with user

## Directory Structure Created

```
Specs/Active/<feature-name>/
├── spec.json          # The main spec file
└── (children/ created later by orchestrator)
```

## Interactive Spec Building

After creating the template, work with the user to fill in:

### 1. Basic Info
```json
{
  "name": "calculator",
  "version": "1.0.0",
  "description": "A calculator that parses and evaluates expressions"
}
```

### 2. Features (what it should do)
```json
{
  "features": [
    {
      "id": "F-001",
      "name": "Expression Parsing",
      "description": "Parse mathematical expressions from strings"
    },
    {
      "id": "F-002", 
      "name": "Expression Evaluation",
      "description": "Evaluate parsed expressions to numeric results"
    }
  ]
}
```

### 3. Interfaces (inputs/outputs)
```json
{
  "interfaces": {
    "consumes": [
      {"name": "expression", "type": "string", "description": "Math expression like '2 + 3 * 4'"}
    ],
    "produces": [
      {"name": "result", "type": "number", "description": "Evaluated result"}
    ]
  }
}
```

### 4. Acceptance Criteria
```json
{
  "criteria": {
    "acceptance": [
      {"id": "AC-001", "description": "Parses basic arithmetic (+, -, *, /)"},
      {"id": "AC-002", "description": "Handles operator precedence correctly"},
      {"id": "AC-003", "description": "Supports parentheses for grouping"}
    ]
  }
}
```

## Tips

- **Start high-level**: Let the Proposer/Critic decide decomposition
- **Be specific on criteria**: Clear pass/fail conditions
- **Define interfaces**: What goes in, what comes out
- **Note constraints**: Language, libraries, patterns to follow

## After Creation

Run the pipeline:
```
/ralph Specs/Active/<feature-name>/spec.json
```

Monitor progress:
```
/status Specs/Active/<feature-name>/spec.json
```
