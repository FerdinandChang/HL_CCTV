let currentCamId = "cam_10";
let roiPoints = [];
let isEditingROI = false;
let draggedPointIdx = -1;
let tsPlayer = null;

const canvas = document.getElementById("roi-canvas");
const ctx = canvas.getContext("2d");
const videoWrapper = document.getElementById("video-wrapper");

window.addEventListener("DOMContentLoaded", () => {
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

function fetchStatus() {
    fetch(`/api/status?cam_id=${currentCamId}`)
        .then(r => r.json())
        .then(data => {
            const statusCard = document.getElementById("status-card");
            const statusText = document.getElementById("status-text");
            const confVal = document.getElementById("conf-val");
            const edgeVal = document.getElementById("edge-val");
            const streakText = document.getElementById("streak-text");
            const streakBar = document.getElementById("streak-bar");
            const sourceBadge = document.getElementById("source-badge");

            statusText.textContent = data.status;
            confVal.textContent = data.confidence + "%";
            edgeVal.textContent = data.edge_density;
            sourceBadge.textContent = `${data.name} | ${data.video_source.split('\\').pop()}`;

            streakText.textContent = `${data.streak} / ${data.streak_threshold} 幀`;
            const pct = Math.min(100, (data.streak / data.streak_threshold) * 100);
            streakBar.style.width = pct + "%";

            if (data.is_alert) {
                statusCard.classList.add("pulse-alert");
                statusText.className = "text-3xl font-black text-red-500 mb-2";
            } else if (data.status.includes("CLEAN")) {
                statusCard.classList.remove("pulse-alert");
                statusText.className = "text-3xl font-black text-emerald-400 mb-2";
            } else if (data.status.includes("Blocked")) {
                statusCard.classList.remove("pulse-alert");
                statusText.className = "text-3xl font-black text-amber-400 mb-2";
            } else {
                statusCard.classList.remove("pulse-alert");
                statusText.className = "text-3xl font-black text-slate-300 mb-2";
            }
        })
        .catch(err => console.error("Status fetch error", err));
}

function fetchDiskUsage() {
    fetch("/api/disk_usage")
        .then(r => r.json())
        .then(data => {
            document.getElementById("disk-drive").textContent = data.drive || "D:";
            const freeEl = document.getElementById("disk-free");
            freeEl.textContent = `${data.free_gb} GB`;
            document.getElementById("disk-pct").textContent = `${data.used_pct}%`;
            
            const bar = document.getElementById("disk-bar");
            bar.style.width = `${data.used_pct}%`;
            if (data.is_low_space) {
                bar.className = "bg-red-500 h-2 rounded-full transition-all duration-500 animate-pulse";
                freeEl.className = "text-red-400 font-bold";
            } else {
                bar.className = "bg-emerald-500 h-2 rounded-full transition-all duration-500";
                freeEl.className = "text-emerald-400";
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
            badge.textContent = `${data.alerts.length} 筆`;

            if (!data.alerts || data.alerts.length === 0) {
                list.innerHTML = `<div class="text-center py-6 text-slate-500 text-xs">目前無警報紀錄</div>`;
                return;
            }

            list.innerHTML = data.alerts.map(a => `
                <div class="flex space-x-3 bg-slate-800/80 p-2.5 rounded-xl border border-red-900/50 hover:bg-slate-800 transition cursor-pointer" onclick="openVideoModal('${a.video_file}', 1)">
                    <img src="/api/snapshots/${a.snapshot_file}" class="w-20 h-14 object-cover rounded-lg border border-slate-700">
                    <div class="text-xs flex-1 flex flex-col justify-center">
                        <div class="font-bold text-red-400">${a.status}</div>
                        <div class="text-slate-400 text-[11px]">${a.timestamp}</div>
                        ${a.video_file ? `<div class="text-emerald-400 text-[10px]">來源: ${a.video_file} (${Math.round(a.video_sec)}秒)</div>` : ''}
                    </div>
                </div>
            `).join("");
        });
}

// 錄影檔案清單（加入點擊彈窗互動）
function fetchVideos() {
    fetch("/api/videos?limit=15")
        .then(r => r.json())
        .then(data => {
            const tbody = document.getElementById("video-table-body");
            if (!data.videos || data.videos.length === 0) {
                tbody.innerHTML = `<tr><td colspan="6" class="py-4 text-center text-slate-500">尚無錄影檔紀錄</td></tr>`;
                return;
            }
            tbody.innerHTML = data.videos.map(v => `
                <tr class="border-b border-slate-800/50 hover:bg-slate-800/60 transition cursor-pointer" onclick="openVideoModal('${v.filename}', ${v.muddy_count})">
                    <td class="py-2.5 px-3 font-mono text-emerald-300 font-bold flex items-center space-x-1.5">
                        <span>🎬</span>
                        <span>${v.filename}</span>
                    </td>
                    <td class="py-2.5 px-3">
                        <span class="px-2 py-0.5 rounded text-[10px] font-bold ${v.status === 'COMPLETED' ? 'bg-emerald-950 text-emerald-400 border border-emerald-800' : 'bg-amber-950 text-amber-400 border border-amber-800'}">
                            ${v.status}
                        </span>
                    </td>
                    <td class="py-2.5 px-3">${v.total_sampled}</td>
                    <td class="py-2.5 px-3">
                        <span class="px-2 py-0.5 rounded text-xs font-black ${v.muddy_count > 0 ? 'bg-red-950 text-red-400 border border-red-800' : 'text-slate-400'}">
                            ${v.muddy_count}
                        </span>
                    </td>
                    <td class="py-2.5 px-3 text-slate-500">${v.processed_at || v.recorded_at || '--'}</td>
                    <td class="py-2.5 px-3 text-right">
                        <button class="bg-slate-800 hover:bg-slate-700 text-slate-200 px-2.5 py-1 rounded text-xs border border-slate-600 font-medium">
                            🔍 詳情 / 播放
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

// ── 影片播放與違規詳情彈窗邏輯 ──────────────────────────────────────────
function openVideoModal(filename, muddyCount) {
    if (!filename || filename === "null" || filename === "--") return;
    
    document.getElementById("modal-filename").textContent = filename;
    document.getElementById("modal-muddy-count").textContent = `${muddyCount} 次`;
    document.getElementById("modal-download-btn").href = `/api/videos/stream/${filename}`;
    document.getElementById("video-modal").classList.remove("hidden");

    const videoEl = document.getElementById("modal-player");
    const streamUrl = `/api/videos/stream/${filename}`;

    // 銷毀舊播放器實例
    if (tsPlayer) {
        tsPlayer.destroy();
        tsPlayer = null;
    }

    // 嘗試透過 mpegts.js 播放 TS 串流
    if (window.mpegts && mpegts.isSupported()) {
        try {
            tsPlayer = mpegts.createPlayer({
                type: 'mse',
                isLive: false,
                url: streamUrl
            });
            tsPlayer.attachMediaElement(videoEl);
            tsPlayer.load();
            tsPlayer.play().catch(e => console.log("Auto-play blocked or waiting user click"));
        } catch (err) {
            console.warn("mpegts failed, fallback to native video src", err);
            videoEl.src = streamUrl;
        }
    } else {
        videoEl.src = streamUrl;
    }

    // 載入該影片的髒污違規截圖
    loadVideoAlerts(filename);
}

function closeVideoModal() {
    const videoEl = document.getElementById("modal-player");
    videoEl.pause();
    if (tsPlayer) {
        tsPlayer.destroy();
        tsPlayer = null;
    }
    document.getElementById("video-modal").classList.add("hidden");
}

function loadVideoAlerts(filename) {
    const container = document.getElementById("modal-alerts-container");
    container.innerHTML = `<span class="text-xs text-slate-500">載入抓拍紀錄中...</span>`;

    fetch(`/api/videos/${filename}/alerts`)
        .then(r => r.json())
        .then(data => {
            if (!data.alerts || data.alerts.length === 0) {
                container.innerHTML = `
                    <div class="bg-slate-950 p-4 rounded-xl border border-slate-800 text-center space-y-1">
                        <div class="text-emerald-400 font-bold text-xs">✅ 無路面髒污違規</div>
                        <div class="text-[11px] text-slate-500">這 30 分鐘錄影路面維持乾淨。</div>
                    </div>
                `;
                return;
            }

            container.innerHTML = data.alerts.map(a => {
                const min = Math.floor(a.video_sec / 60);
                const sec = Math.floor(a.video_sec % 60);
                const timeStr = `${String(min).padStart(2, '0')}:${String(sec).padStart(2, '0')}`;
                return `
                    <div class="bg-slate-950 p-2 rounded-xl border border-red-900/60 flex space-x-2.5">
                        <img src="/api/snapshots/${a.snapshot_file}" class="w-16 h-12 object-cover rounded-lg border border-slate-800 cursor-pointer" onclick="window.open('/api/snapshots/${a.snapshot_file}', '_blank')">
                        <div class="flex-1 text-[11px] flex flex-col justify-center">
                            <div class="font-bold text-red-400">髒污檢測 (${a.confidence.toFixed(1)}%)</div>
                            <div class="text-slate-400 text-[10px]">時間: ${a.timestamp}</div>
                            <button onclick="seekVideo(${a.video_sec})" class="mt-1 bg-red-900/50 hover:bg-red-800 text-red-200 px-2 py-0.5 rounded text-[10px] font-mono font-bold w-fit">
                                ⏩ 跳至 ${timeStr}
                            </button>
                        </div>
                    </div>
                `;
            }).join("");
        });
}

function seekVideo(sec) {
    const videoEl = document.getElementById("modal-player");
    if (tsPlayer) {
        tsPlayer.currentTime = sec;
        tsPlayer.play();
    } else if (videoEl) {
        videoEl.currentTime = sec;
        videoEl.play();
    }
}
