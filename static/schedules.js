/* schedules.js - Unified global vessel schedules page */

(function () {
  "use strict";

  let selectedOrigin = null;
  let selectedDest = null;
  let laneStatusMap = {};
  let vesselDebounce = null;

  const CARRIER_COLORS = {
    "Maersk": "#42b0d5",
    "Hapag-Lloyd": "#f60",
    "MSC": "#8b2fc9",
    "CMA CGM": "#e30613",
    "ONE": "#e4002b",
    "OOCL": "#003087",
    "COSCO": "#c00",
    "Evergreen": "#00843d",
    "Yang Ming": "#003da5",
    "ZIM": "#f5a623",
    "PIL": "#004b8d",
    "HMM": "#005baa",
    "WHL": "#e57200",
    "Wan Hai": "#e57200",
    "SITC": "#1e6f50",
  };

  const DEST_LABELS = {
    "USA": "USA",
    "Canada": "Canada",
    "Europe": "Europe",
    "Mexico": "Mexico",
    "South America": "South America",
    "Central America": "Central America",
    "Australia/NZ": "Australia / NZ",
    "Middle East": "Middle East",
    "Africa": "Africa",
  };

  const DEST_ORDER = [
    "USA",
    "Canada",
    "Europe",
    "Mexico",
    "South America",
    "Central America",
    "Australia/NZ",
    "Middle East",
    "Africa",
  ];

  const GRADE_COLORS = {
    "A+": "#28a745",
    "A": "#28a745",
    "B+": "#7bc67e",
    "B": "#a3d977",
    "C+": "#ffc107",
    "C": "#fd7e14",
    "D": "#dc3545",
    "F": "#721c24",
  };

  function esc(value) {
    if (value === null || value === undefined) return "";
    return String(value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function formatDate(value) {
    if (!value || String(value).trim() === "") return "-";
    const parts = String(value).trim().split(/[ T]/);
    const dateParts = parts[0].split("-");
    if (dateParts.length < 3) return esc(value);
    const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
    const month = months[parseInt(dateParts[1], 10) - 1] || dateParts[1];
    const day = parseInt(dateParts[2], 10);
    return month + " " + day;
  }

  function show(el) {
    el.style.removeProperty("display");
    el.style.removeProperty("important");
    el.style.setProperty("display", "block");
  }

  function hide(el) {
    el.style.setProperty("display", "none", "important");
  }

  function carrierBadge(carrier) {
    if (!carrier) return "<span class='text-secondary'>-</span>";
    const color = CARRIER_COLORS[carrier] || "#6c757d";
    return `<span class="badge" style="background:${color};font-size:0.72rem">${esc(carrier)}</span>`;
  }

  function delayLabel(delayHours) {
    const value = Number(delayHours || 0);
    if (Math.abs(value) >= 24) {
      return (value / 24).toFixed(1) + "d";
    }
    return Math.round(value) + "h";
  }

  function predictedEtaCell(row) {
    if (!row || row.delay_confidence === "none" || row.match_level === "none" || !row.predicted_eta) {
      return '<td class="text-secondary" style="font-size:0.82rem">-</td>';
    }

    const delayHours = Number(row.delay_hours || 0);
    let tone = "text-secondary";
    if (delayHours > 24) tone = "text-danger";
    else if (delayHours > 0) tone = "text-warning";
    else if (delayHours < -6) tone = "text-success";

    const tooltip = [
      (row.on_time_pct != null ? Math.round(row.on_time_pct) + "% on-time" : null),
      ((row.sample_count || 0) + " voyages"),
      ((row.match_level || "none") + " match"),
    ].filter(Boolean).join(" | ");

    return `<td class="${tone}" style="font-size:0.82rem" title="${esc(tooltip)}">
      <strong>${formatDate(row.predicted_eta)}</strong>
      <div class="small text-secondary">${delayHours > 0 ? "+" : ""}${delayLabel(delayHours)}</div>
    </td>`;
  }

  function reliabilityCell(row) {
    const grade = row.reliability_grade;
    if (!grade || grade === "N/A") {
      return '<td class="text-secondary" style="font-size:0.82rem">-</td>';
    }

    const color = GRADE_COLORS[grade] || "#6c757d";
    const otPct = row.reliability_on_time_pct != null ? Math.round(row.reliability_on_time_pct) + "%" : "";
    const samples = row.reliability_sample_count || 0;

    return `<td style="font-size:0.82rem" title="${esc(otPct)} on-time, ${samples} voyages">
      <span class="badge" style="background:${color};font-size:0.72rem;min-width:28px">${grade}</span>
    </td>`;
  }

  const originPillsEl = document.getElementById("originPills");
  const destSection = document.getElementById("destSection");
  const destPillsEl = document.getElementById("destPills");
  const filterSection = document.getElementById("filterSection");
  const filterCarrierEl = document.getElementById("filterCarrier");
  const filterVesselEl = document.getElementById("filterVessel");
  const clearFiltersBtn = document.getElementById("clearFiltersBtn");
  const schedBody = document.getElementById("schedBody");
  const resultCount = document.getElementById("resultCount");
  const syncStatusEl = document.getElementById("syncStatus");
  const syncSchedulesBtn = document.getElementById("syncSchedulesBtn");

  async function loadStats() {
    try {
      const response = await fetch("/api/schedules/stats");
      const data = await response.json();
      document.getElementById("statTotal").textContent = (data.total || 0).toLocaleString();
      document.getElementById("statCarriers").textContent = data.carriers || 0;
      document.getElementById("statLanesWithData").textContent = data.lanes_with_data || data.lanes || 0;
      document.getElementById("statLastUpdated").textContent = data.last_updated || "-";
      document.getElementById("statTopCarrier").textContent = data.top_carrier
        ? data.top_carrier + " " + Math.round(data.top_carrier_pct || 0) + "%"
        : "-";
      const sourceLanes = data.source_lanes || {};
      document.getElementById("statSources").textContent =
        (sourceLanes.csv || 0) + " CSV lanes + " + (sourceLanes.api || 0) + " API lanes";
    } catch (err) {
      // Silent by design.
    }
  }

  async function triggerScheduleSync() {
    if (!syncSchedulesBtn) return;
    syncSchedulesBtn.disabled = true;
    if (syncStatusEl) syncStatusEl.textContent = "Starting API sync...";

    try {
      const response = await fetch("/api/schedules/sync", { method: "POST" });
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.error || "Sync failed");
      }
      if (syncStatusEl) syncStatusEl.textContent = data.message || "Schedule sync started";
      window.setTimeout(async function () {
        await loadLaneStatus();
        await loadStats();
        if (selectedOrigin && selectedDest) {
          fetchResults();
        }
      }, 5000);
    } catch (err) {
      if (syncStatusEl) syncStatusEl.textContent = err.message || "Failed to start sync";
    } finally {
      syncSchedulesBtn.disabled = false;
    }
  }

  async function loadLaneStatus() {
    try {
      const response = await fetch("/api/schedules/lane-status");
      laneStatusMap = await response.json();
    } catch (err) {
      laneStatusMap = {};
    }
  }

  async function loadReliabilityLeaderboard(period) {
    const chosenPeriod = period || "90d";
    const body = document.getElementById("reliabilityBody");
    if (!body) return;

    try {
      const response = await fetch("/api/schedules/reliability/leaderboard?period=" + encodeURIComponent(chosenPeriod));
      const data = await response.json();

      if (!data || data.length === 0) {
        body.innerHTML = '<tr><td colspan="7" class="text-center text-secondary py-3">No reliability data yet</td></tr>';
        return;
      }

      body.innerHTML = data.map((row, index) => {
        const color = GRADE_COLORS[row.reliability_grade] || "#6c757d";
        const delayHours = Number(row.avg_delay_hours || 0);
        const consistencyBar = Math.round(row.consistency_score || 0);

        return `<tr>
          <td class="text-secondary">${index + 1}</td>
          <td>${carrierBadge(row.carrier)}</td>
          <td><span class="badge" style="background:${color};font-size:0.72rem;min-width:28px">${row.reliability_grade}</span></td>
          <td><strong>${Math.round(row.on_time_pct || 0)}%</strong></td>
          <td class="${delayHours > 24 ? "text-danger" : "text-secondary"}" style="font-size:0.82rem">${delayHours > 0 ? "+" : ""}${delayLabel(delayHours)}</td>
          <td>
            <div class="progress" style="height:6px;width:60px;background:#333">
              <div class="progress-bar" style="width:${consistencyBar}%;background:${color}"></div>
            </div>
          </td>
          <td class="text-secondary" style="font-size:0.82rem">${row.total_voyages || 0}</td>
        </tr>`;
      }).join("");
    } catch (err) {
      body.innerHTML = '<tr><td colspan="7" class="text-center text-danger py-3">Failed to load</td></tr>';
    }
  }

  function onOriginSelect(origin) {
    selectedOrigin = origin;
    selectedDest = null;

    originPillsEl.querySelectorAll(".origin-pill").forEach((btn) => {
      btn.classList.toggle("btn-primary", btn.dataset.origin === origin);
      btn.classList.toggle("btn-outline-secondary", btn.dataset.origin !== origin);
    });

    renderDestPills(origin);
    show(destSection);
    hide(filterSection);

    schedBody.innerHTML = `
      <tr>
        <td colspan="10" class="text-center text-secondary py-5">
          <i class="bi bi-compass fs-2 d-block mb-2 opacity-25"></i>
          Now select a destination region
        </td>
      </tr>`;
    resultCount.textContent = "";
    filterCarrierEl.innerHTML = "<option value=''>All Carriers</option>";
    filterVesselEl.value = "";
  }

  function renderDestPills(origin) {
    const statusForOrigin = laneStatusMap[origin] || {};
    destPillsEl.innerHTML = DEST_ORDER.map((dest) => {
      const hasData = !!statusForOrigin[dest];
      const label = DEST_LABELS[dest] || dest;
      const badge = hasData
        ? '<span class="badge bg-success ms-1" style="font-size:0.65rem">&#10003; Data</span>'
        : '<span class="badge bg-secondary ms-1" style="font-size:0.65rem">No Data</span>';
      return `<button class="btn btn-sm btn-outline-secondary dest-pill" data-dest="${esc(dest)}">${label}${badge}</button>`;
    }).join("");

    destPillsEl.querySelectorAll(".dest-pill").forEach((btn) => {
      btn.addEventListener("click", function () {
        onDestSelect(btn.dataset.dest);
      });
    });
  }

  function onDestSelect(dest) {
    selectedDest = dest;

    destPillsEl.querySelectorAll(".dest-pill").forEach((btn) => {
      const active = btn.dataset.dest === dest;
      btn.classList.toggle("btn-success", active);
      btn.classList.toggle("btn-outline-secondary", !active);
    });

    show(filterSection);
    filterVesselEl.value = "";
    filterCarrierEl.innerHTML = "<option value=''>All Carriers</option>";
    fetchResults();
  }

  async function fetchResults() {
    if (!selectedOrigin || !selectedDest) return;

    schedBody.innerHTML = `
      <tr>
        <td colspan="10" class="text-center text-secondary py-4">
          <span class="spinner-border spinner-border-sm me-2"></span>Loading...
        </td>
      </tr>`;
    resultCount.textContent = "";

    const params = new URLSearchParams({
      origin_region: selectedOrigin,
      dest_region: selectedDest,
      carrier: filterCarrierEl.value,
      vessel: filterVesselEl.value.trim(),
    });

    try {
      const response = await fetch("/api/schedules/search?" + params.toString());
      const rows = await response.json();
      renderResults(rows);
      populateCarrierFilter(rows);
    } catch (err) {
      schedBody.innerHTML = `
        <tr>
          <td colspan="10" class="text-center text-danger py-4">Failed to load data.</td>
        </tr>`;
    }
  }

  function renderResults(rows) {
    if (!rows || rows.length === 0) {
      const statusForOrigin = laneStatusMap[selectedOrigin] || {};
      const hasData = !!statusForOrigin[selectedDest];
      const message = hasData
        ? "No sailings match your filters."
        : "No sailings on file - Codex task pending";
      schedBody.innerHTML = `
        <tr>
          <td colspan="10" class="text-center text-secondary py-5">
            <i class="bi bi-ship fs-2 d-block mb-2 opacity-25"></i>
            ${message}
          </td>
        </tr>`;
      resultCount.textContent = "0 sailings found";
      return;
    }

    resultCount.textContent = rows.length + " sailing" + (rows.length !== 1 ? "s" : "") + " found";

    schedBody.innerHTML = rows.map((row) => `
      <tr>
        <td>${carrierBadge(row.carrier)}</td>
        <td style="font-size:0.82rem">${esc(row.origin) || "-"}</td>
        <td style="font-size:0.82rem">${esc(row.destination) || "-"}</td>
        <td class="text-info" style="font-size:0.78rem">${esc(row.vessel_name) || "-"}</td>
        <td class="text-secondary" style="font-size:0.75rem">${esc(row.service) || "-"}</td>
        <td><strong>${formatDate(row.etd)}</strong></td>
        <td class="text-secondary">${formatDate(row.eta)}</td>
        ${predictedEtaCell(row)}
        <td class="text-secondary" style="font-size:0.82rem">${esc(row.transit_time) || "-"}</td>
        ${reliabilityCell(row)}
      </tr>`).join("");
  }

  function populateCarrierFilter(rows) {
    const current = filterCarrierEl.value;
    const carriers = [...new Set(rows.map((row) => row.carrier).filter(Boolean))].sort();
    filterCarrierEl.innerHTML = "<option value=''>All Carriers</option>";
    carriers.forEach((carrier) => {
      const option = document.createElement("option");
      option.value = carrier;
      option.textContent = carrier;
      if (carrier === current) option.selected = true;
      filterCarrierEl.appendChild(option);
    });
  }

  filterCarrierEl.addEventListener("change", function () {
    fetchResults();
  });

  filterVesselEl.addEventListener("input", function () {
    clearTimeout(vesselDebounce);
    vesselDebounce = setTimeout(fetchResults, 350);
  });

  filterVesselEl.addEventListener("keydown", function (event) {
    if (event.key === "Enter") {
      clearTimeout(vesselDebounce);
      fetchResults();
    }
  });

  clearFiltersBtn.addEventListener("click", function () {
    filterCarrierEl.value = "";
    filterVesselEl.value = "";
    fetchResults();
  });

  originPillsEl.addEventListener("click", function (event) {
    const btn = event.target.closest(".origin-pill");
    if (btn) {
      onOriginSelect(btn.dataset.origin);
    }
  });

  async function init() {
    await loadLaneStatus();
    loadStats();
    loadReliabilityLeaderboard("90d");

    const periodEl = document.getElementById("reliabilityPeriod");
    if (periodEl) {
      periodEl.addEventListener("change", function () {
        loadReliabilityLeaderboard(periodEl.value);
      });
    }

    if (syncSchedulesBtn) {
      syncSchedulesBtn.addEventListener("click", triggerScheduleSync);
    }
  }

  init();
})();
