"""
Limpia datos de prueba de la base Postgres compartida por platform-api y el AI Engine.

Borra: organizaciones que no esten en KEEP_COMPANIES (con sus membresias, refresh tokens,
usuarios exclusivos, agentes y documentos), agentes cuya organizacion no existe, y documentos
cuyo nombre contenga "curriculum".

Uso (desde la raiz del repo):
    set POSTGRES_DSN=postgresql://...            (PowerShell: $env:POSTGRES_DSN="postgresql://...")
    python backend/scripts/cleanup_test_data.py            # simulacion: solo muestra que borraria
    python backend/scripts/cleanup_test_data.py --apply    # borra de verdad, en una transaccion
"""
from __future__ import annotations

import os
import sys

import psycopg

KEEP_COMPANIES = {"kronix-ai-e255f08b", "demo-ventas-wsp", "kronix"}
TABLES = ["organizations", "users", "memberships", "refresh_tokens", "agents", "agent_documents"]


def counts(conn) -> dict[str, int]:
    return {t: conn.execute(f"select count(*) from {t}").fetchone()[0] for t in TABLES}


def main() -> None:
    apply = "--apply" in sys.argv
    dsn = os.environ.get("POSTGRES_DSN") or os.environ.get("DATABASE_URL")
    if not dsn:
        sys.exit("Falta POSTGRES_DSN o DATABASE_URL en el entorno")

    with psycopg.connect(dsn) as conn:
        print("ANTES :", counts(conn))
        keep = list(KEEP_COMPANIES)
        drop_orgs = [r[0] for r in conn.execute(
            "select org_id from organizations where company_id <> all(%s)", (keep,))]
        drop_companies = [r[0] for r in conn.execute(
            "select company_id from organizations where org_id = any(%s)", (drop_orgs,))]
        drop_users = [r[0] for r in conn.execute(
            """select u.user_id from users u
               where exists (select 1 from memberships m where m.user_id = u.user_id)
                 and not exists (select 1 from memberships m
                                 where m.user_id = u.user_id and m.org_id <> all(%s))""", (drop_orgs,))]
        drop_agents = [r[0] for r in conn.execute(
            """select a.agent_id from agents a
               where a.company_id = any(%s)
                  or not exists (select 1 from organizations o where o.org_id = a.org_id)""", (drop_companies,))]
        cv_docs = [r[0] for r in conn.execute(
            "select document_id from agent_documents where filename ilike %s", ("%curriculum%",))]

        print(f"A BORRAR: orgs={len(drop_orgs)} usuarios={len(drop_users)} agentes={len(drop_agents)} docs_cv={len(cv_docs)}")
        print("  orgs    :", ", ".join(sorted(drop_companies)))
        emails = [r[0] for r in conn.execute("select email from users where user_id = any(%s) order by 1", (drop_users,))]
        print("  usuarios:", ", ".join(emails))
        names = [r[0] for r in conn.execute("select name from agents where agent_id = any(%s) order by 1", (drop_agents,))]
        print("  agentes :", ", ".join(names))

        if not apply:
            print("\nSimulacion. Ejecuta con --apply para borrar.")
            return

        with conn.transaction():
            d_docs = conn.execute("delete from agent_documents where agent_id = any(%s) or document_id = any(%s)", (drop_agents, cv_docs)).rowcount
            d_agents = conn.execute("delete from agents where agent_id = any(%s)", (drop_agents,)).rowcount
            d_tokens = conn.execute("delete from refresh_tokens where user_id = any(%s) or org_id = any(%s)", (drop_users, drop_orgs)).rowcount
            d_members = conn.execute("delete from memberships where org_id = any(%s) or user_id = any(%s)", (drop_orgs, drop_users)).rowcount
            d_users = conn.execute("delete from users where user_id = any(%s)", (drop_users,)).rowcount
            d_orgs = conn.execute("delete from organizations where org_id = any(%s)", (drop_orgs,)).rowcount
        print(f"BORRADO: documentos={d_docs} agentes={d_agents} tokens={d_tokens} membresias={d_members} usuarios={d_users} orgs={d_orgs}")
        print("DESPUES:", counts(conn))


if __name__ == "__main__":
    main()
