from __future__ import annotations

import os
from dataclasses import dataclass

import pandas as pd
from dotenv import load_dotenv


@dataclass
class MySQLConfig:
    host: str
    user: str
    password: str
    database: str
    query: str


def load_csv_dataset(csv_path: str) -> pd.DataFrame:
    df = pd.read_csv(csv_path)
    required_cols = {"text", "label"}
    missing = required_cols - set(df.columns)
    if missing:
        raise ValueError(f"CSV invalido. Faltan columnas: {missing}")
    return df[["text", "label"]].dropna()


def mysql_config_from_env() -> MySQLConfig:
    load_dotenv()
    return MySQLConfig(
        host=os.getenv("MYSQL_HOST", "localhost"),
        user=os.getenv("MYSQL_USER", "root"),
        password=os.getenv("MYSQL_PASSWORD", ""),
        database=os.getenv("MYSQL_DATABASE", "tweets"),
        query=os.getenv("MYSQL_QUERY", "SELECT text, label FROM tweet WHERE label <> '' LIMIT 5000;"),
    )


def load_mysql_dataset(config: MySQLConfig) -> pd.DataFrame:
    try:
        import mysql.connector
    except ImportError as exc:
        raise ImportError("mysql-connector-python no esta instalado. Corre pip install -r requirements.txt") from exc
    conn = mysql.connector.connect(
        host=config.host,
        user=config.user,
        password=config.password,
        database=config.database,
    )
    try:
        df = pd.read_sql(config.query, conn)
    finally:
        conn.close()
    required_cols = {"text", "label"}
    missing = required_cols - set(df.columns)
    if missing:
        raise ValueError("La query debe devolver columnas text y label. " f"Faltan: {missing}")
    return df[["text", "label"]].dropna()
