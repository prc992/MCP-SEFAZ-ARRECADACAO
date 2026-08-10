import os
import redshift_connector
from dotenv import load_dotenv

load_dotenv()


def _use_ssl() -> bool:
    value = os.getenv("REDSHIFT_SSL", "false").strip().lower()
    return value in {"1", "true", "yes", "on"}


def get_connection():
    use_ssl = _use_ssl()
    return redshift_connector.connect(
        host=os.getenv("REDSHIFT_HOST"),
        port=int(os.getenv("REDSHIFT_PORT", "5439")),
        database=os.getenv("REDSHIFT_DATABASE"),
        user=os.getenv("REDSHIFT_USER"),
        password=os.getenv("REDSHIFT_PASSWORD"),
        ssl=use_ssl,
    )


def executar_sql(sql: str):
    conn = get_connection()

    try:
        cursor = conn.cursor()
        cursor.execute(sql)

        columns = [desc[0] for desc in cursor.description]
        rows = cursor.fetchall()

        resultado = []

        for row in rows:
            resultado.append(dict(zip(columns, row)))

        return resultado

    finally:
        conn.close()