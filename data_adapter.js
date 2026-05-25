/* =========================================================
   Real-data adapter — fetches data.json from Redshift export
   and populates the dashboard's CITIES / CLINICS / BOOKINGS.
   Handles both schemas:
   - NEW: uses `clinic_source_diagnosis` (per-appt rollup, has
     total_done / tagged_done / sti_done / sh_done / others_done)
     and `leads_by_clinic` (lead attributed to first appt's clinic).
   - OLD: falls back to `clinic_source_category` (tag-fanned-out)
     and network-only `leads` (per-clinic leads approximated).
   On fetch failure, throws — no synthetic fallback (the dashboard
   shows the error so users know they're not looking at fake data).
   ========================================================= */
(function(){
  const CITY_LATLNG = {
    'Bangalore':    [12.9716, 77.5946], 'Mumbai':       [19.0760, 72.8777],
    'Delhi':        [28.6139, 77.2090], 'Hyderabad':    [17.3850, 78.4867],
    'Chennai':      [13.0827, 80.2707], 'Kolkata':      [22.5726, 88.3639],
    'Pune':         [18.5204, 73.8567], 'Ahmedabad':    [23.0225, 72.5714],
    'Jaipur':       [26.9124, 75.7873], 'Lucknow':      [26.8467, 80.9462],
    'Chandigarh':   [30.7333, 76.7794], 'Kochi':        [9.9312,  76.2673],
    'Coimbatore':   [11.0168, 76.9558], 'Mysuru':       [12.2958, 76.6394],
    'Nagpur':       [21.1458, 79.0882], 'Nashik':       [19.9975, 73.7898],
    'Navi Mumbai':  [19.0330, 73.0297], 'Aurangabad':   [19.8762, 75.3433],
    'Bhopal':       [23.2599, 77.4126], 'Gandhinagar':  [23.2156, 72.6369],
    'Mangaluru':    [12.9141, 74.8560], 'Amravati':     [20.9374, 77.7796],
    'Hubli':        [15.3647, 75.1240], 'Practo Online':[20.5937, 78.9629],
    'Visakhapatnam':[17.6868, 83.2185], 'Surat':        [21.1702, 72.8311],
    'Ranchi':       [23.3441, 85.3096], 'Vijayawada':   [16.5062, 80.6480],
  };
  const T1 = new Set(['Bangalore','Mumbai','Delhi','Hyderabad','Chennai','Kolkata','Pune','Ahmedabad']);

  function slugCity(name){
    if (!name) return 'online';
    return String(name).toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g,'') || 'unknown';
  }
  function normCity(c){ return c && c.city ? c.city : 'Online'; }
  function ymd(d){ return d.toISOString().slice(0,10); }

  // Migrate OLD-schema `clinic_source_category` rows (one row per tag, with `tag_type` and `done`)
  // into NEW-schema `clinic_source_diagnosis` shape (one row per day×clinic×source, with
  // total_done/tagged_done/sti_done/sh_done/others_done). Old query INNER-JOIN'd to tags so
  // tagged_done == sum of all tag rows (best we can derive); total_done is unknowable from
  // OLD alone, so we approximate it from the `bookings` table.
  function migrateOldSchema(real){
    if (!real.clinic_source_category) return [];
    const SH_TAGS = new Set(['ed_plus','pe_plus','ed_plus_pe_plus']);
    const grouped = {};  // key: d|loc|src → {total_done, tagged_done, sti_done, sh_done, others_done}
    for (const r of real.clinic_source_category){
      const key = `${r.d}|${r.location_id}|${r.source}`;
      if (!grouped[key]) grouped[key] = {
        d: r.d, location_id: r.location_id, source: r.source,
        total_done: 0, tagged_done: 0, sti_done: 0, sh_done: 0, others_done: 0,
      };
      const g = grouped[key];
      // OLD schema: each `done` is COUNT(DISTINCT appt_id) for THIS tag. Sum across tags
      // overstates appts with multiple tags but is still our only signal for tagged_done.
      g.tagged_done += r.done;
      if (r.tag_type === 'sti') g.sti_done += r.done;
      else if (SH_TAGS.has(r.tag_type)) g.sh_done += r.done;
      else g.others_done += r.done;
    }
    // total_done from bookings table (truth)
    const bookDone = {};
    for (const r of (real.bookings||[])){
      const k = `${r.d}|${r.location_id}`;
      bookDone[k] = (bookDone[k]||0) + (r.done||0);
    }
    // Allocate total_done proportionally across rows that share day+clinic (split by source via tagged_done share)
    const sumByDayLoc = {};
    Object.values(grouped).forEach(g => {
      const k = `${g.d}|${g.location_id}`;
      sumByDayLoc[k] = (sumByDayLoc[k]||0) + g.tagged_done;
    });
    Object.values(grouped).forEach(g => {
      const k = `${g.d}|${g.location_id}`;
      const dayLocTotal = bookDone[k] || g.tagged_done;
      const share = sumByDayLoc[k] > 0 ? g.tagged_done / sumByDayLoc[k] : 0;
      g.total_done = Math.round(dayLocTotal * share);
      // tagged_done capped at total_done (avoids fan-out artifact)
      if (g.tagged_done > g.total_done) g.tagged_done = g.total_done;
    });
    return Object.values(grouped);
  }

  window.__applyRealData = function(real){
    // ---- 0. Schema normalization ----
    const csd = (real.clinic_source_diagnosis && real.clinic_source_diagnosis.length)
      ? real.clinic_source_diagnosis
      : migrateOldSchema(real);
    const haveLeadsByClinic = !!(real.leads_by_clinic && real.leads_by_clinic.length);

    // ---- 1. CITIES from unique clinic.city ----
    const cityNames = [...new Set(real.clinics.map(c => normCity(c)))].sort();
    CITIES.length = 0;
    cityNames.forEach(name => {
      const ll = CITY_LATLNG[name] || [20.5937, 78.9629];
      CITIES.push({
        id: slugCity(name),
        name,
        lat: ll[0], lng: ll[1],
        clinicCount: real.clinics.filter(c => normCity(c) === name).length,
        baseDaily: 0,
        trend: 0,
        tier: T1.has(name) ? 't1' : 't2',
      });
    });

    // ---- 2. CLINICS — 1:1 with real data ----
    CLINICS.length = 0;
    real.clinics.forEach((c, idx) => {
      const cityId = slugCity(normCity(c));
      const slug = `${cityId}-${idx+1}`;
      // Maturity: from clinic created_at (if present) → days since launch
      let ageDays = null;
      if (c.created_at){
        try { ageDays = Math.floor((Date.now() - new Date(c.created_at).getTime()) / 86400000); }
        catch(e){}
      }
      CLINICS.push({
        id: slug, realId: c.id, code: c.code,
        name: (c.name || c.code || 'Clinic').replace(/_Allo_?Clinic$/i, '').replace(/_/g,' ').trim(),
        cityId, capacity: 0, trend: 0, ageDays,
        catShare: {sti:0, sh:0, others:0, untagged:0},
        chShare: {},
      });
    });

    // ---- 3. Network leads-by-day-source (used as fallback per-clinic allocation) ----
    const leadsByDay = {};
    for (const r of (real.leads||[])){
      if (!leadsByDay[r.d]) leadsByDay[r.d] = {};
      leadsByDay[r.d][r.source] = (leadsByDay[r.d][r.source] || 0) + r.leads;
    }

    // ---- 4. Per-clinic-per-day-source leads (NEW schema) ----
    // shape: clinicLeads[location_id][dateStr][source] = leads
    const clinicLeads = {};  // by realId
    const unattributedLeads = {}; // by dateStr → {source: leads}
    if (haveLeadsByClinic){
      for (const r of real.leads_by_clinic){
        if (r.location_id == null){
          if (!unattributedLeads[r.d]) unattributedLeads[r.d] = {};
          unattributedLeads[r.d][r.source] = (unattributedLeads[r.d][r.source]||0) + r.leads;
          continue;
        }
        if (!clinicLeads[r.location_id]) clinicLeads[r.location_id] = {};
        if (!clinicLeads[r.location_id][r.d]) clinicLeads[r.location_id][r.d] = {};
        clinicLeads[r.location_id][r.d][r.source] = r.leads;
      }
    }

    // ---- 5. Bookings index ----
    const bookIdx = {};
    for (const r of real.bookings){
      if (!bookIdx[r.location_id]) bookIdx[r.location_id] = {};
      bookIdx[r.location_id][r.d] = {bookings: r.bookings, done: r.done, missed: r.missed||0, cancelled: r.cancelled||0};
    }

    // ---- 6. CSD index for per-clinic diagnosis rollup ----
    // csdIdx[location_id][dateStr] = {total_done, tagged_done, sti_done, sh_done, others_done, bySource:{src→{...}}}
    const csdIdx = {};
    for (const r of csd){
      if (!csdIdx[r.location_id]) csdIdx[r.location_id] = {};
      if (!csdIdx[r.location_id][r.d]){
        csdIdx[r.location_id][r.d] = {
          total_done: 0, tagged_done: 0, sti_done: 0, sh_done: 0, others_done: 0,
          bySource: {},
        };
      }
      const x = csdIdx[r.location_id][r.d];
      x.total_done   += r.total_done   || 0;
      x.tagged_done  += r.tagged_done  || 0;
      x.sti_done     += r.sti_done     || 0;
      x.sh_done      += r.sh_done      || 0;
      x.others_done  += r.others_done  || 0;
      x.bySource[r.source] = {
        total_done:   r.total_done   || 0,
        tagged_done:  r.tagged_done  || 0,
        sti_done:     r.sti_done     || 0,
        sh_done:      r.sh_done      || 0,
        others_done:  r.others_done  || 0,
      };
    }

    // ---- 7. Build dates ----
    const DAYS = real.lookback_days || 180;
    const today = new Date(); today.setHours(0,0,0,0);
    const allDatesNew = [];
    for (let i = DAYS-1; i >= 0; i--){
      const d = new Date(today); d.setDate(d.getDate() - i);
      allDatesNew.push(d);
    }
    try { globalThis.TODAY = today; } catch(e){}
    try { globalThis.DAYS  = DAYS;  } catch(e){}
    if (typeof allDates !== 'undefined'){
      allDates.length = 0;
      allDatesNew.forEach(d => allDates.push(d));
    }

    // ---- 8. Per-clinic daily series in BOOKINGS shape ----
    Object.keys(BOOKINGS).forEach(k => delete BOOKINGS[k]);

    const CH_IDS = (typeof CHANNELS !== 'undefined' ? CHANNELS.map(c=>c.id) : []);

    for (const cl of CLINICS){
      const series = [];
      let prior90Total = 0, recent14Total = 0;
      const bIdx = bookIdx[cl.realId] || {};
      const cIdx = csdIdx[cl.realId] || {};
      const lIdx = clinicLeads[cl.realId] || {};

      for (let i = 0; i < DAYS; i++){
        const d = allDatesNew[i];
        const dStr = ymd(d);
        const b = bIdx[dStr] || {bookings:0, done:0, missed:0, cancelled:0};
        const total = b.bookings;
        const done = b.done;
        const c = cIdx[dStr] || {total_done:done, tagged_done:0, sti_done:0, sh_done:0, others_done:0, bySource:{}};

        // Diagnosis breakdown: byCat counts done by category, including "untagged" as a real bucket
        const tagged = c.tagged_done;
        const untagged = Math.max(0, done - tagged);
        const byCat = {
          sti:      c.sti_done,
          sh:       c.sh_done,
          others:   c.others_done,
          untagged: untagged,
        };

        // Channel allocation: prefer per-clinic real leads; else fall back to bySource done; else day-network leads
        const byCh = {};
        CH_IDS.forEach(ch => byCh[ch] = 0);
        const todayLeads = lIdx[dStr];
        if (todayLeads){
          Object.entries(todayLeads).forEach(([src, n]) => {
            if (byCh.hasOwnProperty(src)) byCh[src] = n;
            else byCh.other = (byCh.other||0) + n;
          });
        } else if (Object.keys(c.bySource).length){
          // Distribute bookings by clinic's per-source done share
          const total_src = Object.values(c.bySource).reduce((s,v)=>s+v.total_done, 0) || 1;
          Object.entries(c.bySource).forEach(([src, vals]) => {
            const share = vals.total_done / total_src;
            const tgt = byCh.hasOwnProperty(src) ? src : 'other';
            byCh[tgt] = (byCh[tgt]||0) + total * share;
          });
        } else {
          // Last resort: network-level lead mix
          const lD = leadsByDay[dStr] || {};
          const lSum = Object.values(lD).reduce((s,v)=>s+v, 0);
          if (lSum > 0){
            CH_IDS.forEach(src => {
              byCh[src] = total * ((lD[src] || 0) / lSum);
            });
          } else {
            byCh.organic = total;
          }
        }

        // Lead count for this clinic
        const leads = todayLeads ? Object.values(todayLeads).reduce((s,v)=>s+v,0) : 0;

        // Expected = 14d moving avg
        let expected = total;
        if (i >= 14){
          let win = 0; for (let j=i-14;j<i;j++) win += series[j].total;
          expected = win / 14 || total;
        }

        series.push({date:d, total, expected, byCat, byCh, leads, done, missed:b.missed, cancelled:b.cancelled,
                     sti_done:c.sti_done, sh_done:c.sh_done, others_done:c.others_done, tagged_done:c.tagged_done});
        if (i < DAYS - 14) prior90Total += total;
        else recent14Total += total;
      }
      BOOKINGS[cl.id] = series;

      const dailyAvg = series.reduce((s,r)=>s+r.total,0) / DAYS;
      cl.capacity = Math.max(dailyAvg, 0.5);
      const priorAvg = prior90Total / Math.max(DAYS-14, 1);
      const recentAvg = recent14Total / 14;
      cl.trend = priorAvg > 0 ? (recentAvg - priorAvg) / priorAvg : 0;

      // catShare from totals (not averages) — more accurate
      const totDone = series.reduce((s,r)=>s+r.done, 0) || 1;
      cl.catShare = {
        sti:      series.reduce((s,r)=>s+r.byCat.sti, 0) / totDone,
        sh:       series.reduce((s,r)=>s+r.byCat.sh, 0) / totDone,
        others:   series.reduce((s,r)=>s+r.byCat.others, 0) / totDone,
        untagged: series.reduce((s,r)=>s+r.byCat.untagged, 0) / totDone,
      };
      cl.tagCoverage = totDone > 0
        ? series.reduce((s,r)=>s+r.tagged_done, 0) / totDone
        : 0;

      // chShare from totals
      const totBkg = series.reduce((s,r)=>s+r.total, 0) || 1;
      cl.chShare = {};
      CH_IDS.forEach(ch => {
        cl.chShare[ch] = series.reduce((s,r)=>s+(r.byCh[ch]||0), 0) / totBkg;
      });
    }

    // ---- 9. City rollup ----
    CITIES.forEach(c => {
      const clinics = CLINICS.filter(cl => cl.cityId === c.id);
      c.baseDaily = clinics.reduce((s,cl)=>s+cl.capacity, 0);
      c.trend = clinics.length > 0
        ? clinics.reduce((s,cl)=>s+cl.trend, 0) / clinics.length
        : 0;
    });

    // ---- 10. State refresh ----
    if (typeof STATE !== 'undefined'){
      STATE.cities = new Set(CITIES.map(c => c.id));
      STATE.tiers  = new Set(CITIES.map(c => c.tier));
      if (STATE.gran === 'week' && STATE.periods > 12) STATE.periods = 4;
    }

    // ---- 11. Network-level coverage stat (for footer) ----
    const netDone = CLINICS.reduce((s,cl) => s + (BOOKINGS[cl.id]||[]).reduce((a,r)=>a+r.done,0), 0);
    const netTagged = CLINICS.reduce((s,cl) => s + (BOOKINGS[cl.id]||[]).reduce((a,r)=>a+r.tagged_done,0), 0);
    window.__NETWORK_COVERAGE = netDone > 0 ? netTagged / netDone : 0;

    console.log(`[real-data] ${CITIES.length} cities · ${CLINICS.length} clinics · ${DAYS}d · tag coverage ${(window.__NETWORK_COVERAGE*100).toFixed(1)}% · schema=${csd === real.clinic_source_diagnosis ? 'new' : 'migrated-from-old'}`);
    return true;
  };

  window.__loadRealData = async function(url){
    const r = await fetch(url || 'data.json', {cache:'no-cache'});
    if (!r.ok) throw new Error(`Failed to load data.json: HTTP ${r.status}. Run build_data.py to regenerate.`);
    const real = await r.json();
    window.__REAL_DATA = real;
    return real;
  };
})();
