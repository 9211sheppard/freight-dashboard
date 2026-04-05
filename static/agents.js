/* agents.js — Agents Office: world map + country offices */
(function () {
  "use strict";

  let DATA = null;        // full API response

  /* ── ISO2 → approximate map coordinates (percent of SVG viewBox) ──────── */
  const COORDS = {
    US: [18, 38], CA: [18, 25], MX: [14, 45], BR: [32, 62], AR: [28, 75],
    CO: [24, 52], CL: [25, 72], PE: [23, 58], EC: [22, 55], VE: [26, 50],
    CR: [17, 48], PA: [18, 50],
    GB: [47, 26], IE: [45, 26], FR: [48, 32], ES: [46, 36], PT: [44, 36],
    DE: [50, 28], NL: [49, 26], BE: [49, 28], CH: [50, 30], AT: [52, 30],
    IT: [51, 34], PL: [53, 27], CZ: [52, 28], HU: [54, 30], RO: [55, 30],
    HR: [53, 32], GR: [54, 35], TR: [58, 35], SE: [52, 20], DK: [50, 24],
    NO: [50, 18], FI: [55, 18], UA: [57, 27], RU: [65, 22],
    CN: [77, 38], JP: [85, 35], KR: [83, 36], TW: [82, 42], HK: [80, 42],
    IN: [70, 45], PK: [67, 40], BD: [73, 43], LK: [71, 50],
    SG: [77, 54], MY: [76, 52], ID: [79, 56], TH: [76, 48], VN: [78, 47],
    PH: [82, 48], AU: [84, 68], NZ: [90, 74],
    SA: [61, 42], AE: [63, 42], QA: [62, 43], KW: [61, 40], BH: [62, 42],
    OM: [63, 44], EG: [56, 40], JO: [58, 38], LB: [58, 36], IL: [57, 38],
    MA: [45, 40], NG: [50, 50], GH: [47, 50], KE: [58, 55], TZ: [58, 58],
    ZA: [55, 70],
  };

  /* ── Fetch data & render ──────────────────────────────────────────────── */
  async function init() {
    try {
      const res = await fetch("/api/agents/stats");
      DATA = await res.json();
      renderStats(DATA.totals);
      renderMap(DATA.countries);
      renderGrid(DATA.countries);
      bindSearch();
    } catch (e) {
      console.error("Failed to load agent stats:", e);
    }
  }

  /* ── Stats bar ────────────────────────────────────────────────────────── */
  function renderStats(t) {
    document.getElementById("statAgents").textContent = t.total_agents;
    document.getElementById("statCountries").textContent = t.total_countries;
    document.getElementById("statContacts").textContent = t.total_contacts.toLocaleString();
    document.getElementById("statResponse").textContent = t.overall_response_rate + "%";
  }

  /* ── SVG World Map ────────────────────────────────────────────────────── */
  function renderMap(countries) {
    const container = document.getElementById("worldMap");

    // Build SVG
    let svg = `<svg viewBox="0 0 100 85" xmlns="http://www.w3.org/2000/svg" class="agents-map">`;

    // Background with subtle grid
    svg += `<rect width="100" height="85" fill="#1a1d21" rx="4"/>`;

    // Simplified continent outlines (subtle)
    svg += `<g class="continents" opacity="0.12" stroke="#5e6975" stroke-width="0.15" fill="none">`;
    // North America
    svg += `<path d="M5,15 Q15,10 25,15 L30,20 Q28,30 25,35 L20,40 Q15,42 10,45 L8,40 Q3,30 5,15Z"/>`;
    // South America
    svg += `<path d="M20,48 Q25,45 30,48 L35,55 Q35,65 30,72 L27,78 Q24,80 22,75 L20,65 Q18,55 20,48Z"/>`;
    // Europe
    svg += `<path d="M43,18 Q48,15 55,18 L58,22 Q57,28 55,32 L50,35 Q46,37 44,33 L43,25Z"/>`;
    // Africa
    svg += `<path d="M44,38 Q50,36 58,38 L60,45 Q60,55 58,62 L55,68 Q52,72 48,68 L45,58 Q43,48 44,38Z"/>`;
    // Asia
    svg += `<path d="M58,15 Q70,10 85,18 L88,25 Q88,35 85,40 L78,45 Q70,48 65,42 L60,35 Q58,25 58,15Z"/>`;
    // Australia
    svg += `<path d="M78,60 Q85,58 90,62 L92,68 Q90,73 85,72 L80,70 Q77,65 78,60Z"/>`;
    svg += `</g>`;

    // Country markers
    const maxContacts = Math.max(...countries.map(c => c.contacts), 1);
    for (const c of countries) {
      const pos = COORDS[c.iso2];
      if (!pos) continue;

      const intensity = Math.max(0.3, c.contacts / maxContacts);
      const r = 1.2 + intensity * 1.3;
      const color = c.emails_sent > 0
        ? (c.response_rate > 20 ? "#00d97e" : c.response_rate > 0 ? "#f6c343" : "#0dcaf0")
        : "#6c757d";

      svg += `<g class="country-marker" data-iso="${c.iso2}" data-key="${c.country_key}" style="cursor:pointer">`;
      // Glow
      svg += `<circle cx="${pos[0]}" cy="${pos[1]}" r="${r + 0.6}" fill="${color}" opacity="0.2"/>`;
      // Dot
      svg += `<circle cx="${pos[0]}" cy="${pos[1]}" r="${r}" fill="${color}" opacity="0.85" class="marker-dot"/>`;
      // Flag label (tiny)
      svg += `<text x="${pos[0]}" y="${pos[1] + 0.5}" text-anchor="middle" font-size="1.3" fill="#fff" font-weight="600" font-family="system-ui,sans-serif" class="flag-label">${c.iso2}</text>`;
      svg += `</g>`;
    }

    svg += `</svg>`;
    container.innerHTML = svg;

    // Click handlers
    container.querySelectorAll(".country-marker").forEach(g => {
      g.addEventListener("click", () => {
        const key = g.dataset.key;
        selectCountry(key);
      });
    });
  }

  /* ── Country Grid ─────────────────────────────────────────────────────── */
  function renderGrid(countries) {
    const grid = document.getElementById("countryGrid");
    grid.innerHTML = "";
    for (const c of countries) {
      const card = document.createElement("div");
      card.className = "col-6 col-sm-4 col-md-3 col-lg-2";
      card.dataset.countryKey = c.country_key;
      card.dataset.searchText = (c.country + " " + c.agents.map(a => a.name).join(" ")).toLowerCase();

      const activityClass = c.emails_sent > 0
        ? (c.response_rate > 20 ? "office-active" : "office-moderate")
        : "office-idle";

      card.innerHTML = `
        <div class="office-card ${activityClass}" data-key="${c.country_key}">
          <div class="office-flag">${c.flag}</div>
          <div class="office-name">${c.country}</div>
          <div class="office-meta">
            <span title="Agents">${c.agent_count} <i class="bi bi-person-fill"></i></span>
            <span title="Contacts">${c.contacts} <i class="bi bi-people"></i></span>
          </div>
          ${c.emails_sent > 0 ? `<div class="office-rate">${c.response_rate}%</div>` : ""}
        </div>`;
      card.querySelector(".office-card").addEventListener("click", () => selectCountry(c.country_key));
      grid.appendChild(card);
    }
  }

  /* ── Select Country → show detail panel ───────────────────────────────── */
  function selectCountry(key) {
    if (!DATA) return;
    const c = DATA.countries.find(x => x.country_key === key);
    if (!c) return;
    document.getElementById("detailPlaceholder").classList.add("d-none");
    const card = document.getElementById("detailCard");
    card.classList.remove("d-none");

    document.getElementById("detailFlag").textContent = c.flag;
    document.getElementById("detailCountry").textContent = c.country;
    document.getElementById("detailSubtitle").textContent = `${c.agent_count} agents | ${c.iso2} office`;
    document.getElementById("detailContacts").textContent = c.contacts.toLocaleString();
    document.getElementById("detailSent").textContent = c.emails_sent.toLocaleString();
    document.getElementById("detailReplies").textContent = c.replies.toLocaleString();
    document.getElementById("detailRate").textContent = c.response_rate + "%";
    document.getElementById("detailRateBar").style.width = Math.min(c.response_rate, 100) + "%";

    // Agent roster
    const roster = document.getElementById("agentRoster");
    roster.innerHTML = "";
    for (const agent of c.agents) {
      const div = document.createElement("div");
      div.className = "agent-row";
      const initials = agent.name.charAt(0).toUpperCase();
      const aliasTag = agent.has_alias
        ? `<span class="badge bg-info bg-opacity-25 text-info">alias</span>`
        : `<span class="badge bg-secondary bg-opacity-25 text-secondary">shared</span>`;
      div.innerHTML = `
        <div class="agent-avatar">${initials}</div>
        <div class="agent-info">
          <div class="agent-name">${agent.name} ${aliasTag}</div>
          <div class="agent-email">${agent.email}</div>
        </div>`;
      roster.appendChild(div);
    }

    // Highlight on map
    document.querySelectorAll(".country-marker").forEach(g => {
      g.classList.toggle("selected", g.dataset.key === key);
    });

    // Highlight in grid
    document.querySelectorAll(".office-card").forEach(el => {
      el.classList.toggle("office-selected", el.dataset.key === key);
    });

    // Scroll detail into view on mobile
    if (window.innerWidth < 992) {
      card.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }

  /* ── Close detail ─────────────────────────────────────────────────────── */
  document.getElementById("detailClose").addEventListener("click", () => {
    document.getElementById("detailCard").classList.add("d-none");
    document.getElementById("detailPlaceholder").classList.remove("d-none");
    document.querySelectorAll(".country-marker").forEach(g => g.classList.remove("selected"));
    document.querySelectorAll(".office-card").forEach(el => el.classList.remove("office-selected"));
  });

  /* ── Search ───────────────────────────────────────────────────────────── */
  function bindSearch() {
    const input = document.getElementById("countrySearch");
    input.addEventListener("input", () => {
      const q = input.value.toLowerCase().trim();
      document.querySelectorAll("#countryGrid > div").forEach(el => {
        const match = !q || el.dataset.searchText.includes(q);
        el.style.display = match ? "" : "none";
      });
      // Also highlight matching map markers
      document.querySelectorAll(".country-marker").forEach(g => {
        if (!q) {
          g.style.opacity = "";
          return;
        }
        const key = g.dataset.key;
        const c = DATA.countries.find(x => x.country_key === key);
        const text = c ? (c.country + " " + c.agents.map(a => a.name).join(" ")).toLowerCase() : "";
        g.style.opacity = text.includes(q) ? "1" : "0.15";
      });
    });
  }

  /* ── Boot ──────────────────────────────────────────────────────────────── */
  document.addEventListener("DOMContentLoaded", init);
})();
