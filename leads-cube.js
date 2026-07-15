/* ============================================================================
 * leads-cube.js  ·  SHARED leads computation — the single source of truth.
 * The DATA is data_leads_city.json / data_leads.json (built by build_leads_city.py
 * / build_notbooked.py). This module is the ONE place the leads metrics are derived,
 * so bookings-funnel.html and marketing-diagnostic.html can never drift.
 *
 * SCHEMA  (version 1)
 * ------------------------------------------------------------------------------
 * A cube file = { _meta:{weeks:[26], days:[56], channels:[…], mediums:[…]}, "<cityKey>":{cells:[…]} }
 *   cityKey     : a real city ("Bangalore") OR the national bucket "— no city · online / untracked"
 *   cell        : { loc, ch, md, num, url, rel, int, istr, cat, bk, w:[26], d:[56] }
 *     loc  = clinic locality ('' = city-level, no clinic)
 *     ch   = raw channel: GMB | Google Ads | Meta | Practo | Organic | Other   (Meta = fbclid-attributed)
 *     md   = medium: call | web | wa_gmb | wa_org | whatsapp | book
 *     num  = exophone dialed ('' = not a call)      url = landing url
 *     rel  = relevance (in-scope/out-of-scope/unknown)   int = AI intent   istr = AI intent-strength
 *     cat  = AI category (STI/SH/MH/Other/…)
 *     bk   = booked LAG bucket: w0 (same wk) | w1 (≤2wk) | later | prior | notbooked
 *     w    = 26 weekly counts (NEWEST-first, aligned with the bookings cube)
 *     d    = 56 daily counts  (recent 8 wks incl. the current partial week)
 * ------------------------------------------------------------------------------
 * A lead counts as "booked" when its bk bucket ∈ the chosen window (BOOKED_SET).
 * L2B (lead→book%) = booked ÷ total leads, using that window.  <-- the funnel definition.
 * ========================================================================== */
(function (root) {
  'use strict';
  var VERSION = 1;

  // which lag buckets count as "booked" per window  (matches bookings-funnel's BOOKED_SET)
  var BOOKED_SET = {
    ever: ['w0', 'w1', 'later', 'prior', 'booked'],
    '2wk': ['w0', 'w1'],
    week: ['w0']
  };
  var CHANNELS = ['GMB', 'Google Ads', 'Meta', 'Practo', 'Organic', 'Organic · Blog', 'Other'];
  var NO_CITY_PREFIX = '— no city';   // the national / online-untracked bucket key prefix

  function bookedSet(win) { return new Set(BOOKED_SET[win] || BOOKED_SET.ever); }
  // canonical channel name (the cube already emits canonical names; this guards legacy 'Google')
  function channelOf(ch) { return ch === 'Google' ? 'Google Ads' : (ch || 'Other'); }
  function isNoCity(cityKey) { return ('' + cityKey).indexOf(NO_CITY_PREFIX) === 0; }

  // does a cell pass the breakdown filters?  filters = {md,int,istr,cat,num,ch} (each 'All'/undefined = no filter)
  function cellPass(cell, f) {
    if (!f) return true;
    if (f.md && f.md !== 'All' && cell.md !== f.md) return false;
    if (f.ch && f.ch !== 'All' && channelOf(cell.ch) !== f.ch) return false;
    if (f.int && f.int !== 'All' && (cell.int || '') !== f.int) return false;
    if (f.istr && f.istr !== 'All' && (cell.istr || '') !== f.istr) return false;
    if (f.cat && f.cat !== 'All' && (cell.cat || 'na') !== f.cat) return false;
    if (f.num && f.num !== 'All' && (cell.num || '') !== f.num) return false;
    return true;
  }

  // Aggregate a flat list of cells into weekly series + per-dimension breakdown maps. Returns arrays in the
  // cube's own week order (NEWEST-first). Caller remaps to its own axis if needed (see remap()).
  //   opts = { bookwin:'ever'|'2wk'|'week', filters:{…} }
  //   returns.by = { channel, medium, intent, strength, category, status, number } — each a {value:[N]} map
  //   (mirrors the bookings-funnel leads pivot's dimensions so both pages break leads down identically)
  function aggregate(cells, opts) {
    opts = opts || {};
    var bs = bookedSet(opts.bookwin || 'ever'), f = opts.filters || null;
    var N = (cells[0] && cells[0].w && cells[0].w.length) || 26;
    var leads = new Array(N).fill(0), booked = new Array(N).fill(0), byChannel = {};
    var by = { channel: byChannel, medium: {}, intent: {}, strength: {}, category: {}, status: {}, number: {} };
    var bookedBy = { channel: {}, medium: {}, intent: {}, strength: {}, category: {} };   // BOOKED-only per dim → lets callers compute L2B by any dimension
    function bump(map, key, i, v) { var a = map[key] || (map[key] = new Array(N).fill(0)); a[i] += v; }
    for (var ci = 0; ci < cells.length; ci++) {
      var c = cells[ci];
      if (!cellPass(c, f)) continue;
      var bk = bs.has(c.bk), w = c.w || [];
      var ch = channelOf(c.ch), md = c.md || 'na', it = c.int || 'na', st = c.istr || 'na', ca = c.cat || 'na';
      var status = bk ? 'booked' : 'not booked', num = c.num || '(not a call)';
      for (var i = 0; i < N; i++) {
        var v = w[i] || 0; if (!v) continue;
        leads[i] += v; if (bk) booked[i] += v;
        bump(byChannel, ch, i, v); bump(by.medium, md, i, v); bump(by.intent, it, i, v);
        bump(by.strength, st, i, v); bump(by.category, ca, i, v); bump(by.status, status, i, v); bump(by.number, num, i, v);
        if (bk) { bump(bookedBy.channel, ch, i, v); bump(bookedBy.medium, md, i, v); bump(bookedBy.intent, it, i, v); bump(bookedBy.strength, st, i, v); bump(bookedBy.category, ca, i, v); }
      }
    }
    var notbooked = leads.map(function (v, i) { return v - (booked[i] || 0); });
    var bookRate = leads.map(function (v, i) { return v ? 100 * booked[i] / v : 0; });   // 0-100
    return { weeks: N, by_channel: byChannel, by: by, bookedBy: bookedBy, leads: leads, booked: booked, notbooked: notbooked, book_rate: bookRate };
  }

  // remap a NEWEST-first cube array to a target week axis (e.g. the diagnostic's OLDEST-first D.weeks)
  //   cubeWeeks: the cube _meta.weeks (newest-first) ; targetWeeks: destination axis
  function weekMap(cubeWeeks, targetWeeks) { return cubeWeeks.map(function (w) { return targetWeeks.indexOf(w); }); }
  function remap(srcArr, map, targetLen) {
    var out = new Array(targetLen).fill(0);
    for (var i = 0; i < map.length; i++) { var di = map[i]; if (di >= 0) out[di] = srcArr[i] || 0; }
    return out;
  }

  // ---- scope selection: pull the cells for a scope out of a city-keyed cube ----
  // scope = { cities:Set|null, clinics:Set<'City|Locality'>|null, national:bool, cityLevel:bool }
  //   cities   : include real cities in this set (all their cells)         null = all cities
  //   clinics  : include only these 'City|Locality' clinic cells
  //   national : include the no-city bucket
  //   cityLevel: include loc-empty ("no clinic") cells for the in-scope cities
  // Returns { cells:[…], flags:[…] } — flags lists any unsupported request so callers never silently default.
  function selectCells(cube, scope) {
    scope = scope || {};
    var cells = [], flags = [];
    for (var key in cube) {
      if (key === '_meta') continue;
      var no = isNoCity(key);
      var list = (cube[key].cells) || [];
      for (var i = 0; i < list.length; i++) {
        var cell = list[i];
        if (no) { if (scope.national !== false) cells.push(cell); continue; }
        // real city
        if (scope.cities && !scope.cities.has(key)) continue;
        if (cell.loc) {
          if (scope.clinics) { if (!scope.clinics.has(key + '|' + cell.loc)) continue; }
          cells.push(cell);
        } else {
          // city-level (no clinic). If clinics filter is active, these have no clinic → excluded.
          if (scope.clinics) continue;
          if (scope.cityLevel === false) continue;
          cells.push(cell);
        }
      }
    }
    return { cells: cells, flags: flags };
  }

  root.LeadsCube = {
    VERSION: VERSION,
    BOOKED_SET: BOOKED_SET,
    CHANNELS: CHANNELS,
    NO_CITY_PREFIX: NO_CITY_PREFIX,
    bookedSet: bookedSet,
    channelOf: channelOf,
    isNoCity: isNoCity,
    cellPass: cellPass,
    aggregate: aggregate,
    selectCells: selectCells,
    weekMap: weekMap,
    remap: remap
  };
})(typeof module !== 'undefined' && module.exports ? module.exports : (typeof window !== 'undefined' ? window : this));
