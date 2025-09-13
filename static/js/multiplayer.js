// ===== Multiplayer – konfig =====
const ROUND_TIME_SEC = 60; // ändra om du vill
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
const tblBody  = $('#mpRoundTable tbody');
const btnNextRound = $('#btnNextRound');
const btnFinal     = $('#btnFinal');
const mpTimerEl    = $('#mpTimer');

// ===== Global state =====
const S = {
  code: "", nickname: "", city: "", rounds: 5, roundNo: 1,
  players: [], hasGuessed: false, myGuess: null,
  pollTimer: null, countdownTimer: null, timeLeft: ROUND_TIME_SEC,
  mapLocked: false,
};

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

// ===== Kartklick => gissning =====
window.onMapClick = async (lat, lon) => {
  if(vGame?.style.display==='block' && !S.hasGuessed && !S.mapLocked){
    await sendGuess(lat, lon);
  }
};

// ===== Lobby (visa & polla tills spelet startar) =====
async function enterLobby(){
  clearInterval(S.pollTimer);
  clearInterval(S.countdownTimer);

  vLobby.style.display='block';
  vGame.style.display='none';
  vFinal.style.display='none';

  // Läs initial info (spelare mm)
  try{
    const r = await fetchJson(`/api/match/lobby?code=${encodeURIComponent(S.code)}`);
    if(r?.players) S.players = r.players;
    if(r?.status === 'active'){
      // Värden hann redan starta – hoppa direkt in
      return await enterRound();
    }
  }catch{}

  // Polla lobbyn – när status==active -> in i runda
  S.pollTimer = setInterval(async ()=>{
    try{
      const r = await fetchJson(`/api/match/lobby?code=${encodeURIComponent(S.code)}`);
      if(r?.players) S.players = r.players;
      if(r?.status === 'active'){
        clearInterval(S.pollTimer);
        await enterRound();
      }
    }catch{}
  }, 2000);
}

// ===== Starta en runda =====
async function enterRound(){
  clearInterval(S.pollTimer);
  clearInterval(S.countdownTimer);
  S.hasGuessed = false;
  S.myGuess = null;
  setMapLocked(false);

  vLobby.style.display='none';
  vFinal.style.display='none';
  vGame.style.display='block';

  gRoundNo.textContent = S.roundNo;
  gCode.textContent    = S.code;
  mpYou.textContent    = 'Klicka på kartan för att gissa.';
  if($('#info')) $('#info').textContent = 'Klicka på kartan för att gissa.';

  // HÄMTA rundadata & sätt ledtråd
  const r = await fetchJson(`/api/match/round?code=${encodeURIComponent(S.code)}&round_no=${S.roundNo}`);
  const clue = r?.round?.clue || '';
  if (document.getElementById('clue')) {
    document.getElementById('clue').textContent = `Ledtråd: ${clue}`;
  }

  renderRoundBoard([]);

  // starta polling av round_result
  S.pollTimer = setInterval(refreshRoundBoard, 2000);

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
        autoGuessBecauseTimeout(); // skickar gissning
      }
    }
  },1000);
}
function updateTimer(){
  const t = Math.max(0, S.timeLeft);
  const mm = String(Math.floor(t/60)).padStart(2,'0');
  const ss = String(t%60).padStart(2,'0');
  if(mpTimerEl) mpTimerEl.textContent = `${mm}:${ss}`;
}
async function autoGuessBecauseTimeout(){
  // använd kartans center eller stadens center
  let latlon = null;
  if(window.map){
    const c = window.map.getCenter();
    latlon = {lat:c.lat, lon:c.lng};
  }else if(CITY_CENTERS[S.city]){
    latlon = CITY_CENTERS[S.city];
  }else{
    latlon = {lat:59.334, lon:18.063}; // fallback Sthlm
  }
  mpYou.innerHTML = `Tiden tog slut – automatiskt skickad gissning. Väntar på övriga ...`;
  await sendGuess(latlon.lat, latlon.lon);
}

// ===== Skicka gissning =====
async function sendGuess(lat, lon){
  try{
    const r = await fetchJson(`/api/match/guess?round_no=${S.roundNo}`, {
      method:'POST',
      body:{ code:S.code, nickname:S.nickname, lat, lon }
    });
    S.hasGuessed = true;
    S.myGuess = {lat, lon};
    setMapLocked(true); // LÅS kartan efter gissning

    const km = r?.distance_m!=null ? (r.distance_m/1000).toFixed(2) : null;
    if($('#info')){
      $('#info').innerHTML = km!=null
        ? `<strong>Din gissning:</strong> ${km} km · väntar på övriga spelare ...`
        : `Din gissning är mottagen – väntar på övriga spelare ...`;
    }
    mpYou.innerHTML = km!=null
      ? `Du har gissat: <strong>${r.distance_m} m</strong> – väntar på övriga spelare ...`
      : `Gissning mottagen – väntar på övriga spelare ...`;

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
    if(lob?.players) S.players = lob.players;
  }catch{}

  let res;
  try{
    res = await fetchJson(`/api/match/round_result?code=${encodeURIComponent(S.code)}&round_no=${S.roundNo}`);
  }catch(e){ return; }

  const board = Array.isArray(res?.leaderboard) ? res.leaderboard : [];
  renderRoundBoard(board);

  const doneCount = board.length;
  const total = S.players.length;

  if(doneCount>=total && total>0){
    clearInterval(S.pollTimer);
    clearInterval(S.countdownTimer);
    await showSolutionAndButtons(res);
  }else{
    if($('#info')) $('#info').innerHTML = `Väntar på övriga: <strong>${doneCount}/${total}</strong> spelare klara.`;
  }
}
function renderRoundBoard(board){
  const doneBy = new Map(board.map(r=>[r.nickname, r.distance_m]));
  const rows = S.players.map(p=>{
    const dist = doneBy.get(p);
    const status = dist!=null ? `<span class="badge badge-done">Klar</span>` : `<span class="badge badge-wait">Väntar ...</span>`;
    const distTxt = dist!=null ? `${dist} m` : '–';
    return `<tr><td>${esc(p)}</td><td>${status}</td><td>${distTxt}</td></tr>`;
  });
  tblBody.innerHTML = rows.join('');
}

// ===== Facit + knappar =====
async function showSolutionAndButtons(res){
  const sol = res?.solution;
  if(sol?.lat!=null && sol?.lon!=null){
    try{
      if(typeof clearMapGraphics==='function') clearMapGraphics();
      if(S.myGuess){
        const bearing = typeof bearingDeg==='function'
          ? bearingDeg(S.myGuess.lat,S.myGuess.lon,sol.lat,sol.lon) : 0;
        window.guessMarker = L.marker([S.myGuess.lat,S.myGuess.lon], {icon: makeArrowIcon(bearing)}).addTo(map);
      }
      window.trueMarker = L.marker([sol.lat,sol.lon], {icon: makeCheckIcon()}).addTo(map);
      if(S.myGuess){
        window.line = L.polyline([[S.myGuess.lat,S.myGuess.lon],[sol.lat,sol.lon]], {color:'#444', weight:2}).addTo(map);
        map.fitBounds(window.line.getBounds(), {padding:[30,30]});
      }
    }catch{}
    if($('#info') && S.myGuess){
      const dkm = haversineKm(S.myGuess.lat,S.myGuess.lon,sol.lat,sol.lon);
      const addr = (sol.address || '').trim();
      $('#info').innerHTML =
        `<strong>Avstånd:</strong> ${dkm.toFixed(2)} km` +
        (addr ? ` · <strong>Rätt adress:</strong> ${esc(addr)}` : '') +
        `.`;
    }
  }
  btnNextRound.style.display = (S.roundNo < S.rounds) ? 'inline-block' : 'none';
  btnFinal.style.display     = (S.roundNo >= S.rounds) ? 'inline-block' : 'none';
}


// ===== Knappar =====
btnNextRound?.addEventListener('click', async ()=>{
  S.roundNo += 1;
  await enterRound();
});
btnFinal?.addEventListener('click', async ()=>{
  try{
    const res = await fetchJson(`/api/match/final?code=${encodeURIComponent(S.code)}`);
    vGame.style.display='none';
    vFinal.style.display='block';
    $('#finalBoard').innerHTML = (res.final||[]).map((r,i)=>`<li>${i+1}. ${esc(r.nickname)} – ${r.total_m} m</li>`).join('');
  }catch(e){ alert('Kunde inte hämta slutresultat: '+e.message); }
});

// ===== Publika hjälpare som index.html använder =====
window.Utmana = {
  setSession({code, city, rounds, nickname}){
    S.code = code; S.city = city; S.rounds = rounds; S.nickname = nickname;
  },
  enterLobby,
  enterRound,
};
