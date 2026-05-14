import os
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List

from dem_manager import get_dem_for_point
from hydro_analyzer import calculate_catchment
from meteo_analyzer import fetch_meteo_data
from db import init_db, get_conn
from csv_importer import validate_and_parse, import_to_db, get_observations
from routing_engine import PhysicsForecaster, Level1Corrector

# Initialise DB on startup
init_db()

app = FastAPI(title="Catchment Analyzer + Flood Forecast")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

class AnalyzeRequest(BaseModel):
    lat: float
    lon: float

@app.post("/api/analyze")
async def analyze_point(req: AnalyzeRequest):
    try:
        # 1. Get appropriate DEM
        dem_path, dem_source, res_meters = get_dem_for_point(req.lat, req.lon)
        
        # 2. Perform Hydro Analysis
        results = calculate_catchment(dem_path, req.lat, req.lon)
        results["dem_source"] = dem_source
        results["dem_accuracy"] = f"约 {res_meters} 米"
        
        # 3. Add Meteorology and CN Calculation
        meteo = fetch_meteo_data(
            req.lat, 
            req.lon, 
            area_km2=results.get("area_km2", 0.0),
            delta_h=results.get("delta_h", 0.0)
        )
        results["meteo"] = meteo
        
        return results
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

class RecalculateMeteoRequest(BaseModel):
    lat: float
    lon: float
    area_km2: float
    delta_h: float
    custom_forecast: List[float]

@app.post("/api/recalculate_meteo")
async def recalculate_meteo_endpoint(req: RecalculateMeteoRequest):
    try:
        meteo = fetch_meteo_data(req.lat, req.lon, area_km2=req.area_km2,
                                  delta_h=req.delta_h, custom_forecast=req.custom_forecast)
        return {"meteo": meteo}
    except Exception as e:
        import traceback; traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

class AnalyzeNetworkRequest(BaseModel):
    min_lat: float; min_lon: float; max_lat: float; max_lon: float
    threshold: int = 500

from dem_manager import get_dem_for_bbox
from hydro_analyzer import analyze_network

@app.post("/api/analyze_network")
async def analyze_network_endpoint(req: AnalyzeNetworkRequest):
    try:
        dem_path, dem_source, res_meters = get_dem_for_bbox(
            req.min_lat, req.min_lon, req.max_lat, req.max_lon, pad=0.05)
        results = analyze_network(dem_path, threshold=req.threshold)
        results["dem_source"] = dem_source
        results["dem_accuracy"] = f"约 {res_meters} 米"
        return results
    except Exception as e:
        import traceback; traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

# ─────────────────────────────────────────────────────────────────────────────
# Phase 2 — Station Management
# ─────────────────────────────────────────────────────────────────────────────

class SaveStationRequest(BaseModel):
    """Save an analyzed point as a forecast station."""
    id: str
    name: str
    lat: float
    lon: float
    area_km2: float = 0
    slope_s0: float = 0.01
    w_channel: float = 10
    cn_prior: float = 75
    n_prior: float = 0.04
    tc_hours: float = 1.0
    max_elev: float = 0
    min_elev: float = 0
    delta_h: float = 0
    dem_source: str = ""
    alert_l1_m: float = 1.0
    alert_l2_m: float = 1.5
    alert_l3_m: float = 2.0
    catchment_geojson: Optional[str] = None

@app.post("/api/station/save")
async def save_station(req: SaveStationRequest):
    """Create or update a forecast station from analysis results."""
    import json, uuid, traceback as _tb
    station_id = req.id or str(uuid.uuid4())[:8]
    try:
        with get_conn() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO stations
                  (id,name,lat,lon,type,area_km2,slope_s0,w_channel,
                   cn_prior,n_prior,tc_hours,max_elev,min_elev,delta_h,
                   dem_source,alert_l1_m,alert_l2_m,alert_l3_m,
                   catchment_geojson,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)
            """, (station_id, req.name, req.lat, req.lon, "outlet",
                  req.area_km2, req.slope_s0, req.w_channel,
                  req.cn_prior, req.n_prior, req.tc_hours,
                  req.max_elev, req.min_elev, req.delta_h,
                  req.dem_source, req.alert_l1_m, req.alert_l2_m, req.alert_l3_m,
                  req.catchment_geojson))
        _forecasters.pop(station_id, None)
        return {"status": "ok", "station_id": station_id}
    except Exception as e:
        _tb.print_exc()
        raise HTTPException(status_code=500, detail=f"保存站点失败: {e}")

@app.get("/api/stations")
async def list_stations():
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM stations ORDER BY created_at DESC").fetchall()
    return [dict(r) for r in rows]

@app.get("/api/station/{station_id}")
async def get_station(station_id: str):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM stations WHERE id=?", (station_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="站点不存在")
    return dict(row)

@app.delete("/api/station/{station_id}")
async def delete_station(station_id: str):
    with get_conn() as conn:
        conn.execute("DELETE FROM stations WHERE id=?", (station_id,))
        conn.execute("DELETE FROM subpoints WHERE station_id=?", (station_id,))
    _forecasters.pop(station_id, None)
    return {"status": "ok"}

# ── Sub-monitoring Points ────────────────────────────────────────────────────

class SubpointCreate(BaseModel):
    id: Optional[str] = None
    name: str
    lat: float
    lon: float
    type: str = "rain_gauge"   # 'rain_gauge' | 'upstream_level'
    note: Optional[str] = None

@app.post("/api/station/{station_id}/subpoints")
async def add_subpoint(station_id: str, req: SubpointCreate):
    import uuid
    pt_id = req.id or f"sub_{uuid.uuid4().hex[:6]}"
    with get_conn() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO subpoints (id,station_id,name,lat,lon,type,note)
            VALUES (?,?,?,?,?,?,?)
        """, (pt_id, station_id, req.name, req.lat, req.lon, req.type, req.note))
    return {"status": "ok", "id": pt_id}

@app.get("/api/station/{station_id}/subpoints")
async def list_subpoints(station_id: str):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM subpoints WHERE station_id=? ORDER BY created_at", (station_id,)
        ).fetchall()
    return [dict(r) for r in rows]

@app.delete("/api/station/{station_id}/subpoints/{pt_id}")
async def delete_subpoint(station_id: str, pt_id: str):
    with get_conn() as conn:
        conn.execute("DELETE FROM subpoints WHERE id=? AND station_id=?", (pt_id, station_id))
    return {"status": "ok"}

# ── CSV Import ───────────────────────────────────────────────────────────────

@app.post("/api/observation/import/{station_id}")
async def import_observations(station_id: str, file: UploadFile = File(...)):
    try:
        content = await file.read()
        df, warnings = validate_and_parse(content)
        summary = import_to_db(station_id, df)
        summary["warnings"] = warnings
        summary["filename"] = file.filename
        return summary
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        import traceback; traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/observations/{station_id}")
async def get_obs(station_id: str, limit: int = 500):
    return get_observations(station_id, limit=limit)

# ── Data Template Generation ─────────────────────────────────────────────────

from fastapi.responses import StreamingResponse
import io as _io

@app.get("/api/station/{station_id}/template")
async def generate_data_template(station_id: str, years: int = 1):
    """
    Generate a 5-min resolution CSV template with 1-year historical precipitation
    (from Open-Meteo) and physics-simulated water level.
    """
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM stations WHERE id=?", (station_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="站点不存在")
    st = dict(row)

    try:
        from template_gen import generate_template_csv
        csv_bytes = generate_template_csv(
            lat=st["lat"], lon=st["lon"],
            area_km2=st["area_km2"] or 10,
            tc_hours=st["tc_hours"] or 1.0,
            slope_s0=st["slope_s0"] or 0.01,
            w_channel=st["w_channel"] or 10,
            cn=st["cn_prior"] or 75,
            n_manning=st["n_prior"] or 0.04,
            years=years,
        )
        filename = f"{station_id}_template_{years}yr.csv"
        return StreamingResponse(
            _io.BytesIO(csv_bytes),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'}
        )
    except Exception as e:
        import traceback; traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"模板生成失败: {e}")

# ── Forecast ─────────────────────────────────────────────────────────────────

# In-memory forecaster cache: station_id → (PhysicsForecaster, Level1Corrector)
_forecasters: dict = {}

def _get_or_build_forecaster(station_id: str):
    if station_id in _forecasters:
        return _forecasters[station_id]
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM stations WHERE id=?", (station_id,)).fetchone()
    if not row:
        return None
    st = dict(row)
    cn  = st.get("cn_corrected") or st.get("cn_prior") or 75
    n   = st.get("n_corrected")  or st.get("n_prior")  or 0.04
    fc = PhysicsForecaster(
        area_km2   = st["area_km2"] or 10,
        tc_hours   = st["tc_hours"] or 1.0,
        slope_s0   = st["slope_s0"] or 0.01,
        w_channel_m= st["w_channel"] or 10,
        cn=cn, n_manning=n,
    )
    corr = Level1Corrector()
    _forecasters[station_id] = (fc, corr)
    return fc, corr

@app.get("/api/forecast/{station_id}")
async def get_forecast(station_id: str):
    """60-minute forecast with Level-1 correction."""
    result = _get_or_build_forecaster(station_id)
    if result is None:
        raise HTTPException(status_code=404, detail="站点不存在")
    fc, corr = result

    obs = get_observations(station_id, limit=72)
    if not obs:
        raise HTTPException(status_code=404, detail="无观测数据，请先导入CSV")

    rain_hist = [float(o.get("rainfall_mm") or 0) for o in obs[-24:]]
    forecast = fc.forecast(rain_hist)

    # Alert level
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM stations WHERE id=?", (station_id,)).fetchone()
    h_peak = forecast["h_peak"]
    alert = 0
    if row:
        if h_peak >= row["alert_l3_m"]: alert = 3
        elif h_peak >= row["alert_l2_m"]: alert = 2
        elif h_peak >= row["alert_l1_m"]: alert = 1

    forecast["alert_level"] = alert
    forecast["station_id"] = station_id
    return forecast

@app.get("/api/hydrograph/{station_id}")
async def get_hydrograph(station_id: str, limit: int = 288):
    """
    Full process output: historical observations + 60-min forecast.
    Returns combined time series for chart rendering.
    limit: number of historical records (~24h at 5min = 288).
    """
    result = _get_or_build_forecaster(station_id)
    if result is None:
        raise HTTPException(status_code=404, detail="站点不存在")
    fc, corr = result

    obs = get_observations(station_id, limit=limit)
    if not obs:
        return {"historical": [], "forecast": [], "alert_level": 0}

    # Historical series
    historical = [
        {
            "time": o["timestamp"],
            "rainfall_mm": float(o.get("rainfall_mm") or 0),
            "h_obs": float(o["water_level_m"]) if o.get("water_level_m") is not None else None,
        }
        for o in obs
    ]

    # Level-1 error correction
    recent_with_level = [o for o in obs[-12:] if o.get("water_level_m") is not None]
    if len(recent_with_level) >= 3:
        for i, r in enumerate(recent_with_level[:-1]):
            h_obs = float(r["water_level_m"])
            rain_window = [float(x.get("rainfall_mm") or 0) for x in obs[max(0, len(obs)-24-i):-i-1]]
            fc_temp = fc.forecast(rain_window or [0]*24)
            h_pred = fc_temp["h_series"][0] if fc_temp["h_series"] else h_obs
            corr.add_observation(h_obs, h_pred)

        corrections = corr.compute_corrections(fc.cn, fc.n)
        fc.update_params(cn=corrections["cn"], n=corrections["n"])

    # 60-min forecast
    rain_hist = [float(o.get("rainfall_mm") or 0) for o in obs[-24:]]
    fc_result = fc.forecast(rain_hist)

    # Build forecast timestamps starting from last observation
    try:
        from datetime import datetime, timedelta
        last_time = datetime.fromisoformat(obs[-1]["timestamp"])
    except Exception:
        last_time = datetime.now()

    forecast_series = []
    for i, (step_min, h, q) in enumerate(zip(
        fc_result["time_steps"], fc_result["h_series"], fc_result["q_series"]
    )):
        t = last_time + timedelta(minutes=(i + 1) * 5)
        forecast_series.append({
            "time": t.strftime("%Y-%m-%d %H:%M:%S"),
            "h_forecast": h,
            "q_forecast": q,
        })

    # Alert level
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM stations WHERE id=?", (station_id,)).fetchone()
    h_peak = fc_result["h_peak"]
    alert = 0
    if row:
        if h_peak >= row["alert_l3_m"]: alert = 3
        elif h_peak >= row["alert_l2_m"]: alert = 2
        elif h_peak >= row["alert_l1_m"]: alert = 1

    return {
        "historical": historical,
        "forecast": forecast_series,
        "h_peak": h_peak,
        "q_peak": fc_result["q_peak"],
        "t_peak_min": fc_result["t_peak_min"],
        "cn_used": fc.cn,
        "n_used": fc.n,
        "alert_level": alert,
        "alert_thresholds": {
            "l1": float(row["alert_l1_m"]) if row else 1.0,
            "l2": float(row["alert_l2_m"]) if row else 1.5,
            "l3": float(row["alert_l3_m"]) if row else 2.0,
        } if row else {},
    }

# ── PINN Training ─────────────────────────────────────────────────────────────

@app.post("/api/model/train/{station_id}")
async def train_model(station_id: str, epochs: int = 300):
    try:
        from pinn_model import TORCH_AVAILABLE, train_pinn
        if not TORCH_AVAILABLE:
            return {"status": "skipped", "message": "PyTorch 未安装，跳过 PINN 训练。请在服务器执行: pip install torch"}

        with get_conn() as conn:
            row = conn.execute("SELECT * FROM stations WHERE id=?", (station_id,)).fetchone()
            conn.execute("UPDATE stations SET training_status='training' WHERE id=?", (station_id,))

        obs = get_observations(station_id, limit=50000)
        params = dict(row) if row else {}
        result = train_pinn(obs, params, epochs=epochs)

        # Handle training errors (no data, PyTorch missing, etc.)
        if result.get("status") == "error":
            with get_conn() as conn:
                conn.execute("UPDATE stations SET training_status='error' WHERE id=?", (station_id,))
            raise HTTPException(status_code=400, detail=result.get("message", "训练失败"))

        import json
        meta = json.dumps(result)
        cn_l = result.get("cn_learned")
        n_l  = result.get("n_learned")
        with get_conn() as conn:
            conn.execute("""
                UPDATE stations
                SET training_status='trained', training_meta=?,
                    cn_corrected=?, n_corrected=?, updated_at=CURRENT_TIMESTAMP
                WHERE id=?
            """, (meta, cn_l, n_l, station_id))
        # Invalidate forecaster cache so new params take effect
        _forecasters.pop(station_id, None)
        return result
    except HTTPException:
        raise  # pass through 400/422 etc without wrapping
    except Exception as e:
        import traceback; traceback.print_exc()
        with get_conn() as conn:
            conn.execute("UPDATE stations SET training_status='error' WHERE id=?", (station_id,))
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/model/recalculate/{station_id}")
async def recalculate_params(station_id: str):
    """
    Manually trigger Level-1 parameter recalculation using all available
    historical observations. Re-fits CN and n from error series.
    """
    obs = get_observations(station_id, limit=200)
    if len(obs) < 6:
        raise HTTPException(status_code=422, detail="历史数据不足（需至少6条含水位记录）")

    result = _get_or_build_forecaster(station_id)
    if result is None:
        raise HTTPException(status_code=404, detail="站点不存在")
    fc, corr = result

    # Feed all errors through the corrector
    rain_window = []
    for o in obs:
        rain_window.append(float(o.get("rainfall_mm") or 0))
        h_obs = o.get("water_level_m")
        if h_obs is None: continue
        fc_temp = fc.forecast(rain_window[-24:] if len(rain_window) >= 24 else [0]*(24-len(rain_window)) + rain_window)
        h_pred = fc_temp["h_series"][0] if fc_temp["h_series"] else float(h_obs)
        corr.add_observation(float(h_obs), h_pred)

    corrections = corr.compute_corrections(fc.cn, fc.n)
    fc.update_params(cn=corrections["cn"], n=corrections["n"])

    with get_conn() as conn:
        conn.execute("""
            UPDATE stations SET cn_corrected=?, n_corrected=?, updated_at=CURRENT_TIMESTAMP
            WHERE id=?
        """, (corrections["cn"], corrections["n"], station_id))

    return {
        "status": "ok",
        "cn_prior": fc.cn, "n_prior": fc.n,
        "cn_corrected": corrections["cn"],
        "n_corrected":  corrections["n"],
        "bias": corrections["bias"],
        "trend": corrections["trend"],
        "obs_used": len([o for o in obs if o.get("water_level_m") is not None]),
    }

@app.get("/api/model/status/{station_id}")
async def model_status(station_id: str):
    import json
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM stations WHERE id=?", (station_id,)).fetchone()
    from pinn_model import ONNX_PATH, TORCH_AVAILABLE, get_inferencer
    inf = get_inferencer()
    meta = {}
    if row and row["training_meta"]:
        try: meta = json.loads(row["training_meta"])
        except: pass
    return {
        "torch_available": TORCH_AVAILABLE,
        "onnx_ready": inf.is_ready(),
        "training_status": row["training_status"] if row else "unknown",
        "cn_corrected": row["cn_corrected"] if row else None,
        "n_corrected": row["n_corrected"] if row else None,
        "training_meta": meta,
    }

# ── Static Frontend ───────────────────────────────────────────────────────────
frontend_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")
if os.path.exists(frontend_dir):
    app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")


