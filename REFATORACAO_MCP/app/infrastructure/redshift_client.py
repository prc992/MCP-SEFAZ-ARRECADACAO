import logging
import os
import ssl
from typing import Any, Sequence

import pg8000.dbapi
from dotenv import load_dotenv
from app.shared.logging_utils import preview_text


load_dotenv()


logger = logging.getLogger(__name__)


def _use_ssl() -> bool:
    value = os.getenv("REDSHIFT_SSL", "false").strip().lower()
    return value in {"1", "true", "yes", "on"}


def get_connection():
    use_ssl = _use_ssl()
    logger.info(
        "Conectando ao Redshift host=%s database=%s user=%s ssl=%s",
        os.getenv("REDSHIFT_HOST"),
        os.getenv("REDSHIFT_DATABASE"),
        os.getenv("REDSHIFT_USER"),
        use_ssl,
    )
    connect_kwargs: dict[str, Any] = {
        "host": os.getenv("REDSHIFT_HOST"),
        "port": int(os.getenv("REDSHIFT_PORT", "5439")),
        "database": os.getenv("REDSHIFT_DATABASE"),
        "user": os.getenv("REDSHIFT_USER"),
        "password": os.getenv("REDSHIFT_PASSWORD"),
    }
    if use_ssl:
        connect_kwargs["ssl_context"] = ssl.create_default_context()
    return pg8000.dbapi.connect(**connect_kwargs)


def execute_sql(sql: str, params: Sequence[Any] | None = None) -> list[dict]:
    conn = get_connection()
    try:
        logger.debug("Executando SQL=%s params=%s", preview_text(sql), params)
        cursor = conn.cursor()
        if params is None:
            cursor.execute(sql)
        else:
            cursor.execute(sql, params)
        columns = [desc[0] for desc in cursor.description]
        rows = cursor.fetchall()
        logger.info("SQL executado com sucesso rows=%s", len(rows))
        return [dict(zip(columns, row)) for row in rows]
    except Exception:
        logger.exception("Falha ao executar SQL")
        raise
    finally:
        conn.close()
