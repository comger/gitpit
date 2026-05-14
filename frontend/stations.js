// ─── State ────────────────────────────────────────────────────────────────────
let currentStation = null;
let subMap = null;
let subMapMarkers = [];
let pendingLatLng = null;
let lossChartInst = null;
let hydroChartInst = null;
let trainPollTimer = null;

// ─── Init ─────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    loadStations();
    bindTabs();
    bindSubpointUI();
    bindTemplateUI();
    bindTrainUI();
    bindRecalcUI();
    bindHydroUI();

    // Auto-select station from URL param
    const urlId = new URLSearchParams(location.search).get('id');
    if (urlId) setTimeout(() => selectStation(urlId), 600);
});

// ─── Stations List ────────────────────────────────────────────────────────────
async function loadStations() {
    const container = document.getElementById('station-cards');
    try {
        const res = await fetch('/api/stations');
        const stations = await res.json();
        if (!stations.length) {
            container.innerHTML = `<div style="padding:20px;text-align:center;color:#475569;font-size:13px">
                暂无预报站。<br>请在<a href="/" style="color:#60a5fa">汇水分析页</a>分析后保存。</div>`;
            return;
        }
        container.innerHTML = stations.map(s => `
            <div class="station-card" id="card-${s.id}" onclick="selectStation('${s.id}')">
                <div style="display:flex;align-items:flex-start;justify-content:space-between">
                    <div class="sc-name">${s.name}</div>
                    <button class="btn-del-station" onclick="deleteStation(event,'${s.id}','${s.name}')">🗑</button>
                </div>
                <div class="sc-meta">
                    <span>${s.lat.toFixed(4)}, ${s.lon.toFixed(4)}</span>
                    <span>${(s.area_km2||0).toFixed(2)} km²</span>
                </div>
                <div style="margin-top:6px">
                    <span class="sc-badge ${badgeClass(s.training_status)}">${badgeLabel(s.training_status)}</span>
                </div>
            </div>`).join('');
    } catch(e) {
        container.innerHTML = `<div style="padding:20px;color:#ef4444;font-size:13px">加载失败: ${e.message}</div>`;
    }
}

function badgeClass(s) {
    return {trained:'badge-trained',training:'badge-training',error:'badge-error'}[s]||'badge-untrained';
}
function badgeLabel(s) {
    return {trained:'✅ 已训练',training:'⏳ 训练中',error:'❌ 错误'}[s]||'○ 未训练';
}

async function deleteStation(e, id, name) {
    e.stopPropagation();
    if (!confirm(`确认删除站点「${name}」？此操作不可恢复。`)) return;
    await fetch(`/api/station/${id}`, {method:'DELETE'});
    if (currentStation?.id === id) {
        currentStation = null;
        document.getElementById('no-selection').style.display = 'flex';
        document.getElementById('station-detail').style.display = 'none';
    }
    loadStations();
}

// ─── Select Station ───────────────────────────────────────────────────────────
async function selectStation(id) {
    document.querySelectorAll('.station-card').forEach(c => c.classList.remove('active'));
    const card = document.getElementById('card-'+id);
    if (card) card.classList.add('active');

    try {
        const res = await fetch(`/api/station/${id}`);
        if (!res.ok) return;
        currentStation = await res.json();

        document.getElementById('no-selection').style.display = 'none';
        document.getElementById('station-detail').style.display = 'flex';

        document.getElementById('dh-name').textContent = currentStation.name;
        document.getElementById('dh-meta').textContent =
            `${currentStation.lat.toFixed(5)}, ${currentStation.lon.toFixed(5)} | ` +
            `面积 ${(currentStation.area_km2||0).toFixed(3)} km² | ${currentStation.dem_source||''}`;
        document.getElementById('dh-badge').innerHTML =
            `<span class="sc-badge ${badgeClass(currentStation.training_status)}">${badgeLabel(currentStation.training_status)}</span>`;

        // Load first tab
        loadSubpoints();
        initSubMap();
        renderTemplateParams();
        refreshTrainStatus();
    } catch(e) { console.error(e); }
}

// ─── Tabs ─────────────────────────────────────────────────────────────────────
function bindTabs() {
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const tab = btn.dataset.tab;
            document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            document.querySelectorAll('.tab-content').forEach(tc => tc.style.display='none');
            document.getElementById('tab-'+tab).style.display = 'block';
            if (tab==='subpoints') { initSubMap(); loadSubpoints(); }
            if (tab==='train') refreshTrainStatus();
            if (tab==='hydrograph') loadHydrograph();
        });
    });
}

// ─── Sub-points ───────────────────────────────────────────────────────────────
function initSubMap() {
    if (subMap) { subMap.invalidateSize(); return; }
    if (!currentStation) return;
    subMap = L.map('subpoint-map', {zoomControl:true}).setView([currentStation.lat, currentStation.lon], 12);
    L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_nolabels/{z}/{x}/{y}{r}.png',
        {attribution:'© OSM © CARTO', subdomains:'abcd', maxZoom:20}).addTo(subMap);

    // Station outlet marker
    L.circleMarker([currentStation.lat, currentStation.lon],
        {radius:8, fillColor:'#ef4444', color:'#fff', weight:2, fillOpacity:1}).addTo(subMap)
        .bindPopup(`<b>${currentStation.name}</b><br>出口断面`);

    subMap.on('click', e => {
        pendingLatLng = e.latlng;
        const inp = document.getElementById('sp-name');
        if (!inp.value) inp.value = `点_${e.latlng.lat.toFixed(3)}_${e.latlng.lng.toFixed(3)}`;
        // Show temp marker
        if (window._pendingMarker) subMap.removeLayer(window._pendingMarker);
        window._pendingMarker = L.circleMarker(e.latlng,
            {radius:6, fillColor:'#fbbf24', color:'#fff', weight:2, fillOpacity:.9}).addTo(subMap)
            .bindPopup('点击"添加补点"确认').openPopup();
    });
}

function bindSubpointUI() {
    document.getElementById('btn-add-sp').addEventListener('click', async () => {
        if (!currentStation) return;
        const name = document.getElementById('sp-name').value.trim();
        const type = document.getElementById('sp-type').value;
        const note = document.getElementById('sp-note').value.trim();
        if (!name) { alert('请输入补点名称'); return; }
        if (!pendingLatLng) { alert('请先在地图上点击选择位置'); return; }

        const body = {name, type, note, lat:pendingLatLng.lat, lon:pendingLatLng.lng};
        const res = await fetch(`/api/station/${currentStation.id}/subpoints`, {
            method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)
        });
        if (res.ok) {
            document.getElementById('sp-name').value = '';
            document.getElementById('sp-note').value = '';
            pendingLatLng = null;
            if (window._pendingMarker) { subMap.removeLayer(window._pendingMarker); window._pendingMarker=null; }
            loadSubpoints();
        }
    });
}

async function loadSubpoints() {
    if (!currentStation) return;
    const res = await fetch(`/api/station/${currentStation.id}/subpoints`);
    const pts = await res.json();

    // Clear old markers (except outlet)
    subMapMarkers.forEach(m => subMap && subMap.removeLayer(m));
    subMapMarkers = [];

    const list = document.getElementById('sp-list');
    if (!pts.length) {
        list.innerHTML = '<div style="padding:12px;color:#475569;font-size:12px;text-align:center">暂无补点，请在地图上点击添加</div>';
        return;
    }

    list.innerHTML = pts.map(pt => `
        <div class="subpoint-item">
            <span class="sp-type-badge ${pt.type==='rain_gauge'?'sp-rain':'sp-level'}">
                ${pt.type==='rain_gauge'?'🌧 雨量':'💧 水位'}
            </span>
            <span class="sp-name">${pt.name}</span>
            <span class="sp-coords">${pt.lat.toFixed(4)}, ${pt.lon.toFixed(4)}</span>
            <button class="btn btn-danger btn-sm" onclick="deleteSubpoint('${pt.id}')">删除</button>
        </div>`).join('');

    pts.forEach(pt => {
        if (!subMap) return;
        const color = pt.type==='rain_gauge'?'#60a5fa':'#fbbf24';
        const m = L.circleMarker([pt.lat, pt.lon],
            {radius:6, fillColor:color, color:'#fff', weight:2, fillOpacity:.9}).addTo(subMap)
            .bindPopup(`<b>${pt.name}</b><br>${pt.type==='rain_gauge'?'雨量计':'上游水位站'}`);
        subMapMarkers.push(m);
    });
}

async function deleteSubpoint(ptId) {
    if (!currentStation || !confirm('确认删除该补点？')) return;
    await fetch(`/api/station/${currentStation.id}/subpoints/${ptId}`, {method:'DELETE'});
    loadSubpoints();
}

// ─── Template ─────────────────────────────────────────────────────────────────
function renderTemplateParams() {
    if (!currentStation) return;
    const s = currentStation;
    const items = [
        {l:'CN 先验值', v:(s.cn_prior||75).toFixed(1), u:''},
        {l:'Manning n', v:(s.n_prior||0.04).toFixed(4), u:''},
        {l:'汇水面积', v:(s.area_km2||0).toFixed(3), u:'km²'},
        {l:'汇流时间', v:(s.tc_hours||1).toFixed(2), u:'h'},
        {l:'河道坡降', v:((s.slope_s0||0.01)*100).toFixed(3), u:'%'},
        {l:'断面宽度', v:(s.w_channel||10).toFixed(1), u:'m'},
    ];
    document.getElementById('template-params').innerHTML = items.map(i=>
        `<div class="param-card"><div class="pc-label">${i.l}</div><div class="pc-value">${i.v}</div><div class="pc-unit">${i.u}</div></div>`
    ).join('');
}

function bindTemplateUI() {
    document.getElementById('btn-gen-tpl').addEventListener('click', async () => {
        if (!currentStation) return;
        const years = document.getElementById('tpl-years').value;
        const btn = document.getElementById('btn-gen-tpl');
        const status = document.getElementById('tpl-status');
        btn.disabled = true; btn.innerHTML='⏳ 正在生成（约需30-90秒）...';
        status.textContent = '正在从 Open-Meteo 获取历史气象数据并生成模板...';
        try {
            const res = await fetch(`/api/station/${currentStation.id}/template?years=${years}`);
            if (!res.ok) { const e=await res.json(); throw new Error(e.detail); }
            const blob = await res.blob();
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href=url; a.download=`${currentStation.id}_template_${years}yr.csv`;
            document.body.appendChild(a); a.click(); a.remove();
            status.textContent = '✅ 模板已生成并下载';
        } catch(e) {
            status.textContent = '❌ 生成失败: '+e.message;
        } finally {
            btn.disabled=false; btn.innerHTML='⬇️ 生成并下载模板';
        }
    });

    const zone = document.getElementById('upload-zone');
    const fileInput = document.getElementById('csv-file-input');
    zone.addEventListener('click', () => fileInput.click());
    zone.addEventListener('dragover', e => { e.preventDefault(); zone.classList.add('dragover'); });
    zone.addEventListener('dragleave', () => zone.classList.remove('dragover'));
    zone.addEventListener('drop', e => { e.preventDefault(); zone.classList.remove('dragover'); doImport(e.dataTransfer.files[0]); });
    fileInput.addEventListener('change', () => { if(fileInput.files[0]) doImport(fileInput.files[0]); });
}

async function doImport(file) {
    if (!currentStation || !file) return;
    const result = document.getElementById('import-result');
    result.style.display='block'; result.className=''; result.textContent='⏳ 正在导入...';
    const fd = new FormData(); fd.append('file', file);
    try {
        const res = await fetch(`/api/observation/import/${currentStation.id}`, {method:'POST', body:fd});
        if (!res.ok) {
            let errMsg = '导入失败';
            try { const e = await res.json(); errMsg = e.detail || errMsg; }
            catch { errMsg = (await res.text()).slice(0, 200); }
            throw new Error(errMsg);
        }
        const data = await res.json();
        result.className='ok';
        result.innerHTML=`✅ 导入成功 — 共 <b>${data.total_rows}</b> 条，新增 <b>${data.inserted}</b>，跳过 <b>${data.skipped||0}</b>`
            +`<br><span style="font-size:11px;color:#64748b">${data.time_start||''} → ${data.time_end||''} | 累计降雨 ${data.total_rainfall_mm||0} mm${data.has_water_level?' | 含水位数据':''}</span>`
            +(data.warnings?.length?`<br><span style="font-size:11px;color:#fbbf24">⚠ ${data.warnings.join('; ')}</span>`:'');
    } catch(e) {
        result.className='err'; result.textContent='❌ 导入失败: '+e.message;
    }
}

// ─── Training ─────────────────────────────────────────────────────────────────
function bindTrainUI() {
    document.getElementById('btn-train').addEventListener('click', async () => {
        if (!currentStation) return;
        const epochs = document.getElementById('train-epochs').value;
        const btn = document.getElementById('btn-train');
        btn.disabled=true; btn.textContent='⏳ 训练中...';
        setTrainStatus('running','正在训练 PINN 模型...');
        try {
            const res = await fetch(`/api/model/train/${currentStation.id}?epochs=${epochs}`, {method:'POST'});
            const data = await res.json();
            if (!res.ok) throw new Error(data.detail);
            if (data.status==='skipped') {
                setTrainStatus('idle', data.message);
            } else {
                setTrainStatus('done','训练完成！');
                renderTrainResult(data);
                loadStations();
            }
        } catch(e) {
            setTrainStatus('error','训练失败: '+e.message);
        } finally {
            btn.disabled=false; btn.textContent='🚀 开始训练';
        }
    });

    document.getElementById('btn-refresh-status').addEventListener('click', refreshTrainStatus);
}

function setTrainStatus(state, text) {
    const dot = document.getElementById('train-dot');
    const txt = document.getElementById('train-status-text');
    dot.className='pulse-dot '+state;
    txt.innerHTML = state==='running'
        ? `<span class="spinner-sm"></span> &nbsp;${text}`
        : text;
}

async function refreshTrainStatus() {
    if (!currentStation) return;
    try {
        const res = await fetch(`/api/model/status/${currentStation.id}`);
        const data = await res.json();
        const s = data.training_status;
        const stateMap = {trained:'done', training:'running', error:'error', untrained:'idle', unknown:'idle'};
        const textMap = {
            trained:`✅ 已训练 | CN: ${data.cn_corrected?.toFixed(2)||'-'} | n: ${data.n_corrected?.toFixed(5)||'-'}`,
            training:'⏳ 训练进行中...',
            error:'❌ 上次训练出错',
            untrained:'○ 尚未训练',
            unknown:'○ 状态未知'
        };
        setTrainStatus(stateMap[s]||'idle', textMap[s]||s);
        if (data.training_meta && data.training_meta.status==='ok') {
            renderTrainResult(data.training_meta);
        }
    } catch(e) { console.warn(e); }
}

function renderTrainResult(data) {
    document.getElementById('train-result').style.display='block';
    document.getElementById('loss-meta').innerHTML = [
        {l:'最终损失',v:data.final_loss?.toFixed(6)||'-'},
        {l:'学习 CN',v:data.cn_learned?.toFixed(2)||'-'},
        {l:'学习 n',v:data.n_learned?.toFixed(5)||'-'},
        {l:'训练样本',v:data.samples||'-'},
    ].map(i=>`<div class="loss-meta-item"><div class="lmi-label">${i.l}</div><div class="lmi-val">${i.v}</div></div>`).join('');

    if (data.loss_curve && data.loss_curve.length) {
        const ctx = document.getElementById('loss-chart');
        if (lossChartInst) lossChartInst.destroy();
        const labels = data.loss_curve.map((_,i)=>`Ep ${i*50}`);
        lossChartInst = new Chart(ctx, {
            type:'line',
            data:{labels, datasets:[{
                label:'Training Loss', data:data.loss_curve,
                borderColor:'#a78bfa', backgroundColor:'rgba(167,139,250,0.1)',
                borderWidth:2, fill:true, tension:0.3, pointRadius:3
            }]},
            options:{responsive:true,maintainAspectRatio:false,
                plugins:{legend:{labels:{color:'rgba(255,255,255,0.6)'}}},
                scales:{
                    x:{ticks:{color:'rgba(255,255,255,0.5)'},grid:{color:'rgba(255,255,255,0.07)'}},
                    y:{ticks:{color:'rgba(255,255,255,0.5)'},grid:{color:'rgba(255,255,255,0.07)'},beginAtZero:true}
                }}
        });
    }
}

// ─── Recalculate ──────────────────────────────────────────────────────────────
function bindRecalcUI() {
    document.getElementById('btn-recalc').addEventListener('click', async () => {
        if (!currentStation) return;
        const btn = document.getElementById('btn-recalc');
        btn.disabled=true; btn.textContent='⏳ 计算中...';
        try {
            const res = await fetch(`/api/model/recalculate/${currentStation.id}`, {method:'POST'});
            const data = await res.json();
            if (!res.ok) throw new Error(data.detail);
            const result = document.getElementById('recalc-result');
            result.style.display='block';
            document.getElementById('rc-cn-before').textContent = data.cn_prior?.toFixed(2)||'-';
            document.getElementById('rc-n-before').textContent = 'n = '+(data.n_prior?.toFixed(5)||'-');
            document.getElementById('rc-cn-after').textContent = data.cn_corrected?.toFixed(2)||'-';
            document.getElementById('rc-n-after').textContent = 'n = '+(data.n_corrected?.toFixed(5)||'-');
            document.getElementById('recalc-stats').innerHTML = [
                {l:'偏差 Bias',v:(data.bias||0).toFixed(4),u:'m'},
                {l:'趋势 Trend',v:(data.trend||0).toFixed(6),u:''},
                {l:'使用观测',v:data.obs_used||'-',u:'条'},
            ].map(i=>`<div class="param-card highlight"><div class="pc-label">${i.l}</div><div class="pc-value">${i.v}</div><div class="pc-unit">${i.u}</div></div>`).join('');
            loadStations();
        } catch(e) {
            alert('参数重算失败: '+e.message);
        } finally {
            btn.disabled=false; btn.textContent='⚙️ 触发参数重算';
        }
    });
}

// ─── Hydrograph ───────────────────────────────────────────────────────────────
function bindHydroUI() {
    document.getElementById('btn-load-hydro').addEventListener('click', loadHydrograph);
}

async function loadHydrograph() {
    if (!currentStation) return;
    const btn = document.getElementById('btn-load-hydro');
    btn.disabled=true; btn.textContent='⏳ 加载中...';
    try {
        const res = await fetch(`/api/hydrograph/${currentStation.id}?limit=576`);
        if (!res.ok) { const e=await res.json(); throw new Error(e.detail); }
        const data = await res.json();
        renderHydroChart(data);
    } catch(e) {
        alert('加载预报过程失败: '+e.message);
    } finally {
        btn.disabled=false; btn.textContent='🔄 加载/刷新';
    }
}

function renderHydroChart(data) {
    const hist = data.historical || [];
    const fc = data.forecast || [];
    const thresholds = data.alert_thresholds || {};

    // Build labels and series
    const allTimes = [...hist.map(r=>r.time), ...fc.map(r=>r.time)];
    const labFmt = t => {
        const d = new Date(t.replace(' ','T'));
        return `${(d.getMonth()+1).toString().padStart(2,'0')}/${d.getDate().toString().padStart(2,'0')} ${d.getHours().toString().padStart(2,'0')}:${d.getMinutes().toString().padStart(2,'0')}`;
    };
    const labels = allTimes.map(labFmt);
    const nHist = hist.length;

    const rainData = allTimes.map((_,i) => i<nHist ? (parseFloat(hist[i].rainfall_mm)||0) : null);
    const hObsData = allTimes.map((_,i) => i<nHist ? (hist[i].h_obs!=null?parseFloat(hist[i].h_obs):null) : null);
    const hFcData = allTimes.map((_,i) => i>=nHist ? parseFloat(fc[i-nHist].h_forecast) : null);

    const alert = data.alert_level||0;
    const alertColors = ['#475569','#fbbf24','#f97316','#ef4444'];

    // Peak info
    const peakBox = document.getElementById('hydro-peak-info');
    const peakGrid = document.getElementById('hydro-peaks');
    if (data.h_peak) {
        peakBox.style.display='block';
        peakGrid.innerHTML = [
            {l:'预报峰值水位',v:data.h_peak?.toFixed(3),u:'m',cls:'warning'},
            {l:'预报洪峰流量',v:data.q_peak?.toFixed(2),u:'m³/s',cls:''},
            {l:'峰现时间',v:(data.t_peak_min||0)+'分钟后',u:'',cls:''},
            {l:'预警等级',v:alert?`Ⅱ级预警`.replace('Ⅱ',['○','Ⅰ','Ⅱ','Ⅲ'][alert]):'无预警',u:'',cls:alert?'warning':''},
        ].map(i=>`<div class="param-card ${i.cls}"><div class="pc-label">${i.l}</div><div class="pc-value">${i.v}</div><div class="pc-unit">${i.u}</div></div>`).join('');
    }

    // Alert legend
    const leg = document.getElementById('hydro-alert-legend');
    leg.innerHTML = [
        {c:'#34d399',l:`L1 预警: ${thresholds.l1||1.0}m`},
        {c:'#fbbf24',l:`L2 预警: ${thresholds.l2||1.5}m`},
        {c:'#ef4444',l:`L3 预警: ${thresholds.l3||2.0}m`},
    ].map(i=>`<div class="al-item"><div class="al-dot" style="background:${i.c}"></div><span style="color:${i.c}">${i.l}</span></div>`).join('');

    // Draw chart
    const ctx = document.getElementById('hydro-chart');
    if (hydroChartInst) hydroChartInst.destroy();

    const alertLines = Object.entries({l1:{c:'#34d399',l:'L1预警'},l2:{c:'#fbbf24',l:'L2预警'},l3:{c:'#ef4444',l:'L3预警'}})
        .filter(([k])=>thresholds[k])
        .map(([k,v])=>({
            label:v.l, data:allTimes.map(()=>thresholds[k]),
            borderColor:v.c, borderWidth:1.5, borderDash:[4,4],
            pointRadius:0, fill:false, yAxisID:'yH'
        }));

    hydroChartInst = new Chart(ctx, {
        type: 'bar',
        data: {
            labels,
            datasets: [
                {
                    type:'bar', label:'降雨量 (mm)', data:rainData,
                    backgroundColor:'rgba(96,165,250,0.5)', yAxisID:'yR', order:2
                },
                {
                    type:'line', label:'实测水位 (m)', data:hObsData,
                    borderColor:'#34d399', backgroundColor:'rgba(52,211,153,0.1)',
                    borderWidth:2, fill:true, tension:0.2, pointRadius:0, yAxisID:'yH', order:1
                },
                {
                    type:'line', label:'预报水位 (m)', data:hFcData,
                    borderColor:'#f97316', borderWidth:2.5,
                    borderDash:[6,3], fill:false, tension:0.2, pointRadius:0, yAxisID:'yH', order:1
                },
                ...alertLines
            ]
        },
        options: {
            responsive:true, maintainAspectRatio:false,
            interaction:{mode:'index',intersect:false},
            plugins:{
                legend:{display:true,labels:{color:'rgba(255,255,255,0.65)',font:{size:11},boxWidth:14}},
                tooltip:{callbacks:{
                    label:ctx=>ctx.dataset.label+': '+ctx.raw
                }}
            },
            scales:{
                x:{ticks:{color:'rgba(255,255,255,0.5)',maxTicksLimit:12,maxRotation:0},grid:{color:'rgba(255,255,255,0.06)'}},
                yH:{position:'left',title:{display:true,text:'水位 (m)',color:'#34d399'},ticks:{color:'#94a3b8'},grid:{color:'rgba(255,255,255,0.07)'},beginAtZero:true},
                yR:{position:'right',title:{display:true,text:'降雨 (mm)',color:'#60a5fa'},ticks:{color:'#60a5fa'},grid:{drawOnChartArea:false},reverse:true,
                    min:-Math.max(...rainData.filter(v=>v!=null))*4}
            }
        }
    });
}
