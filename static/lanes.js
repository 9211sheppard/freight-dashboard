/* lanes.js — Shipping Lanes */

(function () {
  "use strict";

  // ── Port code lookup (LOCODE) ─────────────────────────────────────────────
  const PORT_CODES = {
    // China
    "Shanghai":              "CNSHA",
    "Ningbo":                "CNNGB",
    "Shenzhen":              "CNYTN",
    "Shenzhen (Yantian)":    "CNYTN",
    "Shenzhen (Shekou)":     "CNSHK",
    "Guangzhou (Nansha)":    "CNGGZ",
    "Qingdao":               "CNTAO",
    "Tianjin":               "CNTSN",
    "Xiamen":                "CNXMN",
    "Dalian":                "CNDLC",
    "Lianyungang":           "CNLYG",
    // USA
    "Los Angeles":           "USLAX",
    "Long Beach":            "USLGB",
    "Oakland":               "USOAK",
    "Seattle":               "USSEA",
    "Tacoma":                "USTIW",
    "New York / New Jersey": "USNYC",
    "New York / Newark":     "USNYC",
    "New York":              "USNYC",
    "Savannah":              "USSAV",
    "Charleston":            "USCHS",
    "Norfolk":               "USORF",
    "Houston":               "USHOU",
    "Miami":                 "USMIA",
    // Canada
    "Vancouver":             "CAVAN",
    "Prince Rupert":         "CAPRR",
    "Montreal":              "CAMTR",
    "Halifax":               "CAHA",
    // India
    "Nhava Sheva / JNPT":    "INNSA",
    "Nhava Sheva (JNPT)":    "INNSA",
    "Nhava Sheva":           "INNSA",
    "Mumbai":                "INBOM",
    "Mundra":                "INMUN",
    "Hazira":                "INHAZ",
    "Pipavav":               "INPAV",
    "Chennai":               "INMAA",
    "Kolkata":               "INCCU",
    "Kolkata (Haldia)":      "INCCU",
    "Cochin":                "INCOK",
    "Visakhapatnam":         "INVTZ",
    "Vizag":                 "INVTZ",
    // UAE
    "Jebel Ali":             "AEJEA",
    "Jebel Ali (Dubai)":     "AEJEA",
    "Dubai":                 "AEJEA",
    "Khalifa Port":          "AEKHL",
    "Khalifa Port (Abu Dhabi)": "AEKHL",
    "Abu Dhabi":             "AEKHL",
    "Sharjah":               "AEKLF",
    "Khor Fakkan":           "AEKLF",
    "Sharjah (Khor Fakkan)": "AEKLF",
    "Fujairah":              "AEFJR",
    // Europe
    "Rotterdam":             "NLRTM",
    "Antwerp":               "BEANR",
    "Hamburg":               "DEHAM",
    "Bremerhaven":           "DEBRV",
    "Felixstowe":            "GBFXT",
    "London Gateway":        "GBLGP",
    "Le Havre":              "FRLEH",
    "Valencia":              "ESVLC",
    "Barcelona":             "ESBCN",
    "Genoa":                 "ITGOA",
  };

  function portCode(name) { return PORT_CODES[name] || null; }

  function portLabel(name) {
    if (!name) return "";
    const code = portCode(name);
    return code
      ? `${esc(name)} <span class="port-code">${code}</span>`
      : esc(name);
  }

  // ── DOM refs ──────────────────────────────────────────────────────────────
  const filterLaneGroup   = document.getElementById("filterLaneGroup");
  const filterOrigin      = document.getElementById("filterOrigin");
  const filterDestination = document.getElementById("filterDestination");
  const filterCarrier     = document.getElementById("filterCarrier");
  const filterVessel      = document.getElementById("filterVessel");
  const clearVessel       = document.getElementById("clearVessel");
  let lanesBody           = document.getElementById("lanesBody");
  const lanesResultCount  = document.getElementById("lanesResultCount");
  const lanesLastChecked  = document.getElementById("lanesLastChecked");
  const statTotal         = document.getElementById("statTotal");
  const statActive        = document.getElementById("statActive");
  const statOrigins       = document.getElementById("statOrigins");
  const statDestinations  = document.getElementById("statDestinations");

  let _vesselDebounce = null;

  // ── Helpers ───────────────────────────────────────────────────────────────
  function esc(s) {
    if (!s) return "";
    return String(s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;")
      .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  function formatDate(str) {
    if (!str || str.trim() === "") return "—";
    const parts = str.trim().split(/[ T]/);
    const dp = parts[0].split("-");
    if (dp.length < 3) return str;
    const months = ["Jan","Feb","Mar","Apr","May","Jun",
                    "Jul","Aug","Sep","Oct","Nov","Dec"];
    const month = months[parseInt(dp[1], 10) - 1] || dp[1];
    const day   = parseInt(dp[2], 10);
    return parts[1] ? `${month} ${day}` : `${month} ${day}`;
  }

  // ── Alliance badge colours ────────────────────────────────────────────────
  const ALLIANCE_STYLE = {
    "Gemini":      "background:#0d3b6e;color:#90caf9",
    "Ocean":       "background:#1b4332;color:#86efac",
    "Premier":     "background:#4a1942;color:#f0abfc",
    "Independent": "background:#2d2d2d;color:#d1d5db",
  };

  function allianceBadge(alliance) {
    if (!alliance) return "";
    const style = ALLIANCE_STYLE[alliance] || "background:#333;color:#ccc";
    return ` <span class="alliance-badge" style="${style}">${esc(alliance)}</span>`;
  }

  // ── Render one row ────────────────────────────────────────────────────────
  function renderRow(lane) {
    const serviceVessel = [lane.service, lane.vessel]
      .filter(Boolean).join(" · ") || "—";

    const carrierCell = lane.carrier
      ? esc(lane.carrier) + allianceBadge(lane.alliance)
      : "—";

    const freqCell = lane.frequency
      ? `<span class="freq-badge">${esc(lane.frequency)}</span>` : "";

    return `
      <tr>
        <td>${portLabel(lane.origin_name)}</td>
        <td>${portLabel(lane.destination_name)}</td>
        <td class="small">${carrierCell}</td>
        <td class="fw-medium">${esc(serviceVessel)}${freqCell}</td>
        <td class="lane-date-cell">${formatDate(lane.etd)}</td>
        <td class="lane-date-cell">${formatDate(lane.eta)}</td>
        <td class="text-muted small">${esc(lane.transit) || "—"}</td>
      </tr>`;
  }

  function renderEmpty(msg) {
    lanesBody.innerHTML = `
      <tr><td colspan="7">
        <div class="empty-state">
          <i class="bi bi-ship"></i>
          <div>${msg || "No sailings found."}</div>
        </div>
      </td></tr>`;
  }

  // ── Fetch & render ────────────────────────────────────────────────────────
  function fetchLanes() {
    const params = new URLSearchParams();
    if (filterLaneGroup && filterLaneGroup.value) params.set("lane_group", filterLaneGroup.value);
    if (filterOrigin.value)      params.set("origin",      filterOrigin.value);
    if (filterDestination.value) params.set("destination", filterDestination.value);
    if (filterCarrier.value)     params.set("carrier",     filterCarrier.value);
    if (filterVessel.value.trim()) params.set("vessel",    filterVessel.value.trim());

    fetch(`/api/lanes/search?${params}`)
      .then(r => r.json())
      .then(data => {
        if (!data || data.length === 0) {
          renderEmpty("No sailings found for the selected filters.");
          if (lanesResultCount) lanesResultCount.textContent = "0 results";
          return;
        }
        // Swap entire tbody element — zero flash, no intermediate empty state
        const newTbody = document.createElement("tbody");
        newTbody.id    = "lanesBody";
        newTbody.innerHTML = data.map(renderRow).join("");
        lanesBody.parentNode.replaceChild(newTbody, lanesBody);
        lanesBody = newTbody;

        if (lanesResultCount)
          lanesResultCount.textContent = `${data.length} sailing${data.length !== 1 ? "s" : ""}`;
        const checked = data.find(r => r.last_checked);
        if (checked && lanesLastChecked)
          lanesLastChecked.textContent = `Updated: ${formatDate(checked.last_checked)}`;
      })
      .catch(() => { renderEmpty("Failed to load lanes data."); });
  }

  function fetchStats() {
    fetch("/api/lanes/stats").then(r => r.json()).then(data => {
      if (statTotal)        statTotal.textContent        = data.total        || 0;
      if (statActive)       statActive.textContent       = data.active       || 0;
      if (statOrigins)      statOrigins.textContent      = data.origins      || 0;
      if (statDestinations) statDestinations.textContent = data.destinations || 0;
    }).catch(() => {});
  }

  function fetchOptions() {
    fetch("/api/lanes/options").then(r => r.json()).then(data => {
      if (filterOrigin) {
        const cur = filterOrigin.value;
        filterOrigin.innerHTML = '<option value="">All Origins</option>';
        (data.origins || []).forEach(o => {
          const opt = document.createElement("option");
          opt.value = o;
          const code = portCode(o);
          opt.textContent = code ? `${o} (${code})` : o;
          if (o === cur) opt.selected = true;
          filterOrigin.appendChild(opt);
        });
      }
      if (filterDestination) {
        const cur = filterDestination.value;
        filterDestination.innerHTML = '<option value="">All Destinations</option>';
        (data.destinations || []).forEach(d => {
          const opt = document.createElement("option");
          opt.value = d;
          const code = portCode(d);
          opt.textContent = code ? `${d} (${code})` : d;
          if (d === cur) opt.selected = true;
          filterDestination.appendChild(opt);
        });
      }
      if (filterCarrier) {
        const cur = filterCarrier.value;
        filterCarrier.innerHTML = '<option value="">All Carriers</option>';
        (data.carriers || []).forEach(c => {
          const opt = document.createElement("option");
          opt.value = c;
          opt.textContent = c;
          if (c === cur) opt.selected = true;
          filterCarrier.appendChild(opt);
        });
      }
    }).catch(() => {});
  }

  // ── Events ────────────────────────────────────────────────────────────────
  [filterLaneGroup, filterOrigin, filterDestination, filterCarrier].forEach(el => {
    if (el) el.addEventListener("change", fetchLanes);
  });

  if (filterVessel) {
    filterVessel.addEventListener("input", () => {
      clearTimeout(_vesselDebounce);
      _vesselDebounce = setTimeout(fetchLanes, 320);
    });
  }

  if (clearVessel) {
    clearVessel.addEventListener("click", () => {
      filterVessel.value = "";
      fetchLanes();
    });
  }

  // ── Init ──────────────────────────────────────────────────────────────────
  fetchOptions();
  fetchStats();
  fetchLanes();

})();
