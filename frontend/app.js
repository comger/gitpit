// Map Initialization
const map = L.map('map', {
    zoomControl: false, // Using custom positioning if needed
    doubleClickZoom: false
}).setView([39.9, 116.4], 10); // Default set to Beijing, user can drag

// Add dark mode basemap without road labels (CartoDB Dark Matter No Labels)
L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_nolabels/{z}/{x}/{y}{r}.png', {
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/attributions">CARTO</a>',
    subdomains: 'abcd',
    maxZoom: 20
}).addTo(map);

// Add zoom control to top right to not block the floating panel
L.control.zoom({ position: 'topright' }).addTo(map);

// DOM Elements
const statusBox = document.getElementById('status');
const resultsPanel = document.getElementById('results');
const loader = document.getElementById('loader');
const areaVal = document.getElementById('area-val');
const demAccuracyVal = document.getElementById('dem-accuracy-val');
const demSourceVal = document.getElementById('dem-source-val');
const btnExportArea = document.getElementById('btn-export-area');
const btnExportPath = document.getElementById('btn-export-path');
const searchInput = document.getElementById('search-input');
const btnSearch = document.getElementById('btn-search');

const meteoSidebar = document.getElementById('meteo-sidebar');
const topMeteoBar = document.getElementById('top-meteo-bar');
const topP5Val = document.getElementById('top-p5-val');
const topP5VolVal = document.getElementById('top-p5-vol-val');
const topTempVal = document.getElementById('top-temp-val');
const topForecast = document.getElementById('top-forecast');

const meteoApiVal = document.getElementById('meteo-api-val');
const meteoAmcVal = document.getElementById('meteo-amc-val');
const meteoKVal = document.getElementById('meteo-k-val');
const meteoCnVal = document.getElementById('meteo-cn-val');
const meteoPdesign1Val = document.getElementById('meteo-pdesign1-val');
const meteoSVal = document.getElementById('meteo-s-val');
const meteoIaVal = document.getElementById('meteo-ia-val');
const meteoQsVal = document.getElementById('meteo-qs-val');
const meteoFVal = document.getElementById('meteo-f-val');

const hydroPanel = document.getElementById('hydro-panel');
const hydroContent = document.getElementById('hydro-content');
const hydroLVal = document.getElementById('hydro-l-val');
const hydroTcVal = document.getElementById('hydro-tc-val');
const hydroQpVal = document.getElementById('hydro-qp-val');
const hydroStageVal = document.getElementById('hydro-stage-val');

// State
let currentCatchmentGeoJSON = null;
let currentPathGeoJSON = null;
let currentAnalysisParams = null;
let mapLayers = [];

function clearMap() {
    mapLayers.forEach(layer => map.removeLayer(layer));
    mapLayers = [];
}

function showStatus(message, type) {
    if (type === 'success') {
        statusBox.classList.add('hidden');
        setTimeout(() => alert(message), 100);
        return;
    }
    statusBox.classList.remove('hidden');
    statusBox.className = `status-box ${type}`;
    statusBox.textContent = message;
}

function showLoader(text) {
    if (text) document.querySelector('#loader p').textContent = text;
    loader.classList.remove('hidden');
}

function hideLoader() {
    loader.classList.add('hidden');
}

function downloadGeoJSON(data, filename) {
    const dataStr = "data:text/json;charset=utf-8," + encodeURIComponent(JSON.stringify(data));
    const a = document.createElement('a');
    a.setAttribute("href", dataStr);
    a.setAttribute("download", filename);
    document.body.appendChild(a);
    a.click();
    a.remove();
}

// Map Double Click Event
map.on('dblclick', async (e) => {
    const lat = e.latlng.lat;
    const lon = e.latlng.lng;
    
    // Add point marker temporarily
    const marker = L.circleMarker([lat, lon], {
        radius: 6,
        fillColor: "#ef4444",
        color: "#ffffff",
        weight: 2,
        opacity: 1,
        fillOpacity: 1
    }).addTo(map);
    
    // Prompt the user
    if (!window.confirm("是否在此提取集雨面积信息？")) {
        map.removeLayer(marker);
        return;
    }
    
    clearMap();
    resultsPanel.classList.add('hidden');
    mapLayers.push(marker);
    marker.addTo(map);

    showStatus(`正在解析坐标 (${lat.toFixed(4)}, ${lon.toFixed(4)})...`, 'empty');
    showLoader('正在分析地形并计算汇流路径...');

    try {
        const response = await fetch('/api/analyze', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ lat, lon })
        });
        
        if (!response.ok) {
            const errData = await response.json();
            throw new Error(errData.detail || '服务器请求错误');
        }
        
        const data = await response.json();
        
        // Save state for export and recalculation
        currentCatchmentGeoJSON = data.catchment;
        currentPathGeoJSON = data.flow_path;
        currentAnalysisParams = {
            lat: data.pour_point?.coordinates?.[1] || lat,
            lon: data.pour_point?.coordinates?.[0] || lon,
            area_km2: data.area_km2 || 0,
            delta_h: data.delta_h || 0
        };
        
        // Draw Catchment
        if (data.catchment && data.catchment.features.length > 0) {
            const catchmentLayer = L.geoJSON(data.catchment, {
                style: {
                    color: '#34d399',
                    weight: 2,
                    opacity: 0.8,
                    fillColor: '#10b981',
                    fillOpacity: 0.2
                }
            }).addTo(map);
            mapLayers.push(catchmentLayer);
            
            // Adjust map view to fit catchment
            map.fitBounds(catchmentLayer.getBounds(), { padding: [50, 50] });
        }
        
        // Draw Flow Path
        if (data.flow_path && Object.keys(data.flow_path).length > 0) {
            const pathLayer = L.geoJSON(data.flow_path, {
                style: {
                    color: '#60a5fa',
                    weight: 3,
                    opacity: 0.9
                }
            }).addTo(map);
            mapLayers.push(pathLayer);
        }
        
        // Update marker to snapped point if available
        if (data.pour_point && data.pour_point.coordinates) {
            marker.setLatLng([data.pour_point.coordinates[1], data.pour_point.coordinates[0]]);
        }
        
        // Update UI
        areaVal.textContent = `${data.area_km2.toFixed(3)} km²`;
        demAccuracyVal.textContent = data.dem_accuracy || '未知';
        
        // Update tag styling based on source
        demSourceVal.textContent = data.dem_source;
        if (data.dem_source.includes('local')) {
            demSourceVal.style.background = 'rgba(16, 185, 129, 0.2)';
            demSourceVal.style.color = '#6ee7b7';
        } else {
            demSourceVal.style.background = 'rgba(59, 130, 246, 0.2)';
            demSourceVal.style.color = '#93c5fd';
        }
        
        // Update Meteo Panel
        if (data.meteo && !data.meteo.error) {
            updateMeteoUI(data.meteo);
        } else {
            meteoSidebar.classList.add('hidden');
            if (topMeteoBar) topMeteoBar.classList.add('hidden');
            if (hydroPanel) hydroPanel.classList.add('hidden');
        }

        // Render Stream Order Stats
        const streamSection = document.getElementById('stream-order-section');
        const streamTbody = document.getElementById('stream-order-tbody');
        console.log('[stream_order_stats]', data.stream_order_stats);
        if (streamSection && streamTbody) {
            streamSection.classList.remove('hidden');
            if (data.stream_order_stats && data.stream_order_stats.length > 0) {
                const orderLabels = { 1: '一级 (支沟)', 2: '二级 (支流)', 3: '三级 (干流)' };
                const orderColors = { 1: '#93c5fd', 2: '#34d399', 3: '#f59e0b' };
                streamTbody.innerHTML = data.stream_order_stats.map(s => `
                    <tr style="border-top: 1px solid rgba(255,255,255,0.07);">
                        <td style="padding: 5px 0; color: ${orderColors[s.order] || '#fff'}; font-weight: 700;">${orderLabels[s.order] || `${s.order}级`}</td>
                        <td style="text-align:right; padding: 5px 4px; color: #e2e8f0;">${s.total_length_km}</td>
                        <td style="text-align:right; padding: 5px 4px; color: #e2e8f0;">${s.elev_drop_m}</td>
                        <td style="text-align:right; padding: 5px 4px; color: ${orderColors[s.order] || '#fff'}; font-weight: 600;">${s.avg_slope_pct}%</td>
                    </tr>
                `).join('');
            } else {
                streamTbody.innerHTML = `<tr><td colspan="4" style="padding: 8px 0; color: rgba(255,255,255,0.4); font-size: 11px;">河道数据计算中或不足</td></tr>`;
            }
        }
        
        showStatus('分析完成！', 'success');
        resultsPanel.classList.remove('hidden');
        // Fire custom event to show "Save as Station" button
        map.fireEvent('analysissuccess', { data });
        
    } catch (error) {
        showStatus(`错误: ${error.message}`, 'error');
    } finally {
        hideLoader();
    }
});

function updateMeteoUI(meteoData) {
    if (topP5Val) topP5Val.textContent = `${meteoData.p5_mm} mm`;
    if (topP5VolVal) topP5VolVal.textContent = `${meteoData.p5_vol_m3.toLocaleString()} m³`;
    if (topTempVal) topTempVal.textContent = meteoData.today_temp;
    
    let forecastHtml = '';
    meteoData.forecast.forEach((f, idx) => {
        const day = new Date(f.date).toLocaleDateString('zh-CN', {month:'numeric', day:'numeric'});
        forecastHtml += `
        <div class="forecast-cell" style="text-align: center; padding: 6px 12px; background: rgba(96,165,250,0.08); border-radius: 10px; border: 1px solid rgba(96,165,250,0.15); min-width: 58px;">
            <span class="date" style="font-size: 11px; display:block; color: rgba(255,255,255,0.55); margin-bottom: 4px; letter-spacing: 0.5px;">${day}</span>
            <div style="display:flex; align-items: baseline; justify-content: center; gap: 2px;">
                <input type="number" class="forecast-input" data-idx="${idx}" value="${f.precip_mm}" step="0.1" min="0" max="999" style="width: 38px; background: transparent; border: none; border-bottom: 1.5px dashed rgba(96,165,250,0.6); color: #93c5fd; font-weight: 800; text-align: center; font-size: 18px; outline: none;">
                <span style="color: rgba(147,197,253,0.7); font-size: 10px; font-weight: 600;">mm</span>
            </div>
        </div>
        `;
    });
    if (topForecast) {
        topForecast.innerHTML = forecastHtml;
        // The event listener is now on the explicit recalculate button, not the inputs.
    }
    if (topMeteoBar) topMeteoBar.classList.remove('hidden');

    // Update Right Sidebar Meteo Factors
    if (meteoApiVal) meteoApiVal.textContent = `${meteoData.api_val} mm`;
    if (meteoAmcVal) meteoAmcVal.textContent = meteoData.amc;
    if (meteoKVal) meteoKVal.textContent = meteoData.k_val;
    if (meteoCnVal) meteoCnVal.textContent = meteoData.final_cn;
    if (meteoPdesign1Val) meteoPdesign1Val.textContent = meteoData.p_design_mm;
    const pdesignLabelEl = document.getElementById('meteo-pdesign-label');
    if (pdesignLabelEl && meteoData.p_design_label) pdesignLabelEl.textContent = meteoData.p_design_label;
    if (meteoSVal) meteoSVal.textContent = `${meteoData.s_val} mm`;
    if (meteoIaVal) meteoIaVal.textContent = `${meteoData.ia_val} mm`;
    if (meteoQsVal) meteoQsVal.textContent = `${meteoData.qs_val} mm`;
    if (meteoFVal) meteoFVal.innerHTML = `${meteoData.f_val}`;

    // Map generated equation strings for teaching
    if (meteoData.eqs) {
        const eqPaths = {
            'eq-p5': meteoData.eqs.eq_p5,
            'eq-p5-vol': meteoData.eqs.eq_p5_vol,
            'eq-api': meteoData.eqs.eq_api,
            'eq-amc': meteoData.eqs.eq_amc,
            'eq-cn': meteoData.eqs.eq_cn,
            'eq-s': meteoData.eqs.eq_s,
            'eq-ia': meteoData.eqs.eq_ia,
            'eq-qs': meteoData.eqs.eq_qs,
            'eq-f': meteoData.eqs.eq_f,
            'eq-l': meteoData.eqs.eq_l,
            'eq-tc': meteoData.eqs.eq_tc,
            'eq-qp': meteoData.eqs.eq_qp,
            'eq-depth': meteoData.eqs.eq_depth
        };
        for (const [id, html] of Object.entries(eqPaths)) {
            const el = document.getElementById(id);
            if (el && html) el.innerHTML = html;
        }
    }
    meteoSidebar.classList.remove('hidden');

    // --- Unit Hydrograph Rendering (Bottom Standalone Panel) ---
    if (meteoData.routing && hydroPanel) {
        hydroPanel.classList.remove('hidden');
        if (hydroLVal) hydroLVal.textContent = `${meteoData.routing.l_km.toFixed(1)} km`;
        if (hydroTcVal) hydroTcVal.textContent = `${meteoData.routing.tc_hours.toFixed(1)} h`;
        if (hydroQpVal) hydroQpVal.textContent = `${meteoData.routing.qp_m3s.toFixed(1)} m³/s`;
        if (hydroStageVal) hydroStageVal.textContent = `${meteoData.routing.max_stage_depth_m.toFixed(2)} m`;
        
        // Rebind tips double-clicks specifically for dynamically shown hydro items
        const hydroItems = hydroPanel.querySelectorAll('.result-item.interactive');
        hydroItems.forEach(item => {
            if (!item.dataset.bound) {
                item.dataset.bound = "true";
                const hint = item.querySelector('.formula-hint');
                if (hint) {
                    item.addEventListener('dblclick', () => {
                        window.getSelection().removeAllRanges();
                        hint.classList.toggle('show');
                    });
                }
            }
        });
        
        renderHydrograph(meteoData.routing.time_series, meteoData.routing.q_series, meteoData.routing.stage_series);
    }
}

async function triggerRecalculateMeteo() {
    if (!currentAnalysisParams) return;
    
    // Extract values from inputs
    const inputs = topForecast.querySelectorAll('.forecast-input');
    const customForecast = [];
    inputs.forEach(input => {
        customForecast.push(parseFloat(input.value) || 0.0);
    });
    
    // Add nice pulsing effect to UI to indicate loading
    [meteoSidebar, hydroPanel].forEach(el => {
        if (el) el.style.opacity = '0.5';
    });
    
    try {
        const payload = Object.assign({}, currentAnalysisParams, { custom_forecast: customForecast });
        const res = await fetch('/api/recalculate_meteo', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(payload)
        });
        if (res.ok) {
            const data = await res.json();
            if (data.meteo && !data.meteo.error) {
                // Remove focus to prevent continuous triggers
                document.activeElement.blur();
                updateMeteoUI(data.meteo);
                showStatus('产汇流与河道演进参数已极速更新', 'success');
            }
        }
    } catch(err) {
        console.error(err);
        showStatus('更新失败', 'error');
    } finally {
        [meteoSidebar, hydroPanel].forEach(el => {
            if (el) el.style.opacity = '1.0';
        });
    }
}

// Setup Export Listeners
btnExportArea.addEventListener('click', () => {
    if (currentCatchmentGeoJSON) {
        downloadGeoJSON(currentCatchmentGeoJSON, 'catchment_area.geojson');
    }
});

btnExportPath.addEventListener('click', () => {
    if (currentPathGeoJSON) {
        downloadGeoJSON(currentPathGeoJSON, 'flow_path.geojson');
    }
});

// Search functionality
btnSearch.addEventListener('click', async () => {
    const val = searchInput.value.trim();
    if (!val) return;
    
    // Check if it's lat,lon coordinate
    const coordMatch = val.match(/^([-+]?\d*\.?\d+)\s*,\s*([-+]?\d*\.?\d+)$/);
    if (coordMatch) {
        const lat = parseFloat(coordMatch[1]);
        const lon = parseFloat(coordMatch[2]);
        map.setView([lat, lon], 14);
        // Simulate a click
        map.fireEvent('click', { latlng: L.latLng(lat, lon) });
        return;
    }
    
    // Fallback to nominatim search
    showLoader('正在搜索地点...');
    try {
        const res = await fetch(`https://nominatim.openstreetmap.org/search?format=json&q=${encodeURIComponent(val)}`);
        const data = await res.json();
        if (data && data.length > 0) {
            const loc = data[0];
            const lat = parseFloat(loc.lat);
            const lon = parseFloat(loc.lon);
            map.setView([lat, lon], 14);
        } else {
            alert('未找到相关地点');
        }
    } catch (e) {
        alert('搜索服务暂时不可用');
    } finally {
        hideLoader();
    }
});

const btnRecalcMeteo = document.getElementById('btn-recalc-meteo');
if (btnRecalcMeteo) {
    btnRecalcMeteo.addEventListener('click', triggerRecalculateMeteo);
}

const btnAnalyzeNetwork = document.getElementById('btn-analyze-network');
btnAnalyzeNetwork.addEventListener('click', async () => {
    const bounds = map.getBounds();
    const min_lat = bounds.getSouth();
    const min_lon = bounds.getWest();
    const max_lat = bounds.getNorth();
    const max_lon = bounds.getEast();

    if (!window.confirm("确定要提取当前屏幕区域(外扩5公里)的完整水网吗？可能需要几十秒时间。")) {
        return;
    }
    
    clearMap();
    resultsPanel.classList.add('hidden');
    
    showStatus('正在生成全域水网...', 'empty');
    showLoader('这可能需要一分钟时间，正在后台合成DEM及计算流向与流速...');

    try {
        const response = await fetch('/api/analyze_network', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ 
                min_lat, min_lon, max_lat, max_lon, 
                threshold: 500 // Can adjust parameter or expose to UI
            })
        });
        
        if (!response.ok) {
            const errData = await response.json();
            throw new Error(errData.detail || '服务器请求错误');
        }
        
        const data = await response.json();
        
        currentPathGeoJSON = data.flow_path;
        currentCatchmentGeoJSON = null; // Clear catchment
        
        if (data.flow_path && Object.keys(data.flow_path).length > 0) {
            const pathLayer = L.geoJSON(data.flow_path, {
                style: {
                    color: '#60a5fa',
                    weight: 2,
                    opacity: 0.8
                }
            }).addTo(map);
            mapLayers.push(pathLayer);
        }
        
        areaVal.textContent = `- km²`;
        demAccuracyVal.textContent = data.dem_accuracy || '未知';
        demSourceVal.textContent = data.dem_source;
        if (data.dem_source.includes('local')) {
            demSourceVal.style.background = 'rgba(16, 185, 129, 0.2)';
            demSourceVal.style.color = '#6ee7b7';
        } else {
            demSourceVal.style.background = 'rgba(59, 130, 246, 0.2)';
            demSourceVal.style.color = '#93c5fd';
        }
        
        showStatus('水网提取完成！', 'success');
        resultsPanel.classList.remove('hidden');
        
    } catch (error) {
        showStatus(`错误: ${error.message}`, 'error');
    } finally {
        hideLoader();
    }
});

// Setup Toggle for Meteo Sidebar
const btnToggleMeteo = document.getElementById('btn-toggle-meteo');
const meteoContent = document.getElementById('meteo-content');
if (btnToggleMeteo && meteoContent) {
    btnToggleMeteo.addEventListener('click', () => {
        if (meteoContent.style.display === 'none') {
            meteoContent.style.display = 'block';
            btnToggleMeteo.textContent = '–';
        } else {
            meteoContent.style.display = 'none';
            btnToggleMeteo.textContent = '+';
        }
    });

    // Setup Double Click for Formulas
    const items = meteoContent.querySelectorAll('.result-item');
    items.forEach(item => {
        const hint = item.querySelector('.formula-hint');
        if (hint) {
            item.classList.add('interactive');
            item.title = "双击展开/隐藏计算公式";
            item.addEventListener('dblclick', (e) => {
                // Prevent text selection on double click
                window.getSelection().removeAllRanges();
                hint.classList.toggle('show');
            });
        }
    });
}



function renderHydrograph(timeSeries, qSeries, stageSeries) {
    const ctx = document.getElementById('hydrograph-chart');
    if (!ctx) return;
    if (window.hydroChartInstance) {
        window.hydroChartInstance.destroy();
    }

    const datasets = [{
        label: '流量 Q (m³/s)',
        data: qSeries,
        borderColor: '#60a5fa',
        backgroundColor: 'rgba(96, 165, 250, 0.15)',
        borderWidth: 2,
        fill: true,
        tension: 0.2,
        pointRadius: 0,
        pointHitRadius: 10,
        yAxisID: 'yQ'
    }];

    const scales = {
        x: {
            title: { display: true, text: '时间 (小时)', color: 'rgba(255,255,255,0.5)', font: {size: 10} },
            ticks: { color: 'rgba(255,255,255,0.7)', maxTicksLimit: 8 },
            grid: { color: 'rgba(255,255,255,0.1)' }
        },
        yQ: {
            position: 'left',
            title: { display: true, text: '流量 (m³/s)', color: '#60a5fa', font: {size: 10} },
            ticks: { color: '#60a5fa' },
            grid: { color: 'rgba(255,255,255,0.08)' },
            beginAtZero: true
        }
    };

    const tooltipCallbacks = {
        title: (ctx) => '时间: ' + ctx[0].label + ' 小时',
        label: (ctx) => {
            if (ctx.dataset.yAxisID === 'yQ') return '流量: ' + ctx.raw + ' m³/s';
            if (ctx.dataset.yAxisID === 'yH') return '水深: ' + ctx.raw + ' m';
            return '';
        }
    };

    if (stageSeries && stageSeries.length > 0) {
        datasets.push({
            label: '假定断面水深 h (m)',
            data: stageSeries,
            borderColor: '#f87171',
            backgroundColor: 'rgba(248, 113, 113, 0.1)',
            borderWidth: 2,
            borderDash: [4, 3],
            fill: false,
            tension: 0.2,
            pointRadius: 0,
            pointHitRadius: 10,
            yAxisID: 'yH'
        });
        scales.yH = {
            position: 'right',
            title: { display: true, text: '水深 (m)', color: '#f87171', font: {size: 10} },
            ticks: { color: '#f87171' },
            grid: { drawOnChartArea: false },
            beginAtZero: true
        };
    }

    window.hydroChartInstance = new Chart(ctx, {
        type: 'line',
        data: { labels: timeSeries, datasets },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            plugins: {
                legend: {
                    display: true,
                    labels: { color: 'rgba(255,255,255,0.7)', font: {size: 11}, boxWidth: 14 }
                },
                tooltip: { callbacks: tooltipCallbacks }
            },
            scales
        }
    });
}

// ─── Save as Forecast Station ─────────────────────────────────────────────────
const btnSaveStation = document.getElementById('btn-save-station');
const saveStationStatus = document.getElementById('save-station-status');
const saveStationName = document.getElementById('save-station-name');

// Show the save button only after a successful analysis
const _origShowResults = () => resultsPanel.classList.remove('hidden');

// Hook into analysis result to expose the save button
function showSaveStationButton(analysisData) {
    if (!btnSaveStation) return;
    btnSaveStation.style.display = 'block';
    saveStationStatus.style.display = 'none';
    // Pre-fill a default name from coordinates
    if (saveStationName && !saveStationName.value) {
        const lat = (analysisData.pour_point?.coordinates?.[1] || currentAnalysisParams?.lat || 0).toFixed(4);
        const lon = (analysisData.pour_point?.coordinates?.[0] || currentAnalysisParams?.lon || 0).toFixed(4);
        saveStationName.value = `预报站_${lat}_${lon}`;
    }
    // Save the latest raw analysis data for station saving
    window._lastAnalysisData = analysisData;
}

// Patch dblclick handler to call showSaveStationButton after analysis
const _originalDblHandler = map._events.dblclick;

// Override: patch fetch response processing via monkey-patching showStatus
const _origAnalysisSuccess = window.__analysisSuccessHook;
// We directly observe when analysis results are rendered by patching the analyze block.
// Since the data flow is inside the dblclick async closure, we use an event-based approach:
map.on('analysissuccess', (e) => showSaveStationButton(e.data));

if (btnSaveStation) {
    btnSaveStation.addEventListener('click', async () => {
        const data = window._lastAnalysisData;
        if (!data || !currentAnalysisParams) return;

        const name = saveStationName.value.trim();
        if (!name) {
            saveStationStatus.style.display = 'block';
            saveStationStatus.className = 'err';
            saveStationStatus.textContent = '请输入站点名称';
            return;
        }

        btnSaveStation.disabled = true;
        btnSaveStation.textContent = '⏳ 保存中...';
        saveStationStatus.style.display = 'none';

        try {
            // Generate unique ID from coords
            const lat = currentAnalysisParams.lat;
            const lon = currentAnalysisParams.lon;
            const stationId = 'st_' + Math.abs(Math.round(lat * 1000)).toString(36) +
                              Math.abs(Math.round(lon * 1000)).toString(36);

            const payload = {
                id: stationId,
                name: name,
                lat: lat,
                lon: lon,
                area_km2: data.area_km2 || 0,
                delta_h: data.delta_h || 0,
                max_elev: data.max_elev || 0,
                min_elev: data.min_elev || 0,
                dem_source: data.dem_source || '',
                slope_s0: data.slope_s0 || 0.01,
                w_channel: data.w_channel || 10,
                tc_hours: data.meteo?.routing?.tc_hours || 1.0,
                cn_prior: data.meteo?.final_cn || 75,
                n_prior: 0.04,
                alert_l1_m: 1.0,
                alert_l2_m: 1.5,
                alert_l3_m: 2.0,
                catchment_geojson: currentCatchmentGeoJSON ? JSON.stringify(currentCatchmentGeoJSON) : null,
            };

            const res = await fetch('/api/station/save', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(payload)
            });

            if (!res.ok) {
                let errMsg = '保存失败';
                try {
                    const err = await res.json();
                    errMsg = err.detail || errMsg;
                } catch {
                    errMsg = (await res.text()).slice(0, 120);
                }
                throw new Error(errMsg);
            }

            const result = await res.json();
            saveStationStatus.style.display = 'block';
            saveStationStatus.className = 'ok';
            saveStationStatus.innerHTML =
                `✅ 已保存！<a href="/stations.html?id=${result.station_id}" ` +
                `style="color:#34d399;margin-left:6px;font-weight:700;">前往管理 →</a>`;
            btnSaveStation.textContent = '✅ 已保存为预报站';
        } catch (err) {
            saveStationStatus.style.display = 'block';
            saveStationStatus.className = 'err';
            saveStationStatus.textContent = '❌ ' + err.message;
            btnSaveStation.textContent = '📌 保存为预报站';
        } finally {
            btnSaveStation.disabled = false;
        }
    });
}
