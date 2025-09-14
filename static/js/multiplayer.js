// ===== Multiplayer – konfig =====
const ROUND_TIME_SEC = 30; // 30 sek/omgång
const CITY_CENTERS = {
  stockholm: {lat:59.334, lon:18.063},
  goteborg:  {lat:57.707, lon:11.967},
  malmo:     {lat:55.605, lon:13.003},
};

// ===== Hjälp =====
const $ = (s)=>document.querySelector(s);
const esc = (s)=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
async function fetchJson(url, opt){
  const o = opt||{};
  const headers = {'Content-Type':'application/json', ...(o.headers||{})};
  const body = o.body ? JSON.stringify(o.body) : undefined;
  const res = await fetch(url, {...o, headers, body});
  if(!res.ok){ throw new Error((await res.text())||res.statusText); }
  return res.json();
}
function haversineKm(lat1,lon1,lat2,lon2){
  const R=6371,toRad=x=>x*Math.PI/180;
  const dLat=toRad(lat2-lat1), dLon=toRad(lon2-lon1);
  const a=Math.sin(dLat/2)**2+Math.cos(toRad(lat1))*Math.cos(toRad(lat2))*Math.sin(dLon/2)**2;
  return 2*R*Math.asin(Math.sqrt(a));
}

// ===== UI-element =====
const vLobby = $('#mp-lobby');
const vGame  = $('#mp-game');
const vFinal = $('#mp-final');
const gRoundNo = $('#gRoundNo');
const gCode    = $('#gCode');
const mpYou    = $('#mpYou');
const tblBody  = $('#mpRoundTable tbody');  // döljs i MP
const btnNextRound = $('#btnNextRound');    // döljs / används ej i auto-flödet
const btnFinal     = $('#btnFinal');        // döljs helt
const mpTimerEl    = $('#mpTimer');         // döljs (vi visar tid i panelen)

// ===== Global state =====
const S = {
  code: "", nickname: "", city: "", rounds: 5, roundNo: 1,
  players: [], hasGuessed: false, myGuess: null,
  pollTimer: null, countdownTimer: null, timeLeft: ROUND_TIME_SEC,
  mapLocked: false,
  finished: false,
  revealCountdown: null,
  // Sidebar-data
  roundBoards: {},        // { [roundNo]: [{nickname, distance_m}] }
  currentClue: '',
  answerText: null,
  distanceText: null,
  nextRoundLeft: null,    // sekunder till nästa runda/final efter reveal
  roundRevealed: false,   // om facit för aktuell runda är visat
  timeoutPenalty: false,  // om vi fick 50 000 m pga timeout
};

// ===== Lager & städfunktion för rundgrafik =====
function ensureRoundLayer(){
  if (!window.map) return null;
  if (!window.roundLayer) window.roundLayer = L.layerGroup().addTo(window.map);
  return window.roundLayer;
}
function clearRoundGraphics(){
  try{
    if (window.roundLayer) window.roundLayer.clearLayers();
    window.guessMarker = null;
    window.trueMarker  = null;
    window.line        = null;
  }catch{}
}

// ===== Karta: lås/öppna interaktion =====
function setMapLocked(flag){
  S.mapLocked = !!flag;
  if(!window.map) return;
  const m = window.map;
  if(flag){
    m.dragging.disable();
    m.scrollWheelZoom.disable();
    m.doubleClickZoom.disable();
    m.boxZoom.disable();
    m.keyboard.disable();
    if(m.tap) m.tap.disable();
  }else{
    m.dragging.enable();
    m.scrollWheelZoom.enable();
    m.doubleClickZoom.enable();
    m.boxZoom.enable();
    m.keyboard.enable();
    if(m.tap) m.tap.enable();
  }
}

// ===== Dölja singelplayer-grejer och mittentabellen =====
function hideSPBits(){
  const infoBox = $('#info');
  if (infoBox) { try{ infoBox.remove(); }catch{ infoBox.style.display='none'; } }
  const roundTable = document.getElementById('mpRoundTable');
  if (roundTable) roundTable.style.display = 'none';
  if (mpTimerEl) mpTimerEl.style.display = 'none';
  if (btnFinal) btnFinal.style.display = 'none'; // ta bort "Visa slutresultat"
}

// ===== Totals & Sidebar-render =====
function computeTotals(){
  const totals = new Map(); // nickname -> total_m
  Object.entries(S.roundBoards).forEach(([roundNo, arr])=>{
    const rn = Number(roundNo);
    if (!Number.isFinite(rn)) return;
    // räkna bara färdiga rundor; för aktuell runda endast när reveal skett
    if (rn > S.roundNo) return;
    if (rn === S.roundNo && !S.roundRevealed) return;
    (arr||[]).forEach(r=>{
      if (typeof r.distance_m === 'number') {
        totals.set(r.nickname, (totals.get(r.nickname)||0) + r.distance_m);
      }
    });
  });
  return Array.from(totals.entries())
    .map(([nickname, total_m]) => ({nickname, total_m}))
    .sort((a,b)=>a.total_m-b.total_m);
}

function renderSidebar(){
  if (!mpYou) return;

  // Tid (under ronden)
  const t = Math.max(0, S.timeLeft|0);
  const mm = String(Math.floor(t/60)).padStart(2,'0');
  const ss = String(t%60).padStart(2,'0');

  let roundListHtml = '<li>—</li>';
  if (!S.roundRevealed){
    // Visa endast "Klar/Väntar…" under pågående omgång
    const doneSet = new Set((S.roundBoards[S.roundNo]||[]).map(r=>r.nickname));
    const items = (S.players||[]).map(n=>{
      const done = doneSet.has(n);
      return `<li>${esc(n)} – ${done ? 'Klar' : 'Väntar…'}</li>`;
    });
    roundListHtml = items.join('') || '<li>—</li>';
  } else {
    // Visa avstånd först NÄR omgången är klar
    const arr = (S.roundBoards[S.roundNo]||[]).slice().sort((a,b)=>a.distance_m-b.distance_m);
    roundListHtml = arr.map(r=>`<li>${esc(r.nickname)} – ${r.distance_m} m</li>`).join('') || '<li>—</li>';
  }

  // Totalt (utan extra "1.")
  const totals = computeTotals();
  const totalsList = totals.map(r=>`<li>${esc(r.nickname)} – ${r.total_m} m</li>`).join('') || '<li>—</li>';

  // Facit/avstånd
  const answerBlock = S.answerText ? `
    <div class="row"><span class="lbl">Rätt adress:</span> <span>${esc(S.answerText)}</span></div>
    <div class="row"><span class="lbl">Ditt avstånd:</span> <span>${esc(S.distanceText||'')}</span></div>
    <div style="height:8px"></div>
  ` : '';

  // “Ny runda / slutresultat om …”
  const nextMsg = (S.nextRoundLeft!=null)
    ? `<div class="sub"><em>${S.roundNo >= S.rounds ? 'Slutresultat visas om' : 'Ny runda startar om'}: ${S.nextRoundLeft}s</em></div>`
    : '';

  // OBS: Vi visar inte "Runda • Kod" här (rubriken finns redan större ovanför)
  mpYou.innerHTML = `
    <div class="mp-panel">
      <div class="row"><span class="lbl">Ledtråd:</span> <span id="mpClueText">${esc(S.currentClue||'')}</span></div>
      <div class="row"><span class="lbl">Tid:</span> <span id="mpTimeText">${mm}:${ss}</span></div>
      ${answerBlock}
      ${nextMsg}
      <div class="sub">Omgång ${S.roundNo}: resultat</div>
      <ol id="mpRoundBoard">${roundListHtml}</ol>
      <div style="height:10px"></div>
      <div class="sub">Totalställning</div>
      <ol id="mpTotalsBoard">${totalsList}</ol>
    </div>
  `;
}

// ===== Kartklick => gissning =====
window.onMapClick = async (lat, lon) => {
  if (vGame?.style.display==='block' && !S.hasGuessed && !S.mapLocked){
    try{
      const layer = ensureRoundLayer();
      if (window.guessMarker) (layer || window.map).removeLayer(window.guessMarker);
      window.guessMarker = L.marker([lat, lon], { title: 'Din gissning' })
        .addTo(layer || window.map);
    }catch(e){ console.warn('Kunde inte rita egen markör:', e); }
    await sendGuess(lat, lon);
  }
};

// ===== Lobby (visa & polla tills spelet startar) =====
async function enterLobby(){
  clearInterval(S.pollTimer);
  clearInterval(S.countdownTimer);
  if (!S.roundNo) S.roundNo = 1;

  hideSPBits();

  // Nollställ sidebar-data
  S.roundBoards = {};
  S.currentClue = '';
  S.answerText = null;
  S.distanceText = null;
  S.nextRoundLeft = null;
  S.roundRevealed = false;
  S.timeoutPenalty = false;
  renderSidebar();

  vLobby.style.display = 'block';
  vGame.style.display  = 'none';
  vFinal.style.display = 'none';

  // Visa väntemeddelande i lobbyn
  const msgId = 'mpLobbyMsg';
  const msgEl = document.getElementById(msgId) || (() => {
    const p = document.createElement('p');
    p.id = msgId;
    p.style.marginTop = '12px';
    vLobby.appendChild(p);
    return p;
  })();
  msgEl.innerHTML = `<em>Inväntar att värden ska starta spelet…</em>`;

  // Kolla om ronden redan finns publicerad
  const detectRoundStarted = async () => {
    try{
      const rr = await fetchJson(`/api/match/round?code=${encodeURIComponent(S.code)}&round_no=${S.roundNo}`);
      return !!rr?.round;
    }catch{ return false; }
  };

  // Försök initialt
  try{
    const r = await fetchJson(`/api/match/lobby?code=${encodeURIComponent(S.code)}`);
    if (r?.players) S.players = r.players;
    if (r?.status === 'active' || await detectRoundStarted()){
      return await enterRound();
    }
  }catch{}

  // Polla lobbyn – när status==active ELLER rond hittas -> gå in i runda
  clearInterval(S.pollTimer);
  S.pollTimer = setInterval(async () => {
    try{
      const r = await fetchJson(`/api/match/lobby?code=${encodeURIComponent(S.code)}`);
      if (r?.players) S.players = r.players;
      if (r?.status === 'active' || await detectRoundStarted()){
        clearInterval(S.pollTimer);
        await enterRound();
      }
    }catch{}
  }, 1500);
}

// ===== Starta en runda =====
async function enterRound(){
  clearInterval(S.pollTimer);
  clearInterval(S.countdownTimer);

  // Om vi redan passerat sista rundan -> visa final
  if (S.roundNo > S.rounds) {
    S.finished = true;
    await showFinal();
    return;
  }

  S.hasGuessed = false;
  S.myGuess = null;
  S.answerText = null;
  S.distanceText = null;
  S.nextRoundLeft = null;
  S.roundRevealed = false;
  S.timeoutPenalty = false;

  clearRoundGraphics();
  if (S.revealCountdown){ clearInterval(S.revealCountdown); S.revealCountdown = null; }

  setMapLocked(false);

  vLobby.style.display='none';
  vFinal.style.display='none';
  vGame.style.display='block';

  hideSPBits();

  // säkerställ att kartan lyssnar på klick (bind en gång)
  if (window.map && !window.map._mpClickBound){
    window.map.on('click', e => window.onMapClick(e.latlng.lat, e.latlng.lng));
    window.map._mpClickBound = true;
  }

  gRoundNo.textContent = S.roundNo;
  gCode.textContent    = S.code;

  // HÄMTA rundadata & sätt ledtråd (race-tåligt)
  let r = null;
  try{
    r = await fetchJson(`/api/match/round?code=${encodeURIComponent(S.code)}&round_no=${S.roundNo}`);
  }catch(e){ /* ronden publiceras strax – polling tar över */ }
  S.currentClue = r?.round?.clue || '';
  const clueEl = document.getElementById('clue');
  if (clueEl) clueEl.textContent = S.currentClue ? `Ledtråd: ${S.currentClue}` : 'Väntar på ledtråd…';

  // starta polling direkt (och kör en första uppdatering)
  clearInterval(S.pollTimer);
  S.pollTimer = setInterval(refreshRoundBoard, 2000);
  renderSidebar();
  refreshRoundBoard();

  // starta nedräkning
  startCountdown();
}

// ===== Nedräkning/timeout =====
function startCountdown(){
  S.timeLeft = ROUND_TIME_SEC;
  updateTimer();
  S.countdownTimer = setInterval(()=>{
    S.timeLeft -= 1;
    updateTimer();
    if(S.timeLeft<=0){
      clearInterval(S.countdownTimer);
      if(!S.hasGuessed){
        autoGuessBecauseTimeout(); // timeout -> straffpoäng
      }
    }
  },1000);
}
function updateTimer(){
  renderSidebar(); // uppdatera tiden i panelen
}
async function autoGuessBecauseTimeout(){
  // välj neutral punkt men markera timeout-straff
  let latlon = null;
  if(window.map){
    const c = window.map.getCenter();
    latlon = {lat:c.lat, lon:c.lng};
  }else if(CITY_CENTERS[S.city]){
    latlon = CITY_CENTERS[S.city];
  }else{
    latlon = {lat:59.334, lon:18.063}; // fallback Sthlm
  }
  S.timeoutPenalty = true;
  await sendGuess(latlon.lat, latlon.lon, { timedOut:true });
}

// ===== Skicka gissning =====
async function sendGuess(lat, lon, opt={}){
  try{
    const body = { code:S.code, nickname:S.nickname, lat, lon };
    if (opt.timedOut){ body.timed_out = true; body.penalty_m = 50000; }
    const r = await fetchJson(`/api/match/guess?round_no=${S.roundNo}`, {
      method:'POST',
      body
    });
    S.hasGuessed = true;
    S.myGuess = {lat, lon};
    setMapLocked(true); // LÅS kartan efter gissning
    renderSidebar();
    await refreshRoundBoard();
  }catch(e){
    alert('Kunde inte skicka gissning: ' + e.message);
  }
}

// ===== Live-board för rundan =====
async function refreshRoundBoard(){
  // uppdatera spelare (ifall någon droppat/joinat)
  try{
    const lob = await fetchJson(`/api/match/lobby?code=${encodeURIComponent(S.code)}`);
    if (lob?.players) S.players = lob.players;
  }catch{}

  let res;
  try {
    res = await fetchJson(`/api/match/round_result?code=${encodeURIComponent(S.code)}&round_no=${S.roundNo}`);
    // kasta bort ev. koordinater så vi inte råkar rita motståndares markörer
    if (res && Array.isArray(res.leaderboard)) {
      res.leaderboard = res.leaderboard.map(r => {
        const { nickname, distance_m } = r ?? {};
        return { nickname, distance_m };
      });
    }
  } catch(e) { return; }

  const board = Array.isArray(res?.leaderboard) ? res.leaderboard : [];

  // Normalisera till unika per spelare
  const uniq = Array.from(board.reduce((m, r)=> m.set(r.nickname, r), new Map()).values());
  S.roundBoards[S.roundNo] = uniq;

  renderSidebar(); // uppdatera panelen (utan att visa avstånd om ej reveal)

  // räkna klara
  const doneSet = new Set(uniq.map(r => r.nickname));
  const doneCount = doneSet.size;
  const total = new Set(S.players || []).size;

  if (doneCount >= total && total > 0){
    clearInterval(S.pollTimer);
    clearInterval(S.countdownTimer);
    await showSolutionAndButtons(res);  // auto-reveal + auto-next/final
  }
}

// ===== Facit + nästa/final =====
async function showSolutionAndButtons(res){
  const sol = res?.solution;
  S.roundRevealed = true; // nu får vi visa avstånd i panelen

  // RITA FACIT + DIN GISSNING + LINJE
  if (sol?.lat!=null && sol?.lon!=null){
    try{
      clearRoundGraphics();
      const layer = ensureRoundLayer();

      if (S.myGuess){
        const bearing = (typeof bearingDeg==='function')
          ? bearingDeg(S.myGuess.lat, S.myGuess.lon, sol.lat, sol.lon)
          : 0;
        window.guessMarker = L.marker([S.myGuess.lat, S.myGuess.lon], { icon: makeArrowIcon(bearing), title: 'Du' }).addTo(layer);
      }

      window.trueMarker = L.marker([sol.lat, sol.lon], { icon: makeCheckIcon(), title: 'Facit' }).addTo(layer);

      if (S.myGuess){
        window.line = L.polyline([[S.myGuess.lat, S.myGuess.lon],[sol.lat, sol.lon]], { weight: 2 }).addTo(layer);
        map.fitBounds(window.line.getBounds(), { padding:[30,30] });
      }
    }catch{}

    if (S.myGuess){
      if (S.timeoutPenalty){
        // tvinga 50 000 m lokalt (och i totals), om servern inte redan gjort det
        const arr = S.roundBoards[S.roundNo] || [];
        const idx = arr.findIndex(r=>r.nickname===S.nickname);
        const rec = { nickname:S.nickname, distance_m:50000 };
        if (idx>=0) arr[idx] = rec; else arr.push(rec);
        S.roundBoards[S.roundNo] = arr;
        S.answerText = (sol.address || '').trim() || null;
        S.distanceText = `50.00 km`;
      }else{
        const dkm = haversineKm(S.myGuess.lat,S.myGuess.lon,sol.lat,sol.lon);
        S.answerText = (sol.address || '').trim() || null;
        S.distanceText = `${dkm.toFixed(2)} km`;
      }
      renderSidebar();
    }
  }

  // Countdown -> nästa runda eller final (utan knapp)
  S.nextRoundLeft = 10;
  renderSidebar();

  if (S.revealCountdown) clearInterval(S.revealCountdown);
  S.revealCountdown = setInterval(async ()=>{
    S.nextRoundLeft -= 1;
    if (S.nextRoundLeft <= 0){
      clearInterval(S.revealCountdown);
      S.revealCountdown = null;
      S.nextRoundLeft = null;

      if (S.roundNo >= S.rounds){
        await showFinal();            // visa slutresultat automatiskt
      }else{
        S.roundNo += 1;
        await enterRound();
      }
    }else{
      renderSidebar();
    }
  }, 1000);
}

// ===== Final =====
async function showFinal(){
  try{
    const res = await fetchJson(`/api/match/final?code=${encodeURIComponent(S.code)}`);
    vGame.style.display='none';
    vFinal.style.display='block';

    // rensa ev. gammalt innehåll
    const ul = document.getElementById('finalBoard');
    if (ul) ul.innerHTML = (res.final||[]).map((r,i)=>{
      const nick = String(r.nickname||'').replace(/^\s*\d+[\.\)]?\s*/,''); // ta bort ev. inbyggd numrering
      return `<li>${i+1}. ${esc(nick)} – ${r.total_m} m</li>`;
    }).join('');

    // "Spela igen"-knapp
    if (!document.getElementById('btnPlayAgain')){
      const btn = document.createElement('button');
      btn.id = 'btnPlayAgain';
      btn.textContent = 'Spela igen';
      btn.style.marginTop = '12px';
      btn.addEventListener('click', ()=>{ window.location.reload(); }); // tillbaka till startsidan
      vFinal.appendChild(btn);
    }
  }catch(e){ alert('Kunde inte hämta slutresultat: '+e.message); }
}

// ===== Knappar (btnFinal döljs; kvar för safety om den finns) =====
btnNextRound?.addEventListener('click', async ()=>{
  if (S.roundNo >= S.rounds) { await showFinal(); return; }
  S.roundNo += 1;
  await enterRound();
});
btnFinal?.addEventListener('click', async ()=>{ await showFinal(); });

// ===== Publika hjälpare =====
window.Utmana = {
  setSession({code, city, rounds, nickname}){ S.code = code; S.city = city; S.rounds = rounds; S.nickname = nickname; },
  enterLobby,
  enterRound,
};
