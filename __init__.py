<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>OCP Monitor — {{ cluster_name }}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600&family=Space+Grotesk:wght@300;400;500;600;700&display=swap" rel="stylesheet">
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<style>
  :root {
    --bg:        #080c18;
    --bg2:       #0d1323;
    --bg3:       #121929;
    --bg4:       #1a2235;
    --border:    #1f2d47;
    --border2:   #2a3d5e;
    --text:      #e8eef8;
    --text2:     #9ab0cc;
    --text3:     #5a7090;
    --accent:    #4f9cf9;
    --accent2:   #2563eb;
    --green:     #22d3a0;
    --green-bg:  rgba(34,211,160,.12);
    --amber:     #fbbf24;
    --amber-bg:  rgba(251,191,36,.12);
    --red:       #f87171;
    --red-bg:    rgba(248,113,113,.12);
    --purple:    #a78bfa;
    --purple-bg: rgba(167,139,250,.12);
    --blue-bg:   rgba(79,156,249,.12);
    --mono:      'JetBrains Mono', monospace;
    --sans:      'Space Grotesk', sans-serif;
    --radius:    8px;
    --radius-lg: 12px;
    --shadow:    0 4px 24px rgba(0,0,0,.4);
  }

  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

  body {
    background: var(--bg);
    color: var(--text);
    font-family: var(--sans);
    font-size: 14px;
    line-height: 1.6;
    min-height: 100vh;
  }

  a { color: var(--accent); text-decoration: none; }
  a:hover { text-decoration: underline; color: #7ab8fb; }

  /* ── Layout ── */
  .layout { display: flex; min-height: 100vh; }

  .sidebar {
    width: 230px;
    flex-shrink: 0;
    background: var(--bg2);
    border-right: 1px solid var(--border);
    display: flex;
    flex-direction: column;
    position: sticky;
    top: 0;
    height: 100vh;
    overflow-y: auto;
  }

  .sidebar-logo {
    padding: 22px 20px 18px;
    border-bottom: 1px solid var(--border);
    background: linear-gradient(135deg, rgba(79,156,249,.08), transparent);
  }

  .sidebar-logo .brand {
    display: flex;
    align-items: center;
    gap: 9px;
    margin-bottom: 6px;
  }

  .logo-icon {
    width: 28px; height: 28px;
    background: linear-gradient(135deg, var(--accent), #2563eb);
    border-radius: 7px;
    display: flex; align-items: center; justify-content: center;
    font-size: 14px;
    flex-shrink: 0;
    box-shadow: 0 2px 10px rgba(79,156,249,.3);
  }

  .sidebar-logo .name {
    font-family: var(--mono);
    font-size: 12px;
    font-weight: 600;
    letter-spacing: .1em;
    text-transform: uppercase;
    color: var(--accent);
  }

  .sidebar-logo .cluster {
    font-size: 12px;
    color: var(--text2);
    margin-top: 2px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    padding-left: 37px;
  }

  .sidebar nav { padding: 14px 0; flex: 1; }

  .nav-section {
    padding: 8px 20px 4px;
    font-size: 10px;
    font-family: var(--mono);
    letter-spacing: .12em;
    text-transform: uppercase;
    color: var(--text3);
  }

  .nav-item {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 9px 20px;
    color: var(--text2);
    font-size: 13px;
    font-weight: 400;
    cursor: pointer;
    transition: background .15s, color .15s, border-color .15s;
    border-left: 2px solid transparent;
    margin: 1px 0;
  }

  .nav-item:hover { background: var(--bg3); color: var(--text); text-decoration: none; }

  .nav-item.active {
    color: var(--accent);
    border-left-color: var(--accent);
    background: var(--blue-bg);
    font-weight: 500;
  }

  .nav-icon { width: 16px; height: 16px; opacity: .7; flex-shrink: 0; }
  .nav-item.active .nav-icon { opacity: 1; }

  .sidebar-footer {
    padding: 16px 20px;
    border-top: 1px solid var(--border);
    font-size: 11px;
    color: var(--text3);
    font-family: var(--mono);
    line-height: 1.8;
  }

  .main { flex: 1; overflow-x: hidden; }

  .topbar {
    background: var(--bg2);
    border-bottom: 1px solid var(--border);
    padding: 14px 28px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    position: sticky;
    top: 0;
    z-index: 10;
    backdrop-filter: blur(8px);
  }

  .topbar-title { font-size: 15px; font-weight: 600; color: var(--text); letter-spacing: .01em; }
  .topbar-right { display: flex; align-items: center; gap: 16px; }
  .topbar-meta { font-size: 11px; color: var(--text3); font-family: var(--mono); }
  .topbar-live {
    display: flex; align-items: center; gap: 6px;
    font-size: 11px; color: var(--green); font-family: var(--mono);
  }
  .live-dot {
    width: 6px; height: 6px; border-radius: 50%;
    background: var(--green);
    animation: pulse-green 2s infinite;
  }
  @keyframes pulse-green { 0%,100%{opacity:1;box-shadow:0 0 0 0 rgba(34,211,160,.4)} 50%{opacity:.7;box-shadow:0 0 0 4px rgba(34,211,160,0)} }

  .content { padding: 24px 28px; max-width: 1280px; }

  /* ── Badges ── */
  .badge {
    display: inline-flex; align-items: center; gap: 5px;
    padding: 3px 10px; border-radius: 20px;
    font-size: 11px; font-weight: 600; font-family: var(--mono);
    letter-spacing: .05em; white-space: nowrap;
  }
  .badge-dot { width: 6px; height: 6px; border-radius: 50%; flex-shrink: 0; }
  .badge-healthy  { background: var(--green-bg);  color: var(--green);  border: 1px solid rgba(34,211,160,.2); }
  .badge-healthy  .badge-dot { background: var(--green);  box-shadow: 0 0 5px var(--green); }
  .badge-warning  { background: var(--amber-bg);  color: var(--amber);  border: 1px solid rgba(251,191,36,.2); }
  .badge-warning  .badge-dot { background: var(--amber); }
  .badge-critical { background: var(--red-bg);    color: var(--red);    border: 1px solid rgba(248,113,113,.2); }
  .badge-critical .badge-dot { background: var(--red); box-shadow: 0 0 5px var(--red); animation: pulse-red 1.5s infinite; }
  .badge-error    { background: var(--purple-bg); color: var(--purple); border: 1px solid rgba(167,139,250,.2); }
  .badge-error    .badge-dot { background: var(--purple); }
  .badge-unknown  { background: var(--bg3); color: var(--text3); border: 1px solid var(--border); }
  .badge-info     { background: var(--blue-bg);   color: var(--accent); border: 1px solid rgba(79,156,249,.2); }

  @keyframes pulse-red { 0%,100%{opacity:1} 50%{opacity:.3} }

  /* ── Metric cards ── */
  .metrics-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
    gap: 14px;
    margin-bottom: 24px;
  }

  .metric-card {
    background: var(--bg2);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    padding: 18px 20px;
    position: relative;
    overflow: hidden;
    transition: border-color .2s, transform .15s;
  }

  .metric-card:hover { border-color: var(--border2); transform: translateY(-1px); }

  .metric-card::after {
    content: '';
    position: absolute;
    inset: 0;
    background: radial-gradient(ellipse at top left, rgba(255,255,255,.02), transparent 60%);
    pointer-events: none;
  }

  .metric-accent {
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 2px;
    border-radius: 2px 2px 0 0;
  }

  .metric-card.green  .metric-accent { background: linear-gradient(90deg, var(--green), transparent); }
  .metric-card.amber  .metric-accent { background: linear-gradient(90deg, var(--amber), transparent); }
  .metric-card.red    .metric-accent { background: linear-gradient(90deg, var(--red), transparent); }
  .metric-card.blue   .metric-accent { background: linear-gradient(90deg, var(--accent), transparent); }
  .metric-card.purple .metric-accent { background: linear-gradient(90deg, var(--purple), transparent); }

  .metric-icon {
    font-size: 18px;
    margin-bottom: 10px;
    display: block;
  }

  .metric-label {
    font-size: 11px; font-family: var(--mono);
    color: var(--text3); text-transform: uppercase;
    letter-spacing: .1em; margin-bottom: 6px;
  }

  .metric-value {
    font-size: 32px; font-weight: 700;
    font-family: var(--mono); line-height: 1;
  }

  .metric-card.green  .metric-value { color: var(--green); }
  .metric-card.amber  .metric-value { color: var(--amber); }
  .metric-card.red    .metric-value { color: var(--red); }
  .metric-card.blue   .metric-value { color: var(--accent); }
  .metric-card.purple .metric-value { color: var(--purple); }

  .metric-sub { font-size: 12px; color: var(--text3); margin-top: 6px; }

  /* ── Charts grid ── */
  .charts-grid {
    display: grid;
    grid-template-columns: 2fr 1fr;
    gap: 14px;
    margin-bottom: 24px;
  }

  .charts-grid-3 {
    display: grid;
    grid-template-columns: 1fr 1fr 1fr;
    gap: 14px;
    margin-bottom: 24px;
  }

  .chart-card {
    background: var(--bg2);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    padding: 18px 20px;
    position: relative;
    overflow: hidden;
  }

  .chart-title {
    font-size: 11px; font-family: var(--mono);
    font-weight: 600; text-transform: uppercase;
    letter-spacing: .1em; color: var(--text2);
    margin-bottom: 16px;
    display: flex; align-items: center; justify-content: space-between;
  }

  .chart-title span { color: var(--text3); font-weight: 400; }

  .chart-wrap { position: relative; }

  /* ── Section header ── */
  .section-header {
    display: flex; align-items: center; justify-content: space-between;
    margin-bottom: 14px; margin-top: 28px;
  }

  .section-title {
    font-size: 12px; font-family: var(--mono); font-weight: 600;
    text-transform: uppercase; letter-spacing: .1em; color: var(--text2);
    display: flex; align-items: center; gap: 8px;
  }

  .section-count {
    font-size: 11px; font-family: var(--mono); color: var(--text3);
    background: var(--bg3); padding: 2px 9px;
    border-radius: 4px; border: 1px solid var(--border);
  }

  /* ── Run table ── */
  .run-table {
    width: 100%; border-collapse: collapse;
    border: 1px solid var(--border);
    border-radius: var(--radius-lg); overflow: hidden;
  }

  .run-table th {
    background: var(--bg3); padding: 11px 16px;
    text-align: left; font-size: 10px; font-family: var(--mono);
    font-weight: 600; text-transform: uppercase; letter-spacing: .1em;
    color: var(--text2); border-bottom: 1px solid var(--border);
  }

  .run-table td {
    padding: 12px 16px; border-bottom: 1px solid var(--border);
    font-size: 13px; vertical-align: middle; color: var(--text);
  }

  .run-table tr:last-child td { border-bottom: none; }
  .run-table tbody tr:hover td { background: var(--bg3); }

  .run-table .mono { font-family: var(--mono); font-size: 12px; color: var(--text2); }
  .run-table .dim  { color: var(--text3); font-size: 12px; font-family: var(--mono); }

  .run-link {
    font-family: var(--mono); font-size: 11px; font-weight: 600;
    color: var(--accent); padding: 4px 10px;
    border: 1px solid rgba(79,156,249,.3); border-radius: 5px;
    transition: all .15s; background: var(--blue-bg);
  }
  .run-link:hover { background: var(--accent); color: #fff; text-decoration: none; border-color: var(--accent); }

  /* ── Status bar in table ── */
  .status-bar {
    height: 4px; border-radius: 2px; width: 100%;
    background: var(--bg4); overflow: hidden;
  }
  .status-bar-fill { height: 100%; border-radius: 2px; transition: width .3s; }

  /* ── Failure cards ── */
  .failure-list { display: flex; flex-direction: column; gap: 14px; }

  .failure-card {
    background: var(--bg2); border: 1px solid var(--border);
    border-radius: var(--radius-lg); overflow: hidden;
    transition: border-color .2s;
  }
  .failure-card:hover { border-color: var(--border2); }

  .failure-header {
    display: flex; align-items: center; gap: 12px;
    padding: 14px 18px; border-bottom: 1px solid var(--border);
    background: var(--bg3);
  }

  .failure-ref {
    font-family: var(--mono); font-size: 11px; font-weight: 600;
    color: var(--text2); background: var(--bg4);
    padding: 3px 8px; border-radius: 5px;
    border: 1px solid var(--border2); flex-shrink: 0;
  }

  .failure-title { flex: 1; font-size: 13px; font-weight: 600; color: var(--text); }
  .failure-component {
    font-family: var(--mono); font-size: 11px; color: var(--text2);
    background: var(--bg4); padding: 3px 9px;
    border-radius: 5px; border: 1px solid var(--border2);
  }

  .failure-body { padding: 18px 20px; }
  .failure-msg { color: var(--text); font-size: 13px; margin-bottom: 16px; line-height: 1.6; }

  .resolution-section { margin-top: 16px; }

  .resolution-label {
    font-size: 10px; font-family: var(--mono);
    text-transform: uppercase; letter-spacing: .1em;
    color: var(--text3); margin-bottom: 8px;
    display: flex; align-items: center; gap: 6px;
  }
  .resolution-label::after {
    content: ''; flex: 1; height: 1px; background: var(--border);
  }

  .step-list { list-style: none; counter-reset: steps; }
  .step-list li {
    counter-increment: steps;
    display: flex; gap: 12px;
    padding: 8px 0; font-size: 13px; color: var(--text);
    border-bottom: 1px solid var(--border);
  }
  .step-list li:last-child { border-bottom: none; }
  .step-list li::before {
    content: counter(steps, decimal-leading-zero);
    font-family: var(--mono); font-size: 10px; font-weight: 600;
    color: var(--accent); flex-shrink: 0; margin-top: 3px; min-width: 24px;
  }

  .cmd-block {
    background: #04080f; border: 1px solid var(--border);
    border-radius: var(--radius); padding: 14px 16px;
    font-family: var(--mono); font-size: 12px; color: #7dd3fc;
    overflow-x: auto; margin-top: 8px; white-space: pre; line-height: 1.8;
    border-left: 3px solid var(--accent);
  }
  .cmd-block .cmd-prompt { color: var(--text3); user-select: none; }

  /* ── Data panels ── */
  .data-grid {
    display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
    gap: 14px; margin-bottom: 14px;
  }

  .data-panel {
    background: var(--bg2); border: 1px solid var(--border);
    border-radius: var(--radius-lg); overflow: hidden;
  }

  .data-panel-header {
    padding: 10px 14px; border-bottom: 1px solid var(--border);
    font-size: 11px; font-family: var(--mono); font-weight: 600;
    text-transform: uppercase; letter-spacing: .08em; color: var(--text2);
    display: flex; align-items: center; justify-content: space-between;
    background: var(--bg3);
  }

  .data-panel-body { padding: 10px 14px; max-height: 220px; overflow-y: auto; }

  .mini-table { width: 100%; border-collapse: collapse; }
  .mini-table td {
    padding: 6px 0; font-size: 12px;
    border-bottom: 1px solid var(--border); vertical-align: top;
    color: var(--text);
  }
  .mini-table tr:last-child td { border-bottom: none; }
  .mini-table .k { color: var(--text2); width: 40%; font-family: var(--mono); font-size: 11px; }

  .ok   { color: var(--green); font-family: var(--mono); font-size: 11px; font-weight: 600; }
  .warn { color: var(--amber); font-family: var(--mono); font-size: 11px; font-weight: 600; }
  .crit { color: var(--red);   font-family: var(--mono); font-size: 11px; font-weight: 600; }

  /* ── Status hero ── */
  .status-hero {
    display: flex; align-items: center; gap: 18px;
    padding: 22px 26px; border-radius: var(--radius-lg);
    margin-bottom: 24px; border: 1px solid var(--border);
  }
  .status-hero.healthy  { background: var(--green-bg);  border-color: rgba(34,211,160,.25); }
  .status-hero.warning  { background: var(--amber-bg);  border-color: rgba(251,191,36,.25); }
  .status-hero.critical { background: var(--red-bg);    border-color: rgba(248,113,113,.25); }
  .status-hero.error    { background: var(--purple-bg); border-color: rgba(167,139,250,.25); }

  .status-indicator {
    width: 48px; height: 48px; border-radius: 50%;
    display: flex; align-items: center; justify-content: center;
    font-size: 20px; flex-shrink: 0; font-weight: 700;
  }
  .status-hero.healthy  .status-indicator { background: rgba(34,211,160,.2);  color: var(--green); }
  .status-hero.warning  .status-indicator { background: rgba(251,191,36,.2);  color: var(--amber); }
  .status-hero.critical .status-indicator { background: rgba(248,113,113,.2); color: var(--red); }
  .status-hero.error    .status-indicator { background: rgba(167,139,250,.2); color: var(--purple); }

  .status-text .label { font-size: 18px; font-weight: 700; letter-spacing: .02em; }
  .status-hero.healthy  .status-text .label { color: var(--green); }
  .status-hero.warning  .status-text .label { color: var(--amber); }
  .status-hero.critical .status-text .label { color: var(--red); }
  .status-hero.error    .status-text .label { color: var(--purple); }

  .status-text .summary { font-size: 13px; color: var(--text2); margin-top: 4px; max-width: 800px; line-height: 1.6; }

  /* ── Incidents ── */
  .incident-table { width: 100%; border-collapse: collapse; }
  .incident-table th, .incident-table td {
    padding: 11px 14px; text-align: left;
    border-bottom: 1px solid var(--border); font-size: 13px;
  }
  .incident-table th {
    font-size: 10px; font-family: var(--mono); font-weight: 600;
    text-transform: uppercase; letter-spacing: .1em;
    color: var(--text2); background: var(--bg3);
  }
  .incident-table td { color: var(--text); }
  .incident-table tbody tr:hover td { background: var(--bg3); }

  .indexed-dot {
    display: inline-block; width: 7px; height: 7px;
    border-radius: 50%; margin-right: 5px; vertical-align: middle;
  }
  .indexed-dot.yes { background: var(--green); box-shadow: 0 0 5px var(--green); }
  .indexed-dot.no  { background: var(--text3); }

  /* ── Form ── */
  .form-card {
    background: var(--bg2); border: 1px solid var(--border);
    border-radius: var(--radius-lg); padding: 24px 26px; margin-bottom: 28px;
  }
  .form-row { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin-bottom: 14px; }
  .form-row.triple { grid-template-columns: 1fr 1fr 1fr; }
  .form-row.full   { grid-template-columns: 1fr; }
  .form-group { display: flex; flex-direction: column; gap: 6px; }
  .form-group label {
    font-size: 11px; font-family: var(--mono); font-weight: 600;
    color: var(--text2); text-transform: uppercase; letter-spacing: .08em;
  }
  .form-control {
    background: var(--bg3); border: 1px solid var(--border2);
    border-radius: var(--radius); color: var(--text);
    padding: 9px 12px; font-family: var(--sans); font-size: 13px;
    outline: none; transition: border-color .15s, box-shadow .15s;
  }
  .form-control:focus { border-color: var(--accent); box-shadow: 0 0 0 3px rgba(79,156,249,.1); }
  select.form-control option { background: var(--bg3); color: var(--text); }
  textarea.form-control { resize: vertical; min-height: 80px; }

  .btn {
    display: inline-flex; align-items: center; gap: 6px;
    padding: 10px 20px; border-radius: var(--radius);
    font-size: 13px; font-weight: 600; cursor: pointer;
    transition: opacity .15s, transform .1s; border: none;
    font-family: var(--sans); letter-spacing: .01em;
  }
  .btn:hover { opacity: .88; transform: translateY(-1px); }
  .btn:active { transform: scale(.98); }
  .btn-primary { background: linear-gradient(135deg, var(--accent), var(--accent2)); color: #fff; box-shadow: 0 2px 12px rgba(79,156,249,.3); }

  /* ── Pagination ── */
  .pagination { display: flex; gap: 6px; align-items: center; margin-top: 18px; }
  .page-btn {
    padding: 6px 12px; border-radius: var(--radius);
    border: 1px solid var(--border); background: var(--bg2);
    color: var(--text2); font-size: 12px; font-family: var(--mono); font-weight: 500;
    cursor: pointer; text-decoration: none; transition: all .15s;
  }
  .page-btn:hover, .page-btn.active {
    background: var(--accent); color: #fff;
    border-color: var(--accent); text-decoration: none;
  }
  .page-btn.disabled { opacity: .35; pointer-events: none; }

  /* ── Collection error ── */
  .collection-errors {
    background: var(--red-bg); border: 1px solid rgba(248,113,113,.25);
    border-radius: var(--radius); padding: 12px 16px; margin-bottom: 18px;
    font-size: 12px; color: var(--red); font-family: var(--mono);
    border-left: 3px solid var(--red);
  }

  /* ── Misc ── */
  .empty-state { text-align: center; padding: 56px 24px; color: var(--text3); font-size: 13px; }
  .empty-state .icon { font-size: 42px; margin-bottom: 14px; }
  .empty-state p { color: var(--text2); margin-top: 6px; }

  .tag {
    display: inline-block; padding: 2px 9px;
    border-radius: 5px; font-size: 11px; font-family: var(--mono); font-weight: 500;
    background: var(--bg4); border: 1px solid var(--border2); color: var(--text2);
    white-space: nowrap;
  }

  .docs-link {
    display: inline-flex; align-items: center; gap: 4px;
    font-size: 11px; font-family: var(--mono); font-weight: 600;
    color: var(--accent); margin-top: 10px;
    padding: 4px 10px; border: 1px solid rgba(79,156,249,.3);
    border-radius: 5px; background: var(--blue-bg);
  }
  .docs-link:hover { background: var(--accent); color: #fff; text-decoration: none; }

  .filter-bar { display: flex; gap: 8px; align-items: center; margin-bottom: 16px; flex-wrap: wrap; }

  /* ── Scrollbar ── */
  ::-webkit-scrollbar { width: 5px; height: 5px; }
  ::-webkit-scrollbar-track { background: transparent; }
  ::-webkit-scrollbar-thumb { background: var(--border2); border-radius: 3px; }

  /* ── Stat row under chart ── */
  .chart-stats {
    display: flex; gap: 20px; margin-top: 14px;
    padding-top: 14px; border-top: 1px solid var(--border);
  }
  .chart-stat-item { text-align: center; flex: 1; }
  .chart-stat-val {
    font-size: 20px; font-weight: 700; font-family: var(--mono);
    display: block; line-height: 1;
  }
  .chart-stat-lbl { font-size: 10px; font-family: var(--mono); color: var(--text3); text-transform: uppercase; letter-spacing: .08em; margin-top: 4px; display: block; }

  /* ── Donut center ── */
  .donut-wrap { position: relative; }
  .donut-center {
    position: absolute; top: 50%; left: 50%;
    transform: translate(-50%, -50%);
    text-align: center; pointer-events: none;
  }
  .donut-center .val { font-size: 24px; font-weight: 700; font-family: var(--mono); color: var(--text); display: block; }
  .donut-center .lbl { font-size: 10px; font-family: var(--mono); color: var(--text3); text-transform: uppercase; letter-spacing: .08em; }

  /* Responsive */
  @media (max-width: 900px) {
    .charts-grid { grid-template-columns: 1fr; }
    .charts-grid-3 { grid-template-columns: 1fr; }
    .sidebar { display: none; }
  }
</style>
</head>
<body>
<div class="layout">

  <!-- ── Sidebar ── -->
  <aside class="sidebar">
    <div class="sidebar-logo">
      <div class="brand">
        <div class="logo-icon">🔭</div>
        <div class="name">OCP Monitor</div>
      </div>
      <div class="cluster">{{ cluster_name }}</div>
    </div>
    <nav>
      <div class="nav-section">Navigation</div>
      <a href="/" class="nav-item {% if page == 'home' %}active{% endif %}">
        <svg class="nav-icon" viewBox="0 0 20 20" fill="currentColor"><path d="M10.707 2.293a1 1 0 00-1.414 0l-7 7a1 1 0 001.414 1.414L4 10.414V17a1 1 0 001 1h2a1 1 0 001-1v-2a1 1 0 011-1h2a1 1 0 011 1v2a1 1 0 001 1h2a1 1 0 001-1v-6.586l.293.293a1 1 0 001.414-1.414l-7-7z"/></svg>
        Dashboard
      </a>
      <a href="/incidents" class="nav-item {% if page == 'incidents' %}active{% endif %}">
        <svg class="nav-icon" viewBox="0 0 20 20" fill="currentColor"><path d="M9 2a1 1 0 000 2h2a1 1 0 100-2H9z"/><path fill-rule="evenodd" d="M4 5a2 2 0 012-2 3 3 0 003 3h2a3 3 0 003-3 2 2 0 012 2v11a2 2 0 01-2 2H6a2 2 0 01-2-2V5zm3 4a1 1 0 000 2h.01a1 1 0 100-2H7zm3 0a1 1 0 000 2h3a1 1 0 100-2h-3zm-3 4a1 1 0 100 2h.01a1 1 0 100-2H7zm3 0a1 1 0 100 2h3a1 1 0 100-2h-3z" clip-rule="evenodd"/></svg>
        Knowledge Base
      </a>
      <a href="/api/docs" class="nav-item">
        <svg class="nav-icon" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M12.316 3.051a1 1 0 01.633 1.265l-4 12a1 1 0 11-1.898-.632l4-12a1 1 0 011.265-.633zM5.707 6.293a1 1 0 010 1.414L3.414 10l2.293 2.293a1 1 0 11-1.414 1.414l-3-3a1 1 0 010-1.414l3-3a1 1 0 011.414 0zm8.586 0a1 1 0 011.414 0l3 3a1 1 0 010 1.414l-3 3a1 1 0 11-1.414-1.414L16.586 10l-2.293-2.293a1 1 0 010-1.414z" clip-rule="evenodd"/></svg>
        API Docs
      </a>
    </nav>
    <div class="sidebar-footer">
      interval: {{ interval_minutes if interval_minutes is defined else '—' }}m<br>
      v1.0.0
    </div>
  </aside>

  <!-- ── Main ── -->
  <main class="main">

    <!-- ════════════════════════════════ HOME PAGE ════════════════════════════ -->
    {% if page == 'home' %}
    <div class="topbar">
      <span class="topbar-title">Monitoring Overview</span>
      <div class="topbar-right">
        <div class="topbar-live"><span class="live-dot"></span> LIVE</div>
        <span class="topbar-meta" id="last-refresh">—</span>
      </div>
    </div>

    <div class="content">

      <!-- Metric strip -->
      <div class="metrics-grid">
        <div class="metric-card {% if latest_status == 'HEALTHY' %}green{% elif latest_status == 'CRITICAL' %}red{% elif latest_status == 'WARNING' %}amber{% else %}blue{% endif %}">
          <div class="metric-accent"></div>
          <span class="metric-icon">{% if latest_status == 'HEALTHY' %}✅{% elif latest_status == 'CRITICAL' %}🔴{% elif latest_status == 'WARNING' %}🟡{% else %}❓{% endif %}</span>
          <div class="metric-label">Current Status</div>
          <div class="metric-value" style="font-size:20px;margin-top:4px;">{{ latest_status }}</div>
          <div class="metric-sub">{{ cluster_name }}</div>
        </div>
        <div class="metric-card blue">
          <div class="metric-accent"></div>
          <span class="metric-icon">📊</span>
          <div class="metric-label">Runs (24h)</div>
          <div class="metric-value">{{ total_24h }}</div>
          <div class="metric-sub">every {{ interval_minutes }}min</div>
        </div>
        <div class="metric-card red">
          <div class="metric-accent"></div>
          <span class="metric-icon">🚨</span>
          <div class="metric-label">Critical (24h)</div>
          <div class="metric-value">{{ critical_24h }}</div>
          <div class="metric-sub">immediate action</div>
        </div>
        <div class="metric-card amber">
          <div class="metric-accent"></div>
          <span class="metric-icon">⚠️</span>
          <div class="metric-label">Warnings (24h)</div>
          <div class="metric-value">{{ warning_24h }}</div>
          <div class="metric-sub">action needed</div>
        </div>
        <div class="metric-card green">
          <div class="metric-accent"></div>
          <span class="metric-icon">✅</span>
          <div class="metric-label">Healthy (24h)</div>
          <div class="metric-value">{{ healthy_24h }}</div>
          <div class="metric-sub">clean runs</div>
        </div>
        <div class="metric-card purple">
          <div class="metric-accent"></div>
          <span class="metric-icon">🧠</span>
          <div class="metric-label">KB Incidents</div>
          <div class="metric-value">{{ incident_count }}</div>
          <div class="metric-sub">{{ indexed_count }} indexed</div>
        </div>
      </div>

      <!-- Charts Row 1: Line chart + Donut -->
      <div class="charts-grid">

        <!-- Run Status Timeline (Line) -->
        <div class="chart-card">
          <div class="chart-title">
            Run Status — Last 20 Runs
            <span>timeline</span>
          </div>
          <div class="chart-wrap">
            <canvas id="timelineChart" height="110"></canvas>
          </div>
          <div class="chart-stats">
            <div class="chart-stat-item">
              <span class="chart-stat-val" style="color:var(--red)">{{ critical_24h }}</span>
              <span class="chart-stat-lbl">Critical</span>
            </div>
            <div class="chart-stat-item">
              <span class="chart-stat-val" style="color:var(--amber)">{{ warning_24h }}</span>
              <span class="chart-stat-lbl">Warning</span>
            </div>
            <div class="chart-stat-item">
              <span class="chart-stat-val" style="color:var(--green)">{{ healthy_24h }}</span>
              <span class="chart-stat-lbl">Healthy</span>
            </div>
            <div class="chart-stat-item">
              <span class="chart-stat-val" style="color:var(--accent)">{{ total_24h }}</span>
              <span class="chart-stat-lbl">Total</span>
            </div>
          </div>
        </div>

        <!-- Status Donut -->
        <div class="chart-card">
          <div class="chart-title">
            Status Distribution
            <span>24h</span>
          </div>
          <div class="donut-wrap" style="max-width:200px;margin:0 auto;">
            <canvas id="donutChart" height="200"></canvas>
            <div class="donut-center">
              <span class="val">{{ total_24h }}</span>
              <span class="lbl">runs</span>
            </div>
          </div>
        </div>

      </div>

      <!-- Charts Row 2: Bar + Failure rate + Duration -->
      <div class="charts-grid-3">

        <!-- Failure count per run (Bar) -->
        <div class="chart-card">
          <div class="chart-title">Failures Per Run <span>last 15</span></div>
          <div class="chart-wrap">
            <canvas id="failureBarChart" height="140"></canvas>
          </div>
        </div>

        <!-- Severity breakdown (Horizontal Bar) -->
        <div class="chart-card">
          <div class="chart-title">Severity Breakdown <span>24h</span></div>
          <div class="chart-wrap">
            <canvas id="severityChart" height="140"></canvas>
          </div>
        </div>

        <!-- Run duration (Area) -->
        <div class="chart-card">
          <div class="chart-title">Run Duration <span>seconds</span></div>
          <div class="chart-wrap">
            <canvas id="durationChart" height="140"></canvas>
          </div>
        </div>

      </div>

      <!-- Recent runs table -->
      <div class="section-header">
        <span class="section-title">
          <svg width="14" height="14" viewBox="0 0 20 20" fill="currentColor"><path d="M3 4a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1zm0 4a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1zm0 4a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1z"/></svg>
          Recent Runs
        </span>
        <span class="section-count">{{ runs|length }} shown</span>
      </div>

      {% if runs %}
      <table class="run-table">
        <thead>
          <tr>
            <th>Status</th>
            <th>Started</th>
            <th>Failures</th>
            <th>Duration</th>
            <th>Email</th>
            <th>Summary</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {% for run in runs %}
          <tr>
            <td>
              {% set s = run.status|lower %}
              <span class="badge badge-{{ s }}">
                <span class="badge-dot"></span>{{ run.status }}
              </span>
            </td>
            <td class="mono">{{ run.started_at[:19].replace('T',' ') if run.started_at else '—' }}</td>
            <td>
              {% if run.failure_count > 0 %}
                <span style="color:var(--red);font-family:var(--mono);font-weight:700;">{{ run.failure_count }}</span>
              {% else %}
                <span style="color:var(--green);font-family:var(--mono);font-weight:600;">0</span>
              {% endif %}
            </td>
            <td>
              <span class="dim">{{ run.duration_s }}s</span>
            </td>
            <td>
              {% if run.email_sent %}
                <span class="ok">✓ sent</span>
              {% else %}
                <span style="color:var(--text3);font-family:var(--mono);font-size:11px;">— no</span>
              {% endif %}
            </td>
            <td style="max-width:320px;color:var(--text2);font-size:12px;">
              {{ run.summary[:100] + '…' if run.summary|length > 100 else run.summary }}
            </td>
            <td>
              <a href="/run/{{ run.id }}" class="run-link">view →</a>
            </td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
      {% else %}
      <div class="empty-state">
        <div class="icon">📡</div>
        <p>No runs recorded yet. The scheduler will populate this once it fires.</p>
      </div>
      {% endif %}

    </div>

    <!-- ════════════════════════════ RUN DETAIL PAGE ══════════════════════════ -->
    {% elif page == 'run_detail' %}
    <div class="topbar">
      <span class="topbar-title">Run Detail — <span style="font-family:var(--mono);font-size:13px;color:var(--text2);">{{ run.id[:8] }}…</span></span>
      <a href="/" style="font-size:12px;color:var(--text3);font-family:var(--mono);">← Back</a>
    </div>

    <div class="content">

      <!-- Status hero -->
      {% set s = run.status|lower %}
      <div class="status-hero {{ s }}">
        <div class="status-indicator">
          {% if s == 'healthy' %}✓{% elif s == 'critical' %}✕{% elif s == 'warning' %}⚠{% else %}!{% endif %}
        </div>
        <div class="status-text">
          <div class="label">{{ run.status }}</div>
          <div class="summary">{{ run.summary }}</div>
        </div>
      </div>

      <!-- Run meta cards -->
      <div class="metrics-grid" style="margin-bottom:24px;">
        <div class="metric-card blue">
          <div class="metric-accent"></div>
          <div class="metric-label">Cluster</div>
          <div class="metric-value" style="font-size:15px;margin-top:6px;color:var(--text);">{{ run.cluster_name }}</div>
        </div>
        <div class="metric-card blue">
          <div class="metric-accent"></div>
          <div class="metric-label">Started</div>
          <div class="metric-value" style="font-size:13px;margin-top:6px;color:var(--text2);">{{ run.started_at[:19].replace('T',' ') if run.started_at else '—' }}</div>
        </div>
        <div class="metric-card {% if run.failure_count > 0 %}red{% else %}green{% endif %}">
          <div class="metric-accent"></div>
          <div class="metric-label">Failures</div>
          <div class="metric-value">{{ run.failure_count }}</div>
        </div>
        <div class="metric-card blue">
          <div class="metric-accent"></div>
          <div class="metric-label">Duration</div>
          <div class="metric-value">{{ run.duration_s }}<span style="font-size:15px;color:var(--text2);">s</span></div>
        </div>
      </div>

      <!-- Detail charts -->
      {% if failures %}
      <div class="charts-grid-3" style="margin-bottom:28px;">

        <!-- Severity donut -->
        <div class="chart-card">
          <div class="chart-title">Severity Split <span>this run</span></div>
          <div class="donut-wrap" style="max-width:180px;margin:0 auto;">
            <canvas id="detailSeverityChart" height="180"></canvas>
            <div class="donut-center">
              <span class="val">{{ failures|length }}</span>
              <span class="lbl">issues</span>
            </div>
          </div>
        </div>

        <!-- Component bar -->
        <div class="chart-card">
          <div class="chart-title">By Component <span>failures</span></div>
          <div class="chart-wrap">
            <canvas id="detailComponentChart" height="160"></canvas>
          </div>
        </div>

        <!-- Failure timeline -->
        <div class="chart-card">
          <div class="chart-title">Detection Time <span>sequence</span></div>
          <div class="chart-wrap">
            <canvas id="detailTimelineChart" height="160"></canvas>
          </div>
        </div>

      </div>
      {% endif %}

      {% if run.collection_errors %}
      <div class="collection-errors">
        ⚠ Collection errors in: {% for k,v in run.collection_errors.items() %}<strong>{{ k }}</strong>{% if not loop.last %}, {% endif %}{% endfor %}
      </div>
      {% endif %}

      <!-- Failures + Resolutions -->
      {% if failures %}
      <div class="section-header">
        <span class="section-title">Failures &amp; Resolutions</span>
        <span class="section-count">{{ failures|length }}</span>
      </div>

      <div class="failure-list">
        {% for f in failures %}
        <div class="failure-card">
          <div class="failure-header">
            <span class="failure-ref">{{ f.failure_ref }}</span>
            {% set sev = f.severity|lower %}
            {% if sev == 'critical' %}
            <span class="badge badge-critical"><span class="badge-dot"></span>CRITICAL</span>
            {% elif sev == 'warning' %}
            <span class="badge badge-warning"><span class="badge-dot"></span>WARNING</span>
            {% else %}
            <span class="badge badge-info"><span class="badge-dot"></span>INFO</span>
            {% endif %}
            <span class="failure-component">{{ f.component }}</span>
            <span class="failure-title">{{ f.resource_name }}</span>
            <span class="dim" style="font-size:11px;font-family:var(--mono);">{{ f.detected_at[:19].replace('T',' ') if f.detected_at else '' }}</span>
          </div>
          <div class="failure-body">
            <p class="failure-msg">{{ f.message }}</p>
            {% if f.resolution %}
            <div class="resolution-section">
              {% if f.resolution.root_cause %}
              <div style="margin-bottom:14px;">
                <div class="resolution-label">Root Cause</div>
                <p style="font-size:13px;color:var(--text2);line-height:1.6;">{{ f.resolution.root_cause }}</p>
              </div>
              {% endif %}
              {% if f.resolution.steps %}
              <div style="margin-bottom:14px;">
                <div class="resolution-label">Resolution Steps</div>
                <ol class="step-list">
                  {% for step in f.resolution.steps %}
                  <li>{{ step }}</li>
                  {% endfor %}
                </ol>
              </div>
              {% endif %}
              {% if f.resolution.commands %}
              <div>
                <div class="resolution-label">Commands</div>
                <div class="cmd-block">{% for cmd in f.resolution.commands %}<span class="cmd-prompt">$ </span>{{ cmd }}
{% endfor %}</div>
              </div>
              {% endif %}
              {% if f.resolution.docs_ref %}
              <a href="{{ f.resolution.docs_ref }}" target="_blank" class="docs-link">📖 OpenShift Docs →</a>
              {% endif %}
            </div>
            {% endif %}
          </div>
        </div>
        {% endfor %}
      </div>

      {% else %}
      <div class="empty-state">
        <div class="icon">✅</div>
        <p>No failures detected in this run. Cluster is healthy.</p>
      </div>
      {% endif %}

      <!-- Raw snapshot -->
      {% if raw %}
      <div class="section-header" style="margin-top:36px;">
        <span class="section-title">Raw Snapshot</span>
      </div>
      <div class="data-grid">
        {% if raw.nodes %}
        <div class="data-panel">
          <div class="data-panel-header">Nodes <span>{{ raw.nodes|length }}</span></div>
          <div class="data-panel-body">
            <table class="mini-table">
              {% for n in raw.nodes[:20] %}
              <tr>
                <td class="k">{{ n.name|truncate(20,true,'…') if n.name else '?' }}</td>
                <td><span class="{% if n.ready %}ok{% else %}crit{% endif %}">{% if n.ready %}✓ Ready{% else %}✕ NotReady{% endif %}</span> <span class="tag" style="margin-left:4px;">{{ n.role or '—' }}</span></td>
              </tr>
              {% endfor %}
            </table>
          </div>
        </div>
        {% endif %}
        {% if raw.operators %}
        <div class="data-panel">
          <div class="data-panel-header">Operators <span>{{ raw.operators|length }}</span></div>
          <div class="data-panel-body">
            <table class="mini-table">
              {% for op in raw.operators[:20] %}
              <tr>
                <td class="k">{{ op.name|truncate(22,true,'…') if op.name else '?' }}</td>
                <td>{% if op.available %}<span class="ok">✓</span>{% else %}<span class="crit">✕</span>{% endif %}{% if op.degraded %}<span class="crit"> DEG</span>{% endif %}</td>
              </tr>
              {% endfor %}
            </table>
          </div>
        </div>
        {% endif %}
        {% if raw.pods %}
        <div class="data-panel">
          <div class="data-panel-header">Failing Pods <span>{{ raw.pods|length }}</span></div>
          <div class="data-panel-body">
            <table class="mini-table">
              {% for pod in raw.pods[:20] %}
              <tr>
                <td class="k">{{ pod.name|truncate(22,true,'…') if pod.name else '?' }}</td>
                <td><span class="crit">{{ pod.phase or '—' }}</span></td>
              </tr>
              {% endfor %}
            </table>
          </div>
        </div>
        {% endif %}
        {% if raw.certs %}
        <div class="data-panel">
          <div class="data-panel-header">Expiring Certs <span>{{ raw.certs|length }}</span></div>
          <div class="data-panel-body">
            <table class="mini-table">
              {% for cert in raw.certs %}
              <tr>
                <td class="k">{{ cert.name|truncate(20,true,'…') if cert.name else '?' }}</td>
                <td><span class="{% if cert.days_remaining <= 7 %}crit{% elif cert.days_remaining <= 14 %}warn{% else %}ok{% endif %}">{{ cert.days_remaining }}d</span></td>
              </tr>
              {% endfor %}
            </table>
          </div>
        </div>
        {% endif %}
        {% if raw.pvcs %}
        <div class="data-panel">
          <div class="data-panel-header">PVC Issues <span>{{ raw.pvcs|length }}</span></div>
          <div class="data-panel-body">
            <table class="mini-table">
              {% for pvc in raw.pvcs %}
              <tr>
                <td class="k">{{ pvc.name|truncate(20,true,'…') if pvc.name else '?' }}</td>
                <td><span class="warn">{{ pvc.phase or pvc.status or '—' }}</span></td>
              </tr>
              {% endfor %}
            </table>
          </div>
        </div>
        {% endif %}
      </div>
      {% endif %}

    </div>

    <!-- ═══════════════════════════ INCIDENTS PAGE ════════════════════════════ -->
    {% elif page == 'incidents' %}
    <div class="topbar">
      <span class="topbar-title">Knowledge Base</span>
      <span class="topbar-meta">{{ total }} incidents · {{ indexed_count if indexed_count is defined else '—' }} indexed</span>
    </div>

    <div class="content">
      <div class="section-header" style="margin-top:0;">
        <span class="section-title">Add Incident</span>
      </div>
      <div class="form-card">
        <form method="POST" action="/incidents">
          <div class="form-row triple">
            <div class="form-group">
              <label>Incident ID *</label>
              <input class="form-control" name="incident_id" placeholder="INC-2024-0042" required>
            </div>
            <div class="form-group">
              <label>Component *</label>
              <select class="form-control" name="component" required>
                <option value="">— select —</option>
                <option>nodes</option><option>operators</option><option>mcpools</option>
                <option>etcd</option><option>pvcs</option><option>pods</option>
                <option>certs</option><option>cp4i</option>
              </select>
            </div>
            <div class="form-group">
              <label>Severity *</label>
              <select class="form-control" name="severity" required>
                <option value="">— select —</option>
                <option>CRITICAL</option><option>WARNING</option><option>INFO</option>
              </select>
            </div>
          </div>
          <div class="form-row">
            <div class="form-group">
              <label>Title *</label>
              <input class="form-control" name="title" placeholder="Short descriptive title" required>
            </div>
            <div class="form-group">
              <label>Occurred At</label>
              <input class="form-control" name="occurred_at" type="datetime-local">
            </div>
          </div>
          <div class="form-row full">
            <div class="form-group">
              <label>Description *</label>
              <textarea class="form-control" name="description" placeholder="Describe the incident — this is what the RAG system embeds and searches" required></textarea>
            </div>
          </div>
          <div class="form-row full">
            <div class="form-group">
              <label>Root Cause</label>
              <textarea class="form-control" name="root_cause" placeholder="What caused it?" style="min-height:60px;"></textarea>
            </div>
          </div>
          <button type="submit" class="btn btn-primary">+ Add to Knowledge Base</button>
        </form>
      </div>

      <div class="section-header">
        <span class="section-title">All Incidents</span>
        <span class="section-count">{{ total }}</span>
      </div>
      <div class="filter-bar">
        {% for comp in components %}
        <a href="/incidents?component={{ comp }}" class="page-btn {% if component_filter == comp %}active{% endif %}">{{ comp }}</a>
        {% endfor %}
        {% if component_filter %}
        <a href="/incidents" class="page-btn">clear ×</a>
        {% endif %}
      </div>

      {% if incidents %}
      <table class="incident-table">
        <thead>
          <tr><th>ID</th><th>Title</th><th>Component</th><th>Severity</th><th>Indexed</th><th>Occurred</th></tr>
        </thead>
        <tbody>
          {% for inc in incidents %}
          <tr>
            <td style="font-family:var(--mono);font-size:11px;color:var(--text2);white-space:nowrap;">{{ inc.incident_id }}</td>
            <td style="max-width:320px;">
              <div style="font-size:13px;color:var(--text);font-weight:500;">{{ inc.title }}</div>
              <div style="font-size:11px;color:var(--text3);margin-top:2px;">{{ inc.description }}</div>
            </td>
            <td><span class="tag">{{ inc.component }}</span></td>
            <td>
              {% set sev = inc.severity|lower if inc.severity else '' %}
              {% if sev == 'critical' %}<span class="badge badge-critical"><span class="badge-dot"></span>CRITICAL</span>
              {% elif sev == 'warning' %}<span class="badge badge-warning"><span class="badge-dot"></span>WARNING</span>
              {% else %}<span class="badge badge-info"><span class="badge-dot"></span>{{ inc.severity or 'INFO' }}</span>
              {% endif %}
            </td>
            <td>
              <span class="indexed-dot {% if inc.indexed %}yes{% else %}no{% endif %}"></span>
              <span style="font-size:11px;font-family:var(--mono);color:var(--text3);">{% if inc.indexed %}yes{% else %}no{% endif %}</span>
            </td>
            <td style="font-family:var(--mono);font-size:11px;color:var(--text3);white-space:nowrap;">{{ inc.occurred_at or '—' }}</td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
      <div class="pagination">
        <a href="/incidents?page={{ current_page - 1 }}{% if component_filter %}&component={{ component_filter }}{% endif %}" class="page-btn {% if current_page <= 1 %}disabled{% endif %}">← prev</a>
        <span style="font-size:12px;font-family:var(--mono);color:var(--text3);">{{ current_page }} / {{ total_pages }}</span>
        <a href="/incidents?page={{ current_page + 1 }}{% if component_filter %}&component={{ component_filter }}{% endif %}" class="page-btn {% if current_page >= total_pages %}disabled{% endif %}">next →</a>
      </div>
      {% else %}
      <div class="empty-state">
        <div class="icon">📚</div>
        <p>No incidents yet. Add one above to seed the RAG pipeline.</p>
      </div>
      {% endif %}
    </div>
    {% endif %}

  </main>
</div>

<script>
// ── Chart.js global defaults ──────────────────────────────────────────────────
Chart.defaults.color = '#9ab0cc';
Chart.defaults.borderColor = '#1f2d47';
Chart.defaults.font.family = "'JetBrains Mono', monospace";
Chart.defaults.font.size = 11;
Chart.defaults.plugins.legend.display = false;
Chart.defaults.plugins.tooltip.backgroundColor = '#0d1323';
Chart.defaults.plugins.tooltip.borderColor = '#2a3d5e';
Chart.defaults.plugins.tooltip.borderWidth = 1;
Chart.defaults.plugins.tooltip.titleColor = '#e8eef8';
Chart.defaults.plugins.tooltip.bodyColor = '#9ab0cc';
Chart.defaults.plugins.tooltip.padding = 10;

// ── Live clock ────────────────────────────────────────────────────────────────
function updateClock() {
  const el = document.getElementById('last-refresh');
  if (el) el.textContent = new Date().toISOString().slice(0,19).replace('T',' ') + ' UTC';
}
updateClock();
setInterval(updateClock, 1000);

// ── Collect run data from Jinja (Home page only) ──────────────────────────────
{% if page == 'home' and runs %}
const runsData = {{ runs | tojson }};

// ── 1. Timeline Line Chart ────────────────────────────────────────────────────
(function() {
  const last20 = runsData.slice(0, 20).reverse();
  const labels = last20.map((r, i) => {
    const d = r.started_at ? r.started_at.slice(11, 16) : i;
    return d;
  });
  const statusToNum = { CRITICAL: 3, WARNING: 2, HEALTHY: 1, ERROR: 2.5 };
  const colors = last20.map(r => {
    if (r.status === 'CRITICAL') return '#f87171';
    if (r.status === 'WARNING')  return '#fbbf24';
    if (r.status === 'HEALTHY')  return '#22d3a0';
    return '#a78bfa';
  });

  const ctx = document.getElementById('timelineChart');
  if (!ctx) return;
  new Chart(ctx, {
    type: 'line',
    data: {
      labels,
      datasets: [{
        data: last20.map(r => statusToNum[r.status] || 1),
        borderColor: '#4f9cf9',
        backgroundColor: 'rgba(79,156,249,.08)',
        pointBackgroundColor: colors,
        pointBorderColor: colors,
        pointRadius: 5,
        pointHoverRadius: 7,
        borderWidth: 2,
        fill: true,
        tension: 0.35,
      }]
    },
    options: {
      responsive: true,
      scales: {
        y: {
          min: 0, max: 4,
          ticks: {
            stepSize: 1,
            callback: v => ({ 1:'HEALTHY', 2:'WARNING', 2.5:'ERROR', 3:'CRITICAL' }[v] || '')
          },
          grid: { color: '#1f2d47' }
        },
        x: { grid: { display: false }, ticks: { maxRotation: 0, maxTicksLimit: 10 } }
      },
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: ctx => {
              const r = last20[ctx.dataIndex];
              return ` ${r.status} — ${r.failure_count} failure(s)`;
            }
          }
        }
      }
    }
  });
})();

// ── 2. Donut Chart ────────────────────────────────────────────────────────────
(function() {
  const critical = {{ critical_24h }};
  const warning  = {{ warning_24h }};
  const healthy  = {{ healthy_24h }};
  const total    = {{ total_24h }};
  const error    = Math.max(0, total - critical - warning - healthy);

  const ctx = document.getElementById('donutChart');
  if (!ctx) return;
  new Chart(ctx, {
    type: 'doughnut',
    data: {
      labels: ['Critical','Warning','Healthy','Error'],
      datasets: [{
        data: [critical, warning, healthy, error],
        backgroundColor: ['#f87171','#fbbf24','#22d3a0','#a78bfa'],
        borderColor: '#0d1323',
        borderWidth: 3,
        hoverOffset: 6,
      }]
    },
    options: {
      cutout: '68%',
      plugins: {
        legend: { display: true, position: 'bottom',
          labels: { padding: 14, usePointStyle: true, pointStyle: 'circle', boxWidth: 7, color: '#9ab0cc' }
        },
        tooltip: { callbacks: { label: ctx => ` ${ctx.label}: ${ctx.raw}` } }
      }
    }
  });
})();

// ── 3. Failure Bar Chart ──────────────────────────────────────────────────────
(function() {
  const last15 = runsData.slice(0, 15).reverse();
  const labels  = last15.map((r, i) => r.started_at ? r.started_at.slice(11,16) : `#${i}`);
  const vals    = last15.map(r => r.failure_count || 0);
  const colors  = last15.map(r => r.failure_count > 0 ? 'rgba(248,113,113,.75)' : 'rgba(34,211,160,.5)');
  const borders = last15.map(r => r.failure_count > 0 ? '#f87171' : '#22d3a0');

  const ctx = document.getElementById('failureBarChart');
  if (!ctx) return;
  new Chart(ctx, {
    type: 'bar',
    data: {
      labels,
      datasets: [{
        data: vals,
        backgroundColor: colors,
        borderColor: borders,
        borderWidth: 1,
        borderRadius: 4,
      }]
    },
    options: {
      responsive: true,
      scales: {
        y: { beginAtZero: true, ticks: { stepSize: 1 }, grid: { color: '#1f2d47' } },
        x: { grid: { display: false }, ticks: { maxRotation: 45 } }
      },
      plugins: { tooltip: { callbacks: { label: ctx => ` ${ctx.raw} failure(s)` } } }
    }
  });
})();

// ── 4. Severity Horizontal Bar ────────────────────────────────────────────────
(function() {
  const critical = {{ critical_24h }};
  const warning  = {{ warning_24h }};
  const healthy  = {{ healthy_24h }};

  const ctx = document.getElementById('severityChart');
  if (!ctx) return;
  new Chart(ctx, {
    type: 'bar',
    data: {
      labels: ['Critical','Warning','Healthy'],
      datasets: [{
        data: [critical, warning, healthy],
        backgroundColor: ['rgba(248,113,113,.7)','rgba(251,191,36,.7)','rgba(34,211,160,.7)'],
        borderColor: ['#f87171','#fbbf24','#22d3a0'],
        borderWidth: 1,
        borderRadius: 4,
      }]
    },
    options: {
      indexAxis: 'y',
      responsive: true,
      scales: {
        x: { beginAtZero: true, ticks: { stepSize: 1 }, grid: { color: '#1f2d47' } },
        y: { grid: { display: false } }
      },
      plugins: { tooltip: { callbacks: { label: ctx => ` ${ctx.raw} runs` } } }
    }
  });
})();

// ── 5. Duration Area Chart ────────────────────────────────────────────────────
(function() {
  const last15 = runsData.slice(0, 15).reverse();
  const labels  = last15.map((r, i) => r.started_at ? r.started_at.slice(11,16) : `#${i}`);
  const vals    = last15.map(r => r.duration_s || 0);

  const ctx = document.getElementById('durationChart');
  if (!ctx) return;
  new Chart(ctx, {
    type: 'line',
    data: {
      labels,
      datasets: [{
        data: vals,
        borderColor: '#a78bfa',
        backgroundColor: 'rgba(167,139,250,.1)',
        borderWidth: 2,
        pointRadius: 3,
        pointBackgroundColor: '#a78bfa',
        fill: true,
        tension: 0.4,
      }]
    },
    options: {
      responsive: true,
      scales: {
        y: { beginAtZero: true, grid: { color: '#1f2d47' }, ticks: { callback: v => `${v}s` } },
        x: { grid: { display: false }, ticks: { maxRotation: 45 } }
      },
      plugins: { tooltip: { callbacks: { label: ctx => ` ${ctx.raw}s` } } }
    }
  });
})();

{% endif %}

// ── Run detail page charts ────────────────────────────────────────────────────
{% if page == 'run_detail' and failures %}
const failuresData = {{ failures | tojson }};

// ── Detail Severity Donut ─────────────────────────────────────────────────────
(function() {
  const critical = failuresData.filter(f => f.severity === 'CRITICAL').length;
  const warning  = failuresData.filter(f => f.severity === 'WARNING').length;
  const info     = failuresData.filter(f => f.severity === 'INFO').length;

  const ctx = document.getElementById('detailSeverityChart');
  if (!ctx) return;
  new Chart(ctx, {
    type: 'doughnut',
    data: {
      labels: ['Critical','Warning','Info'],
      datasets: [{
        data: [critical, warning, info],
        backgroundColor: ['#f87171','#fbbf24','#4f9cf9'],
        borderColor: '#0d1323', borderWidth: 3, hoverOffset: 5,
      }]
    },
    options: {
      cutout: '65%',
      plugins: {
        legend: { display: true, position: 'bottom',
          labels: { padding: 12, usePointStyle: true, pointStyle: 'circle', boxWidth: 7, color: '#9ab0cc' }
        }
      }
    }
  });
})();

// ── Detail Component Bar ──────────────────────────────────────────────────────
(function() {
  const compCount = {};
  failuresData.forEach(f => { compCount[f.component] = (compCount[f.component] || 0) + 1; });
  const labels = Object.keys(compCount);
  const vals   = Object.values(compCount);

  const ctx = document.getElementById('detailComponentChart');
  if (!ctx) return;
  new Chart(ctx, {
    type: 'bar',
    data: {
      labels,
      datasets: [{
        data: vals,
        backgroundColor: 'rgba(79,156,249,.65)',
        borderColor: '#4f9cf9',
        borderWidth: 1, borderRadius: 4,
      }]
    },
    options: {
      indexAxis: 'y',
      responsive: true,
      scales: {
        x: { beginAtZero: true, ticks: { stepSize: 1 }, grid: { color: '#1f2d47' } },
        y: { grid: { display: false } }
      }
    }
  });
})();

// ── Detection sequence (scatter-style) ───────────────────────────────────────
(function() {
  const labels = failuresData.map((f, i) => f.failure_ref || `F-${String(i+1).padStart(3,'0')}`);
  const colors = failuresData.map(f =>
    f.severity === 'CRITICAL' ? '#f87171' :
    f.severity === 'WARNING'  ? '#fbbf24' : '#4f9cf9'
  );

  const ctx = document.getElementById('detailTimelineChart');
  if (!ctx) return;
  new Chart(ctx, {
    type: 'bar',
    data: {
      labels,
      datasets: [{
        data: failuresData.map((_, i) => i + 1),
        backgroundColor: colors.map(c => c + 'aa'),
        borderColor: colors,
        borderWidth: 1, borderRadius: 4,
      }]
    },
    options: {
      responsive: true,
      scales: {
        y: { beginAtZero: true, ticks: { stepSize: 1, callback: v => `#${v}` }, grid: { color: '#1f2d47' } },
        x: { grid: { display: false } }
      },
      plugins: {
        tooltip: { callbacks: { label: ctx => ` ${failuresData[ctx.dataIndex].severity}` } }
      }
    }
  });
})();
{% endif %}
</script>
</body>
</html>
