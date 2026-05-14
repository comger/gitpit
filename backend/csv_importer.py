"""
CSV import and validation for flood observation data.

Expected CSV columns (header must match):
  timestamp       - ISO8601 or 'YYYY-MM-DD HH:MM:SS'
  rainfall_mm     - 时段降雨量 (mm/interval), numeric ≥ 0
  water_level_m   - 实测水位 (m above datum), numeric (可为空)
  flow_m3s        - 实测流量 (m³/s), numeric optional

Example:
  timestamp,rainfall_mm,water_level_m,flow_m3s
  2024-06-01 00:00:00,0.0,0.42,
  2024-06-01 00:05:00,0.2,0.43,
  2024-06-01 00:10:00,1.5,0.45,2.1
"""

import io
import pandas as pd
from datetime import datetime
from typing import Tuple, List, Dict, Any, Union
from db import get_conn


REQUIRED_COLS = {"timestamp", "rainfall_mm"}
OPTIONAL_COLS = {"water_level_m", "h_up_m", "flow_m3s"}
ALL_COLS = REQUIRED_COLS | OPTIONAL_COLS


def validate_and_parse(content: "Union[bytes, str]") -> Tuple[pd.DataFrame, List[str]]:
    """
    Parse CSV bytes and validate schema + data quality.
    Returns (dataframe, list_of_warnings).
    Raises ValueError on fatal schema errors.
    """
    warnings = []

    if isinstance(content, bytes):
        content = content.decode("utf-8-sig")  # handle BOM

    df = pd.read_csv(io.StringIO(content))

    # Strip whitespace from column names
    df.columns = df.columns.str.strip().str.lower()

    # Check required columns
    missing = REQUIRED_COLS - set(df.columns)
    if missing:
        raise ValueError(f"CSV 缺少必要列: {missing}。必需列: {REQUIRED_COLS}")

    # Parse timestamp
    try:
        df["timestamp"] = pd.to_datetime(df["timestamp"])
    except Exception as e:
        raise ValueError(f"时间列格式错误: {e}")

    # Parse numeric columns
    df["rainfall_mm"] = pd.to_numeric(df["rainfall_mm"], errors="coerce").fillna(0).clip(lower=0)

    for col in OPTIONAL_COLS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        else:
            df[col] = None
            
    if df["water_level_m"].isna().all():
        warnings.append("未提供 water_level_m (出口水位) 列，模型将无法进行完全的物理损失对齐")

    # Sort by time
    df = df.sort_values("timestamp").reset_index(drop=True)

    # Detect time resolution
    if len(df) > 1:
        dt_min = df["timestamp"].diff().dt.total_seconds().dropna().median() / 60
        if dt_min < 1:
            warnings.append(f"检测到时间分辨率 {dt_min:.1f} 分钟，建议 ≥ 5 分钟")
        elif dt_min > 60:
            warnings.append(f"时间间隔过大 ({dt_min:.0f}min)，预报精度会降低")

    # Check for unrealistic values
    if df["rainfall_mm"].max() > 300:
        warnings.append(f"发现疑似异常降雨 {df['rainfall_mm'].max():.1f}mm，请核查")

    valid_wl = df["water_level_m"].dropna()
    if len(valid_wl) > 0 and valid_wl.max() > 20:
        warnings.append(f"水位最大值 {valid_wl.max():.2f}m，请确认单位为米(m)")

    return df, warnings


def import_to_db(station_id: str, df: pd.DataFrame) -> Dict[str, Any]:
    """
    Write validated dataframe to observations table.
    Handles duplicates with INSERT OR REPLACE.
    """
    inserted = 0
    skipped = 0

    with get_conn() as conn:
        for _, row in df.iterrows():
            try:
                conn.execute(
                    """INSERT OR REPLACE INTO observations
                       (station_id, timestamp, rainfall_mm, water_level_m, h_up_m, flow_m3s, source)
                       VALUES (?, ?, ?, ?, ?, ?, 'csv')""",
                    (
                        station_id,
                        row["timestamp"].isoformat(),
                        float(row["rainfall_mm"]),
                        float(row["water_level_m"]) if pd.notna(row.get("water_level_m")) else None,
                        float(row["h_up_m"]) if pd.notna(row.get("h_up_m")) else 0.0,
                        float(row["flow_m3s"]) if pd.notna(row.get("flow_m3s")) else None,
                    ),
                )
                inserted += 1
            except Exception:
                skipped += 1

    # Compute summary statistics
    has_wl = bool(df["water_level_m"].notna().any())
    summary = {
        "inserted": int(inserted),
        "skipped": int(skipped),
        "total_rows": int(len(df)),
        "time_start": df["timestamp"].min().isoformat(),
        "time_end": df["timestamp"].max().isoformat(),
        "duration_hours": round(float((df["timestamp"].max() - df["timestamp"].min()).total_seconds() / 3600), 1),
        "total_rainfall_mm": round(float(df["rainfall_mm"].sum()), 1),
        "max_rainfall_mm": round(float(df["rainfall_mm"].max()), 1),
        "has_water_level": has_wl,
        "max_water_level_m": round(float(df["water_level_m"].max()), 3) if has_wl else None,
    }
    return summary


def get_observations(station_id: str, limit: int = 1000) -> List[Dict]:
    """Fetch recent observations for a station."""
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT timestamp, rainfall_mm, water_level_m, flow_m3s
               FROM observations
               WHERE station_id = ?
               ORDER BY timestamp DESC LIMIT ?""",
            (station_id, limit),
        ).fetchall()
    return [dict(r) for r in reversed(rows)]
