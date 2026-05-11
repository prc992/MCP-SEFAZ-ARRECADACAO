import os
import redshift_connector
from dotenv import load_dotenv

load_dotenv()


def main():
    host = os.getenv("REDSHIFT_HOST")
    port = int(os.getenv("REDSHIFT_PORT", "5439"))
    database = os.getenv("REDSHIFT_DATABASE")
    user = os.getenv("REDSHIFT_USER")
    password = os.getenv("REDSHIFT_PASSWORD")
    view_name = os.getenv("REDSHIFT_VIEW")

    print("Tentando conectar em:", host)
    print("Database:", database)
    print("View:", view_name)

    conn = redshift_connector.connect(
        host=host,
        port=port,
        database=database,
        user=user,
        password=password,
        ssl=True,
    )

    try:
        cursor = conn.cursor()

        cursor.execute("SELECT current_date;")
        print("Conexão OK. Data:", cursor.fetchone()[0])

        sql = f"""
            SELECT *
            FROM {view_name}
            LIMIT 5;
        """

        cursor.execute(sql)
        rows = cursor.fetchall()

        print("\nPrimeiras linhas da view:")
        for row in rows:
            print(row)

    finally:
        conn.close()


if __name__ == "__main__":
    main()