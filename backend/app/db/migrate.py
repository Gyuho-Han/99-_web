"""가벼운 스키마 마이그레이션.

Alembic을 쓸 만큼 큰 프로젝트가 아니므로, 서버가 뜰 때 필요한 변경만 직접 적용한다.
두 가지를 본다.

  ① 거래 데이터에 market(kr|us) 축 추가 — 테이블을 다시 만들어야 한다
  ② 뒤늦게 붙은 nullable 컬럼 추가 — ALTER TABLE 한 줄이면 된다

SQLite는 이미 만들어진 테이블의 UNIQUE 제약을 바꿀 수 없어서, 컬럼만 덧붙이는
ALTER로는 부족하다. (user_id, env) 유니크가 걸려 있으면 같은 환경에 국내용·미국용
예수금 행을 나란히 둘 수 없기 때문이다. 그래서 해당 테이블만 새 스키마로 다시 만들고
기존 행을 market='kr'로 옮긴다. 옮기기 전에 DB 파일을 통째로 백업한다.
"""

from __future__ import annotations

import logging
import shutil
from datetime import datetime
from pathlib import Path

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

log = logging.getLogger("kairo.migrate")

# market 축이 필요한 테이블
MARKET_TABLES = [
    "broker_credentials",
    "positions",
    "orders",
    "agent_configs",
    "agent_signals",
    "equity_snapshots",
    "cash_accounts",
]


def _backup_sqlite(engine: Engine) -> Path | None:
    url = engine.url
    if url.get_backend_name() != "sqlite" or not url.database:
        return None
    src = Path(url.database)
    if not src.exists():
        return None
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dst = src.with_suffix(src.suffix + f".bak-{stamp}")
    shutil.copy2(src, dst)
    return dst


def _rebuild(engine: Engine, base, table: str) -> None:
    """테이블을 새 스키마로 다시 만들고 기존 행을 market='kr'로 옮긴다."""
    insp = inspect(engine)
    old_cols = [c["name"] for c in insp.get_columns(table)]
    old_indexes = [i["name"] for i in insp.get_indexes(table) if i.get("name")]

    target = base.metadata.tables[table]
    new_cols = [c.name for c in target.columns]
    carry = [c for c in old_cols if c in new_cols and c != "market"]
    cols_sql = ", ".join(f'"{c}"' for c in carry)

    with engine.begin() as conn:
        # 이름 있는 인덱스는 테이블과 함께 따라다녀 새 테이블 생성 시 이름이 충돌한다.
        for name in old_indexes:
            conn.execute(text(f'DROP INDEX IF EXISTS "{name}"'))
        conn.execute(text(f'ALTER TABLE "{table}" RENAME TO "{table}__old"'))

    target.create(bind=engine)

    with engine.begin() as conn:
        conn.execute(
            text(
                f'INSERT INTO "{table}" ({cols_sql}, "market") '
                f"SELECT {cols_sql}, 'kr' FROM \"{table}__old\""
            )
        )
        moved = conn.execute(text(f'SELECT COUNT(*) FROM "{table}"')).scalar_one()
        conn.execute(text(f'DROP TABLE "{table}__old"'))

    log.info("  %s: %d행을 market='kr'로 옮겼습니다.", table, moved)


# 뒤늦게 붙은 nullable 컬럼. (테이블, 컬럼, SQL 타입)
ADDED_COLUMNS = [
    ("agent_configs", "risk_ack_at", "DATETIME"),
    ("agent_configs", "order_cooldown_seconds", "INTEGER NOT NULL DEFAULT 300"),
    ("agent_configs", "max_daily_orders", "INTEGER NOT NULL DEFAULT 20"),
]


def ensure_columns(engine: Engine) -> list[str]:
    """빠진 nullable 컬럼을 ALTER TABLE 로 덧붙인다. 이미 있으면 아무것도 하지 않는다.

    UNIQUE 제약을 건드리지 않으므로 테이블을 다시 만들 필요가 없다.
    """
    insp = inspect(engine)
    existing = set(insp.get_table_names())
    added: list[str] = []
    for table, column, sql_type in ADDED_COLUMNS:
        if table not in existing:
            continue
        if column in {c["name"] for c in insp.get_columns(table)}:
            continue
        with engine.begin() as conn:
            conn.execute(text(f'ALTER TABLE "{table}" ADD COLUMN "{column}" {sql_type}'))
        added.append(f"{table}.{column}")
        log.info("컬럼을 추가했습니다: %s.%s", table, column)
    return added


def ensure_market_axis(engine: Engine, base) -> list[str]:
    """market 컬럼이 없는 테이블을 찾아 다시 만든다. 이미 최신이면 아무것도 하지 않는다."""
    insp = inspect(engine)
    existing = set(insp.get_table_names())
    todo = [
        t
        for t in MARKET_TABLES
        if t in existing and "market" not in {c["name"] for c in insp.get_columns(t)}
    ]
    if not todo:
        return []

    backup = _backup_sqlite(engine)
    log.warning("스키마를 market(kr|us) 축이 있는 형태로 옮깁니다: %s", ", ".join(todo))
    if backup:
        log.warning("기존 DB는 %s 로 백업했습니다.", backup.name)

    # 외래키 검사를 잠시 끄고 테이블을 갈아 끼운다.
    with engine.connect() as conn:
        conn.execute(text("PRAGMA foreign_keys=OFF"))
        conn.commit()
    try:
        for t in todo:
            _rebuild(engine, base, t)
    except Exception as e:  # noqa: BLE001
        log.error("마이그레이션 중 오류: %s", e)
        if backup:
            log.error(
                "DB를 원래대로 되돌리려면 %s 를 %s 로 덮어쓰세요.",
                backup.name,
                Path(engine.url.database).name,
            )
        raise
    finally:
        with engine.connect() as conn:
            conn.execute(text("PRAGMA foreign_keys=ON"))
            conn.commit()

    log.warning("마이그레이션을 마쳤습니다. 기존 데이터는 모두 '국내' 시장으로 들어갑니다.")
    return todo
