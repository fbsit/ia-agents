from __future__ import annotations

"""
Pool minimo de conexiones Postgres compartido por todos los stores.

Motivacion: la base puede ser remota (p. ej. Railway). Abrir una conexion
TCP+TLS por consulta cuesta ~1s, y un request como "listar agentes" hace
varias consultas. Reusar conexiones baja eso a milisegundos.

Uso (reemplazo directo de `psycopg.connect(dsn)` dentro de un `with`):

    with pooled_connection(psycopg, dsn) as conn:
        conn.execute(...)

Al salir del bloque se hace commit (o rollback si hubo excepcion) y la
conexion vuelve al pool en lugar de cerrarse. Conexiones rotas se descartan.
"""

import os
import queue
import threading
from contextlib import contextmanager
from typing import Any, Iterator


_POOLS: dict[str, "queue.LifoQueue[Any]"] = {}
_POOLS_LOCK = threading.Lock()


def _max_idle() -> int:
    try:
        return max(1, int(os.getenv("PG_POOL_MAX_IDLE", "4")))
    except ValueError:
        return 4


def _pool_for(dsn: str) -> "queue.LifoQueue[Any]":
    with _POOLS_LOCK:
        pool = _POOLS.get(dsn)
        if pool is None:
            pool = queue.LifoQueue(maxsize=_max_idle())
            _POOLS[dsn] = pool
        return pool


def _is_usable(conn: Any) -> bool:
    return not getattr(conn, "closed", False) and not getattr(conn, "broken", False)


def _discard(conn: Any) -> None:
    try:
        conn.close()
    except Exception:  # noqa: BLE001
        pass


@contextmanager
def pooled_connection(psycopg_module: Any, dsn: str) -> Iterator[Any]:
    pool = _pool_for(dsn)
    conn: Any = None
    while conn is None:
        try:
            candidate = pool.get_nowait()
        except queue.Empty:
            break
        if _is_usable(candidate):
            conn = candidate
        else:
            _discard(candidate)
    if conn is None:
        conn = psycopg_module.connect(dsn)

    try:
        yield conn
    except BaseException:
        try:
            conn.rollback()
        except Exception:  # noqa: BLE001
            _discard(conn)
            conn = None
        raise
    else:
        try:
            conn.commit()
        except Exception:  # noqa: BLE001
            _discard(conn)
            conn = None
            raise
    finally:
        if conn is not None:
            if _is_usable(conn):
                try:
                    pool.put_nowait(conn)
                except queue.Full:
                    _discard(conn)
            else:
                _discard(conn)


def close_all_pools() -> None:
    with _POOLS_LOCK:
        pools = list(_POOLS.values())
        _POOLS.clear()
    for pool in pools:
        while True:
            try:
                _discard(pool.get_nowait())
            except queue.Empty:
                break
