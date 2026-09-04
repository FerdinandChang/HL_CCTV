let currentCamId = "cam_10";
let roiPoints = [];
let isEditingROI = false;
let draggedPointIdx = -1;

// 彈窗播放器狀態
let activeVideoFilename = null;
let currentPlaySec = 0;
let isPlaying = true;
let playTimer = null;

const canvas = document.getElementById("roi-canvas");
const ctx = canvas.getContext("2d");

window.addEventListener("DOMContentLoaded", () => {
    initTheme();
    initCanvas();
    fetchROI();
    fetchStatus();
    fetchAlerts();
    fetchRefs();
    fetchVideos();
    fetchDiskUsage();

    setInterval(fetchStatus, 1500);
    setInterval(fetchAlerts, 5000);
    setInterval(fetchVideos, 10000);
    setInterval(fetchDiskUsage, 30000);
});

// ── 主題切換 (白天模式 / 夜間模式) ───────────────────────────────
function initTheme() {
    const savedTheme = localStorage.getItem('hl_cctv_theme') || 'dark';
    applyTheme(savedTheme);
}

function toggleTheme() {
    const isLight = document.body.classList.contains('light-mode');
    const newTheme = isLight ? 'dark' : 'light';
    applyTheme(newTheme);
    localStorage.setItem('hl_cctv_theme', newTheme);
}

function applyTheme(theme) {
    const iconEl = document.getElementById('theme-icon');
    const textEl = document.getElementById('theme-text');
    if (theme === 'light') {
        document.documentElement.classList.remove('dark');
        document.documentElement.classList.add('light');
        document.body.classList.remove('dark');
        document.body.classList.add('light-mode');
        if (iconEl) iconEl.textContent = '🌙';
        if (textEl) textEl.textContent = '夜間模式';
    } else {
        document.documentElement.classList.add('dark');
        document.documentElement.classList.remove('light');
        document.body.classList.add('dark');
        document.body.classList.remove('light-mode');
        if (iconEl) iconEl.textContent = '☀️';
        if (textEl) textEl.textContent = '白天模式';
    }
}

function onCameraChange() {
    currentCamId = document.getElementById("camera-select").value;
    document.getElementById("live-stream").src = `/api/stream/live?cam_id=${currentCamId}&t=${Date.now()}`;
    fetchROI();
    fetchStatus();
    fetchRefs();
}

function initCanvas() {
    function resize() {
        const rect = canvas.getBoundingClientRect();
        canvas.width = rect.width;
        canvas.height = rect.height;
        drawROI();
    }
    window.addEventListener("resize", resize);
    setTimeout(resize, 500);

    canvas.addEventListener("mousedown", onMouseDown);
    canvas.addEventListener("mousemove", onMouseMove);
    canvas.addEventListener("mouseup", onMouseUp);
}

function fetchROI() {
    fetch(`/api/roi?cam_id=${currentCamId}`)
        .then(r => r.json())
        .then(data => {
            roiPoints = data.roi || [];
            drawROI();
        });
}

function drawROI() {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    if (!roiPoints || roiPoints.length < 3) return;

    ctx.beginPath();
    const p0 = toCanvasCoord(roiPoints[0]);
    ctx.moveTo(p0.x, p0.y);
    for (let i = 1; i < roiPoints.length; i++) {
        const p = toCanvasCoord(roiPoints[i]);
        ctx.lineTo(p.x, p.y);
    }
    ctx.closePath();

    ctx.strokeStyle = isEditingROI ? "#f59e0b" : "#10b981";
    ctx.lineWidth = 2;
    ctx.stroke();

    ctx.fillStyle = isEditingROI ? "rgba(245, 158, 11, 0.2)" : "rgba(16, 185, 129, 0.15)";
    ctx.fill();

    if (isEditingROI) {
        roiPoints.forEach((p, idx) => {
            const cp = toCanvasCoord(p);
            ctx.beginPath();
            ctx.arc(cp.x, cp.y, 7, 0, Math.PI * 2);
            ctx.fillStyle = idx === draggedPointIdx ? "#ef4444" : "#f59e0b";
            ctx.fill();
            ctx.strokeStyle = "#ffffff";
            ctx.lineWidth = 2;
            ctx.stroke();
        });
    }
}

function toCanvasCoord(normPoint) {
    return {
        x: normPoint[0] * canvas.width,
        y: normPoint[1] * canvas.height
    };
}

function toNormCoord(canvasPoint) {
    return [
        Math.max(0, Math.min(1, canvasPoint.x / canvas.width)),
        Math.max(0, Math.min(1, canvasPoint.y / canvas.height))
    ];
}

function toggleEditROI() {
    isEditingROI = !isEditingROI;
    canvas.style.pointerEvents = isEditingROI ? "auto" : "none";
    document.getElementById("btn-save-roi").classList.toggle("hidden", !isEditingROI);
    document.getElementById("btn-edit-roi").textContent = isEditingROI ? "❌ 取消編輯" : "✏️ 編輯 ROI";
    drawROI();
}

function saveROI() {
    fetch("/api/roi", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ cam_id: currentCamId, roi: roiPoints })
    })
    .then(r => r.json())
    .then(data => {
        alert("ROI 範圍已成功更新！");
        toggleEditROI();
    });
}

function onMouseDown(e) {
    if (!isEditingROI) return;
    const rect = canvas.getBoundingClientRect();
    const mouseX = e.clientX - rect.left;
    const mouseY = e.clientY - rect.top;

    draggedPointIdx = -1;
    roiPoints.forEach((p, idx) => {
        const cp = toCanvasCoord(p);
        const dist = Math.hypot(cp.x - mouseX, cp.y - mouseY);
        if (dist <= 12) {
            draggedPointIdx = idx;
        }
    });
    drawROI();
}

function onMouseMove(e) {
    if (!isEditingROI || draggedPointIdx === -1) return;
    const rect = canvas.getBoundingClientRect();
    const mouseX = e.clientX - rect.left;
    const mouseY = e.clientY - rect.top;

    roiPoints[draggedPointIdx] = toNormCoord({ x: mouseX, y: mouseY });
    drawROI();
}

function onMouseUp() {
    draggedPointIdx = -1;
    drawROI();
}

// 狀態更新 (加入防禦性檢查，避免 console 報錯)
function fetchStatus() {
    fetch(`/api/status?cam_id=${currentCamId}`)
        .then(r => r.json())
        .then(data => {
            const statusCard = document.getElementById("status-card");
            const statusTextZh = document.getElementById("status-text-zh");
            const statusTextEn = document.getElementById("status-text-en");
            const statusBadge = document.getElementById("status-badge");
            const camTag = document.getElementById("cam-tag");
            if (camTag) camTag.textContent = currentCamId.toUpperCase();

            const confVal = document.getElementById("conf-val");
            const edgeVal = document.getElementById("edge-val");
            const areaVal = document.getElementById("area-val");
            const truckBedVal = document.getElementById("truck-bed-val");
            const suspectVehVal = document.getElementById("suspect-veh-val");
            const streakText = document.getElementById("streak-text");
            const streakBar = document.getElementById("streak-bar");

            // 格式化主狀態與雙語徽章 (支援白天/夜間模式自適應)
            const rawStatus = data.status || "";
            let zhStatus = "路面清潔良好";
            let badgeStyle = "bg-emerald-950/60 border-emerald-800 text-emerald-400 status-clean";

            if (data.is_alert || rawStatus.includes("MUDDY")) {
                zhStatus = "🚨 檢測到路面泥濘髒污";
                badgeStyle = "bg-red-950/80 border-red-700 text-red-400 status-muddy animate-pulse";
                if (statusCard) statusCard.classList.add("pulse-alert");
            } else if (rawStatus.includes("UNCOVERED TRUCK")) {
                zhStatus = "⚠️ 砂石車違規：車斗未覆蓋";
                badgeStyle = "bg-amber-950/80 border-amber-600 text-amber-400 status-uncovered animate-pulse";
                if (statusCard) statusCard.classList.remove("pulse-alert");
            } else if (rawStatus.includes("PASSING") || rawStatus.includes("INSPECTED")) {
                zhStatus = "🚛 工程砂石車過站受檢中";
                badgeStyle = "bg-cyan-950/80 border-cyan-700 text-cyan-400 status-passing";
                if (statusCard) statusCard.classList.remove("pulse-alert");
            } else if (rawStatus.includes("Blocked")) {
                zhStatus = "🚗 車輛 / 人員通行遮擋";
                badgeStyle = "bg-amber-950/70 border-amber-800 text-amber-400 status-blocked";
                if (statusCard) statusCard.classList.remove("pulse-alert");
            } else if (rawStatus.includes("CLEAN")) {
                zhStatus = "✅ 路面清潔良好";
                badgeStyle = "bg-emerald-950/60 border-emerald-800 text-emerald-400 status-clean";
                if (statusCard) statusCard.classList.remove("pulse-alert");
            } else {
                zhStatus = "🔍 監測採集中";
                badgeStyle = "bg-slate-950/80 border-slate-800 text-slate-300 status-idle";
                if (statusCard) statusCard.classList.remove("pulse-alert");
            }

            if (statusTextZh) statusTextZh.textContent = zhStatus;
            if (statusTextEn) statusTextEn.textContent = rawStatus || "System Normal";
            if (statusBadge) statusBadge.className = `py-3 px-4 rounded-xl border flex flex-col items-center justify-center text-center shadow-inner transition-all ${badgeStyle}`;

            // 指標方塊數值
            if (confVal) confVal.textContent = (data.confidence || 0).toFixed(1) + "%";
            if (edgeVal) edgeVal.textContent = (data.edge_density || 0).toFixed(3);
            if (areaVal) areaVal.textContent = (data.muddy_area_pct || 0).toFixed(1) + "%";

            // 車斗防塵狀態 (美化標籤)
            if (truckBedVal) {
                const bedStr = data.truck_bed_status || "無卡車";
                if (bedStr.includes("UNCOVERED")) {
                    truckBedVal.innerHTML = `<span class="text-rose-500 dark:text-rose-400 font-bold flex items-center space-x-1"><span>⚠️ 未覆蓋</span></span>`;
                } else if (bedStr.includes("COVERED")) {
                    truckBedVal.innerHTML = `<span class="text-emerald-600 dark:text-emerald-400 font-bold flex items-center space-x-1"><span>✅ 已覆蓋</span></span>`;
                } else {
                    truckBedVal.innerHTML = `<span class="text-slate-400 font-normal">無卡車</span>`;
                }
            }

            // 更新即時 GPS 座標與管制點名稱
            if (data.gps_lat && data.gps_lng) {
                const gpsText = `${data.gps_lat.toFixed(4)}°N, ${data.gps_lng.toFixed(4)}°E`;
                const gpsElem = document.getElementById("gps-coords");
                if (gpsElem) gpsElem.textContent = gpsText;
                const gpsLink = document.getElementById("gps-coords-link");
                if (gpsLink) gpsLink.href = `https://www.google.com/maps?q=${data.gps_lat},${data.gps_lng}`;
            }
            if (data.location) {
                const locElem = document.getElementById("gps-loc-name");
                if (locElem) locElem.textContent = data.location;
            }

            // 行經車輛鎖定 (精美中文化與雙模式自適應)
            if (suspectVehVal) {
                let sVeh = data.suspect_vehicle || "無行經車輛";
                sVeh = sVeh.replace("Truck", "🚛 砂石車").replace("Vehicle", "🚗 車輛");
                suspectVehVal.textContent = sVeh;
                suspectVehVal.className = sVeh.includes("無") 
                    ? "text-slate-400 font-normal text-xs" 
                    : "veh-active text-sky-300 font-bold bg-sky-950/80 px-2 py-0.5 rounded border border-sky-800 text-xs";
            }

            if (streakText) streakText.textContent = `${data.streak || 0} / ${data.streak_threshold || 3} 幀`;
            if (streakBar) {
                const pct = Math.min(100, ((data.streak || 0) / (data.streak_threshold || 3)) * 100);
                streakBar.style.width = pct + "%";
            }
        })
        .catch(err => console.error("Status fetch error", err));
}

function fetchDiskUsage() {
    fetch("/api/disk_usage")
        .then(r => r.json())
        .then(data => {
            const driveEl = document.getElementById("disk-drive");
            if (driveEl) driveEl.textContent = data.drive || "D:";
            const freeEl = document.getElementById("disk-free");
            if (freeEl) freeEl.textContent = `${data.free_gb} GB`;
            const pctEl = document.getElementById("disk-pct");
            if (pctEl) pctEl.textContent = `${data.used_pct}%`;
            
            const bar = document.getElementById("disk-bar");
            if (bar) {
                bar.style.width = `${data.used_pct}%`;
                if (data.is_low_space) {
                    bar.className = "bg-red-500 h-2 rounded-full transition-all duration-500 animate-pulse";
                    if (freeEl) freeEl.className = "text-red-400 font-bold";
                } else {
                    bar.className = "bg-emerald-500 h-2 rounded-full transition-all duration-500";
                    if (freeEl) freeEl.className = "text-emerald-400";
                }
            }
        })
        .catch(err => console.error("Disk usage fetch error", err));
}

function triggerCleanup() {
    if (!confirm("確定要手動觸發清理 14 天前的無違規錄影檔嗎？")) return;
    fetch("/api/retention/cleanup", { method: "POST" })
        .then(r => r.json())
        .then(data => {
            alert(`清理完成！共刪除 ${data.purged_count} 支舊影片，釋放 ${data.freed_mb} MB 空間。`);
            fetchDiskUsage();
            fetchVideos();
        });
}

function saveRef(label) {
    fetch("/api/refs/save", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ cam_id: currentCamId, label: label })
    })
    .then(r => r.json())
    .then(data => {
        alert(data.message);
        setTimeout(fetchRefs, 1500);
    });
}

function fetchRefs() {
    fetch(`/api/refs?cam_id=${currentCamId}`)
        .then(r => r.json())
        .then(data => {
            const container = document.getElementById("refs-container");
            if (!container) return;
            if (!data.refs || data.refs.length === 0) {
                container.innerHTML = `<span class="col-span-3 text-slate-500 text-xs text-center">尚未儲存樣本</span>`;
                return;
            }
            container.innerHTML = data.refs.map(r => `
                <div class="relative group bg-slate-800 rounded-lg overflow-hidden border ${r.label === 'clean' ? 'border-emerald-700' : 'border-red-700'}">
                    <img src="${r.image_url}" class="w-full h-14 object-cover">
                    <div class="p-1 text-[10px] text-center font-bold ${r.label === 'clean' ? 'text-emerald-400' : 'text-red-400'}">
                        ${r.label.toUpperCase()} (${r.period})
                    </div>
                    <button onclick="deleteRef('${r.id}')" class="absolute top-1 right-1 bg-red-600 text-white rounded-full w-4 h-4 text-[10px] hidden group-hover:flex items-center justify-center">×</button>
                </div>
            `).join("");
        });
}

function deleteRef(refId) {
    if (!confirm("確定要刪除此參考樣本嗎？")) return;
    fetch(`/api/refs/${currentCamId}/${refId}`, { method: "DELETE" })
        .then(r => r.json())
        .then(() => fetchRefs());
}

function fetchAlerts() {
    fetch("/api/alerts?limit=10")
        .then(r => r.json())
        .then(data => {
            const list = document.getElementById("alerts-list");
            const badge = document.getElementById("alert-count");
            if (badge) badge.textContent = `${data.alerts.length} 筆`;
            if (!list) return;

            if (!data.alerts || data.alerts.length === 0) {
                list.innerHTML = `<div class="text-center py-6 text-slate-500 text-xs">目前無警報紀錄</div>`;
                return;
            }

            list.innerHTML = data.alerts.map(a => {
                let titleText = "🚨 道路髒污污染";
                let cardClass = "alert-card-muddy";

                if (a.status === "UNCOVERED_TRUCK" || (a.status && a.status.includes("UNCOVERED"))) {
                    titleText = "⚠️ 車斗未依規定覆蓋防塵設施";
                    cardClass = "alert-card-uncovered";
                }

                const gpsStr = a.gps_lat ? `${a.gps_lat.toFixed(4)}, ${a.gps_lng.toFixed(4)}` : '23.9915, 121.6213';
                return `
                    <div class="flex space-x-3 p-2.5 rounded-xl border ${cardClass} hover:opacity-90 transition cursor-pointer" onclick="openVideoModal('${a.video_file}', 1)">
                        <img src="/api/snapshots/${a.snapshot_file}" class="w-20 h-14 object-cover rounded-lg border border-slate-700">
                        <div class="text-xs flex-1 flex flex-col justify-center">
                            <div class="alert-title font-bold">${titleText}</div>
                            <div class="text-slate-400 text-[11px] flex items-center justify-between mt-0.5">
                                <span>${a.timestamp}</span>
                                <span class="alert-gps-badge font-mono text-[10px] px-1.5 py-0.5 rounded border">📍 ${gpsStr}</span>
                            </div>
                            ${a.video_file ? `<div class="alert-source-filename text-[10px] mt-0.5 font-medium">來源: ${a.video_file} (${Math.round(a.video_sec)}秒)</div>` : ''}
                        </div>
                    </div>
                `;
            }).join("");
        });
}

let currentModalAlerts = [];
let currentModalTab = 'all';

function fetchVideos() {
    fetch("/api/videos?limit=15")
        .then(r => r.json())
        .then(data => {
            const tbody = document.getElementById("video-table-body");
            if (!tbody) return;
            if (!data.videos || data.videos.length === 0) {
                tbody.innerHTML = `<tr><td colspan="7" class="py-4 text-center text-slate-500">尚無錄影檔紀錄</td></tr>`;
                return;
            }
            tbody.innerHTML = data.videos.map(v => `
                <tr class="border-b border-slate-800/50 hover:bg-slate-800/60 transition cursor-pointer" onclick="openVideoModal('${v.filename}', 'all')">
                    <td class="py-2.5 px-3 font-mono video-filename-text text-emerald-300 font-bold flex items-center space-x-1.5 whitespace-nowrap">
                        <span>🎬</span>
                        <span>${v.filename}</span>
                    </td>
                    <td class="py-2.5 px-2 text-center whitespace-nowrap">
                        <span class="px-2 py-0.5 rounded text-[10px] font-bold ${v.status === 'COMPLETED' ? 'badge-completed bg-emerald-950 text-emerald-400 border border-emerald-800' : 'badge-queued bg-amber-950 text-amber-400 border border-amber-800'}">
                            ${v.status}
                        </span>
                    </td>
                    <td class="py-2.5 px-2 text-center whitespace-nowrap font-mono text-slate-300">${v.total_sampled}</td>
                    <td class="py-2.5 px-2 text-center whitespace-nowrap" onclick="event.stopPropagation(); openVideoModal('${v.filename}', 'muddy')" title="點擊檢視本片道路髒污抓拍">
                        <span class="px-2.5 py-0.5 rounded text-xs font-black inline-flex items-center space-x-1 hover:scale-110 transition shadow-sm ${v.muddy_count > 0 ? 'badge-muddy-count bg-red-950 text-red-400 border border-red-800 cursor-pointer' : 'text-slate-400'}">
                            <span>${v.muddy_count || 0}</span>
                        </span>
                    </td>
                    <td class="py-2.5 px-2 text-center whitespace-nowrap" onclick="event.stopPropagation(); openVideoModal('${v.filename}', 'uncovered')" title="點擊檢視本片車斗違規抓拍">
                        <span class="px-2.5 py-0.5 rounded text-xs font-black inline-flex items-center space-x-1 hover:scale-110 transition shadow-sm ${v.uncovered_count > 0 ? 'badge-uncovered-count bg-amber-950 text-amber-300 border border-amber-800 cursor-pointer' : 'text-slate-400'}">
                            <span>${v.uncovered_count || 0}</span>
                        </span>
                    </td>
                    <td class="py-2.5 px-2.5 text-center text-slate-400 whitespace-nowrap font-mono text-[11px]">${v.processed_at || v.recorded_at || '--'}</td>
                    <td class="py-2.5 px-2.5 text-center whitespace-nowrap" onclick="event.stopPropagation(); openVideoModal('${v.filename}', 'all')">
                        <button class="btn-detail bg-slate-800 hover:bg-slate-700 text-slate-200 px-3 py-1 rounded text-xs border border-slate-600 font-medium whitespace-nowrap shadow-sm">
                            🔍 詳情回放
                        </button>
                    </td>
                </tr>
            `).join("");
        });
}

function triggerScan() {
    fetch("/api/videos/scan", { method: "POST" })
        .then(r => r.json())
        .then(data => alert(data.message));
}

// ── 全瀏覽器相容 H.265 即時回放播放器控制 ────────────────────────────────
function openVideoModal(filename, initialTab = 'all') {
    if (!filename || filename === "null" || filename === "--") return;
    
    activeVideoFilename = filename;
    currentPlaySec = 0;
    isPlaying = true;
    currentModalTab = initialTab || 'all';

    document.getElementById("modal-filename").textContent = filename;
    document.getElementById("modal-download-btn").href = `/api/videos/stream/${filename}`;
    document.getElementById("video-modal").classList.remove("hidden");

    startStreamingAtSec(0);
    loadVideoAlerts(filename);

    if (playTimer) clearInterval(playTimer);
    playTimer = setInterval(() => {
        if (isPlaying && currentPlaySec < 1800) {
            currentPlaySec += 1;
            updatePlayTimeUI(currentPlaySec);
        }
    }, 1000);
}

function startStreamingAtSec(sec) {
    currentPlaySec = Math.max(0, Math.min(1800, sec));
    updatePlayTimeUI(currentPlaySec);
    const imgEl = document.getElementById("modal-stream-img");
    imgEl.src = `/api/videos/preview/${activeVideoFilename}?sec=${currentPlaySec}&t=${Date.now()}`;
}

function updatePlayTimeUI(sec) {
    const min = Math.floor(sec / 60);
    const s = Math.floor(sec % 60);
    const timeStr = `${String(min).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
    document.getElementById("current-play-time").textContent = timeStr;
    document.getElementById("label-cur-sec").textContent = timeStr;
    document.getElementById("video-seek-slider").value = sec;
}

function onSliderChange(val) {
    startStreamingAtSec(parseInt(val));
}

function adjustPlayTime(delta) {
    startStreamingAtSec(currentPlaySec + delta);
}

function togglePlayState() {
    isPlaying = !isPlaying;
    const btn = document.getElementById("btn-toggle-play");
    const imgEl = document.getElementById("modal-stream-img");
    if (isPlaying) {
        btn.textContent = "⏸ 暫停";
        btn.className = "bg-emerald-700 hover:bg-emerald-600 text-white px-3 py-1 rounded text-xs font-bold shadow";
        startStreamingAtSec(currentPlaySec);
    } else {
        btn.textContent = "▶ 播放";
        btn.className = "bg-slate-700 hover:bg-slate-600 text-white px-3 py-1 rounded text-xs font-bold shadow";
        imgEl.src = ""; // 停止拉流省資源
    }
}

function closeVideoModal() {
    if (playTimer) {
        clearInterval(playTimer);
        playTimer = null;
    }
    const imgEl = document.getElementById("modal-stream-img");
    imgEl.src = "";
    document.getElementById("video-modal").classList.add("hidden");
    activeVideoFilename = null;
}

function loadVideoAlerts(filename) {
    const container = document.getElementById("modal-alerts-container");
    container.innerHTML = `<span class="text-xs text-slate-500">載入抓拍紀錄中...</span>`;

    fetch(`/api/videos/${filename}/alerts`)
        .then(r => r.json())
        .then(data => {
            currentModalAlerts = data.alerts || [];

            const muddyList = currentModalAlerts.filter(a => 
                a.status && a.status.includes('MUDDY') && !a.status.includes('UNCOVERED')
            );
            const uncoveredList = currentModalAlerts.filter(a => 
                a.status === 'UNCOVERED_TRUCK' || (a.status && a.status.includes('UNCOVERED'))
            );

            // 更新頁籤計數徽章
            const cntAll = document.getElementById("modal-cnt-all");
            const cntMuddy = document.getElementById("modal-cnt-muddy");
            const cntUncovered = document.getElementById("modal-cnt-uncovered");
            if (cntAll) cntAll.textContent = currentModalAlerts.length;
            if (cntMuddy) cntMuddy.textContent = muddyList.length;
            if (cntUncovered) cntUncovered.textContent = uncoveredList.length;

            // 頂部統計欄位
            const countEl = document.getElementById("modal-muddy-count");
            if (countEl) {
                countEl.innerHTML = `
                    <span class="text-rose-400 font-bold">🚨 路污: ${muddyList.length}</span>
                    <span class="text-slate-600 mx-1">|</span>
                    <span class="text-amber-400 font-bold">⚠️ 車斗: ${uncoveredList.length}</span>
                `;
            }

            // 渲染當前選擇之頁籤
            switchModalTab(currentModalTab);
        });
}

function switchModalTab(tab) {
    currentModalTab = tab || 'all';

    const tabAll = document.getElementById("modal-tab-all");
    const tabMuddy = document.getElementById("modal-tab-muddy");
    const tabUncovered = document.getElementById("modal-tab-uncovered");

    // 重設樣式
    if (tabAll) tabAll.className = "flex-1 py-1 px-1.5 rounded-lg font-bold text-center transition text-slate-400 hover:bg-slate-800/60";
    if (tabMuddy) tabMuddy.className = "flex-1 py-1 px-1.5 rounded-lg font-bold text-center transition text-rose-400 hover:bg-slate-800/60";
    if (tabUncovered) tabUncovered.className = "flex-1 py-1 px-1.5 rounded-lg font-bold text-center transition text-amber-400 hover:bg-slate-800/60";

    // 選中高亮 (加入深淺自適應類別)
    if (currentModalTab === 'all' && tabAll) {
        tabAll.className = "modal-tab-active-all flex-1 py-1 px-1.5 rounded-lg font-bold text-center transition bg-slate-800 text-white shadow-sm";
    } else if (currentModalTab === 'muddy' && tabMuddy) {
        tabMuddy.className = "modal-tab-active-muddy flex-1 py-1 px-1.5 rounded-lg font-bold text-center transition bg-rose-950 text-rose-300 border border-rose-800 shadow-sm";
    } else if (currentModalTab === 'uncovered' && tabUncovered) {
        tabUncovered.className = "modal-tab-active-uncovered flex-1 py-1 px-1.5 rounded-lg font-bold text-center transition bg-amber-950 text-amber-300 border border-amber-800 shadow-sm";
    }

    const container = document.getElementById("modal-alerts-container");
    if (!container) return;

    const muddyList = currentModalAlerts.filter(a => 
        a.status && a.status.includes('MUDDY') && !a.status.includes('UNCOVERED')
    );
    const uncoveredList = currentModalAlerts.filter(a => 
        a.status === 'UNCOVERED_TRUCK' || (a.status && a.status.includes('UNCOVERED'))
    );

    let displayList = currentModalAlerts;
    if (currentModalTab === 'muddy') {
        displayList = muddyList;
    } else if (currentModalTab === 'uncovered') {
        displayList = uncoveredList;
    }

    if (displayList.length === 0) {
        if (currentModalTab === 'muddy') {
            container.innerHTML = `
                <div class="bg-slate-950 p-4 rounded-xl border border-slate-800 text-center space-y-2">
                    <div class="text-rose-500 dark:text-rose-400 font-bold text-xs">🚨 本片無道路髒污違規紀錄</div>
                    <div class="text-[11px] text-slate-400 leading-relaxed">
                        經 AI 抽幀比對，此 30 分鐘路面乾淨未達污染標準。<br>
                        ${uncoveredList.length > 0 ? `
                            <button onclick="switchModalTab('uncovered')" class="mt-2 bg-amber-950/80 hover:bg-amber-900 text-amber-300 border border-amber-800 px-3 py-1 rounded text-xs font-bold transition">
                                👉 本片另有 ${uncoveredList.length} 筆【車斗未覆蓋】，點此檢視
                            </button>
                        ` : ''}
                    </div>
                </div>
            `;
        } else if (currentModalTab === 'uncovered') {
            container.innerHTML = `
                <div class="bg-slate-950 p-4 rounded-xl border border-slate-800 text-center space-y-2">
                    <div class="text-amber-500 dark:text-amber-400 font-bold text-xs">⚠️ 本片無車斗未覆蓋違規紀錄</div>
                    <div class="text-[11px] text-slate-400 leading-relaxed">
                        行經卡車車斗防塵網均依規定妥善覆蓋。<br>
                        ${muddyList.length > 0 ? `
                            <button onclick="switchModalTab('muddy')" class="mt-2 bg-rose-950/80 hover:bg-rose-900 text-rose-300 border border-rose-800 px-3 py-1 rounded text-xs font-bold transition">
                                👉 本片另有 ${muddyList.length} 筆【道路髒污事件】，點此檢視
                            </button>
                        ` : ''}
                    </div>
                </div>
            `;
        } else {
            container.innerHTML = `
                <div class="bg-slate-950 p-4 rounded-xl border border-slate-800 text-center space-y-1">
                    <div class="text-emerald-500 dark:text-emerald-400 font-bold text-xs">✅ 無違規事件記錄</div>
                    <div class="text-[11px] text-slate-500">此 30 分鐘錄影全程合規（無路面泥污與車斗未覆蓋）。</div>
                </div>
            `;
        }
        return;
    }

    container.innerHTML = displayList.map(a => {
        const min = Math.floor(a.video_sec / 60);
        const sec = Math.floor(a.video_sec % 60);
        const timeStr = `${String(min).padStart(2, '0')}:${String(sec).padStart(2, '0')}`;

        let tagTitle = "🚨 道路髒污污染";
        let tagColor = "text-rose-500 dark:text-rose-400 font-bold";
        let itemBorder = "modal-card-muddy border-rose-900/60 bg-rose-950/20";
        let btnStyle = "modal-btn-jump-muddy bg-rose-950/80 hover:bg-rose-800 text-rose-200 border border-rose-700/60";

        if (a.status === "UNCOVERED_TRUCK" || (a.status && a.status.includes("UNCOVERED"))) {
            tagTitle = "⚠️ 車斗未覆蓋防塵設施";
            tagColor = "text-amber-500 dark:text-amber-400 font-bold";
            itemBorder = "modal-card-uncovered border-amber-700/60 bg-amber-950/25";
            btnStyle = "modal-btn-jump-uncovered bg-amber-950/80 hover:bg-amber-800 text-amber-200 border border-amber-700/60";
        }

        const confVal = a.confidence ? a.confidence.toFixed(1) : '95.0';

        return `
            <div class="p-2 rounded-xl border ${itemBorder} flex space-x-2.5 transition">
                <img src="/api/snapshots/${a.snapshot_file}" class="w-16 h-12 object-cover rounded-lg border border-slate-700 cursor-pointer hover:opacity-80 transition" onclick="window.open('/api/snapshots/${a.snapshot_file}', '_blank')" title="點擊放大快照">
                <div class="flex-1 text-[11px] flex flex-col justify-center">
                    <div class="${tagColor}">${tagTitle} (${confVal}%)</div>
                    <div class="text-slate-400 text-[10px]">時間: ${a.timestamp}</div>
                    <button onclick="startStreamingAtSec(${a.video_sec})" class="mt-1 ${btnStyle} px-2 py-0.5 rounded text-[10px] font-mono font-bold w-fit shadow transition">
                        ⏩ 跳至 ${timeStr}
                    </button>
                </div>
            </div>
        `;
    }).join("");
}
