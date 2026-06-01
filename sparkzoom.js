// sparkzoom.js — shared sparkline zoom modal for Allo Health demand dashboard
// Click any .spark-wrap element to zoom into actual week-by-week values
// Supports optional second dataset via:
//   data-sparkvals2   = JSON array of second series values
//   data-sparkcolor2  = hex color for second series
//   data-sparklabel2  = label for second series (shown in legend + table)
//   data-sparkylabel  = y-axis label override (defaults to title)
//   data-sparkxlabel  = x-axis label override (default "Week")
(function () {
  'use strict';
  const MODAL_ID = 'sparkZoomModal';

  function injectStyles() {
    if (document.getElementById('sparkZoomCSS')) return;
    const s = document.createElement('style');
    s.id = 'sparkZoomCSS';
    s.textContent = `
      .spark-wrap{cursor:zoom-in;display:inline-block;transition:opacity .15s;}
      .spark-wrap:hover{opacity:.75;}
      .spark-wrap svg,.spark-wrap canvas{pointer-events:none;}
      #${MODAL_ID}{
        position:fixed;inset:0;z-index:9999;
        background:rgba(15,23,42,.65);
        backdrop-filter:blur(6px);-webkit-backdrop-filter:blur(6px);
        display:none;align-items:center;justify-content:center;
      }
      #${MODAL_ID}.open{display:flex;}
      .sz-box{
        background:#fff;border-radius:18px;padding:24px 28px;
        width:min(660px,95vw);max-height:92vh;overflow-y:auto;
        box-shadow:0 24px 80px rgba(15,23,42,.28);
        animation:szIn .17s ease-out;
      }
      @keyframes szIn{from{transform:translateY(6px) scale(.97);opacity:0;}to{transform:none;opacity:1;}}
      .sz-hint{font-size:10px;color:#94a3b8;text-align:center;margin-top:10px;}
    `;
    document.head.appendChild(s);
  }

  function injectModal() {
    if (document.getElementById(MODAL_ID)) return;
    const div = document.createElement('div');
    div.id = MODAL_ID;
    div.innerHTML = `
      <div class="sz-box">
        <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:14px;">
          <div>
            <div id="szTitle" style="font-size:15px;font-weight:700;color:#0f172a;line-height:1.3;"></div>
            <div id="szSub"   style="font-size:11px;color:#64748b;margin-top:2px;"></div>
          </div>
          <button id="szClose" style="flex-shrink:0;border:none;background:#f1f5f9;border-radius:9px;width:32px;height:32px;cursor:pointer;font-size:15px;color:#64748b;display:flex;align-items:center;justify-content:center;margin-left:12px;">✕</button>
        </div>
        <!-- Axis label row: y-label left, x-label right -->
        <div style="display:flex;justify-content:space-between;align-items:center;padding:0 4px;margin-bottom:4px;">
          <div id="szYLabel" style="font-size:10px;font-weight:700;color:#94a3b8;text-transform:uppercase;letter-spacing:.05em;"></div>
          <div id="szXLabel" style="font-size:10px;font-weight:700;color:#94a3b8;text-transform:uppercase;letter-spacing:.05em;"></div>
        </div>
        <div style="height:240px;position:relative;"><canvas id="szCanvas"></canvas></div>
        <!-- Legend (shown only for dual-series) -->
        <div id="szLegend" style="display:none;gap:16px;flex-wrap:wrap;margin-top:10px;padding:8px 12px;background:#f8fafc;border-radius:8px;font-size:11px;font-weight:600;align-items:center;"></div>
        <div id="szTable" style="margin-top:16px;"></div>
        <div class="sz-hint">Click any sparkline throughout the dashboard to zoom in · Esc to close</div>
      </div>`;
    document.body.appendChild(div);
    div.addEventListener('click', e => { if (e.target === div) closeZoom(); });
    document.getElementById('szClose').addEventListener('click', closeZoom);
  }

  let _chart = null;

  function fmtVal(v, fmt) {
    if (v == null) return '—';
    if (fmt === 'pct') return v.toFixed(1) + '%';
    if (fmt === 'inr') return '₹' + Math.round(v).toLocaleString('en-IN');
    if (fmt === 'k')   return v >= 1000 ? (v / 1000).toFixed(1) + 'k' : Math.round(v).toString();
    if (typeof v === 'number') return Number.isInteger(v) ? v.toLocaleString('en-IN') : v.toFixed(1);
    return String(v);
  }

  function wowCell(v, prev) {
    if (v == null || prev == null || prev === 0) return '<span style="color:#94a3b8;font-size:10px;">—</span>';
    const pct = (v - prev) / Math.abs(prev) * 100;
    const clr = Math.abs(pct) < 1 ? '#94a3b8' : pct > 0 ? '#059669' : '#dc2626';
    return `<span style="color:${clr};font-size:10px;font-weight:600;">${pct > 0 ? '▲' : '▼'} ${Math.abs(pct).toFixed(1)}%</span>`;
  }

  function openZoom(el) {
    let vals, labels, vals2;

    const title  = el.getAttribute('data-sparktitle')  || 'Metric';
    const color  = el.getAttribute('data-sparkcolor')  || '#6366f1';
    const fmt    = el.getAttribute('data-sparkfmt')    || '';
    const sub    = el.getAttribute('data-sparksub')    || '';
    // Axis labels — fall back to sensible defaults
    const yLabel = el.getAttribute('data-sparkylabel') || title;
    const xLabel = el.getAttribute('data-sparkxlabel') || 'Week';
    // Optional second series
    const color2 = el.getAttribute('data-sparkcolor2') || '#94a3b8';
    const label2 = el.getAttribute('data-sparklabel2') || 'Comparison';

    try { vals   = JSON.parse(el.getAttribute('data-sparkvals')   || '[]'); } catch (e) { vals = []; }
    try { labels = JSON.parse(el.getAttribute('data-sparklabels') || 'null'); } catch (e) { labels = null; }
    try { vals2  = JSON.parse(el.getAttribute('data-sparkvals2')  || 'null'); } catch (e) { vals2 = null; }
    if (!Array.isArray(labels)) labels = vals.map((_, i) => `Wk ${i + 1}`);

    const hasDual = Array.isArray(vals2) && vals2.length > 0;

    // Populate header
    document.getElementById('szTitle').textContent = title;
    document.getElementById('szSub').textContent   = sub;
    document.getElementById('szYLabel').textContent = '↑ ' + yLabel;
    document.getElementById('szXLabel').textContent = xLabel + ' →';

    // Destroy previous chart
    if (_chart) { try { _chart.destroy(); } catch (e) {} _chart = null; }

    // Build datasets
    const datasets = [];
    if (hasDual) {
      // Second series (total / comparison) — dashed, in the back
      datasets.push({
        label: label2,
        data: vals2,
        borderColor: color2,
        backgroundColor: color2 + '20',
        fill: true,
        tension: 0.35,
        pointRadius: 3,
        pointHoverRadius: 5,
        pointBackgroundColor: color2,
        borderWidth: 1.5,
        borderDash: [5, 3],
        spanGaps: true,
        order: 2,
      });
    }
    // Primary series (category / main metric) — solid, on top
    datasets.push({
      label: title,
      data: vals,
      borderColor: color,
      backgroundColor: color + (hasDual ? '28' : '18'),
      fill: !hasDual,
      tension: 0.35,
      pointRadius: hasDual ? 4 : 5,
      pointHoverRadius: 7,
      pointBackgroundColor: color,
      borderWidth: 2.5,
      spanGaps: true,
      order: 1,
    });

    const ctx = document.getElementById('szCanvas').getContext('2d');
    _chart = new Chart(ctx, {
      type: 'line',
      data: { labels, datasets },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: '#0f172a',
            titleColor: '#94a3b8',
            bodyColor: '#f8fafc',
            padding: 12,
            callbacks: {
              label: c => {
                // datasets[0] is the second series if hasDual, else it's the primary
                const isSecondary = hasDual && c.datasetIndex === 0;
                const lbl = isSecondary ? label2 : title;
                const fmtKey = isSecondary ? '' : fmt;
                return ` ${lbl}: ${fmtVal(c.raw, fmtKey)}`;
              }
            }
          }
        },
        scales: {
          x: {
            grid: { display: false },
            ticks: { font: { size: 10 }, maxRotation: 30 },
            title: {
              display: true,
              text: xLabel,
              font: { size: 10, weight: '600' },
              color: '#94a3b8',
              padding: { top: 6 },
            }
          },
          y: {
            grid: { color: '#f1f5f9' },
            ticks: { font: { size: 10 }, callback: v => fmtVal(v, fmt) },
            beginAtZero: false,
            title: {
              display: true,
              text: yLabel,
              font: { size: 10, weight: '600' },
              color: '#94a3b8',
              padding: { bottom: 6 },
            }
          }
        }
      }
    });

    // Legend (only when dual-series)
    const legendEl = document.getElementById('szLegend');
    if (hasDual) {
      legendEl.style.display = 'flex';
      legendEl.innerHTML = `
        <span style="display:flex;align-items:center;gap:6px;">
          <span style="width:22px;height:3px;background:${color};border-radius:2px;display:inline-block;"></span>
          <span style="color:#0f172a;">${title}</span>
        </span>
        <span style="display:flex;align-items:center;gap:6px;">
          <span style="width:22px;height:0;border-top:2px dashed ${color2};display:inline-block;"></span>
          <span style="color:#64748b;">${label2} (dashed)</span>
        </span>`;
    } else {
      legendEl.style.display = 'none';
    }

    // ── Week-by-week data table ─────────────────────────────────────────────
    const thSt = 'padding:5px 10px;font-size:10px;text-transform:uppercase;letter-spacing:.05em;color:#94a3b8;font-weight:600;border-bottom:1px solid #f1f5f9;white-space:nowrap;';
    const extraTh = hasDual
      ? `<th style="${thSt}text-align:right;">${label2}</th><th style="${thSt}text-align:right;">WoW</th>`
      : '';

    const rows = vals.map((v, i) => {
      const prev  = i > 0 ? vals[i - 1]  : null;
      const v2    = hasDual ? (vals2[i]  ?? null) : null;
      const prev2 = hasDual && i > 0 ? (vals2[i - 1] ?? null) : null;
      const hl    = i === vals.length - 1 ? 'background:#f8fafc;font-weight:600;' : '';
      const extraTd = hasDual
        ? `<td style="padding:5px 10px;font-size:12px;text-align:right;color:#475569;">${fmtVal(v2, '')}</td><td style="padding:5px 10px;text-align:right;">${wowCell(v2, prev2)}</td>`
        : '';
      return `<tr style="border-bottom:1px solid #f8fafc;${hl}">
        <td style="padding:5px 10px;font-size:11px;color:#64748b;white-space:nowrap;">${labels[i] || ''}</td>
        <td style="padding:5px 10px;font-size:12px;font-weight:700;text-align:right;color:#0f172a;">${fmtVal(v, fmt)}</td>
        <td style="padding:5px 10px;text-align:right;">${wowCell(v, prev)}</td>
        ${extraTd}
      </tr>`;
    }).join('');

    document.getElementById('szTable').innerHTML = `
      <div style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.06em;color:#94a3b8;margin-bottom:8px;">Week-by-Week Detail</div>
      <div style="max-height:200px;overflow-y:auto;">
        <table style="width:100%;border-collapse:collapse;">
          <thead style="position:sticky;top:0;background:#fff;z-index:1;">
            <tr>
              <th style="${thSt}text-align:left;">Week</th>
              <th style="${thSt}text-align:right;">${title}</th>
              <th style="${thSt}text-align:right;">WoW</th>
              ${extraTh}
            </tr>
          </thead>
          <tbody>${rows}</tbody>
        </table>
      </div>`;

    document.getElementById(MODAL_ID).classList.add('open');
  }

  function closeZoom() {
    document.getElementById(MODAL_ID)?.classList.remove('open');
  }

  function init() {
    injectStyles();
    injectModal();
    document.addEventListener('click', e => {
      const wrap = e.target.closest?.('.spark-wrap');
      if (wrap) { e.preventDefault(); openZoom(wrap); }
    });
    document.addEventListener('keydown', e => {
      if (e.key === 'Escape') closeZoom();
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
