"""Add, list, search, and delete marginalia notes on conversations and messages."""
from __future__ import annotations


def register_args(parser):
    """Add note-specific CLI arguments via subparsers for each action."""
    subs = parser.add_subparsers(dest="action")

    add_p = subs.add_parser("add", help="Add a note to a conversation or message")
    add_p.add_argument("--conv", help="Conversation ID (required)")
    add_p.add_argument("--msg", help="Message ID (for message-level notes)")
    add_p.add_argument("rest", nargs="*", help="Note text (positional words joined)")

    list_p = subs.add_parser("list", help="List notes for a conversation")
    list_p.add_argument("--conv", help="Conversation ID (required)")
    list_p.add_argument("--msg", help="Filter by message ID")

    search_p = subs.add_parser("search", help="Full-text search across notes")
    search_p.add_argument("rest", nargs="*", help="Search query (positional words joined)")
    search_p.add_argument("--limit", type=int, default=50,
                          help="Max results (default: 50)")

    delete_p = subs.add_parser("delete", help="Delete a note by ID")
    delete_p.add_argument("rest", nargs="*", help="Note ID")


def run(db, args, apply=False):
    """Execute the requested note action."""
    action = args.action

    if action == "add":
        return _add(db, args, apply)
    elif action == "list":
        return _list(db, args)
    elif action == "search":
        return _search(db, args)
    elif action == "delete":
        return _delete(db, args, apply)
    else:
        print("Error: specify an action: add, list, search, or delete.")
        return {"error": "missing action"}


def _add(db, args, apply):
    if not args.conv:
        print("Error: --conv is required for add.")
        return {"error": "missing --conv"}

    text = " ".join(args.rest) if args.rest else ""
    if not text:
        print("Error: note text is required.")
        return {"error": "missing text"}

    if not apply:
        target = f"msg {args.msg}" if args.msg else "conversation"
        print(f"[DRY] Would add note to conv {args.conv[:12]}... ({target}):")
        print(f"  {text!r}")
        print("\nRe-run with --apply to write.")
        return {"action": "add", "applied": False}

    note_id = db.add_note(
        conversation_id=args.conv,
        message_id=args.msg,
        text=text,
    )
    target = "message" if args.msg else "conversation"
    print(f"Added {target} note {note_id} to conv {args.conv[:12]}...")
    return {"action": "add", "applied": True, "note_id": note_id}


def _list(db, args):
    if not args.conv:
        print("Error: --conv is required for list.")
        return {"error": "missing --conv"}

    notes = db.get_notes(conversation_id=args.conv, message_id=args.msg)
    if not notes:
        print("No notes found.")
        return {"action": "list", "count": 0}

    for n in notes:
        target = f"msg {n['message_id']}" if n["target_kind"] == "message" else "conv"
        ts = n["created_at"]
        print(f"  [{n['id'][:12]}...] ({target}) {ts}: {n['text']}")

    print(f"\n{len(notes)} note(s).")
    return {"action": "list", "count": len(notes)}


def _search(db, args):
    query = " ".join(args.rest) if args.rest else ""
    if not query:
        print("Error: search query is required.")
        return {"error": "missing query"}

    limit = getattr(args, "limit", 50)
    results = db.search_notes(query, limit=limit)
    if not results:
        print("No matching notes found.")
        return {"action": "search", "count": 0}

    for n in results:
        conv_short = (n["conversation_id"] or "???")[:12]
        target = f"msg {n['message_id']}" if n["target_kind"] == "message" else "conv"
        print(f"  [{n['id'][:12]}...] conv {conv_short}... ({target}): {n['text']}")

    print(f"\n{len(results)} result(s).")
    return {"action": "search", "count": len(results)}


def _delete(db, args, apply):
    note_id = args.rest[0] if args.rest else None
    if not note_id:
        print("Error: note id is required for delete.")
        return {"error": "missing note_id"}

    if not apply:
        print(f"[DRY] Would delete note {note_id}.")
        print("\nRe-run with --apply to write.")
        return {"action": "delete", "applied": False}

    deleted = db.delete_note(note_id)
    if deleted:
        print(f"Deleted note {note_id}.")
    else:
        print(f"Note {note_id} not found.")
    return {"action": "delete", "applied": True, "deleted": deleted}
