"""
Physics-based flood routing engine.
Implements:
  1. SCS-CN runoff (with correctable CN)
  2. SCS Triangular Unit Hydrograph convolution
  3. Manning's equation for stage depth
  4. 60-minute forward prediction (12 steps × 5 min)

All computation is pure NumPy — runs fast on CPU and is NPU-agnostic.
The PINN layer (Iteration 2) will correct the outputs of this engine.
"""

import numpy as np
from typing import List, Optional, Dict, Any


# ---------------------------------------------------------------------------
# SCS-CN Runoff
# ---------------------------------------------------------------------------

def scs_runoff(P_mm: float, CN: float) -> float:
    """
    SCS-CN net runoff depth (mm) for a single rainfall event.
    P_mm: rainfall depth (mm)
    CN:   curve number (1-99)
    """
    S = (25400.0 / CN) - 254.0
    Ia = 0.2 * S
    if P_mm <= Ia:
        return 0.0
    return ((P_mm - Ia) ** 2) / (P_mm - Ia + S)


# ---------------------------------------------------------------------------
# SCS Triangular Unit Hydrograph
# ---------------------------------------------------------------------------

def build_unit_hydrograph(
    area_km2: float,
    tc_hours: float,
    dt_hours: float = 1.0 / 12,  # 5-minute steps
) -> np.ndarray:
    """
    Build discrete SCS triangular unit hydrograph (ordinate array).
    dt_hours: time step in hours (default 5 min = 1/12 h)
    Returns array of unit discharge [m³/s per mm of net rainfall].
    """
    D = dt_hours  # rainfall duration = 1 time step
    tp = D / 2.0 + 0.6 * tc_hours  # time to peak
    tb = 2.67 * tp  # base time
    qp_unit = 0.208 * area_km2 / tp  # peak unit discharge (m³/s/mm)

    n_steps = int(np.ceil(tb / dt_hours)) + 2
    t = np.arange(n_steps) * dt_hours
    uh = np.where(
        t <= tp,
        (t / tp) * qp_unit,
        np.where(
            t <= tb,
            qp_unit * (1.0 - (t - tp) / (tb - tp)),
            0.0
        )
    )
    return np.maximum(uh, 0.0)


def convolve_runoff(
    rainfall_series: np.ndarray,    # mm per timestep
    area_km2: float,
    tc_hours: float,
    CN: float,
    dt_hours: float = 1.0 / 12,
) -> np.ndarray:
    """
    Convolve net rainfall with SCS UH to get flow hydrograph.
    Returns flow array (m³/s) same length as input + UH.
    """
    uh = build_unit_hydrograph(area_km2, tc_hours, dt_hours)
    # Compute net rainfall for each interval
    net_rain = np.array([scs_runoff(float(p), CN) for p in rainfall_series])
    # Discrete convolution
    flow = np.convolve(net_rain, uh)[:len(rainfall_series) + len(uh) - 1]
    return flow


# ---------------------------------------------------------------------------
# Manning Water Depth
# ---------------------------------------------------------------------------

def manning_depth(
    Q_m3s: float,
    W_m: float,
    S0: float,
    n: float,
    max_depth: float = 15.0,
) -> float:
    """
    Compute normal flow depth for a rectangular channel using Manning's equation.
    Q = (1/n) * A * R^(2/3) * S0^(1/2)
    Solved iteratively for depth H.
    """
    if Q_m3s <= 0 or S0 <= 0:
        return 0.0

    # Closed-form approximation for wide rectangular channel (W >> H):
    # Q ≈ (1/n) * W * H * H^(2/3) * S0^(1/2)
    # H ≈ [(Qn) / (W * sqrt(S0))]^(0.6)
    val = (Q_m3s * n) / (W_m * np.sqrt(S0))
    H_approx = val ** 0.6

    # Refine with Newton-Raphson for narrow channels
    H = H_approx
    for _ in range(10):
        A = W_m * H
        P = W_m + 2.0 * H
        R = A / P
        Q_calc = (1.0 / n) * A * (R ** (2.0 / 3.0)) * (S0 ** 0.5)
        # dQ/dH
        dAdH = W_m
        dPdH = 2.0
        dRdH = (dAdH * P - A * dPdH) / (P ** 2)
        dQdH = (1.0 / n) * (dAdH * R ** (2 / 3) + A * (2 / 3) * R ** (-1 / 3) * dRdH) * S0 ** 0.5
        if abs(dQdH) < 1e-12:
            break
        H = H - (Q_calc - Q_m3s) / dQdH
        H = max(0.001, min(H, max_depth))

    return round(float(H), 4)


# ---------------------------------------------------------------------------
# 60-Minute Forecast Engine
# ---------------------------------------------------------------------------

class PhysicsForecaster:
    """
    Generates 60-minute water level forecast using physics-based model.
    Uses the last N observations to drive the SCS UH convolution.
    """

    STEPS = 12        # 12 steps × 5 min = 60 min
    DT_HOURS = 1 / 12  # 5-minute resolution

    def __init__(
        self,
        area_km2: float,
        tc_hours: float,
        slope_s0: float,
        w_channel_m: float,
        cn: float = 75.0,
        n_manning: float = 0.04,
    ):
        self.area_km2 = area_km2
        self.tc_hours = tc_hours
        self.slope_s0 = slope_s0
        self.w_channel_m = w_channel_m
        self.cn = cn
        self.n = n_manning

        # Pre-build unit hydrograph
        self._uh = build_unit_hydrograph(area_km2, tc_hours, self.DT_HOURS)

    def forecast(
        self,
        obs_rainfall: List[float],  # historical rainfall (mm/5min), latest last
        obs_level: Optional[List[float]] = None,  # historical water levels
        future_rainfall: Optional[List[float]] = None,  # forecast rainfall (12 steps)
    ) -> Dict[str, Any]:
        """
        Produce 60-minute forecast.

        Returns dict with:
          time_steps: [5, 10, ..., 60]  (minutes ahead)
          q_series:   flow forecast (m³/s)
          h_series:   water level forecast (m)
          cn_used:    CN value applied
          n_used:     Manning n applied
        """
        # Extend rainfall with future forcing
        if future_rainfall is None:
            future_rainfall = [0.0] * self.STEPS
        future_rainfall = list(future_rainfall)[:self.STEPS]
        while len(future_rainfall) < self.STEPS:
            future_rainfall.append(0.0)

        combined_rain = list(obs_rainfall) + future_rainfall
        rain_arr = np.array(combined_rain, dtype=float)

        # Convolve net rainfall with UH
        net_rain = np.array([scs_runoff(p, self.cn) for p in rain_arr])
        flow_full = np.convolve(net_rain, self._uh)

        # Extract the forecast window (next 12 steps)
        obs_len = len(obs_rainfall)
        q_fc = flow_full[obs_len: obs_len + self.STEPS]
        if len(q_fc) < self.STEPS:
            q_fc = np.pad(q_fc, (0, self.STEPS - len(q_fc)))

        # Convert flow to water depth
        h_fc = np.array([
            manning_depth(q, self.w_channel_m, self.slope_s0, self.n)
            for q in q_fc
        ])

        return {
            "time_steps": [i * 5 for i in range(1, self.STEPS + 1)],
            "q_series": [round(float(q), 3) for q in q_fc],
            "h_series": [round(float(h), 4) for h in h_fc],
            "h_peak": round(float(h_fc.max()), 4),
            "q_peak": round(float(q_fc.max()), 3),
            "t_peak_min": int((np.argmax(h_fc) + 1) * 5),
            "cn_used": self.cn,
            "n_used": self.n,
            "model": "physics",
        }

    def update_params(self, cn: Optional[float] = None, n: Optional[float] = None):
        """Online parameter correction (Level 1)."""
        if cn is not None:
            self.cn = float(np.clip(cn, 40, 99))
        if n is not None:
            self.n = float(np.clip(n, 0.01, 0.15))
        # Rebuild UH is not needed (UH doesn't depend on CN or n)


# ---------------------------------------------------------------------------
# Level-1 Online Parameter Correction
# ---------------------------------------------------------------------------

class Level1Corrector:
    """
    Lightweight sliding-window error correction.
    No gradient, no model retraining — runs in <1ms.
    """

    def __init__(self, window: int = 6, alpha_cn: float = 0.3, alpha_n: float = 0.1):
        self.window = window
        self.alpha_cn = alpha_cn
        self.alpha_n = alpha_n
        self._errors: List[float] = []

    def add_observation(self, h_obs: float, h_pred: float):
        """Record prediction error."""
        self._errors.append(h_obs - h_pred)
        if len(self._errors) > self.window:
            self._errors.pop(0)

    def compute_corrections(
        self, cn_current: float, n_current: float
    ) -> Dict[str, float]:
        """
        Derive CN and n corrections from error window.

        Bias (systematic over/under prediction) → adjust CN
        Trend (consistently growing error) → adjust n (affects peak shape)
        """
        if len(self._errors) < 2:
            return {"cn": cn_current, "n": n_current, "bias": 0.0, "trend": 0.0}

        errors = np.array(self._errors)
        bias = float(np.mean(errors))
        trend = float(np.polyfit(range(len(errors)), errors, 1)[0])

        # Positive bias = model under-predicts water level = too little runoff = CN too low
        cn_new = cn_current + self.alpha_cn * bias * 2.0
        cn_new = float(np.clip(cn_new, 40, 99))

        # Positive trend = rising error = model losing speed → increase n to slow recession
        n_new = n_current + self.alpha_n * trend * 0.001
        n_new = float(np.clip(n_new, 0.01, 0.15))

        return {
            "cn": round(cn_new, 2),
            "n": round(n_new, 5),
            "bias": round(bias, 4),
            "trend": round(trend, 6),
        }
