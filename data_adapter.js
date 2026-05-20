/* =========================================================
   Real-data adapter — fetches data.json from Redshift export
   and mutates the dashboard's CITIES / CLINICS / BOOKINGS in
   place. Falls back silently to the synthetic data if fetch
   fails (offline / file missing).
   ========================================================= */
(function(){
  // Lat/lng for cities that appear in real data. Add new entries as clinics open.
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
  };
  // Tier 1 = top 8 metros by population. Everything else is Tier 2.
  const T1 = new Set(['Bangalore','Mumbai','Delhi','Hyderabad','Chennai','Kolkata','Pune','Ahmedabad']);
  // utm_source → dashboard channel id (matches existing CHANNELS list).
  const SOURCE_TO_CHAN = {
    'organic':'organic', 'google':'google',
    'gmb':'google_gmb', 'googlelisting':'google_gmb',
    'fb':'fb', 'ig':'fb',
    'practo':'practo',
    'justdial':'justdial',
  };
  // tag_type → category id.
  const TAG_TO_CAT = {
    'ed_plus':'sh', 'pe_plus':'sh', 'ed_plus_pe_plus':'sh',
    'sti':'sti',
    'others':'mh',  // mental-health bucket as proxy
  };
  function mapChan(src){ return SOURCE_TO_CHAN[src] || 'others'; }
  function mapCat(tag){  return TAG_TO_CAT[tag]    || 'mh'; }

  function slugCity(name){
    if (!name) return 'online';
    return String(name).toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g,'') || 'unknown';
  }
  function normCity(c){ return c && c.city ? c.city : 'Online'; }

  // Apply real data in-place to the dashboard globals defined in index.html.
  window.__applyRealData = function(real){
    const todayStr = new Date().toISOString().slice(0,10);
    // ---- 1. CITIES: derived from unique clinic.city values (null city → "Online") ----
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

    // ---- 2. CLINICS: 1-to-1 with real data ----
    CLINICS.length = 0;
    const clinicIdMap = {};
    real.clinics.forEach((c, idx) => {
      const cityId = slugCity(normCity(c));
      const slug = `${cityId}-${idx+1}`;
      clinicIdMap[c.id] = slug;
      CLINICS.push({
        id: slug, realId: c.id, code: c.code,
        name: (c.name || c.code || 'Clinic').replace(/_Allo_?Clinic$/i, '').replace(/_/g,' ').trim(),
        cityId, capacity: 0,
        trend: 0, catShare:{sh:1,sti:0,mh:0}, chShare:{},
      });
    });

    // ---- 3. Build daily channel & category mix tables (global, per day) ----
    const leadsByDay = {}; // d → {chId → leads}
    for (const r of real.leads){
      const d = r.d;
      if (!leadsByDay[d]) leadsByDay[d] = {};
      const chId = mapChan(r.source);
      leadsByDay[d][chId] = (leadsByDay[d][chId] || 0) + r.leads;
    }
    const catByDay = {}; // d → {catId → count}
    for (const r of real.category){
      const d = r.d;
      if (!catByDay[d]) catByDay[d] = {};
      const catId = mapCat(r.tag_type);
      catByDay[d][catId] = (catByDay[d][catId] || 0) + r.n;
    }

    // ---- 4. Build daily bookings index: realClinicId → {dateStr → {bookings, done}} ----
    const bookIdx = {};
    for (const r of real.bookings){
      if (!bookIdx[r.location_id]) bookIdx[r.location_id] = {};
      bookIdx[r.location_id][r.d] = {bookings: r.bookings, done: r.done};
    }

    // ---- 5. Generate per-clinic daily series in BOOKINGS shape ----
    const DAYS = real.lookback_days || 180;
    const today = new Date();
    today.setHours(0,0,0,0);
    const allDatesNew = [];
    for (let i = DAYS-1; i >= 0; i--){
      const d = new Date(today); d.setDate(d.getDate() - i);
      allDatesNew.push(d);
    }
    // Update globals used elsewhere. TODAY/DAYS are `let`-declared in index.html so we
    // poke them via globalThis (works because the script is at module top-level scope).
    try { globalThis.TODAY = today; } catch(e){}
    try { globalThis.DAYS  = DAYS;  } catch(e){}
    if (typeof allDates !== 'undefined'){
      allDates.length = 0;
      allDatesNew.forEach(d => allDates.push(d));
    }

    Object.keys(BOOKINGS).forEach(k => delete BOOKINGS[k]);
    const clinicTrend = {};
    const clinicCapacity = {};
    const totalCatCounts = {sh:0, sti:0, mh:0};
    const totalChCounts = {};

    for (const cl of CLINICS){
      const series = [];
      let prior90Total = 0, recent14Total = 0;
      const idx = bookIdx[cl.realId] || {};
      for (let i = 0; i < DAYS; i++){
        const d = allDatesNew[i];
        const dStr = d.toISOString().slice(0,10);
        const rec = idx[dStr] || {bookings:0, done:0};
        const total = rec.bookings;
        const done  = rec.done;
        // Channel mix from leads on that day; if no leads, default 100% organic
        const lD = leadsByDay[dStr] || {};
        const lSum = Object.values(lD).reduce((s,v)=>s+v, 0);
        const byCh = {};
        ['google','practo','fb','google_gmb','organic','justdial','others'].forEach(ch => {
          byCh[ch] = lSum > 0 ? total * ((lD[ch] || 0) / lSum) : (ch === 'organic' ? total : 0);
        });
        // Category mix from diagnosis tags on that day
        const cD = catByDay[dStr] || {};
        const cSum = (cD.sh||0) + (cD.sti||0) + (cD.mh||0);
        const byCat = {
          sh:  cSum > 0 ? total * ((cD.sh || 0) / cSum)  : total,
          sti: cSum > 0 ? total * ((cD.sti||0) / cSum)   : 0,
          mh:  cSum > 0 ? total * ((cD.mh ||0) / cSum)   : 0,
        };
        // Leads attributed to this clinic, proportional to its share of total bookings that day
        // (real leads are not joinable to clinic; this is a reasonable allocation)
        const leadsForClinic = lSum; // store as global daily and let downstream code apportion
        // Expected = 14-day moving average of bookings (smooth target line)
        let expected = total;
        if (i >= 14){
          let win = 0; for (let j=i-14;j<i;j++) win += series[j].total;
          expected = win / 14 || total;
        }
        series.push({
          date: d, total, expected,
          byCat, byCh,
          leads: leadsForClinic * (total / Math.max(lSum, 1)) * 4, // ~4x bookings as proxy
          done,
        });
        if (i < DAYS - 14) prior90Total += total;
        else recent14Total += total;
      }
      BOOKINGS[cl.id] = series;
      // Compute clinic capacity and trend from real series
      const dailyAvg = series.reduce((s,r)=>s+r.total,0) / DAYS;
      clinicCapacity[cl.id] = Math.max(dailyAvg, 0.5);
      const priorAvg = prior90Total / Math.max(DAYS-14, 1);
      const recentAvg = recent14Total / 14;
      clinicTrend[cl.id] = priorAvg > 0 ? (recentAvg - priorAvg) / priorAvg : 0;
      cl.capacity = clinicCapacity[cl.id];
      cl.trend = clinicTrend[cl.id];
      // Per-clinic catShare = average across days where this clinic had bookings
      let csh=0, csti=0, cmh=0, n=0;
      for (const s of series){
        const t = s.total; if (t <= 0) continue;
        csh += s.byCat.sh / t; csti += s.byCat.sti / t; cmh += s.byCat.mh / t; n++;
        totalCatCounts.sh += s.byCat.sh; totalCatCounts.sti += s.byCat.sti; totalCatCounts.mh += s.byCat.mh;
      }
      cl.catShare = n > 0 ? {sh:csh/n, sti:csti/n, mh:cmh/n} : {sh:1, sti:0, mh:0};
      // Per-clinic chShare = average channel share
      const chSum = {google:0,practo:0,fb:0,google_gmb:0,organic:0,justdial:0,others:0};
      let m=0;
      for (const s of series){
        const t = s.total; if (t <= 0) continue;
        Object.keys(chSum).forEach(k => { chSum[k] += s.byCh[k] / t; });
        m++;
      }
      cl.chShare = m > 0
        ? Object.fromEntries(Object.entries(chSum).map(([k,v])=>[k, v/m]))
        : {google:0,practo:0,fb:0,google_gmb:0,organic:1,justdial:0,others:0};
      Object.entries(cl.chShare).forEach(([k,v]) => { totalChCounts[k] = (totalChCounts[k]||0) + v; });
    }

    // Recompute city baseDaily and trend
    CITIES.forEach(c => {
      const clinics = CLINICS.filter(cl => cl.cityId === c.id);
      c.baseDaily = clinics.reduce((s,cl)=>s+cl.capacity, 0);
      c.trend = clinics.length > 0
        ? clinics.reduce((s,cl)=>s+cl.trend, 0) / clinics.length
        : 0;
    });

    // Refresh STATE.cities and STATE.tiers to match new CITIES
    if (typeof STATE !== 'undefined'){
      STATE.cities = new Set(CITIES.map(c => c.id));
      STATE.tiers  = new Set(CITIES.map(c => c.tier));
      // Cap default lookback so real data (180 days) renders sensibly
      if (STATE.gran === 'week' && STATE.periods > 12) STATE.periods = 4;
    }

    console.log(`[real-data] applied ${CITIES.length} cities, ${CLINICS.length} clinics, ${DAYS} days`);
    return true;
  };

  // Fetch + apply on init. Caller awaits this before initMap/renderAll.
  window.__loadRealData = async function(url){
    try {
      const r = await fetch(url || 'data.json', {cache:'no-cache'});
      if (!r.ok) throw new Error('HTTP ' + r.status);
      const real = await r.json();
      window.__REAL_DATA = real;
      return real;
    } catch(e){
      console.warn('[real-data] using synthetic fallback:', e.message);
      return null;
    }
  };
})();
