/* stripe/lanes.js — Shipping Lanes (Stripe Theme) */
(function () {
  "use strict";

  const PORT_CODES = {
    "Shanghai":"CNSHA","Ningbo":"CNNGB","Shenzhen":"CNYTN","Shenzhen (Yantian)":"CNYTN",
    "Shenzhen (Shekou)":"CNSHK","Guangzhou (Nansha)":"CNGGZ","Qingdao":"CNTAO",
    "Tianjin":"CNTSN","Xiamen":"CNXMN","Dalian":"CNDLC","Lianyungang":"CNLYG",
    "Los Angeles":"USLAX","Long Beach":"USLGB","Oakland":"USOAK","Seattle":"USSEA",
    "Tacoma":"USTIW","New York / New Jersey":"USNYC","New York / Newark":"USNYC",
    "New York":"USNYC","Savannah":"USSAV","Charleston":"USCHS","Norfolk":"USORF",
    "Houston":"USHOU","Miami":"USMIA","Vancouver":"CAVAN","Prince Rupert":"CAPRR",
    "Montreal":"CAMTR","Halifax":"CAHA","Nhava Sheva / JNPT":"INNSA","Nhava Sheva (JNPT)":"INNSA",
    "Nhava Sheva":"INNSA","Mumbai":"INBOM","Mundra":"INMUN","Hazira":"INHAZ",
    "Pipavav":"INPAV","Chennai":"INMAA","Kolkata":"INCCU","Kolkata (Haldia)":"INCCU",
    "Cochin":"INCOK","Visakhapatnam":"INVTZ","Vizag":"INVTZ","Jebel Ali":"AEJEA",
    "Jebel Ali (Dubai)":"AEJEA","Dubai":"AEJEA","Khalifa Port":"AEKHL",
    "Khalifa Port (Abu Dhabi)":"AEKHL","Abu Dhabi":"AEKHL","Sharjah":"AEKLF",
    "Khor Fakkan":"AEKLF","Sharjah (Khor Fakkan)":"AEKLF","Fujairah":"AEFJR",
    "Rotterdam":"NLRTM","Antwerp":"BEANR","Hamburg":"DEHAM","Bremerhaven":"DEBRV",
    "Felixstowe":"GBFXT","London Gateway":"GBLGP","Le Havre":"FRLEH",
    "Valencia":"ESVLC","Barcelona":"ESBCN","Genoa":"ITGOA",
  };

  function portCode(name) { return PORT_CODES[name] || null; }
  function portLabel(name) {
    if (!name) return "";
    const code = portCode(name);
    return code
      ? `${esc(name)} <span class="s-port-code">${code}</span>`
      : esc(name);
  }

  const filterLaneGroup   = document.getElementById("filterLaneGroup");
  const filterOrigin      = document.getElementById("filterOrigin");
  const filterDestination = document.getElementById("filterDestination");
  const filterCarrier     = document.getElementById("filterCarrier");
  const filterVessel      = document.getElementById("filterVessel");
  let lanesBody           = document.getElementById("lanesBody");
  const lanesResultCount  = document.getElementById("lanesResultCount");
  const lanesLastChecked  = document.getElementById("lanesLastChecked");
  const statTotal         = document.getElementById("statTotal");
  const statActive        = document.getElementById("statActive");
  const statOrigins       = document.getElementById("statOrigins");
  const statDestinations  = document.getElementById("statDestinations");

  let _vesselDebounce = null;

  function esc(s) {
    if (!s) return "";
    return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
  }

  function formatDate(str) {
    if (!str || str.trim() === "") return "—";
    const parts = str.trim().split(/[ T]/);
    const dp = parts[0].split("-");
    if (dp.length < 3) return str;
    const months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
    const month = months[parseInt(dp[1], 10) - 1] || dp[1];
    return `${month} ${parseInt(dp[2], 10)}`;
  }

  const ALLIANCE_COLORS = {
    "Gemini":      { bg: "#eef0ff", color: "#4338ca" },
    "Ocean":       { bg: "#ecfdf5", color: "#059669" },
    "Premier":     { bg: "#fdf4ff", color: "#9333ea" },
    "Independent": { bg: "#f3f4f6", color: "#6b7280" },
  };

  function allianceBadge(alliance) {
    if (!alliance) return "";
    const c = ALLIANCE_COLORS[alliance] || { bg: "#f3f4f6", color: "#6b7280" };
    return ` <span class="s-alliance-badge" style="background:${c.bg};color:${c.color};">${esc(alliance)}</span>`;
  }

  function renderRow(lane) {
    const serviceVessel = [lane.service, lane.vessel].filter(Boolean).join(" · ") || "—";
    const carrierCell = lane.carrier ? esc(lane.carrier) + allianceBadge(lane.alliance) : "—";
    const freqCell = lane.frequency ? `<span class="s-freq-badge">${esc(lane.frequency)}</span>` : "";

    return `<tr>
      <td>${portLabel(lane.origin_name)}</td>
      <td>${portLabel(lane.destination_name)}</td>
      <td style="font-size:13px;">${carrierCell}</td>
      <td style="font-weight:500;">${esc(serviceVessel)}${freqCell}</td>
      <td style="color:var(--s-text-2);font-size:13px;">${formatDate(lane.etd)}</td>
      <td style="color:var(--s-text-2);font-size:13px;">${formatDate(lane.eta)}</td>
      <td style="color:var(--s-text-3);font-size:13px;">${esc(lane.transit) || "—"}</td>
    </tr>`;
  }

  function renderEmpty(msg) {
    lanesBody.innerHTML = `<tr><td colspan="7" class="s-table-empty">
      <i class="bi bi-ship"></i>${msg || "No sailings found."}
    </td></tr>`;
  }

  function fetchLanes() {
    const params = new URLSearchParams();
    if (filterLaneGroup && filterLaneGroup.value) params.set("lane_group", filterLaneGroup.value);
    if (filterOrigin.value) params.set("origin", filterOrigin.value);
    if (filterDestination.value) params.set("destination", filterDestination.value);
    if (filterCarrier.value) params.set("carrier", filterCarrier.value);
    if (filterVessel.value.trim()) params.set("vessel", filterVessel.value.trim());

    fetch(`/api/lanes/search?${params}`)
      .then(r => r.json())
      .then(data => {
        if (!data || data.length === 0) {
          renderEmpty("No sailings found for the selected filters.");
          if (lanesResultCount) lanesResultCount.textContent = "0 results";
          return;
        }
        const newTbody = document.createElement("tbody");
        newTbody.id = "lanesBody";
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
      if (statTotal) statTotal.textContent = data.total || 0;
      if (statActive) statActive.textContent = data.active || 0;
      if (statOrigins) statOrigins.textContent = data.origins || 0;
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
          opt.value = c; opt.textContent = c;
          if (c === cur) opt.selected = true;
          filterCarrier.appendChild(opt);
        });
      }
    }).catch(() => {});
  }

  [filterLaneGroup, filterOrigin, filterDestination, filterCarrier].forEach(el => {
    if (el) el.addEventListener("change", fetchLanes);
  });

  if (filterVessel) {
    filterVessel.addEventListener("input", () => {
      clearTimeout(_vesselDebounce);
      _vesselDebounce = setTimeout(fetchLanes, 320);
    });
  }

  fetchOptions();
  fetchStats();
  fetchLanes();
})();
