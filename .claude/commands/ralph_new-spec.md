# Create New Ralph Spec

Help the user draft a new feature spec for the pipeline.

## Instructions

Guide the user through creating a spec by asking about:

1. **Name**: A short, kebab-case identifier (e.g., `user-authentication`)
2. **Problem**: What problem does this solve? Why is it needed?
3. **Success Criteria**: How will we know when it's done?
4. **Context**: Any relevant background, constraints, or dependencies
5. **Acceptance Criteria**: Specific behaviors to verify

## Spec Template

Create the spec in `Specs/Active/<name>/spec.json`:

```json
{
  "name": "<name>",
  "problem": "<problem description>",
  "success_criteria": "<how we know it's done>",
  "context": "<background and constraints>",
  "acceptance_criteria": [
    {
      "id": "AC-1",
      "behavior": "<when X happens, Y should occur>"
    }
  ],
  "constraints": {
    "allowed_paths": ["src/<relevant-paths>/"],
    "forbidden_patterns": []
  }
}
```

## Tips

- Keep specs focused - one feature per spec
- Be specific about acceptance criteria
- If the feature is large, consider breaking it into multiple specs
- Reference existing code patterns when relevant

## After Creation

Tell the user:
1. The spec has been created at `Specs/Active/<name>/spec.json`
2. They can review and edit it before submitting
3. Use `/ralph:submit <name>` to start the pipeline (or it will auto-start)
