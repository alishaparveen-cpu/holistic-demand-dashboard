/* ============================================================================
 * bookings-cube.js  ·  SHARED SC-bookings computation — the single source of truth.
 * The DATA is data_bookings_funnel.json (offline, built by the SC-bookings builder)
 * + data_sc_bookings_online.json (online telehealth, merged with on:1). This module is
 * the ONE place SC-bookings metrics + attribution breakdowns are derived, so
 * bookings-funnel.html and marketing-diagnostic.html can never drift.
 *
 * WHAT "SC BOOKINGS" MEANS HERE (important — two definitions coexist by design):
 *   • This cube is the LEAD-DRIVEN ACQUISITION funnel: a booking that traces to the
 *     acquisition path (phone_rank=1 style, first-in-window). ptype ∈ new | reattempt | relapse.
 *   • The diagnostic's ops `bookings.total` is ALL-BOOKED/week incl. returning-patient
 *     rebookings that never came from a fresh lead — structurally larger (it has no lead
 *     origin, so this cube cannot reproduce it). See reference_booking_category_definitions.
 *   • The piece that RECONCILES across both is NEW SC (pt='new' ≈ diag new_tw+new_old).
 *     So callers that want a cross-page-matching number use the pt='new' slice; the
 *     by-channel / by-category / by-maturity breakdowns are what the diagnostic gains.
 *
 * SCHEMA  (version 1)
 * ------------------------------------------------------------------------------
 * A cube file = { _meta:{weeks:[26], days?:[…], …}, "<City|Locality>":{cells:[…], _callcat?} }
 *   cell = { pt, la, ch, md, num, cmp, cat, w:[26], on?, loc?, city? }
 *     pt   = ptype: new | reattempt | relapse            (new = the reconciling slice)
 *     la   = maturity/lead-age of the booking: fresh | wk1 | wk2_4 | mo1_3 | mo3
 *     ch   = channel: GMB | Google Ads | Meta | Practo | Organic | Walk-in | Other
 *     md   = medium: call | web | …          num = exophone ('' = not a call)
 *     cmp  = campaign ('na' = none)          cat = category (SH/STI/MH/Other/na/unknown)
 *     w    = 26 weekly counts (NEWEST-first, aligned with the leads cube)
 *     on   = 1 → online (telehealth, merged from the online SC cube)
 *     loc/city = set only on city/national ROLLUP cells (raw per-clinic cells omit them)
 * ------------------------------------------------------------------------------
 * ========================================================================== */
(function (root) {
  'use strict';
  var VERSION = 1;

  var PTYPES = ['new', 'reattempt', 'relapse'];
  var MATURITY = ['fresh', 'wk1', 'wk2_4', 'mo1_3', 'mo3'];
  var CHANNELS = ['GMB', 'Google Ads', 'Meta', 'Practo', 'Organic', 'Walk-in', 'Other'];
  var NO_CITY_PREFIX = '— no city';

  // canonical channel name (guards the legacy 'Google' token); reuse LeadsCube's if loaded, so the
  // two modules can never disagree on channel naming.
  function channelOf(ch) {
    if (root.LeadsCube && root.LeadsCube.channelOf) return root.LeadsCube.channelOf(ch);
    return ch === 'Google' ? 'Google Ads' : (ch || 'Other');
  }
  function isNoCity(cityKey) { return ('' + cityKey).indexOf(NO_CITY_PREFIX) === 0; }
  function isOnline(cell) { return !!cell.on || cell.city === 'Online'; }

  // does a cell pass the filters?  f = {seg,ptype,channel,maturity,medium,category,campaign,num}
  //   seg: 'offline' | 'online' | 'both'  (each other key: 'All'/undefined = no filter)
  function cellPass(cell, f) {
    if (!f) return true;
    if (f.seg && f.seg !== 'both' && ((f.seg === 'online') !== isOnline(cell))) return false;
    if (f.ptype && f.ptype !== 'All' && cell.pt !== f.ptype) return false;
    if (f.channel && f.channel !== 'All' && channelOf(cell.ch) !== f.channel) return false;
    if (f.maturity && f.maturity !== 'All' && (cell.la || 'na') !== f.maturity) return false;
    if (f.medium && f.medium !== 'All' && cell.md !== f.medium) return false;
    if (f.category && f.category !== 'All' && (cell.cat || 'na') !== f.category) return false;
    if (f.campaign && f.campaign !== 'All' && (cell.cmp || 'na') !== f.campaign) return false;
    if (f.num && f.num !== 'All' && (cell.num || '') !== f.num) return false;
    return true;
  }

  // Aggregate a flat list of cells into weekly series + attribution breakdowns. Arrays are in the
  // cube's own week order (NEWEST-first); the caller remaps to its axis via remap().
  //   opts = { filters:{…} }.  Set filters.ptype='new' for the cross-page-reconciling SC number.
  function aggregate(cells, opts) {
    opts = opts || {};
    var f = opts.filters || null;
    var N = (cells[0] && cells[0].w && cells[0].w.length) || 26;
    var total = new Array(N).fill(0);
    var byCh = {}, byCat = {}, byLa = {}, byPt = {}, byMd = {};
    function bump(map, key, i, v) { var a = map[key] || (map[key] = new Array(N).fill(0)); a[i] += v; }
    for (var ci = 0; ci < cells.length; ci++) {
      var c = cells[ci];
      if (!cellPass(c, f)) continue;
      var w = c.w || [], ch = channelOf(c.ch), cat = c.cat || 'na', la = c.la || 'na', pt = c.pt || 'na', md = c.md || 'na';
      for (var i = 0; i < N; i++) {
        var v = w[i] || 0; if (!v) continue;
        total[i] += v; bump(byCh, ch, i, v); bump(byCat, cat, i, v); bump(byLa, la, i, v); bump(byPt, pt, i, v); bump(byMd, md, i, v);
      }
    }
    return { weeks: N, total: total, by_channel: byCh, by_category: byCat, by_maturity: byLa, by_ptype: byPt, by_medium: byMd };
  }

  // remap a NEWEST-first cube array to a target week axis (reuse LeadsCube's if loaded)
  function weekMap(cubeWeeks, targetWeeks) {
    if (root.LeadsCube && root.LeadsCube.weekMap) return root.LeadsCube.weekMap(cubeWeeks, targetWeeks);
    return cubeWeeks.map(function (w) { return targetWeeks.indexOf(w); });
  }
  function remap(srcArr, map, targetLen) {
    if (root.LeadsCube && root.LeadsCube.remap) return root.LeadsCube.remap(srcArr, map, targetLen);
    var out = new Array(targetLen).fill(0);
    for (var i = 0; i < map.length; i++) { var di = map[i]; if (di >= 0) out[di] = srcArr[i] || 0; }
    return out;
  }

  // ---- scope selection: pull the cells for a scope out of a City|Locality-keyed cube ----
  // scope = { cities:Set|null, clinics:Set<'City|Locality'>|null, national:bool }
  // Returns { cells:[…], flags:[…] }.
  function selectCells(cube, scope) {
    scope = scope || {};
    var cells = [], flags = [];
    for (var key in cube) {
      if (key === '_meta') continue;
      var no = isNoCity(key);
      var parts = ('' + key).split('|'), city = parts[0], loc = parts[1] || '';
      var list = (cube[key].cells) || [];
      for (var i = 0; i < list.length; i++) {
        var cell = list[i];
        if (no) { if (scope.national !== false) cells.push(cell); continue; }
        if (scope.cities && !scope.cities.has(city)) continue;
        if (scope.clinics && !scope.clinics.has(key)) continue;
        cells.push(cell);
      }
    }
    return { cells: cells, flags: flags };
  }

  root.BookingsCube = {
    VERSION: VERSION,
    PTYPES: PTYPES,
    MATURITY: MATURITY,
    CHANNELS: CHANNELS,
    NO_CITY_PREFIX: NO_CITY_PREFIX,
    channelOf: channelOf,
    isNoCity: isNoCity,
    isOnline: isOnline,
    cellPass: cellPass,
    aggregate: aggregate,
    selectCells: selectCells,
    weekMap: weekMap,
    remap: remap
  };
})(typeof module !== 'undefined' && module.exports ? module.exports : (typeof window !== 'undefined' ? window : this));
