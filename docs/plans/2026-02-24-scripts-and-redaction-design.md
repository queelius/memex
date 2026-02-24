# Scripts Framework & Redaction — Design Document

**Date:** 2026-02-24
**Status:** Draft

## Summary

A convention-based scripts framework for memex, plus a `redact` script for content sanitization. Scripts are discoverable modules in `memex/scripts/` (built-in) and `~/.memex/scripts/` (user). The CLI runs them via `memex run <name>`. The first built-in script is `redact` — a composable tool for removing profanity, PII, and sensitive content from conversations.

## Motivation

When sharing conversation exports (HTML SPA, markdown, JSON), the database may contain:
- Profanity — casual swearing in otherwise shareable conversations
- PII — email addresses, phone numbers, API keys leaked in message text
- Personal content — conversations about private matters

The `sensitive` flag handles visibility gating ("hide this from exports"), but doesn't mutate content. Redaction is a separate concern: actually removing or masking content so the database itself is safe to share.

## Design Principles

- **`sensitive` and redaction are orthogonal.** `sensitive` = visibility control (keep but hide). Redaction = content mutation (change or delete). Don't conflate them.
- **Dry-run by default.** Every script defaults to read-only. `--apply` commits changes.
- **Reversible mutations.** Before any content rewrite, store the original as an enrichment. Undo is possible.
- **Composable passes.** Run the redact script multiple times with different word sets and levels. Each pass is independent. Start broad (profanity word list), then get surgical (specific personal topics).

## Scripts Framework

### Convention

Each script is a Python module with:

```python
"""One-line description shown by 'memex run --list'."""

def register_args(parser: argparse.ArgumentParser):
    """Add script-specific arguments."""
    parser.add_argument("--words", ...)

def run(db: Database, args: argparse.Namespace, apply: bool = False) -> dict:
    """Execute the script. Return a summary dict."""
    ...
```

The framework provides `--db`, `--apply`, and `--verbose` automatically. Scripts receive an open `Database` instance (readonly when `apply=False`, writable when `apply=True`).

### Discovery

1. Built-in: `memex/scripts/` (shipped with package)
2. User: `~/.memex/scripts/` (user-created, same convention)
3. User scripts shadow built-in scripts of the same name.

### CLI

```bash
memex run --list                    # Show available scripts with descriptions
memex run redact [args]             # Dry-run by default
memex run redact [args] --apply     # Commit changes
memex run enrich-trivial --apply    # Migrated from scripts/enrich_trivial.py
```

### Migration

`scripts/enrich_trivial.py` becomes `memex/scripts/enrich_trivial.py`, refactored to the convention interface. The standalone `scripts/` dir is retired.

## Redact Script

### Interface

```bash
# Literal word matching
memex run redact --words "fuck,shit,damn" --any --level word

# Regex pattern matching (API keys, emails, etc.)
memex run redact --patterns "sk-[a-zA-Z0-9]{20,}" --any --level word

# Built-in pattern files
memex run redact --pattern-file api_keys.txt --any --level word

# Combine words and patterns
memex run redact --words "fuck,shit" --patterns "\b\d{3}-\d{3}-\d{4}\b" --any --level word

# Match mode: any term triggers (default) vs all terms must appear
memex run redact --words "drunk,wife,kim" --all --level message

# Redaction levels
memex run redact --words "fuck" --any --level word           # inline [REDACTED]
memex run redact --words "drunk,kim" --all --level message   # whole message → [REDACTED]
memex run redact --words "cancer,chemo" --all --level conversation  # delete conversation
```

### Arguments

| Argument | Description |
|---|---|
| `--words` | Comma-separated literal terms to match (case-insensitive) |
| `--patterns` | Comma-separated regex patterns to match |
| `--pattern-file` | Path to a file with one pattern per line (supports comments with `#`) |
| `--any` | Trigger if **any** term/pattern matches (default) |
| `--all` | Trigger only if **all** terms/patterns match |
| `--level` | `word` (inline redact), `message` (replace entire message), `conversation` (delete) |
| `--yes` | Skip interactive review, apply all redactions without prompting |
| `--apply` | Commit changes (default: dry-run). Interactive review by default — prompts for each match. |

### Redaction Levels

| Level | Detection scope | Action |
|---|---|---|
| `word` | Scan message text for matching terms/patterns | Replace each match with `[REDACTED]` inline |
| `message` | Scan message text for matching terms/patterns | Replace entire message content with `[{"type": "text", "text": "[REDACTED]"}]` |
| `conversation` | Scan all messages in conversation | Delete conversation from database |

### Match Modes

- **`--any`** (default): A message matches if it contains at least one word/pattern. Natural for profanity lists — any hit is a hit.
- **`--all`**: A message matches only if it contains every specified word/pattern. Natural for topical detection — "drunk" alone is fine, "drunk" + "wife" + "kim" together means something specific.

For `--level conversation` with `--all`: the terms can appear across different messages in the same conversation (not all required in a single message).

### Built-in Pattern Files

Shipped in `memex/scripts/patterns/`:

| File | Contents |
|---|---|
| `api_keys.txt` | OpenAI `sk-`, GitHub `ghp_`/`gho_`, AWS `AKIA`, generic base64 secrets |
| `pii.txt` | Email addresses, phone numbers, SSN patterns |

Users can add their own pattern files in `~/.memex/scripts/patterns/`.

### Dry-Run Output

```
Scanning 2218 conversations...

  [WORD]  conv abc123... msg m7: "what the [fuck] is this code"
  [WORD]  conv abc123... msg m12: "this [shit] doesn't work"
  [MSG]   conv def456... msg m3: matches all: drunk, wife, kim
  [CONV]  conv ghi789...: matches all across messages: cancer, diagnosis

Summary:
  Word-level redactions:  47 words across 31 messages
  Message-level redactions: 3 messages
  Conversation deletions: 2 conversations

Re-run with --apply to commit changes (interactive review).
Re-run with --apply --yes to commit all without review.
```

Three modes:
1. **No flags** — dry-run. Shows what would be hit, changes nothing.
2. **`--apply`** — interactive. Prompts for each match: redact, skip, all, quit.
3. **`--apply --yes`** — batch. Applies all redactions without prompting.

### Interactive Mode (Default)

When `--apply` is used, interactive review is the default. Each match is presented for review:

```
[1/47] conv abc123... msg m7:
  "what the →fuck← is this code"
  [r]edact  [s]kip  [a]ll (redact all "fuck")  [q]uit
> r
  ✓ redacted

[2/47] conv abc123... msg m12:
  "this →shit← doesn't work"
  [r]edact  [s]kip  [a]ll (redact all "shit")  [q]uit
> a
  ✓ redacting all "shit" (12 remaining matches)

[15/47] conv def456... msg m3:
  "I got →drunk← and told →kim← about..."
  [r]edact  [s]kip  [q]uit
> r
  ✓ redacted (message-level)
```

Actions:
- **r** — redact this match
- **s** — skip (leave unchanged)
- **a** — redact this and all remaining matches of the same term (auto-pilot for one word)
- **q** — stop, apply what's been approved so far

This lets you eyeball context before committing. Especially useful for `--all` matches where you want to verify the combination actually refers to what you think.

### Reversibility

Before any mutation, the script stores the original content:

- **Word/message level**: Save original message content as an enrichment:
  - `type="original_content"`, `value=<original JSON>`, `source="redact"`
  - Keyed by `(conversation_id, "original_content", message_id)` — uses the message_id as the enrichment value identifier
- **Conversation level**: No preservation (it's a delete). User should back up the DB first if they want undo.

A future `memex run unredact` script could restore original content from these enrichments.

### Content Block Handling

Messages store content as JSON arrays of content blocks. Redaction operates on text blocks only:

```python
# Word-level: scan and replace within text blocks
for block in content:
    if block["type"] == "text":
        block["text"] = apply_redactions(block["text"], matches)

# Message-level: replace entire content array
message.content = [{"type": "text", "text": "[REDACTED]"}]
```

Non-text blocks (media, tool_use, tool_result, thinking) are left untouched by word-level redaction. Message-level redaction replaces everything.

## Typical Workflow

```bash
# 1. Blast all profanity (easy win — skip interactive for known-bad words)
memex run redact --words "fuck,shit,damn,ass,bitch,crap" --any --level word          # dry-run first
memex run redact --words "fuck,shit,damn,ass,bitch,crap" --any --level word --apply --yes

# 2. Strip API keys and PII
memex run redact --pattern-file api_keys.txt --any --level word
memex run redact --pattern-file pii.txt --any --level word --apply

# 3. Remove specific personal conversations (interactive — review each match)
memex run redact --words "cancer,chemo,diagnosis" --all --level conversation          # dry-run
memex run redact --words "cancer,chemo,diagnosis" --all --level conversation --apply  # interactive review

# 4. Fine-tune specific situations
memex run redact --words "drunk,kim" --all --level message --apply

# 5. Export clean DB
memex export --format html --output ./public/memex/
```

## Not In Scope

- **AI-powered classification** — Claude reading conversations to flag private topics. Future script.
- **AI-powered rewriting** — coherent rephrasing instead of `[REDACTED]`. Future script.
- **Severity auto-escalation** — automatically promoting word-level to message-level based on density. Keep it manual.
- **Sensitive flag interaction** — redaction and `sensitive` are independent systems.

## Files

```
memex/
  scripts/
    __init__.py          # Discovery + runner utilities
    enrich_trivial.py    # Migrated from scripts/enrich_trivial.py
    redact.py            # Redaction script
    patterns/
      api_keys.txt       # Built-in API key patterns
      pii.txt            # Built-in PII patterns
  cli.py                 # Add 'memex run' subcommand
```
