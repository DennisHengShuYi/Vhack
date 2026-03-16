// HTML Elements
const gridContainer = document.getElementById("simulation-grid");
const logContainer = document.getElementById("log-container");
const dronesContainer = document.getElementById("drones-container");
const startBtn = document.getElementById("start-btn");
const stopBtn = document.getElementById("stop-btn");
const survivorInput = document.getElementById("survivor-count");
const timerDisplay = document.getElementById("timer-display");
const survivorStats = document.getElementById("survivor-stats");

// State
let ws = null;
let timerInterval = null;
let secondsElapsed = 0;
let totalSurvivors = 0;
const GRID_WIDTH = 20;
const GRID_HEIGHT = 15;
const CELL_SIZE = 40;
const GAP_SIZE = 1;

// API Endpoints
const API_URL = "http://127.0.0.1:8000";
const WS_URL = "ws://127.0.0.1:8000/ws";

// Initialize empty 20x20 grid in DOM
function initGrid() {
    gridContainer.innerHTML = '';
    for (let y = 0; y < GRID_HEIGHT; y++) {
        for (let x = 0; x < GRID_WIDTH; x++) {
            const cell = document.createElement("div");
            cell.classList.add("cell");
            cell.id = `cell-${x}-${y}`;
            gridContainer.appendChild(cell);
        }
    }
}

// Timer Functions
function startTimer() {
    stopTimer();
    secondsElapsed = 0;
    updateTimerDisplay();
    timerInterval = setInterval(() => {
        secondsElapsed++;
        updateTimerDisplay();
    }, 1000);
}

function stopTimer() {
    if (timerInterval) clearInterval(timerInterval);
}

function updateTimerDisplay() {
    const m = Math.floor(secondsElapsed / 60).toString().padStart(2, '0');
    const s = (secondsElapsed % 60).toString().padStart(2, '0');
    timerDisplay.innerText = `${m}:${s}`;
}

// Control Buttons
startBtn.addEventListener("click", async () => {
    const count = parseInt(survivorInput.value) || 3;
    try {
        startBtn.disabled = true;
        stopBtn.disabled = false;
        survivorInput.disabled = true;
        
        await fetch(`${API_URL}/start`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ survivor_count: count })
        });
        
        startTimer();
        logContainer.innerHTML = ''; // Clear old logs
        addLog("SYSTEM", "Initialized new simulation. Awaiting Agent command...");
    } catch (e) {
        addLog("ERROR", "Failed to start simulation: " + e.message);
        resetUI();
    }
});

stopBtn.addEventListener("click", async () => {
    try {
        await fetch(`${API_URL}/stop`, { method: 'POST' });
        stopTimer();
        resetUI();
    } catch (e) {
        addLog("ERROR", "Failed to stop simulation: " + e.message);
    }
});

function resetUI() {
    startBtn.disabled = false;
    stopBtn.disabled = true;
    survivorInput.disabled = false;
}

function addLog(type, text, isStream = false) {
    // Basic Markdown Rendering Helper
    function mdToHtml(str) {
        return str
            .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
            .replace(/^\* (.*?)$/gm, '<li>$1</li>')
            .replace(/\n/g, '<br>');
    }

    // If it's a stream and matches the previous type, append to last entry
    if (isStream && logContainer.lastElementChild && logContainer.lastElementChild.classList.contains("streaming-reasoning")) {
        logContainer.lastElementChild.innerHTML = mdToHtml(logContainer.lastElementChild.getAttribute("data-raw") + text);
        logContainer.lastElementChild.setAttribute("data-raw", logContainer.lastElementChild.getAttribute("data-raw") + text);
        logContainer.scrollTop = logContainer.scrollHeight;
        return;
    }

    const div = document.createElement("div");
    div.classList.add("log-entry");
    div.setAttribute("data-raw", text);
    
    if (isStream) {
        div.classList.add("streaming-reasoning", "reasoning");
    } else {
        // Improved parsing for non-stream logs
        if (text.toLowerCase().includes("mission log") || text.includes("Reasoning") || text.startsWith("###")) {
            div.classList.add("reasoning");
        } else if (text.includes("Calling Tool") || text.includes("[COMMAND]") || text.includes("assign_scan_zone")) {
            div.classList.add("tool");
        } else if (text.includes("[SYSTEM]")) {
            div.classList.add("sys-msg");
        } else if (type === "ERROR") {
            div.classList.add("error");
        }
    }
    
    div.innerHTML = mdToHtml(text);
    logContainer.appendChild(div);
    logContainer.scrollTop = logContainer.scrollHeight;
}

// Handle incoming grid state overrides
function renderGridState(gridData, hiddenSurvivors) {
    for (let y = 0; y < GRID_HEIGHT; y++) {
        for (let x = 0; x < GRID_WIDTH; x++) {
            let cellState = gridData[y][x].state;
            const cellDiv = document.getElementById(`cell-${x}-${y}`);
            
            // Check if this unscanned cell is actually a hidden survivor
            if (cellState === "UNSCANNED" && hiddenSurvivors) {
                const isHidden = hiddenSurvivors.some(loc => loc[0] === x && loc[1] === y);
                if (isHidden) {
                    cellState = "HIDDEN_SURVIVOR";
                    cellDiv.innerText = "🆘"; // Initial dimmed indicator
                } else {
                    cellDiv.innerText = "";
                }
            } else if (cellState === "SURVIVOR_DETECTED") {
                cellDiv.innerText = "🆘"; // Official detected indicator
            } else {
                cellDiv.innerText = "";
            }

            if (!cellDiv.classList.contains(cellState)) {
                cellDiv.className = `cell ${cellState}`;
            }
        }
    }
}

// Render Fleet Telemetry
function renderFleetState(dronesData) {
    dronesContainer.innerHTML = ''; // Clear list
    Object.keys(dronesData).forEach(droneId => {
        const d = dronesData[droneId];
        
        // 1. Update/Create Side Panel Card
        const card = document.createElement("div");
        card.className = "drone-card";
        
        const battColor = d.battery > 50 ? "var(--success)" : (d.battery > 20 ? "var(--warning)" : "var(--danger)");
        
        card.innerHTML = `
            <div class="drone-header">
                <span class="drone-name">🚁 ${droneId}</span>
                <span class="drone-status-badge status-${d.status}">${d.status}</span>
            </div>
            <div style="font-size: 0.8rem; color: var(--text-muted); display:flex; justify-content: space-between;">
                <span>POS: (${d.x}, ${d.y})</span>
                <span>${d.battery}%</span>
            </div>
            <div class="battery-bar">
                <div class="battery-fill" style="width: ${d.battery}%; background-color: ${battColor};"></div>
            </div>
        `;
        dronesContainer.appendChild(card);
        
        // 2. Update/Create Icon on Map
        let icon = document.getElementById(`icon-${droneId}`);
        if (!icon) {
            icon = document.createElement("div");
            icon.id = `icon-${droneId}`;
            icon.className = "drone-icon";
            document.querySelector(".grid-wrapper").appendChild(icon);
        }
        
        // Extract number and update html
        const dNum = droneId.split("_")[1] || "";
        icon.innerHTML = `<span style="font-size:20px">🚁</span><span style="font-size:14px; font-weight:bold; text-shadow:1px 1px 2px black; margin-left:-3px;">${dNum}</span>`;
        
        // Calculate exact absolute position
        // 10px padding of grid-wrapper + (pos * (CELL_SIZE + GAP_SIZE))
        const leftPos = 10 + (d.x * (CELL_SIZE + GAP_SIZE));
        const topPos = 10 + (d.y * (CELL_SIZE + GAP_SIZE));
        
        // Use translate for smoother CSS hardware acceleration
        icon.style.transform = `translate(${leftPos}px, ${topPos}px)`;
    });
}

// WebSocket Connection
function connectWebSocket() {
    addLog("SYSTEM", "Attempting to connect to Command Center...");
    ws = new WebSocket(WS_URL);
    
    ws.onopen = () => {
        addLog("SYSTEM", "WebSocket Connected. Status: Green.");
        document.body.style.borderTop = "4px solid var(--success)";
    };
    
    ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        
        if (data.type === "state_update") {
            renderGridState(data.grid, data.hidden_survivors);
            renderFleetState(data.drones);
            
            // Update Stats
            totalSurvivors = data.total_survivors;
            survivorStats.innerText = `${data.survivors_found} / ${totalSurvivors}`;
            
            // Auto-stop logic (if we found all survivors but the simulation thinks it's running)
            if (data.survivors_found > 0 && data.survivors_found === totalSurvivors && stopBtn.disabled === false) {
                stopTimer();
                resetUI();
                addLog("SYSTEM", "ALL SURVIVORS LOCATED! MISSION ACCOMPLISHED.");
            }
            
        } else if (data.type === "log") {
            addLog("AGENT", data.message, !!data.is_stream);
        }
    };
    
    ws.onclose = (event) => {
        addLog("SYSTEM", `Disconnected (Code: ${event.code}). Reconnecting in 3s...`);
        document.body.style.borderTop = "4px solid var(--danger)";
        setTimeout(connectWebSocket, 3000);
    };
    
    ws.onerror = (err) => {
        addLog("ERROR", "WebSocket connectivity issue detected.");
        console.error("WS Error:", err);
    }
}

// Initial Boot
initGrid();
connectWebSocket();
