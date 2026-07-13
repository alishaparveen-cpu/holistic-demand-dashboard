/* ============================================================================
 * leads-pivot.js  ·  the bookings-funnel LEADS pivot, extracted as a self-contained,
 * parameterized widget so marketing-diagnostic.html can mount the SAME layer-bar pivot
 * (ordered/reorderable dimensions + add-dimension chips + nested weekly drill-down).
 *
 *   const p = LeadsPivot.create({ mount, cells, weeks, nwk });
 *   p.setCells(cells);  p.setView(view);  p.render();
 *
 * cells = RAW leads-cube cells, each ALREADY tagged with .city and .loc :
 *   { city, loc, ch, md, num, url, rel, int, istr, cat, bk, w:[N] }   (w NEWEST-first)
 * weeks = week label strings, NEWEST-first (aligned to w index 0 = newest).
 * All state lives on the instance — no host-global collisions. CSS is scoped under .lpv.
 * ========================================================================== */
(function (root) {
  'use strict';

  // ---------- colors (copied from bookings-funnel) ----------
  var MODEC = { call: 'var(--lc-call)', web: 'var(--lc-web)', whatsapp: 'var(--lc-wa)', wa_gmb: 'var(--lc-wa)', wa_org: '#1F9D76', book: 'var(--lc-book)', walkin: 'var(--lc-walk)', outbound: '#B8862E', other: 'var(--lc-other)' };
  var CHAN_C = { 'GMB': '#3E7CB1', 'Google Ads': '#E0952A', 'Practo': '#8257C4', 'Meta': '#4E73C4', 'Organic': '#2E9E8F', 'Walk-in': '#9AA3B0', 'Other': '#c2c8d2' };
  var CAT_C = { STI: '#C05B4D', SH: '#1f9e8f', MH: '#8257c4', Other: '#9aa3b0', unknown: '#b0b6c0', na: '#c7ccd4' };
  var WEB_ATTR = { 'GMB': '🌐 clinic page', 'Google Ads': '🌐 clinic page · gclid', 'Meta': '🌐 clinic page · fbclid', 'Organic': '🌐 clinic page' };
  var WA_TBC = '💬 wa no. — TBC';
  var NUMLABEL = {};   // number -> {l,reg,out} — optional, set via LeadsPivot.setNumLabels()

  // ---------- dimension registry ----------
  var DIMS = {
    channel: { label: 'Channel', field: 'channel', values: [{ k: 'GMB' }, { k: 'Google Ads' }, { k: 'Practo' }, { k: 'Meta' }, { k: 'Organic' }, { k: 'Walk-in' }, { k: 'Other' }], color: function (v) { return CHAN_C[v] || 'var(--lc-accent)'; } },
    medium: { label: 'Medium', field: 'medium', values: [{ k: 'call', l: 'Call (inbound)' }, { k: 'outbound', l: 'Outbound (L2C called)' }, { k: 'web', l: 'Web' }, { k: 'wa_gmb', l: 'WhatsApp · GMB' }, { k: 'wa_org', l: 'WhatsApp · organic' }, { k: 'whatsapp', l: 'WhatsApp · other' }, { k: 'book', l: 'Practo book' }, { k: 'walkin', l: 'Walk-in' }, { k: 'other', l: 'Other / untagged' }], color: function (v) { return MODEC[v] || 'var(--lc-other)'; } },
    category: { label: 'Call category (AI audit)', field: 'category', values: [{ k: 'STI' }, { k: 'SH' }, { k: 'MH' }, { k: 'Other' }, { k: 'unknown', l: '— call · not audited' }, { k: 'na', l: '— not a call lead' }], color: function (v) { return CAT_C[v] || 'var(--lc-other)'; } }
  };
  DIMS.status = { label: 'Booked?', field: 'status', values: [{ k: 'booked', l: 'Booked an SC' }, { k: 'notbooked', l: 'Did NOT book' }], color: function (v) { return v === 'booked' ? '#2E7D5B' : '#B8503C'; } };
  DIMS.number = { label: 'Number dialed', field: 'num', values: [], color: function (v) { return v === '' ? '#c7ccd4' : 'var(--lc-call)'; } };
  DIMS.clinic = { label: 'Clinic (in city)', field: 'loc', values: [], color: function () { return '#7C5CBF'; } };
  DIMS.city = { label: 'City', field: 'city', values: [], color: function () { return '#2C6CAE'; } };
  DIMS.citygroup = { label: 'Attribution', field: 'citygroup', values: [{ k: 'attr', l: '✓ attributed to a city' }, { k: 'nocity', l: '— no city · online / untracked' }], color: function (v) { return v === 'attr' ? '#2C6CAE' : '#c7ccd4'; } };
  DIMS.strength = { label: 'Intent strength (AI)', field: 'strength', values: [{ k: 'STRONG', l: 'Strong intent' }, { k: 'LOW', l: 'Low intent' }, { k: 'COULD_NOT_DETERMINE', l: '— could not determine' }, { k: 'NOT_A_PATIENT', l: '— not a patient' }, { k: '', l: '— web / not audited' }], color: function (v) { return v === 'STRONG' ? '#2E7D5B' : (v === 'LOW' ? '#C87B2E' : (v === 'NOT_A_PATIENT' ? '#B8503C' : '#c7ccd4')); } };
  DIMS.intent = {
    label: 'Intent (AI)', field: 'intent', values: [{ k: 'TALK_TO_DOCTOR', l: 'Talk to doctor' }, { k: 'TALK_TO_THERAPIST', l: 'Talk to therapist' }, { k: 'NEEDS_TESTS', l: 'Needs tests' }, { k: 'NEEDS_MEDS', l: 'Needs meds' }, { k: 'OTHER', l: 'Other' }, { k: 'COULD_NOT_DETERMINE', l: 'Couldn’t determine' }, { k: '', l: '— web / not audited' }],
    color: function (v) { return ({ TALK_TO_DOCTOR: '#2C6CAE', TALK_TO_THERAPIST: '#8257C4', NEEDS_TESTS: '#1f9e8f', NEEDS_MEDS: '#C87B2E', OTHER: '#9aa3b0', COULD_NOT_DETERMINE: '#b0b6c0' }[v] || '#c7ccd4'); }
  };
  DIMS.channel.values.forEach(function (v) { v.l = v.l || v.k; });
  DIMS.category.values.forEach(function (v) { v.l = v.l || v.k; });
  var DIMLIST = ['citygroup', 'city', 'clinic', 'channel', 'medium', 'number', 'intent', 'strength', 'category', 'status'];
  var DYNAMIC = { city: 1, clinic: 1, number: 1 };   // value-lists built from the data per instance

  function valuesFor(inst, dk) { return DYNAMIC[dk] ? (inst.dimValues[dk] || []) : DIMS[dk].values; }
  function labOf(inst, dk, k) { var v = valuesFor(inst, dk).find(function (x) { return x.k === k; }); return v ? (v.l || v.k) : (k || '—'); }

  var MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  function fmtWk(d) { if (!d) return ''; var p = ('' + d).split('-'); return (+p[2]) + ' ' + MON[+p[1] - 1]; }

  // ---------- per-instance weekly helpers (weekly view only; no cumulative/day-of-week) ----------
  function view(inst) { return inst.view || { cols: [], ncur: 1, club: 1 }; }
  function weekArr(inst, cells) { var L = inst.weeks.length, a = new Array(L).fill(0); cells.forEach(function (c) { var ar = c.arr || []; for (var i = 0; i < L; i++) a[i] += ar[i] || 0; }); return a; }
  // sum a weekly series over ONLY the weeks the current window/grain shows (across all columns)
  function shownSum(inst, wk) { var cols = view(inst).cols, s = 0; for (var c = 0; c < cols.length; c++) { var ix = cols[c].cubeIdxs || []; for (var k = 0; k < ix.length; k++) s += wk[ix[k]] || 0; } return s; }
  function shownWeeks(inst) { return view(inst).cols.reduce(function (s, c) { return s + (c.cubeIdxs ? c.cubeIdxs.length : 0); }, 0); }
  // per-column block values + now/before/Δ, honoring CLUB (monthly) · CURN · BASEN · WEND from the page
  function blockVals(inst, wk) {
    var v = view(inst), cols = v.cols || [], ncur = v.ncur || 1;
    var vals = cols.map(function (c) { var s = 0, ix = c.cubeIdxs || []; for (var k = 0; k < ix.length; k++) s += wk[ix[k]] || 0; return s; });   // oldest→newest column totals
    var n = vals.length, nb = Math.max(0, n - ncur);
    var curV = vals.slice(nb), baseV = vals.slice(0, nb), avg = function (a) { return a.length ? a.reduce(function (x, y) { return x + y; }, 0) / a.length : null; };
    var now = avg(curV) || 0, before = avg(baseV);
    var cls, txt;
    if (before == null || before < 1) { txt = now > 0 ? '▲ new' : '—'; cls = 'flat'; }
    else { var d = Math.max(-99, Math.min(999, Math.round(100 * (now - before) / before))); cls = d >= 2 ? 'up' : (d <= -8 ? 'dn' : (d <= -2 ? 'amber' : 'flat')); txt = (d < 0 ? '↓ ' : d > 0 ? '↑ ' : '→ ') + Math.abs(d) + '%'; }
    return { vals: vals, nb: nb, now: now, before: before, cls: cls, txt: txt };
  }
  var ZSVG = '';
  function fmtNum(v, isPct) { if (v == null) return '·'; if (isPct) return Math.round(v) + '%'; var a = Math.abs(v); return a >= 1000 ? Math.round(v).toLocaleString('en-US') : ('' + (Math.round(v * 10) / 10)); }
  var STCLS = { up: 'green', dn: 'red', amber: 'amber', flat: 'base' };   // pivot delta cls -> the host page's .mc status classes
  // the row's right side — reuses the DIAGNOSTIC's own classes (fchange·mc·avgmk) so columns line up with the stage headline
  function trailHTML(inst, wk, isPct) {
    var bv = blockVals(inst, wk), st = STCLS[bv.cls] || 'base';
    var chips = bv.vals.map(function (val, j) { return '<span class="mc ' + (j >= bv.nb ? st : 'base') + '">' + fmtNum(val, isPct) + '</span>'; }).join('');
    return '<span class="fchange"><span class="mc ' + st + '" style="min-width:auto;white-space:nowrap">' + bv.txt + '</span></span>' + chips
      + '<span class="avgmk avgbefore"><span class="avglab">before</span>' + (bv.before == null ? '—' : fmtNum(bv.before, isPct)) + '</span>'
      + '<span class="avgmk avgnow ' + st + '"><span class="avglab">now</span>' + fmtNum(bv.now, isPct) + '</span>';
  }
  // click a number chip / Δ / before / now → open the trend chart (else the row toggles its drill-down)
  function zoomHit(e) { return e.target.closest('.mc,.avgmk'); }

  function cellPass(inst, c) { for (var i = 0; i < DIMLIST.length; i++) { var dk = DIMLIST[i]; if (!inst.sel[dk].has(c[DIMS[dk].field])) return false; } return true; }

  // raw cube cell -> pivot cell
  function buildLeadCells(raw) {
    var chOf = (root.LeadsCube && root.LeadsCube.channelOf) || function (x) { return x === 'Google' ? 'Google Ads' : (x || 'Other'); };
    var BS = (root.LeadsCube && root.LeadsCube.bookedSet) ? root.LeadsCube.bookedSet('ever') : new Set(['w0', 'w1', 'later', 'prior', 'booked']);
    return (raw || []).map(function (c) {
      var city = c.city || '', loc = c.loc || '';
      return {
        channel: chOf(c.ch), medium: c.md, num: c.num || '', url: c.url || '', relevance: c.rel || 'unknown',
        intent: c.int || '', strength: c.istr || '', category: c.cat || 'na', status: BS.has(c.bk) ? 'booked' : 'notbooked',
        loc: loc, city: city, citygroup: (city && city.indexOf('— no city') !== 0) ? 'attr' : 'nocity', arr: c.w || []
      };
    });
  }

  // ---------- recursive render ----------
  function renderNumList(inst, container, sub, depth) {
    var nums = {}, junk = 0;
    sub.forEach(function (c) { var s = shownSum(inst, weekArr(inst, [c])); if (!s) return; if (c.num && c.num.length === 10) nums[c.num] = (nums[c.num] || 0) + s; else if (c.num) junk += s; });
    var list = Object.entries(nums).sort(function (a, b) { return b[1] - a[1]; });
    if (!list.length && !junk) return;
    var body = list.map(function (e) { var nl = NUMLABEL[e[0]]; return '<div class="numrow">☎ ' + e[0] + (nl ? ' · ' + nl.l : '') + ' &nbsp;<b>' + e[1] + '</b></div>'; }).join('') + (junk ? '<div class="numrow out">☎ untagged / short numbers &nbsp;' + junk + '</div>' : '');
    var cnt = list.length + (junk ? 1 : 0);
    var nl = document.createElement('div'); nl.className = 'numlist'; nl.style.paddingLeft = (15 + depth * 20) + 'px';
    nl.innerHTML = '<div class="numtoggle" style="color:var(--lc-faint);margin-bottom:2px;cursor:pointer;user-select:none">▸ ☎ ' + cnt + ' numbers dialed · last ' + shownWeeks(inst) + ' wks <span style="opacity:.7">(click to expand)</span></div><div class="numbody" style="display:none">' + body + '</div>';
    var tg = nl.querySelector('.numtoggle'), bd = nl.querySelector('.numbody');
    tg.onclick = function (e) { e.stopPropagation(); var open = bd.style.display === 'none'; bd.style.display = open ? 'block' : 'none'; tg.innerHTML = (open ? '▾ ' : '▸ ') + '☎ ' + cnt + ' numbers dialed · last ' + shownWeeks(inst) + ' wks' + (open ? '' : ' <span style="opacity:.7">(click to expand)</span>'); };
    container.appendChild(nl);
  }

  function appendLeadTriplet(inst, container, cells, padPx) {
    var gW = weekArr(inst, cells), bkW = weekArr(inst, cells.filter(function (c) { return c.status === 'booked'; }));
    var nbW = gW.map(function (t, i) { return t - (bkW[i] || 0); }), rateArr = gW.map(function (t, i) { return t ? Math.round(100 * bkW[i] / t) : 0; });
    function sub(lbl, arr, cls, isPct, col) {
      var row = document.createElement('div'); row.className = 'frow subr ' + cls;
      row.innerHTML = '<span class="flab" style="padding-left:' + (padPx || 6) + 'px">' + lbl + '</span>' + trailHTML(inst, arr, isPct);
      container.appendChild(row); row.onclick = function (e) { if (zoomHit(e)) openChart(inst, lbl, arr, col); };
    }
    sub('↳ booked', bkW, 'bkd', false, '#2E7D5B');
    sub('↳ not booked', nbW, 'nbk', false, '#B8503C');
    sub('→ book rate %', rateArr, 'rate', true, '#1F6F5C');
  }

  function renderLevel(inst, container, cells, depth, parentTot, parentWk, path, pathVals) {
    var order = inst.order, dk = order[depth], last = depth === order.length - 1;
    valuesFor(inst, dk).forEach(function (v) {
      if (!inst.sel[dk].has(v.k)) return;
      var sub = cells.filter(function (c) { return c[DIMS[dk].field] === v.k; });
      var wk = weekArr(inst, sub), t = shownSum(inst, wk); if (!t) return;
      var key = path + '/' + dk + ':' + v.k, col = DIMS[dk].color(v.k);
      var row = document.createElement('div'); row.style.paddingLeft = (15 + depth * 20) + 'px';
      var callNums = (dk === 'medium' && v.k === 'call') ? Array.from(new Set(sub.map(function (c) { return c.num; }).filter(Boolean))) : [];
      var attr = '';
      if (dk === 'channel') {
        if (v.k === 'GMB') attr = '<span class="attr">☎ GMB no. / 🌐 campaign</span>';
        else if (v.k === 'Practo') attr = '<span class="attr">🩺 Practo clinic / doctor</span>';
        else attr = '<span class="attr">🎯 clinic locality · AI-audit of the call</span>';
      } else if (dk === 'medium') {
        var chan = pathVals.channel;
        if (v.k === 'call') { attr = callNums.length > 1 ? '<span class="attr">☎ ' + callNums.length + ' numbers ▾</span>' : (callNums.length === 1 ? '<span class="attr">☎ ' + callNums[0] + '</span>' : '<span class="attr">☎ call</span>'); }
        else if (v.k === 'web') { var urls = Array.from(new Set(sub.map(function (c) { return c.url; }).filter(Boolean))); attr = urls.length ? '<span class="attr" title="' + urls.join('  |  ') + '">🌐 ' + urls[0] + (urls.length > 1 ? ' (+' + (urls.length - 1) + ')' : '') + '</span>' : '<span class="attr">' + (chan ? (WEB_ATTR[chan] || '🌐 clinic page') : '🌐 clinic page') + '</span>'; }
        else if (v.k === 'wa_gmb') attr = '<span class="attr">💬 GMB WhatsApp</span>';
        else if (v.k === 'wa_org') attr = '<span class="attr">💬 organic WhatsApp</span>';
        else if (v.k === 'whatsapp') attr = '<span class="attr tbc">' + WA_TBC + '</span>';
        else if (v.k === 'book') attr = '<span class="attr">Practo booking</span>';
      } else if (dk === 'category' && v.k === 'unknown') attr = '<span class="attr">no audit</span>';
      var callExp = last && dk === 'medium' && v.k === 'call' && callNums.length > 1;
      var hasKids = !last || callExp;
      var showTrip = dk !== 'status' && order[depth + 1] !== 'status' && inst.sel.status.size === DIMS.status.values.length;
      if (showTrip) hasKids = true;
      row.className = 'frow' + (hasKids ? ' clk' : '');
      row.innerHTML = '<span class="flab" style="padding-left:' + (6 + depth * 16) + 'px">'
        + '<span class="lpvchev">' + (hasKids ? (inst.open[key] ? '▾' : '▶') : '') + '</span>'
        + '<span class="lpvdot" style="background:' + col + '"></span>' + labOf(inst, dk, v.k) + attr + '</span>' + trailHTML(inst, wk, false);
      container.appendChild(row);
      var crumb = Object.keys(pathVals).map(function (d2) { return labOf(inst, d2, pathVals[d2]); }); crumb.push(labOf(inst, dk, v.k));
      row.onclick = function (e) { if (zoomHit(e)) { e.stopPropagation(); openChart(inst, crumb.join(' › '), wk, col); return; } if (hasKids) { inst.open[key] = !inst.open[key]; draw(inst); } };
      if (hasKids) {
        var kidbox = document.createElement('div'); kidbox.style.display = inst.open[key] ? 'block' : 'none'; container.appendChild(kidbox);
        if (inst.open[key]) {
          var nextVals = Object.assign({}, pathVals); nextVals[dk] = v.k;
          if (showTrip) {
            appendLeadTriplet(inst, kidbox, sub, 15 + (depth + 1) * 20);
            if (dk === 'medium' && v.k === 'call' && order[depth + 1] !== 'number') renderNumList(inst, kidbox, sub, depth + 1);
            if (!last) renderLevel(inst, kidbox, sub, depth + 1, t, wk, key, nextVals);
          } else {
            if (dk === 'medium' && v.k === 'call' && order[depth + 1] !== 'number') renderNumList(inst, kidbox, sub, depth + 1);
            if (!last) renderLevel(inst, kidbox, sub, depth + 1, t, wk, key, nextVals);
          }
        }
      }
    });
    // lead→book % row under the Booked? split
    if (dk === 'status' && inst.sel.status.size === DIMS.status.values.length) {
      var bkW = weekArr(inst, cells.filter(function (c) { return c.status === 'booked'; })), ttW = weekArr(inst, cells);
      var rateArr = ttW.map(function (tt, i) { return tt ? Math.round(100 * bkW[i] / tt) : 0; });
      var bRow = document.createElement('div'); bRow.className = 'frow brate';
      bRow.innerHTML = '<span class="flab" style="padding-left:' + (6 + depth * 16) + 'px"><span class="lpvchev"></span>→ book rate %</span>' + trailHTML(inst, rateArr, true);
      container.appendChild(bRow);
      bRow.onclick = function (e) { if (zoomHit(e)) openChart(inst, 'Book rate %', rateArr, '#2E7D5B'); };
    }
  }

  function draw(inst) {
    var cells = inst.cells.filter(function (c) { return cellPass(inst, c); });
    var gWk = weekArr(inst, cells), tot = shownSum(inst, gWk);
    var vw = view(inst), cols = vw.cols || [], nwks = cols.reduce(function (s, c) { return s + (c.cubeIdxs ? c.cubeIdxs.length : 0); }, 0);
    inst.els.heroN.textContent = Math.round(tot).toLocaleString('en-IN');
    inst.els.heroL.textContent = 'attributable leads · last ' + nwks + ' wks' + (vw.club > 1 ? ' (' + cols.length + ' months)' : '');
    // header row (same columns as the rows) — the layer path, Δ, full week titles, before, now
    inst.els.head.innerHTML = '<span class="flab lpvhcol">' + inst.order.map(function (d) { return DIMS[d].label; }).join(' → ') + '</span>'
      + '<span class="fchange lpvhcol" style="justify-content:flex-start">Δ AVG</span>'
      + cols.map(function (c) { return '<span class="mc lpvhcol lpvwklab">' + (c.label || '') + '</span>'; }).join('')
      + '<span class="avgmk avgbefore lpvhcol"><span class="avglab">before</span></span><span class="avgmk avgnow lpvhcol"><span class="avglab">now</span></span>';
    var flow = inst.els.flow; flow.innerHTML = '';
    if (!tot) { flow.innerHTML = '<div class="empty">no rows match the current selection</div>'; return; }
    renderLevel(inst, flow, cells, 0, tot, gWk, '', {});
    var foot = document.createElement('div'); foot.className = 'frow foot';
    foot.innerHTML = '<span class="flab" style="font-weight:800;padding-left:6px">Total leads</span>' + trailHTML(inst, gWk, false);
    flow.appendChild(foot);
    foot.onclick = function (e) { if (zoomHit(e)) openChart(inst, 'Total · all shown', gWk, 'var(--lc-accent)'); };
    if (inst.sel.status.size === DIMS.status.values.length) appendLeadTriplet(inst, flow, cells, 0);
  }

  // ---------- layer bar ----------
  var dragIdx = null, dragInst = null;
  function renderLayerBar(inst) {
    var bar = inst.els.bar;
    Array.prototype.slice.call(bar.querySelectorAll('.chip,.arrow,.ghost,.pinchip,.leadb')).forEach(function (c) { c.remove(); });
    var pins = inst.pins || [];
    var lead = bar.querySelector('.lead'); if (lead) lead.textContent = pins.length ? 'Scope ·' : 'Break down ·';
    pins.forEach(function (p) { var pc = document.createElement('div'); pc.className = 'pinchip'; pc.title = 'set by the page scope above'; pc.innerHTML = '<span class="lock">🔒</span>' + p; bar.appendChild(pc); });
    if (pins.length) { var lb = document.createElement('span'); lb.className = 'leadb'; lb.textContent = '→ break down by'; bar.appendChild(lb); }
    inst.order.forEach(function (dk, i) {
      var vals = valuesFor(inst, dk).filter(function (v) { return !inst.present[dk] || inst.present[dk].has(v.k); });
      var ntot = vals.length, nsel = vals.filter(function (v) { return inst.sel[dk].has(v.k); }).length;
      var chip = document.createElement('div'); chip.className = 'chip'; chip.draggable = true; chip.dataset.i = i;
      chip.innerHTML = '<span class="grip">⋮⋮</span><span class="ord">' + (i + 1) + '</span><span class="nm">' + DIMS[dk].label + '</span><span class="cnt">' + nsel + '/' + ntot + '</span><span class="cv">▾</span>' + (inst.order.length > 1 ? '<span class="rm" title="remove layer">×</span>' : '');
      var pop = document.createElement('div'); pop.className = 'pop';
      pop.innerHTML = '<div class="pact"><button data-a="all">All</button><button data-a="none">None</button></div>' + vals.map(function (v) { return '<label><input type="checkbox" data-k="' + v.k + '" ' + (inst.sel[dk].has(v.k) ? 'checked' : '') + '><span class="sw" style="background:' + DIMS[dk].color(v.k) + '"></span>' + (v.l || v.k) + '</label>'; }).join('');
      if (dk === 'status') {
        var bk = 0, tt = 0; inst.cells.forEach(function (c) { var pass = true; for (var j = 0; j < DIMLIST.length; j++) { var d2 = DIMLIST[j]; if (d2 === 'status') continue; if (!inst.sel[d2].has(c[DIMS[d2].field])) { pass = false; break; } } if (!pass) return; var s = shownSum(inst, weekArr(inst, [c])); tt += s; if (c.status === 'booked') bk += s; });
        pop.innerHTML += '<div style="border-top:1px solid var(--lc-line);margin-top:6px;padding-top:7px;font-size:12px;color:#1F6F5C;font-weight:700">→ book rate ' + (tt ? Math.round(100 * bk / tt) : 0) + '% <span style="color:var(--lc-faint);font-weight:400">· ' + bk + '/' + tt + '</span></div>';
      }
      chip.appendChild(pop);
      chip.onclick = function (e) {
        if (e.target.closest('.pop')) return;
        if (e.target.classList.contains('rm')) { e.stopPropagation(); inst.order.splice(i, 1); inst.open = {}; renderLayerBar(inst); draw(inst); return; }
        var open = pop.classList.contains('show');
        inst.mount.querySelectorAll('.pop').forEach(function (p) { p.classList.remove('show'); });
        inst.mount.querySelectorAll('.chip').forEach(function (c) { c.classList.remove('open2'); });
        if (!open) { pop.classList.add('show'); chip.classList.add('open2'); }
      };
      var updCnt = function () { chip.querySelector('.cnt').textContent = vals.filter(function (v) { return inst.sel[dk].has(v.k); }).length + '/' + ntot; };
      pop.querySelectorAll('.pact button').forEach(function (b) { b.onclick = function (e) { e.stopPropagation(); if (b.dataset.a === 'all') vals.forEach(function (v) { inst.sel[dk].add(v.k); }); else vals.forEach(function (v) { inst.sel[dk].delete(v.k); }); pop.querySelectorAll('input').forEach(function (inp) { inp.checked = inst.sel[dk].has(inp.dataset.k); }); updCnt(); draw(inst); }; });
      pop.querySelectorAll('input').forEach(function (inp) { inp.onclick = function (e) { e.stopPropagation(); if (inp.checked) inst.sel[dk].add(inp.dataset.k); else inst.sel[dk].delete(inp.dataset.k); updCnt(); draw(inst); }; });
      chip.ondragstart = function (e) { dragIdx = i; dragInst = inst; chip.classList.add('drag'); e.dataTransfer.effectAllowed = 'move'; };
      chip.ondragend = function () { chip.classList.remove('drag'); inst.mount.querySelectorAll('.chip').forEach(function (c) { c.classList.remove('over'); }); };
      chip.ondragover = function (e) { e.preventDefault(); chip.classList.add('over'); };
      chip.ondragleave = function () { chip.classList.remove('over'); };
      chip.ondrop = function (e) { e.preventDefault(); var to = +chip.dataset.i; if (dragInst !== inst || dragIdx === null || dragIdx === to) return; var m = inst.order.splice(dragIdx, 1)[0]; inst.order.splice(to, 0, m); dragIdx = null; dragInst = null; inst.open = {}; renderLayerBar(inst); draw(inst); };
      bar.appendChild(chip);
      if (i < inst.order.length - 1) { var a = document.createElement('span'); a.className = 'arrow'; a.textContent = '→'; bar.appendChild(a); }
    });
    DIMLIST.filter(function (d) { return inst.order.indexOf(d) < 0; }).filter(function (d) { return ['clinic', 'city', 'citygroup'].indexOf(d) < 0 || (inst.present[d] && inst.present[d].size > 1); }).forEach(function (dk) {
      var g = document.createElement('div'); g.className = 'ghost'; g.textContent = '＋ ' + DIMS[dk].label;
      g.onclick = function () { inst.order.push(dk); inst.open = {}; renderLayerBar(inst); draw(inst); };
      bar.appendChild(g);
    });
  }

  // ---------- shared zoom modal ----------
  var _cur = null;
  function ensureModal() {
    if (document.getElementById('lpv-cmodal')) return;
    var m = document.createElement('div'); m.id = 'lpv-cmodal'; m.className = 'lpv-cmodal';
    m.innerHTML = '<div class="cbox"><button class="cx" onclick="LeadsPivot._close()">✕</button><h3 id="lpv-ctitle"></h3><div class="csub" id="lpv-csub"></div><div id="lpv-cchart"></div></div>';
    m.onclick = function (e) { if (e.target === m) LeadsPivot._close(); };
    document.body.appendChild(m);
  }
  function openChart(inst, title, wk, col) { ensureModal(); _cur = { weeks: inst.weeks, wk: wk, col: col || 'var(--lc-accent)', title: title, a: null, b: null, zwin: 5 }; renderChart(); document.getElementById('lpv-cmodal').classList.add('on'); }
  function renderChart() {
    var C = _cur; if (!C) return;
    document.getElementById('lpv-ctitle').textContent = C.title;
    var allV = [], allL = []; for (var i = C.weeks.length - 1; i >= 0; i--) { allV.push(C.wk[i] || 0); allL.push(fmtWk(C.weeks[i])); }
    var tot = allV.length, win = (C.zwin && C.zwin < tot) ? C.zwin : tot;
    var v = allV.slice(tot - win), labels = allL.slice(tot - win), n = v.length, col = C.col;
    var F = function (x) { return Math.round(x).toLocaleString('en-IN'); };
    var W = 720, H = 300, pad = 42, padT = 26;
    var vmx = Math.max.apply(null, [1].concat(v)), rng = vmx || 1, lo = 0, hi = vmx + rng * 0.16;
    var x = function (i) { return pad + i * (W - 2 * pad) / ((n - 1) || 1); }, y = function (val) { var yy = H - pad - ((val - lo) / ((hi - lo) || 1)) * (H - pad - padT); return Math.max(padT, Math.min(H - pad, yy)); };
    var p = '', pts = '', lbls = '', prev = null;
    v.forEach(function (val, i) {
      if (prev != null) p += '<line x1="' + x(prev.i).toFixed(1) + '" y1="' + y(prev.v).toFixed(1) + '" x2="' + x(i).toFixed(1) + '" y2="' + y(val).toFixed(1) + '" stroke="' + col + '" stroke-width="2.2"/>'; prev = { i: i, v: val };
      var sel = (i === C.a || i === C.b);
      pts += '<circle cx="' + x(i).toFixed(1) + '" cy="' + y(val).toFixed(1) + '" r="13" fill="transparent" style="cursor:pointer" onclick="LeadsPivot._pick(' + i + ')"></circle><circle cx="' + x(i).toFixed(1) + '" cy="' + y(val).toFixed(1) + '" r="' + (sel ? 5.5 : 3.2) + '" fill="' + (sel ? (i === C.a ? '#1F6F5C' : '#C2691F') : col) + '" stroke="' + (sel ? '#fff' : col) + '" stroke-width="' + (sel ? 2 : 0) + '" style="cursor:pointer" onclick="LeadsPivot._pick(' + i + ')"><title>' + labels[i] + ': ' + F(val) + '</title></circle>';
      lbls += '<text x="' + x(i).toFixed(1) + '" y="' + (y(val) - 9).toFixed(1) + '" font-size="11" fill="' + col + '" text-anchor="middle" font-weight="700">' + F(val) + '</text>';
    });
    var gl = ''; [0, .5, 1].forEach(function (f) { var yy = H - pad - (f * (H - pad - padT)); gl += '<line x1="' + pad + '" y1="' + yy + '" x2="' + (W - pad) + '" y2="' + yy + '" stroke="var(--lc-line2)"/><text x="4" y="' + (yy + 3) + '" font-size="10" fill="var(--lc-faint)">' + F(lo + f * (hi - lo)) + '</text>'; });
    var rot = n > 8, Hv = rot ? H + 44 : H, xl = '';
    labels.forEach(function (L, i) { var lx = x(i).toFixed(1), ly = (H - pad + 15).toFixed(1); xl += rot ? '<text x="' + lx + '" y="' + ly + '" font-size="9" fill="var(--lc-faint)" text-anchor="end" transform="rotate(-40 ' + lx + ' ' + ly + ')">' + L + '</text>' : '<text x="' + lx + '" y="' + (H - 9) + '" font-size="9" fill="var(--lc-faint)" text-anchor="middle">' + L + '</text>'; });
    var avg = v.length ? v.reduce(function (a, b) { return a + b; }, 0) / v.length : null, avgLine = '';
    if (avg != null) { var ya = y(avg); avgLine = '<line x1="' + pad + '" y1="' + ya.toFixed(1) + '" x2="' + (W - pad) + '" y2="' + ya.toFixed(1) + '" stroke="' + col + '" stroke-width="1.3" stroke-dasharray="6 4" opacity="0.5"/>'; }
    var conn = ''; if (C.a != null && C.b != null) conn = '<line x1="' + x(C.a).toFixed(1) + '" y1="' + y(v[C.a]).toFixed(1) + '" x2="' + x(C.b).toFixed(1) + '" y2="' + y(v[C.b]).toFixed(1) + '" stroke="#C2691F" stroke-width="1.6" stroke-dasharray="5 3"/>';
    var zbtn = function (lbl, val) { return '<button onclick="LeadsPivot._zwin(' + val + ')" style="border:1px solid ' + (C.zwin === val ? 'var(--lc-accent);background:var(--lc-accent);color:#fff' : 'var(--lc-line);background:var(--lc-sheet);color:var(--lc-muted)') + ';border-radius:6px;padding:2px 9px;font-size:10.5px;font-weight:700;cursor:pointer;margin-left:4px">' + lbl + '</button>'; };
    document.getElementById('lpv-cchart').innerHTML = '<svg width="100%" viewBox="0 0 ' + W + ' ' + Hv + '">' + gl + avgLine + conn + p + pts + lbls + xl + '</svg><div style="font-size:11px;color:var(--lc-muted);margin-top:6px">oldest→newest · ' + n + ' weeks · dashed = average' + (avg != null ? ' (' + F(avg) + ')' : '') + '<span style="margin-left:10px;color:var(--lc-faint)">window:</span>' + zbtn('full', 0) + zbtn('12w', 12) + zbtn('5w', 5) + '</div>';
    var pb = document.getElementById('lpv-csub');
    if (C.a != null && C.b != null) { var a = v[C.a], b = v[C.b], pc = a ? Math.round((b - a) / Math.abs(a) * 100) : 0, cc = pc > 0 ? '#1F6F5C' : pc < 0 ? '#B23A2E' : 'var(--lc-muted)'; pb.innerHTML = '<b style="color:#1F6F5C">' + labels[C.a] + '</b> ' + F(a) + ' → <b style="color:#C2691F">' + labels[C.b] + '</b> ' + F(b) + ' &nbsp;<span style="color:' + cc + ';font-weight:700;font-size:14px">' + (pc > 0 ? '+' : '') + pc + '%</span> &nbsp;<span style="cursor:pointer;color:var(--lc-faint)" onclick="LeadsPivot._clear()">✕ clear</span>'; }
    else if (C.a != null) pb.innerHTML = 'Selected <b style="color:#1F6F5C">' + labels[C.a] + '</b> ' + F(v[C.a]) + ' — click another point to compare';
    else pb.innerHTML = '<span style="color:var(--lc-muted)">➜ Click any two points to compare — % change between them.</span>';
  }

  // ---------- CSS (scoped under .lpv / .lpv-cmodal) ----------
  // inherit the HOST page's design tokens (fallbacks match the marketing-diagnostic palette) so the pivot matches the page theme
  var CSS = '.lpv{--lc-accent:var(--accent,#2C6CAE);--lc-ink:var(--ink,#16232E);--lc-ink2:var(--ink2,#44566A);--lc-muted:var(--muted,#7B8A9B);--lc-faint:var(--faint,#A6B4C3);--lc-sheet:var(--sheet,#fff);--lc-inset:var(--inset,#E4EDF6);--lc-line:var(--line,#D5DFEA);--lc-line2:var(--line2,#E5ECF3);--lc-call:var(--accent,#2C6CAE);--lc-web:var(--good,#1F6F5C);--lc-wa:#3E9E6B;--lc-book:#8257c4;--lc-walk:var(--faint,#A6B4C3);--lc-other:#c2c8d2;--lc-good:var(--good,#1F6F5C);--lc-bad:var(--bad,#C24A6B);--lc-warn:var(--warn,#B8862E);--lc-gbg:var(--gbg,#E5F0EB);--lc-rbg:var(--rbg,#FCE8DA);--lc-drbg:var(--drbg,#FAD4DE);--lc-abg:var(--abg,#FAF2E6);color:var(--lc-ink);font-size:13px}'
    + '.lpv .lpv-hero{display:flex;align-items:baseline;gap:10px;margin:6px 0 12px}.lpv .lpv-hero .n{font-family:Fraunces,serif;font-size:32px;font-weight:600;line-height:1}.lpv .lpv-hero .l{font-size:13px;color:var(--lc-muted)}'
    + '.lpv .layerbar{display:flex;align-items:center;gap:9px;flex-wrap:wrap;margin:6px 0 14px}.lpv .layerbar .lead{font-size:11px;color:var(--lc-faint);font-weight:600;margin-right:2px}.lpv .layerbar .leadb{font-size:11px;color:var(--lc-faint);font-weight:600;margin:0 1px}'
    + '.lpv .pinchip{display:inline-flex;align-items:center;gap:6px;background:var(--lc-inset);border:1px solid var(--lc-line);border-radius:10px;padding:7px 11px;font-size:12.5px;font-weight:700;color:var(--lc-ink2);cursor:default}.lpv .pinchip .lock{font-size:9px;opacity:.6}'
    + '.lpv .chip{position:relative;display:inline-flex;align-items:center;gap:8px;background:var(--lc-sheet);border:1px solid var(--lc-line);border-radius:10px;padding:7px 11px;cursor:grab;user-select:none}.lpv .chip:hover{border-color:var(--lc-accent)}.lpv .chip.drag{opacity:.4}.lpv .chip.over{border-color:var(--lc-accent);box-shadow:0 0 0 2px color-mix(in srgb,var(--lc-accent) 30%,transparent)}'
    + '.lpv .chip .ord{font-family:JetBrains Mono,monospace;font-size:10px;font-weight:700;color:#fff;background:var(--lc-accent);width:16px;height:16px;border-radius:5px;display:flex;align-items:center;justify-content:center}.lpv .chip .nm{font-weight:700;font-size:12.5px}.lpv .chip .cnt{font-family:JetBrains Mono,monospace;font-size:10.5px;color:var(--lc-muted)}.lpv .chip .grip{color:var(--lc-faint);font-size:13px;letter-spacing:-2px}.lpv .chip .cv{font-size:10px;color:var(--lc-faint)}.lpv .chip.open2 .cv{transform:rotate(180deg)}.lpv .chip .rm{font-size:13px;color:var(--lc-faint);padding:0 2px;border-radius:4px}.lpv .chip .rm:hover{color:#B8503C;background:var(--lc-inset)}'
    + '.lpv .ghost{display:inline-flex;align-items:center;background:transparent;border:1px dashed var(--lc-line);border-radius:10px;padding:6px 10px;font-size:11.5px;font-weight:600;color:var(--lc-muted);cursor:pointer}.lpv .ghost:hover{border-color:var(--lc-accent);color:var(--lc-accent)}.lpv .arrow{color:var(--lc-faint);font-size:13px}'
    + '.lpv .pop{position:absolute;top:calc(100% + 5px);left:0;z-index:40;background:var(--lc-sheet);border:1px solid var(--lc-line);border-radius:10px;box-shadow:0 10px 30px rgba(20,28,24,.16);padding:8px;min-width:190px;display:none}.lpv .pop.show{display:block}.lpv .pop .pact{display:flex;gap:6px;margin-bottom:6px}.lpv .pop .pact button{flex:1;font:inherit;font-size:10.5px;font-weight:600;padding:4px;border:1px solid var(--lc-line);border-radius:6px;background:var(--lc-inset);color:var(--lc-muted);cursor:pointer}.lpv .pop label{display:flex;align-items:center;gap:8px;padding:5px 6px;border-radius:7px;cursor:pointer;font-size:12px}.lpv .pop label:hover{background:var(--lc-inset)}.lpv .pop label .sw{width:9px;height:9px;border-radius:2px;flex:none}.lpv .pop input{accent-color:var(--lc-accent)}'
    // rows reuse the HOST page's .frow/.flab/.fchange/.mc/.avgmk classes (so columns line up with the stage headline); only pivot-specific bits are scoped here
    + '.lpv .lpv-table{margin-top:2px}'
    + '.lpv .lpvhead .lpvhcol,.lpv .lpvhead .avglab{font-size:9.5px;font-weight:800;letter-spacing:.03em;text-transform:uppercase;color:var(--lc-faint)}.lpv .lpvhead .mc{background:none;box-shadow:none}.lpv .lpvwklab{font-family:Inter,sans-serif;white-space:nowrap;color:var(--lc-faint)}'
    + '.lpv .lpvchev{width:14px;flex:none;display:inline-block;text-align:center;color:var(--lc-faint);font-size:10px}.lpv .lpvdot{width:8px;height:8px;border-radius:2px;display:inline-block;margin:0 5px 0 1px;flex:none}.lpv .attr{font-family:JetBrains Mono,monospace;font-size:10px;color:var(--lc-faint);margin-left:4px;font-weight:400}.lpv .attr.tbc{color:var(--lc-warn)}'
    + '.lpv .frow.clk{cursor:pointer}.lpv .frow.clk:hover{background:var(--lc-inset)}.lpv .frow.subr .flab{padding-left:24px}.lpv .frow.subr.bkd .flab{color:var(--lc-good)}.lpv .frow.subr.nbk .flab{color:var(--lc-bad)}.lpv .frow.subr.rate .flab,.lpv .frow.brate .flab{color:var(--lc-good);font-style:italic;font-weight:700}.lpv .frow.brate{background:var(--lc-gbg)}.lpv .frow.foot{border-top:2px solid var(--lc-line);margin-top:2px;background:var(--lc-inset)}'
    + '.lpv .numlist{padding:2px 0 7px 24px;font-family:JetBrains Mono,monospace;font-size:10px;color:var(--lc-muted)}.lpv .numrow{padding:1.5px 0}.lpv .numrow.out{color:var(--lc-faint);font-style:italic}.lpv .empty{padding:16px;color:var(--lc-faint);text-align:center}'
    + '.lpv-cmodal{position:fixed;inset:0;background:rgba(20,28,24,.5);display:none;align-items:center;justify-content:center;z-index:600;padding:20px}.lpv-cmodal.on{display:flex}.lpv-cmodal .cbox{background:#fff;border-radius:14px;padding:18px 22px 22px;max-width:760px;width:100%;box-shadow:0 20px 60px rgba(0,0,0,.32)}@media (prefers-color-scheme:dark){.lpv-cmodal .cbox{background:#181b21}}.lpv-cmodal h3{font-family:Fraunces,serif;margin:0 0 4px;font-size:18px}.lpv-cmodal .csub{font-size:11.5px;color:#5b6472;margin-bottom:10px}.lpv-cmodal .cx{float:right;border:none;background:none;font-size:19px;color:#5b6472;cursor:pointer;line-height:1}';

  function injectCSS() { if (document.getElementById('lpv-style')) return; var s = document.createElement('style'); s.id = 'lpv-style'; s.textContent = CSS; document.head.appendChild(s); }

  // ---------- factory ----------
  function distinct(cells, field) { var s = {}; cells.forEach(function (c) { s[c[field] || ''] = 1; }); return Object.keys(s).sort(); }

  function create(opts) {
    injectCSS(); ensureModal();
    var inst = { mount: opts.mount, weeks: (opts.weeks || []).slice(), view: opts.view || { cols: [], ncur: 1, club: 1 }, pins: opts.pins || [], order: (opts.order && opts.order.slice()) || ['channel', 'medium'], sel: {}, open: {}, present: {}, dimValues: {}, cells: [], els: {} };
    // scaffold — flush rows (no bordered box) so the table flows straight under the stage headline
    var wrap = document.createElement('div'); wrap.className = 'lpv';
    wrap.innerHTML = '<div class="lpv-hero"><span class="n"></span><span class="l"></span></div>'
      + '<div class="layerbar"><span class="lead">Layers ·</span></div>'
      + '<div class="lpv-table"><div class="frow head lpvhead"></div><div class="flow"></div></div>';
    inst.mount.innerHTML = ''; inst.mount.appendChild(wrap);
    inst.els = { heroN: wrap.querySelector('.lpv-hero .n'), heroL: wrap.querySelector('.lpv-hero .l'), bar: wrap.querySelector('.layerbar'), head: wrap.querySelector('.lpvhead'), flow: wrap.querySelector('.flow') };
    inst.setCells = function (raw) {
      inst.cells = buildLeadCells(raw);
      inst.dimValues.city = distinct(inst.cells, 'city').map(function (k) { return { k: k, l: k || '(no city)' }; });
      inst.dimValues.clinic = distinct(inst.cells, 'loc').map(function (k) { return { k: k, l: k || '(city-level · no clinic)' }; });
      inst.dimValues.number = distinct(inst.cells, 'num').map(function (k) { return { k: k, l: k || '(not a call)' }; });
      inst.present = { citygroup: new Set(inst.cells.map(function (c) { return c.citygroup; })), city: new Set(inst.cells.map(function (c) { return c.city; })), clinic: new Set(inst.cells.map(function (c) { return c.loc; })) };
      inst.sel = {}; DIMLIST.forEach(function (dk) { inst.sel[dk] = new Set(valuesFor(inst, dk).map(function (v) { return v.k; })); });
      inst.open = {};
      inst.order = inst.order.filter(function (d) { return DIMLIST.indexOf(d) >= 0; }); if (!inst.order.length) inst.order = ['channel', 'medium'];
      inst.render();
    };
    inst.setView = function (v) { inst.view = v || inst.view; draw(inst); };   // window/grain changed → re-draw columns (layer bar unchanged)
    inst.render = function () { renderLayerBar(inst); draw(inst); };
    inst.setCells(opts.cells || []);
    return inst;
  }

  // close popovers on outside click
  document.addEventListener('click', function (e) { if (!e.target.closest('.chip')) { document.querySelectorAll('.lpv .pop').forEach(function (p) { p.classList.remove('show'); }); document.querySelectorAll('.lpv .chip').forEach(function (c) { c.classList.remove('open2'); }); } });

  root.LeadsPivot = {
    create: create,
    setNumLabels: function (m) { NUMLABEL = m || {}; },
    _close: function () { var m = document.getElementById('lpv-cmodal'); if (m) m.classList.remove('on'); _cur = null; },
    _pick: function (i) { if (!_cur) return; if (_cur.a === null) _cur.a = i; else if (_cur.b === null) { if (i === _cur.a) _cur.a = null; else _cur.b = i; } else { _cur.a = i; _cur.b = null; } renderChart(); },
    _clear: function () { if (_cur) { _cur.a = null; _cur.b = null; renderChart(); } },
    _zwin: function (n) { if (_cur) { _cur.zwin = n; _cur.a = null; _cur.b = null; renderChart(); } }
  };
})(typeof window !== 'undefined' ? window : this);
