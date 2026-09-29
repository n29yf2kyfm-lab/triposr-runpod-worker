---
name: claude-agent-sdk
description: Build an app that runs Claude Code's agent loop inside it, with the Claude Agent SDK for Python (`claude-agent-sdk`). Use when the user wants an agent in their own program: a one-off task (`query()`), a multi-turn session (`ClaudeSDKClient`), custom tools (`@tool` + `create_sdk_mcp_server`), permissions and hooks that gate what the agent may do, or reading back cost, usage and the session id. Triggers: "Agent SDK", "claude-agent-sdk", "put Claude Code in my app", "agent loop in Python", "custom tool for Claude", "ClaudeSDKClient", "ClaudeAgentOptions". Not for plain Messages API calls (use the claude-api skill) and not for Claude Code CLI setup.
---

# Claude Agent SDK (Python)

The SDK puts Claude Code's agent loop inside your application. The loop is:

**prompt → Claude reasons → tools act → result**, and each tool result comes back
as new context for the next turn. The model reasons, the SDK executes the tools,
and your app decides what the agent is allowed to reach.

Every name below was checked against the installed package (`claude-agent-sdk`
0.2.161, 2026-09-29) and the official reference at
https://code.claude.com/docs/en/agent-sdk/python. If the installed version is
newer, confirm a field exists before using it:

```bash
python -c "import dataclasses, claude_agent_sdk as s; print([f.name for f in dataclasses.fields(s.ClaudeAgentOptions)])"
```

Never guess an option name. A wrong name raises `TypeError` at construction.
That is the good case. The bad case is a wrong *value* that is silently ignored.

## The six steps, in order

### 01 Start

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install claude-agent-sdk
```

The SDK drives the Claude Code runtime, so the machine needs that runtime and a
credential for it (`ANTHROPIC_API_KEY`, or a configured Claude Code login). Keep
keys in the environment. Never put them in source or in a tracked file.

### 02 Pick the interface

| you want | use |
|---|---|
| one task, fresh session, then done | `query()` |
| a conversation: follow-ups keep context, can interrupt | `ClaudeSDKClient` |

```python
import asyncio
from claude_agent_sdk import query, ClaudeAgentOptions

async def main():
    options = ClaudeAgentOptions(
        system_prompt="You are a careful Python reviewer.",
        allowed_tools=["Read", "Grep", "Glob"],     # read-only: least privilege
        max_turns=8,
        max_budget_usd=0.50,
    )
    async for message in query(prompt="Find unused imports in src/", options=options):
        print(message)

asyncio.run(main())
```

```python
from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions

async def chat():
    async with ClaudeSDKClient(options=ClaudeAgentOptions(allowed_tools=["Read"])) as client:
        await client.query("Summarise README.md")
        async for message in client.receive_response():   # stops at the ResultMessage
            print(message)
        await client.query("Now list its section headings")  # same session, same context
        async for message in client.receive_response():
            print(message)
```

`ClaudeSDKClient` methods: `connect()`, `query(prompt, session_id=...)`,
`receive_messages()`, `receive_response()`, `interrupt()`, `disconnect()`.

### 03 Control the agent: tools and permissions define its reach

`ClaudeAgentOptions` fields that decide reach and cost:

- `allowed_tools` / `disallowed_tools`: lists of tool names (`"Read"`, `"Edit"`,
  `"Bash"`, `"Glob"`, `"Grep"`, `"mcp__<server>__<tool>"`).
- `permission_mode`: one of `"default"`, `"acceptEdits"`, `"plan"`, `"dontAsk"`,
  `"bypassPermissions"`, `"auto"`. Do not use `"bypassPermissions"` outside a
  throwaway sandbox.
- `cwd`, `add_dirs`: where the agent may work.
- `max_turns`, `max_budget_usd`: hard caps. Set both in anything unattended.
- `system_prompt`, `model`, `mcp_servers`, `hooks`, `can_use_tool`, `sandbox`.

Hooks validate, block, audit and log. A hook is an async function
`(input, tool_use_id, context) -> dict`. It is registered per event with a
`HookMatcher`:

```python
from claude_agent_sdk import ClaudeAgentOptions, HookMatcher

async def no_rm(input, tool_use_id, context):
    cmd = input.get("tool_input", {}).get("command", "")
    if "rm -rf" in cmd:
        return {"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": "Destructive delete blocked by policy.",
        }}
    return {}

options = ClaudeAgentOptions(
    allowed_tools=["Bash", "Read"],
    hooks={"PreToolUse": [HookMatcher(matcher="Bash", hooks=[no_rm])]},
)
```

`permissionDecision` takes `"allow"`, `"deny"`, `"ask"` or `"defer"`. The hook
events are `PreToolUse`, `PostToolUse`, `PostToolUseFailure`, `UserPromptSubmit`,
`Stop`, `SubagentStart`, `SubagentStop`, `PreCompact`, `Notification` and
`PermissionRequest`.

**Prove a hook fires.** A deny hook that never matches looks exactly like a
policy that is working. Before you trust it, run it once against an input it
must block and once against an input it must allow.

### 04 Extend: built-ins, custom tools, MCP

The built-in tools include Read, Edit, Write, Bash, Glob and Grep. Custom tools
are Python functions served as an in-process MCP server:

```python
from claude_agent_sdk import tool, create_sdk_mcp_server, ClaudeAgentOptions

@tool("stock_level", "Litres of a fluid in stock", {"fluid": str})
async def stock_level(args):
    litres = {"oil": 12.5, "coolant": 4.0}.get(args["fluid"], 0.0)
    return {"content": [{"type": "text", "text": f"{litres} L"}]}

shop = create_sdk_mcp_server(name="shop", version="1.0.0", tools=[stock_level])

options = ClaudeAgentOptions(
    mcp_servers={"shop": shop},
    allowed_tools=["mcp__shop__stock_level"],   # mcp__<server key>__<tool name>
)
```

The server key in `mcp_servers` becomes the middle part of the tool name. If the
allowed name does not match, the tool is never offered and nothing reports an error.

### 05 Capture the result

The last message is a `ResultMessage`. Save these fields for every run:

```python
from claude_agent_sdk import ResultMessage, AssistantMessage, TextBlock

async for message in query(prompt=task, options=options):
    if isinstance(message, AssistantMessage):
        for block in message.content:
            if isinstance(block, TextBlock):
                print(block.text)
    elif isinstance(message, ResultMessage):
        record = {
            "status": message.subtype,          # "success", "error_max_turns", ...
            "is_error": message.is_error,
            "session_id": message.session_id,   # resume later with options.resume
            "cost_usd": message.total_cost_usd,
            "usage": message.usage,             # input/output/cache token counts
            "turns": message.num_turns,
            "ms": message.duration_ms,
            "result": message.result,
        }
```

Tool results become the next turn's context, so a run's cost grows with how
much the tools return. Return compact tool output.

### 06 Ship safely

- **Least privilege.** Start from read-only tools and add only what the task needs.
- **Cap cost.** Set `max_budget_usd` and `max_turns` on every unattended run.
- **Verify outputs.** Check what the agent wrote: run the tests, diff the files.
  A success status only means the loop finished.
- **Log every run.** Store `session_id`, cost, usage, status and denied
  permissions (`permission_denials`).
- **Keep secrets out of reach.** Do not give Bash to an agent that runs where
  the credentials live, unless a hook blocks reading them.

## Who does what

| model reasons | SDK executes | your app enforces |
|---|---|---|
| plans, picks tools, writes | runs tools, streams messages, tracks cost | allowed tools, hooks, caps, what gets saved |

## Related

- Plain Messages API calls, prompt caching and model choice: the `claude-api` skill.
- TypeScript: `@anthropic-ai/claude-agent-sdk` has the same concepts; check its
  reference for exact names rather than translating these.
