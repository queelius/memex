"""Redact sensitive content from conversations (word/message/conversation level)."""
from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# ── Data Structures ─────────────────────────────────────────────


@dataclass
class Match:
    conversation_id: str
    message_id: str
    term: str
    start: int
    end: int
    block_index: int


@dataclass
class ScanResult:
    conversation_id: str
    message_id: str
    matches: list[Match] = field(default_factory=list)
    content: list[dict] = field(default_factory=list)


# ── Detection Engine ────────────────────────────────────────────


def compile_matchers(words=None, patterns=None, pattern_file=None):
    """Compile words and patterns into a list of (compiled_regex, label) tuples.

    Words get word-boundary matching and case-insensitive flags.
    Patterns are used as-is.
    """
    matchers = []

    if words:
        for word in words:
            regex = re.compile(r"\b" + re.escape(word) + r"\b", re.IGNORECASE)
            matchers.append((regex, word))

    if patterns:
        for pattern in patterns:
            regex = re.compile(pattern)
            matchers.append((regex, pattern))

    if pattern_file:
        file_patterns = load_pattern_file(pattern_file)
        for pattern in file_patterns:
            regex = re.compile(pattern)
            matchers.append((regex, pattern))

    if not matchers:
        raise ValueError("No words, patterns, or pattern file provided.")

    return matchers


def load_pattern_file(path):
    """Load patterns from a file, one per line. Skips comments (#) and blanks.

    Resolves bare filenames against built-in patterns/ dir first, then
    ~/.memex/scripts/patterns/, then treats as absolute/relative path.
    """
    p = Path(path)
    if not p.is_absolute() and not p.exists():
        # Try built-in patterns dir
        builtin = Path(__file__).parent / "patterns" / path
        if builtin.exists():
            p = builtin
        else:
            # Try user patterns dir
            user = Path.home() / ".memex" / "scripts" / "patterns" / path
            if user.exists():
                p = user

    lines = p.read_text().strip().splitlines()
    return [
        line.strip() for line in lines
        if line.strip() and not line.strip().startswith("#")
    ]


def scan_message(content, matchers, conversation_id, message_id):
    """Scan a message's content blocks for matcher hits.

    Only scans text blocks; non-text blocks are ignored.
    Returns a ScanResult with all matches found.
    """
    result = ScanResult(
        conversation_id=conversation_id,
        message_id=message_id,
        content=content,
    )

    for block_idx, block in enumerate(content):
        if not isinstance(block, dict) or block.get("type") != "text":
            continue
        text = block.get("text", "")
        for regex, term in matchers:
            for m in regex.finditer(text):
                result.matches.append(Match(
                    conversation_id=conversation_id,
                    message_id=message_id,
                    term=term,
                    start=m.start(),
                    end=m.end(),
                    block_index=block_idx,
                ))

    return result


def check_match_mode(matches, mode, matchers):
    """Check if matches satisfy the match mode.

    'any': at least one matcher produced a hit.
    'all': every matcher produced at least one hit.
    """
    if mode == "any":
        return len(matches) > 0
    elif mode == "all":
        matched_terms = {m.term for m in matches}
        required_terms = {term for _, term in matchers}
        return required_terms.issubset(matched_terms)
    return False


def register_args(parser):
    """Add redact-specific CLI arguments."""
    parser.add_argument("--words", help="Comma-separated literal terms to match")
    parser.add_argument("--patterns", help="Comma-separated regex patterns")
    parser.add_argument("--pattern-file", help="File with one pattern per line")
    parser.add_argument("--level", choices=["word", "message", "conversation"],
                        default="word", help="Redaction level (default: word)")
    parser.add_argument("--match-mode", choices=["any", "all"], default="any",
                        help="'any' (default) or 'all' terms must match")
    parser.add_argument("--yes", action="store_true",
                        help="Skip interactive review, apply all")


def run(db, args, apply=False):
    """Scan and optionally redact content."""
    # Parse word/pattern args
    words = [w.strip() for w in args.words.split(",")] if args.words else None
    patterns = [p.strip() for p in args.patterns.split(",")] if args.patterns else None
    matchers = compile_matchers(words=words, patterns=patterns,
                                pattern_file=args.pattern_file)

    # Scan all messages
    all_convs = _load_all_conversation_ids(db)
    pending = []  # list of (ScanResult, action_level)
    conv_hits = {}  # conversation_id -> list of ScanResults (for conversation-level)

    for conv_id in all_convs:
        messages = db.execute_sql(
            "SELECT id, content FROM messages WHERE conversation_id=? ORDER BY created_at",
            (conv_id,),
        )
        for msg_row in messages:
            content = json.loads(msg_row["content"]) if isinstance(msg_row["content"], str) else msg_row["content"]
            result = scan_message(content, matchers, conv_id, msg_row["id"])
            if result.matches:
                if args.level == "conversation":
                    conv_hits.setdefault(conv_id, []).append(result)
                else:
                    if check_match_mode(result.matches, args.match_mode, matchers):
                        pending.append(result)

    # For conversation-level: check match mode across all messages in conv
    if args.level == "conversation":
        for conv_id, results in conv_hits.items():
            all_matches = [m for r in results for m in r.matches]
            if check_match_mode(all_matches, args.match_mode, matchers):
                # Use first result as representative
                combined = ScanResult(
                    conversation_id=conv_id,
                    message_id="(all)",
                    matches=all_matches,
                    content=[],
                )
                pending.append(combined)

    # Build stats
    stats = _compute_stats(pending, args.level)

    if not apply:
        _print_dry_run(pending, args.level, stats)
        return stats

    # Apply mode
    if args.yes:
        _apply_batch(db, pending, args.level)
    else:
        interactive_stats = interactive_review(pending, db, args.level)
        stats.update(interactive_stats)

    return stats


def _load_all_conversation_ids(db):
    rows = db.execute_sql("SELECT id FROM conversations")
    return [r["id"] for r in rows]


def _compute_stats(pending, level):
    stats = {"word_redactions": 0, "message_redactions": 0, "conversation_deletions": 0,
             "total_matches": len(pending)}
    if level == "word":
        stats["word_redactions"] = sum(len(r.matches) for r in pending)
    elif level == "message":
        stats["message_redactions"] = len(pending)
    elif level == "conversation":
        stats["conversation_deletions"] = len(pending)
    return stats


def _print_dry_run(pending, level, stats):
    if not pending:
        print("No matches found.")
        return

    for result in pending:
        conv_short = result.conversation_id[:12]
        if level == "word":
            for match in result.matches:
                print(f"  [WORD]  conv {conv_short}... msg {result.message_id}: "
                      f"matched '{match.term}' at {match.start}:{match.end}")
        elif level == "message":
            terms = ", ".join(sorted({m.term for m in result.matches}))
            print(f"  [MSG]   conv {conv_short}... msg {result.message_id}: "
                  f"matches: {terms}")
        elif level == "conversation":
            terms = ", ".join(sorted({m.term for m in result.matches}))
            print(f"  [CONV]  conv {conv_short}...: matches across messages: {terms}")

    print(f"\nSummary:")
    if stats["word_redactions"]:
        print(f"  Word-level redactions:  {stats['word_redactions']}")
    if stats["message_redactions"]:
        print(f"  Message-level redactions: {stats['message_redactions']}")
    if stats["conversation_deletions"]:
        print(f"  Conversation deletions: {stats['conversation_deletions']}")
    print(f"\nRe-run with --apply to commit changes.")


# ── Mutation Engine ─────────────────────────────────────────────


def redact_word_level(content, matches):
    """Replace matched spans with [REDACTED] in text blocks.

    Processes matches right-to-left within each block to preserve offsets.
    """
    result = copy.deepcopy(content)
    # Group matches by block_index, sort by start descending
    by_block = {}
    for m in matches:
        by_block.setdefault(m.block_index, []).append(m)

    for block_idx, block_matches in by_block.items():
        if block_idx >= len(result):
            continue
        block = result[block_idx]
        if block.get("type") != "text":
            continue
        text = block["text"]
        # Sort right-to-left to preserve offsets
        for m in sorted(block_matches, key=lambda x: x.start, reverse=True):
            text = text[:m.start] + "[REDACTED]" + text[m.end:]
        block["text"] = text

    return result


def redact_message_level():
    """Return replacement content for a fully redacted message."""
    return [{"type": "text", "text": "[REDACTED]"}]


def _save_original(db, conv_id, msg_id, original_content):
    """Save original content as enrichment before redacting."""
    db.save_enrichment(
        conv_id, "original_content", msg_id, "redact",
    )


def _apply_single(db, result, level):
    """Apply a single redaction action to the database."""
    if level == "word":
        new_content = redact_word_level(result.content, result.matches)
        _save_original(db, result.conversation_id, result.message_id, result.content)
        db.update_message_content(result.conversation_id, result.message_id, new_content)
    elif level == "message":
        _save_original(db, result.conversation_id, result.message_id, result.content)
        db.update_message_content(result.conversation_id, result.message_id,
                                  redact_message_level())
    elif level == "conversation":
        db.delete_conversation(result.conversation_id)


def _apply_batch(db, pending, level):
    """Apply all pending redactions without prompting."""
    for result in pending:
        _apply_single(db, result, level)


# ── Interactive Review ──────────────────────────────────────────


def interactive_review(pending, db, level, input_fn=None):
    """Interactively review each match before applying."""
    if input_fn is None:
        input_fn = input
    auto_terms = set()
    stats = {"redacted": 0, "skipped": 0}

    for i, result in enumerate(pending):
        # Auto-apply if all terms in this result are in auto_terms
        if level == "word" and all(m.term in auto_terms for m in result.matches):
            _apply_single(db, result, level)
            stats["redacted"] += 1
            continue

        # Display context
        conv_short = result.conversation_id[:12]
        if level == "word":
            for m in result.matches:
                if m.term in auto_terms:
                    continue
                text = result.content[m.block_index]["text"] if m.block_index < len(result.content) else ""
                preview = text[max(0, m.start - 20):m.end + 20]
                print(f"\n[{i+1}/{len(pending)}] conv {conv_short}... msg {result.message_id}:")
                print(f"  ...{preview}...")
                choice = input_fn("  [r]edact  [s]kip  [a]ll  [q]uit\n> ").strip().lower()
                if choice == "r":
                    _apply_single(db, result, level)
                    stats["redacted"] += 1
                    break
                elif choice == "a":
                    auto_terms.add(m.term)
                    _apply_single(db, result, level)
                    stats["redacted"] += 1
                    break
                elif choice == "s":
                    stats["skipped"] += 1
                    break
                elif choice == "q":
                    return stats
        else:
            terms = ", ".join(sorted({m.term for m in result.matches}))
            print(f"\n[{i+1}/{len(pending)}] conv {conv_short}... msg {result.message_id}:")
            print(f"  matches: {terms}")
            choice = input_fn("  [r]edact  [s]kip  [q]uit\n> ").strip().lower()
            if choice == "r":
                _apply_single(db, result, level)
                stats["redacted"] += 1
            elif choice == "s":
                stats["skipped"] += 1
            elif choice == "q":
                return stats

    return stats
