// sparkzoom.js — shared sparkline zoom modal for Allo Health demand dashboard
// Click any .spark-wrap element to zoom into actual week-by-week values
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
        width:min(580px,93vw);max-height:90vh;overflow-y:auto;
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
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:18px;">
          <div>
            <div id="szTitle" style="font-size:15px;font-weight:700;color:#0f172a;line-height:1.3;"></div>
            <div id="szSub"   style="font-size:11px;color:#64748b;margin-top:2px;"></div>
          </div>
          <button id="szClose" style="flex-shrink:0;border:none;background:#f1f5f9;border-radius:9px;width:32px;height:32px;cursor:pointer;font-size:15px;color:#64748b;display:flex;align-items:center;justify-content:center;margin-left:12px;">✕</button>
        </div>
        <div style="height:220px;position:relative;"><canvas id="szCanvas"></canvas></div>
        <div id="szTable" style="margin-top:16px;"></div>
        <div class="sz-hint">Click any sparkline throughout the dashboard to zoom</div>
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

  function openZoom(el) {
    let vals, labels;
    const title  = el.getAttribute('data-sparktitle')  || 'Metric';
    const color  = el.getAttribute('data-sparkcolor')  || '#6366f1';
    const fmt    = el.getAttribute('data-sparkfmt')    || '';
    const sub    = el.getAttribute('data-sparksub')    || '';

    try { vals   = JSON.parse(el.getAttribute('data-sparkvals')   || '[]'); } catch (e) { vals = []; }
    try { labels = JSON.parse(el.getAttribute('data-sparklabels') || 'null'); } catch (e) { labels = null; }
    if (!Array.isArray(labels)) labels = vals.map((_, i) => `Wk ${i + 1}`);

    document.getElementById('szTitle').textContent = title;
    document.getElementById('szSub').textContent   = sub;

    if (_chart) { try { _chart.destroy(); } catch (e) {} _chart = null; }

    const ctx = document.getElementById('szCanvas').getContext('2d');
    _chart = new Chart(ctx, {
      type: 'line',
      data: {
        labels,
        datasets: [{
          label: title,
          data: vals,
          borderColor: color,
          backgroundColor: color + '18',
          fill: true,
          tension: 0.35,
          pointRadius: 5,
          pointHoverRadius: 7,
          pointBackgroundColor: color,
          borderWidth: 2.5,
          spanGaps: true,
        }]
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: '#0f172a', titleColor: '#94a3b8', bodyColor: '#f8fafc', padding: 12,
            callbacks: { label: c => ` ${title}: ${fmtVal(c.raw, fmt)}` }
          }
        },
        scales: {
          x: { grid: { display: false }, ticks: { font: { size: 10 }, maxRotation: 0 } },
          y: {
            grid: { color: '#f1f5f9' },
            ticks: { font: { size: 10 }, callback: v => fmtVal(v, fmt) },
            beginAtZero: false
          }
        }
      }
    });

    // Week-by-week table
    const rows = vals.map((v, i) => {
      const prev = i > 0 ? vals[i - 1] : null;
      let wowHtml = '<span style="color:#94a3b8;font-size:10px;">—</span>';
      if (v != null && prev != null && prev !== 0) {
        const pct = (v - prev) / Math.abs(prev) * 100;
        const clr = Math.abs(pct) < 1 ? '#94a3b8' : pct > 0 ? '#059669' : '#dc2626';
        wowHtml = `<span style="color:${clr};font-size:10px;font-weight:600;">${pct > 0 ? '▲' : '▼'} ${Math.abs(pct).toFixed(1)}%</span>`;
      }
      const highlight = i === vals.length - 1 ? 'background:#f8fafc;font-weight:600;' : '';
      return `<tr style="border-bottom:1px solid #f8fafc;${highlight}">
        <td style="padding:5px 10px;font-size:11px;color:#64748b;white-space:nowrap;">${labels[i] || ''}</td>
        <td style="padding:5px 10px;font-size:12px;font-weight:700;text-align:right;color:#0f172a;">${fmtVal(v, fmt)}</td>
        <td style="padding:5px 10px;text-align:right;">${wowHtml}</td>
      </tr>`;
    }).join('');

    document.getElementById('szTable').innerHTML = `
      <div style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.06em;color:#94a3b8;margin-bottom:8px;">Week-by-Week</div>
      <div style="max-height:220px;overflow-y:auto;">
        <table style="width:100%;border-collapse:collapse;">
          <thead style="position:sticky;top:0;background:#fff;z-index:1;">
            <tr>
              <th style="padding:5px 10px;font-size:10px;text-transform:uppercase;letter-spacing:.05em;color:#94a3b8;text-align:left;font-weight:600;border-bottom:1px solid #f1f5f9;">Week</th>
              <th style="padding:5px 10px;font-size:10px;text-transform:uppercase;letter-spacing:.05em;color:#94a3b8;text-align:right;font-weight:600;border-bottom:1px solid #f1f5f9;">Value</th>
              <th style="padding:5px 10px;font-size:10px;text-transform:uppercase;letter-spacing:.05em;color:#94a3b8;text-align:right;font-weight:600;border-bottom:1px solid #f1f5f9;">WoW</th>
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
