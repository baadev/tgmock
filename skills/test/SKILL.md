---
name: tgmock:test
description: Test and debug Telegram bots through tgmock inside Codex. Use this skill whenever the user wants to exercise a Telegram bot flow, verify buttons, debug startup or response issues, or explicitly mentions tg_start, tg_send, tg_tap, tg_snapshot, tg_logs, tg_restart, or tg_reset.
---

You are testing a Telegram bot through `tgmock` MCP tools inside Codex.

## Core rules

1. Inspect the target project first.
   - Confirm the project root.
   - Confirm how the bot is started.
   - Confirm the likely readiness log if startup is not already configured.

2. Start explicitly with `project_root`.
   - Use `tg_start(project_root=...)` unless you are certain the MCP server already runs from the correct root.

3. Test the flow directly.
   - `tg_send` for user messages
   - `tg_tap` for inline keyboard buttons
   - `tg_snapshot` for current state
   - `tg_events` for side effects
   - `tg_logs` for stdout/stderr diagnosis

4. Clean up.
   - Use `tg_stop()` when the session is no longer needed.

## Typical flow

```text
tg_start(project_root="...")
tg_send("/start")
tg_snapshot()
tg_tap("Settings")
tg_logs()
tg_stop()
```

## Testing patterns

### Command flow

- send `/start`
- confirm greeting text
- send `/help`
- confirm help text

### Button flow

- call `tg_send` to render the menu
- call `tg_tap("Visible button label")`
- inspect the next snapshot

### Multi-step flow

- send the first command
- answer each question with `tg_send`
- inspect snapshots between steps when the branch matters

### Multi-user flow

Use `user_id` to keep sessions independent:

```text
tg_send("hello", user_id=111)
tg_send("hello", user_id=222)
tg_snapshot(user_id=222)
```

### Side-effect assertions

If the bot posts structured test events, inspect them with `tg_events(type="...")` instead of inferring everything from UI text.

## Debugging workflow

When the bot fails or times out:

1. read `tg_logs()`
2. inspect `tg_snapshot()`
3. inspect `tg_events()`
4. use `tg_restart(project_root=...)` if the process needs a clean restart

## Practical guidance

- `tg_tap` does partial case-insensitive matching.
- Reply keyboard buttons should usually be sent through `tg_send("Button text")`.
- `tg_reset(user_id=...)` is cheaper than restarting the whole session when only one user state is dirty.
- If startup problems persist, fix configuration first instead of brute-forcing more test steps.
