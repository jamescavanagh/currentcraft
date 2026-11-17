"""Reversible slash topics -> NATS subjects. Encode EVERY literal level, so dots never change hierarchy.

A final MQTT # includes its parent; NATS > does not. Filters use both parent and descendant subjects.
"""
from app.application.messaging.contracts import valid_pattern, TOPIC_RE


def topic_to_subject(topic: str, prefix: str = "dm") -> str:
    if not TOPIC_RE.fullmatch(topic):
        raise ValueError("invalid literal topic")
    return prefix + "." + ".".join("t" + level.encode().hex() for level in topic.split("/"))


def subject_to_topic(subject: str, prefix: str = "dm") -> str:
    if not subject.startswith(prefix + "."):
        raise ValueError("foreign subject namespace")
    tokens = subject[len(prefix) + 1:].split(".")
    try:
        if any(not t.startswith("t") or len(t) < 3 for t in tokens):
            raise ValueError("invalid subject token")
        topic = "/".join(bytes.fromhex(t[1:]).decode() for t in tokens)
    except (ValueError, UnicodeError) as exc:
        raise ValueError("invalid encoded subject") from exc
    if topic_to_subject(topic, prefix) != subject:
        raise ValueError("noncanonical subject")
    return topic


def pattern_to_subjects(pattern: str, prefix: str = "dm") -> tuple[str, ...]:
    if not valid_pattern(pattern) or pattern == "#":
        raise ValueError("use an explicit filter such as raw/#")
    levels = pattern.split("/")
    recursive = levels[-1] == "#"
    if recursive:
        levels = levels[:-1]
    base = prefix + "." + ".".join("*" if t == "+" else "t" + t.encode().hex() for t in levels)
    return (base, base + ".>") if recursive else (base,)
