from __future__ import annotations

import logging
import os
import sys
import traceback
from typing import Any


def setup_console_logging(default_level: str = "INFO") -> None:
    level_name = os.getenv("APP_LOG_LEVEL", default_level).upper()
    level = getattr(logging, level_name, logging.INFO)

    root_logger = logging.getLogger()
    if not root_logger.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)s %(name)s:%(lineno)d %(message)s"
            )
        )
        root_logger.addHandler(handler)

    root_logger.setLevel(level)


def preview_text(value: Any, max_len: int = 240) -> str:
    text = str(value)
    if len(text) <= max_len:
        return text
    return f"{text[:max_len]}..."


def iter_exception_leaves(exc: BaseException) -> list[BaseException]:
    leaves: list[BaseException] = []
    stack: list[BaseException] = [exc]
    seen: set[int] = set()

    while stack:
        current = stack.pop()
        current_id = id(current)
        if current_id in seen:
            continue
        seen.add(current_id)

        group_exceptions = getattr(current, "exceptions", None)
        if group_exceptions:
            stack.extend(reversed(list(group_exceptions)))
            continue

        leaves.append(current)

    return leaves


def exception_chain_text(exc: BaseException) -> str:
    parts: list[str] = []
    current: BaseException | None = exc
    seen: set[int] = set()

    while current is not None and id(current) not in seen:
        seen.add(id(current))
        parts.append(f"{type(current).__name__}: {current}")
        current = current.__cause__ or current.__context__

    return " -> ".join(parts)


def log_exception_tree(logger: logging.Logger, exc: BaseException, header: str) -> None:
    logger.error("%s", header)
    logger.error("Exceção recebida: %s: %s", type(exc).__name__, exc)

    leaves = iter_exception_leaves(exc)
    if len(leaves) > 1 or leaves and leaves[0] is not exc:
        for index, leaf in enumerate(leaves, start=1):
            logger.error("Leaf %s: %s: %s", index, type(leaf).__name__, leaf)
            logger.error("Leaf chain %s: %s", index, exception_chain_text(leaf))
            logger.debug(
                "Leaf traceback %s:\n%s",
                index,
                "".join(traceback.format_exception(type(leaf), leaf, leaf.__traceback__)),
            )
        return

    logger.error("Chain: %s", exception_chain_text(exc))
    logger.debug("Traceback:\n%s", "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))