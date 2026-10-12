import sys
from pathlib import Path

CURRENT_FILE = Path(__file__).resolve()
PROJECT_ROOT = CURRENT_FILE.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd
from sqlalchemy import Engine, text

from core.logger import logger
from database.db.session import engine


def _coerce_bool_series(series: pd.Series) -> pd.Series:
    """Coerce a pandas Series with values like 0/1, "0"/"1", "true"/"false" to booleans."""
    true_vals = {"1", "true", "t", "yes", "y"}
    false_vals = {"0", "false", "f", "no", "n"}

    def to_bool(x):
        if isinstance(x, bool):
            return x
        if pd.isna(x):
            return False
        s = str(x).strip().lower()
        if s in true_vals:
            return True
        if s in false_vals:
            return False
        # Fallback: non-empty/non-zero truthiness
        try:
            return bool(int(s))
        except Exception:
            return s not in ("", "0", "false", "none", "nan")

    return series.map(to_bool)


async def seed_vehicle_data(engine: Engine):
    src_dir = CURRENT_FILE.parent / "src"

    # Map CSV paths
    tables = {
        "damage": src_dir / "damage_types.csv",
        "document": src_dir / "document.csv",
        "drive": src_dir / "drive.csv",
        "make": src_dir / "makes.csv",
        "model": src_dir / "models.csv",
        "status": src_dir / "status.csv",
        "transmission": src_dir / "transmissions.csv",
        "vehicle_type": src_dir / "vehicle_type.csv",
        "title_indicators": src_dir / "title_indicators.csv",
    }

    # Deletion order: children first, then parents (to satisfy FKs)
    delete_order = [
        "model",
        "make",
        "vehicle_type",
        "transmission",
        "drive",
        "status",
        "document",
        "damage",
        "title_indicators",
    ]

    # Insertion order: parents first, then children
    insert_order = [
        "vehicle_type",
        "make",
        "damage",
        "document",
        "status",
        "drive",
        "transmission",
        "model",
        "title_indicators",
    ]

    # Phase 1: delete existing data without dropping tables (preserve schema & FKs)
    with engine.begin() as conn:
        for table in delete_order:
            logger.info(f"Clearing table {table}")
            try:
                conn.execute(text(f'DELETE FROM "{table}"'))
            except Exception as e:
                logger.warning(f"Failed to delete from {table}: {e}")

    # Phase 2: insert data
    for table in insert_order:
        path = tables[table]
        logger.info(f"Seeding table {table} from {path}")
        df = pd.read_csv(path)

        # Handle boolean columns if they exist
        bool_columns = ["is_active", "is_default", "is_enabled"]
        for col in bool_columns:
            if col in df.columns:
                df[col] = _coerce_bool_series(df[col])

        df.to_sql(table, engine, if_exists="append", index=False)


if __name__ == "__main__":
    import asyncio

    asyncio.run(seed_vehicle_data(engine))
