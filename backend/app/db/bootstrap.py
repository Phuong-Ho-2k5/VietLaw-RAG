"""Provision a DML-only runtime role using the owner connection, only on explicit CLI invocation."""

import os

from psycopg import sql

from app.db.session import engine


def provision_runtime(password: str):
    if len(password) < 24 or not password.isalnum():
        raise ValueError(
            "Runtime password must contain at least 24 ASCII letters/digits for Compose URLs"
        )
    with engine().begin() as conn:
        row = conn.exec_driver_sql(
            "SELECT rolsuper,rolcreaterole,rolcreatedb FROM pg_roles WHERE rolname='vietlaw_app'"
        ).first()
        if row and any(row):
            raise ValueError("Existing runtime role is privileged; refusing to reuse")
        if not row:
            command = sql.SQL(
                "CREATE ROLE vietlaw_app LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE"
            ).format(sql.Literal(password))
            # Avoid putting credential SQL in SQLAlchemy's statement logging/errors.
            conn.connection.driver_connection.execute(command)
        else:
            conn.connection.driver_connection.execute(
                sql.SQL("ALTER ROLE vietlaw_app PASSWORD {}").format(sql.Literal(password))
            )
        conn.exec_driver_sql("GRANT USAGE ON SCHEMA public TO vietlaw_app")
        conn.exec_driver_sql(
            "GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA public TO vietlaw_app"
        )


if __name__ == "__main__":
    provision_runtime(os.environ["PROVISION_RUNTIME_PASSWORD"])
    print("Runtime role provisioned with DML privileges")
