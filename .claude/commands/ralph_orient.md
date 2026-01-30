# Orient to Ralph Pipeline

Immediately get up to speed on this project and the Ralph pipeline state.

## Instructions

Run through this checklist to understand the current state:

### 1. Read Project Configuration

```bash
cat ralph.config.json
```

Extract:
- Project name
- Tech stack (language, framework, runtime)
- MCP tools configured
- Source directory
- Max iterations setting

### 2. Check Pipeline Status

Look in `.ralph/state/` for:
- `specs/*.json` - Active spec states
- `message_bus.json` - Pending messages

Count specs by phase:
- `ARCHITECTURE` / `AWAITING_ARCH_APPROVAL`
- `IMPLEMENTATION` / `AWAITING_IMPL_APPROVAL`  
- `INTEGRATION` / `AWAITING_INTEG_APPROVAL`
- `COMPLETE` / `BLOCKED` / `FAILED`

### 3. Check for Pending Approvals

Any specs in `AWAITING_*` phases need user attention. List them prominently.

### 4. Scan Active Specs

```bash
ls Specs/Active/
```

For each spec directory, read `spec.json` to understand:
- What feature is being built
- Current phase and iteration
- Any errors from previous iterations

### 5. Quick Project Scan

Glance at the project structure to understand what exists:
- Main source directories
- Test locations
- Key configuration files

## Output Format

Present a clear orientation summary:

```
╔══════════════════════════════════════════════════════════════╗
║                    Ralph Pipeline - Oriented                 ║
╚══════════════════════════════════════════════════════════════╝

📁 Project: <name>
🔧 Stack: <language> / <framework> / <runtime>
🛠️  MCP Tools: <tools>

═══════════════════════════════════════════════════════════════

📊 Pipeline Status
───────────────────────────────────────────────────────────────
Active Specs: X
Pending Approval: Y ⚠️
Completed: Z
Blocked/Failed: W

⏳ In Progress:
  • <spec-name>: IMPLEMENTATION (iter 2/15)
  
⚠️ Needs Your Review:
  • <spec-name>: Architecture ready for approval
    └─ Run: /ralph:approve <spec-name>

═══════════════════════════════════════════════════════════════

📂 Project Structure
───────────────────────────────────────────────────────────────
<brief tree or key directories>

═══════════════════════════════════════════════════════════════

💡 Quick Actions
───────────────────────────────────────────────────────────────
• /ralph:new-spec    - Create a new feature spec
• /ralph:status      - Detailed pipeline status
• /ralph:approve     - Approve pending work
• /ralph:reject      - Reject with feedback
```

## If No ralph.config.json

The project hasn't been configured yet. Tell the user:

```
⚠️ Ralph not configured for this project yet.

Run: /ralph:detect-stack

This will analyze your project and create ralph.config.json
```

## If No Active Specs

```
✨ Pipeline is idle - no active specs.

Ready to start? Run: /ralph:new-spec
```

## Remember

You are the **Interface Agent**. Your job is to:
1. Help users create and refine specs
2. Present approval requests clearly  
3. Query status on demand
4. **Never implement features directly** - always use specs

The pipeline handles: Architecture → Implementation → Verification
You handle: User communication, spec drafting, approvals
