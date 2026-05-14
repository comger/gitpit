import requests

def get_amc_and_cn(p5: float, base_cn: float) -> tuple[str, float]:
    """
    Calculate Antecedent Moisture Condition (AMC) and adjusted CN
    based on 5-day antecedent rainfall (p5 in mm).
    Uses a Continuous Linear Interpolation between the standard SCS growing season bounds
    to provide dynamic mapping for all rainfall events.
    """
    # Standard SCS Discrete Bounds
    cn_I = base_cn / (2.281 - 0.0128 * base_cn)
    cn_III = base_cn / (0.427 + 0.00573 * base_cn)
    
    # Continuous Interpolation Mode
    if p5 <= 0.0:
        amc = "I (极度干旱)"
        cn_adj = cn_I
    elif p5 < 36.0:
        amc = "I-II (偏干)"
        # Interpolate between CN_I (at 0mm) and base_cn (at 36mm)
        cn_adj = cn_I + (p5 / 36.0) * (base_cn - cn_I)
    elif p5 <= 53.0:
        amc = "II (正常)"
        # Interpolate between base_cn (at 36mm) and CN_III (at 53mm)
        cn_adj = base_cn + ((p5 - 36.0) / (53.0 - 36.0)) * (cn_III - base_cn)
    else:
        amc = "III (极度湿润)"
        # Cap at CN_III but allow slight continuous scaling up to CN=99 for extreme events (>150mm)
        extra = (p5 - 53.0) / 100.0 * (99.0 - cn_III)
        cn_adj = min(99.0, cn_III + extra)
        
    return amc, round(cn_adj, 1)

def fetch_meteo_data(lat: float, lon: float, base_cn: float = 75.0, area_km2: float = 0.0, delta_h: float = 0.0, custom_forecast: list = None) -> dict:
    """
    Fetches meteorology from Open-Meteo, calculates AMC and final CN.
    """
    url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&daily=precipitation_sum,temperature_2m_max,temperature_2m_min&past_days=5&forecast_days=3&timezone=auto"
    
    try:
        res = requests.get(url, timeout=5)
        res.raise_for_status()
        data = res.json()
        
        daily = data.get("daily", {})
        precip = daily.get("precipitation_sum", [])
        tmax = daily.get("temperature_2m_max", [])
        tmin = daily.get("temperature_2m_min", [])
        dates = daily.get("time", [])
        
        # Open-Meteo with past_days=5 and forecast=3 returns 8 days total
        # Indices 0 to 4 are past 5 days, 0 is 5 days ago, 4 is yesterday.
        past_precip = precip[:5]
        p5 = sum(p for p in past_precip if p is not None)
        
        # Calculate API (Antecedent Precipitation Index) with K=0.9
        k = 0.90
        api_val = 0.0
        for i, p in enumerate(past_precip):
            if p is not None:
                # index 4 is 1 day ago (K^1), index 0 is 5 days ago (K^5)
                days_ago = 5 - i
                api_val += p * (k ** days_ago)
                
        amc, final_cn = get_amc_and_cn(p5, base_cn)

        # Inject custom forecast if provided
        if custom_forecast and len(custom_forecast) == 3:
            for i in range(3):
                if 5 + i < len(precip):
                    precip[5 + i] = custom_forecast[i]
                else:
                    precip.append(custom_forecast[i])
        
        # Determine actual forecast cumulative precip for P5 context
        forecast_precips = [p for p in precip[5:8] if p is not None]
        sum_forecast_p = sum(forecast_precips) if forecast_precips else 0.0
        
        # Design storm = maximum SINGLE-DAY rainfall in forecast window
        # SCS Unit Hydrograph is driven by a single storm event, not multi-day cumulative.
        # Using the peak daily amount as the design storm is physically correct for short-T_c catchments.
        P_design = max(forecast_precips) if forecast_precips else 0.0
        p_design_day_idx = forecast_precips.index(P_design) if forecast_precips else 0
        p_design_date = dates[5 + p_design_day_idx] if len(dates) > 5 + p_design_day_idx else ""
        S = (25400.0 / final_cn) - 254.0 if final_cn > 0 else 9999.0
        Ia = 0.2 * S # Initial Abstraction
        
        if P_design <= Ia:
            runoff_f = 0.0
            runoff_vol_m3 = 0.0
            R_val = 0.0
        else:
            R_val = ((P_design - Ia)**2) / (P_design - Ia + S)
            runoff_f = R_val / P_design
            # Runoff volume: R (mm) * Area (km2) * 1000 = m3
            runoff_vol_m3 = R_val * area_km2 * 1000.0
            
        # Compile exact step-by-step equation strings for UI
        past_str = " + ".join([str(p) if p is not None else "0" for p in past_precip])
        eq_p5 = f"= {past_str} = {round(p5, 1)}"
        eq_p5_vol = f"= {round(p5, 1)} × {round(area_km2, 2)} × 1000 = {round(p5 * area_km2 * 1000, 1)}"
        
        api_terms = [f"{p}×0.9^{5-i}" for i, p in enumerate(past_precip) if p is not None and p > 0]
        eq_api = f"= {' + '.join(api_terms)} = {round(api_val, 2)}" if api_terms else "= 0"
        
        eq_amc = f"P₅ ({round(p5, 1)}) ➔ {amc.split(' ')[0]}"
        eq_cn = f"= f(P₅={round(p5,1)}, Base={round(base_cn,1)}) = {round(final_cn, 1)}"
        eq_s = f"= 25400 / {round(final_cn, 1)} - 254 = {round(S, 2)} mm"
        eq_ia = f"= 0.2 × {round(S, 2)} = {round(Ia, 2)} mm"
        
        # Design storm note for UI
        p_design_label = f"{p_design_date[:5] if p_design_date else '预报'} 单日最大 {round(P_design, 1)} mm"
        
        eq_qs = f"= ({round(P_design, 1)} - {round(Ia, 2)})² / ({round(P_design, 1)} - {round(Ia, 2)} + {round(S, 2)}) = {round(R_val, 2)} mm"
        eq_f = f"= {round(R_val, 2)} / {round(P_design, 1)} = {round(runoff_f, 3)}"
        if P_design <= Ia:
            eq_qs = f"P({round(P_design,1)}) <= Iₐ({round(Ia,2)}), 降雨被坑洼拦截, Qₛ = 0"
            eq_f = f"P({round(P_design,1)}) <= Iₐ({round(Ia,2)}) ➔ α = 0"
            
        eq_rvol = f"= {round(R_val, 2)} × {round(area_km2, 2)} × 1000 = {round(runoff_vol_m3, 1)}"
        
        # ---------------------------------------------
        # SCS Unit Hydrograph & River Stage Routing
        # ---------------------------------------------
        # 1. Hack's Law for Main Channel Length
        L_km = 1.4 * (area_km2 ** 0.6)
        L_m = L_km * 1000.0
        
        # 2. Average channel slope
        slope = delta_h / L_m if L_m > 0 else 0.001
        slope_adj = max(0.001, slope)
        
        # 3. Kirpich formula (metric): Tc in minutes (L in meters, S in m/m)
        tc_minutes = 0.0195 * (L_m ** 0.77) * (slope_adj ** -0.385)
        tc_hours = tc_minutes / 60.0
        
        # 4. SCS Triangular Unit Hydrograph Generation
        D = 1.0 # Assume duration of excess rainfall D = 1 hour
        tp_hours = D / 2.0 + 0.6 * tc_hours
        tb_hours = 2.67 * tp_hours
        
        # Unit peak discharge (m3/s) & Actual peak discharge
        qp_unit = (0.208 * area_km2) / tp_hours if tp_hours > 0 else 0.0
        Qp = qp_unit * R_val
        
        time_series = []
        q_series = []
        if Qp > 0:
            step = max(0.5, tb_hours / 20.0)
            t = 0.0
            while t <= tb_hours:
                if t <= tp_hours:
                    q = (t / tp_hours) * Qp
                else:
                    q = Qp * (1.0 - (t - tp_hours) / (tb_hours - tp_hours))
                time_series.append(round(t, 2))
                q_series.append(round(max(0, q), 2))
                t += step
            if time_series[-1] != round(tb_hours, 2):
                time_series.append(round(tb_hours, 2))
                q_series.append(0.0)
                
        # 5. Manning's Routing for Peak Stage Depth
        n_manning = 0.04
        W_channel = max(2.0, 2.5 * (area_km2 ** 0.5)) # Geomorphic Width
        
        max_stage_depth = 0.0
        if Qp > 0:
            try:
                val = (Qp * n_manning) / (W_channel * (slope_adj ** 0.5))
                max_stage_depth = val ** 0.6
            except:
                max_stage_depth = 0.0
                
        # 6. Build UI equation traces for Hydrograph
        eq_l = f"L = 1.4 × {round(area_km2, 2)}^0.6 = {round(L_km, 2)} km"
        eq_tc = f"T\_c = 0.0195 × ({round(L_m, 1)})^0.77 × ({round(slope_adj, 4)})^-0.385 / 60 = {round(tc_hours, 2)} h"
        eq_tp = f"T\_p = 1/2 + 0.6 × {round(tc_hours, 2)} = {round(tp_hours, 2)} h"
        eq_qp = f"Q\_p = (0.208 × {round(area_km2, 2)} / {round(tp_hours, 2)}) × {round(R_val, 2)} = {round(Qp, 1)} m³/s"
        eq_depth = f"h = [({round(Qp, 1)} × 0.04) / ({round(W_channel, 1)} × √{round(slope_adj, 4)})]^0.6 = {round(max_stage_depth, 2)} m"
        
        # Today's temp (index 5)
        today_tmax = tmax[5] if len(tmax) > 5 else None
        today_tmin = tmin[5] if len(tmin) > 5 else None
        
        # Forecast for next 3 days (indices 5, 6, 7)
        # 5 is today, 6 is tomorrow, 7 is day after
        forecast = []
        for i in range(5, min(8, len(dates))):
            forecast.append({
                "date": dates[i],
                "precip_mm": precip[i],
                "tmax": tmax[i],
                "tmin": tmin[i]
            })
            
        return {
            "p5_mm": round(p5, 1),
            "p5_vol_m3": round(p5 * area_km2 * 1000, 1),
            "api_val": round(api_val, 2),
            "k_val": k,
            "p_design_mm": round(P_design, 1),
            "p_design_label": p_design_label,
            "p_design_3day_mm": round(sum_forecast_p, 1),
            "s_val": round(S, 2),
            "ia_val": round(Ia, 2),
            "qs_val": round(R_val, 2),
            "f_val": round(runoff_f, 3),
            "r_vol_m3": round(runoff_vol_m3, 1),
            "amc": amc,
            "base_cn": base_cn,
            "final_cn": final_cn,
            "today_temp": f"{today_tmin}°C - {today_tmax}°C" if today_tmin is not None else "未知",
            "forecast": forecast,
            "routing": {
                "l_km": round(L_km, 2),
                "slope": round(slope_adj, 4),
                "tc_hours": round(tc_hours, 2),
                "tp_hours": round(tp_hours, 2),
                "qp_m3s": round(Qp, 1),
                "w_channel_m": round(W_channel, 1),
                "max_stage_depth_m": round(max_stage_depth, 2),
                "time_series": time_series,
                "q_series": q_series,
                "stage_series": [
                    round(((q * n_manning) / (W_channel * (slope_adj ** 0.5))) ** 0.6, 3)
                    if q > 0 else 0.0
                    for q in q_series
                ]
            },
            "eqs": {
                "eq_p5": eq_p5,
                "eq_p5_vol": eq_p5_vol,
                "eq_api": eq_api,
                "eq_amc": eq_amc,
                "eq_cn": eq_cn,
                "eq_s": eq_s,
                "eq_ia": eq_ia,
                "eq_qs": eq_qs,
                "eq_f": eq_f,
                "eq_rvol": eq_rvol,
                "eq_l": eq_l,
                "eq_tc": eq_tc,
                "eq_tp": eq_tp,
                "eq_qp": eq_qp,
                "eq_depth": eq_depth
            }
        }
        
    except Exception as e:
        print(f"Error fetching meteo data: {e}")
        return {
            "error": str(e)
        }
