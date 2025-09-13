// static/js/multiplayer.js
(function () {
  const view = id => document.getElementById(id);
  const $ = sel => document.querySelector(sel);

  // ======= Meny & vyer =======
  const tabPlay    = view('tabPlay');        // Spela-knappen
  const navUtmana  = view('navUtmana');      // Utmana-knappen
  const vPlay      = view('view-play');      // Singleplayer-vy (måste finnas i HTML)
  const vUtmana    = view('view-utmana');    // Multiplayer-vy (måste finnas i HTML)

  // Multiplayer-vyns element
  const vAuth      = view('mp-auth');
  const formCreate = view('formCreate');
  const hostName   = view('hostName');
  const hostCity   = view('hostCity');
  const hostRounds = view('hostRounds');

  const formJoin   = view('formJoin');
  const joinCode   = view('joinCode');
  const joinNick   = view('joinNick');

  const vLobby     = view('mp-lobby');
  const lbCode     = view('lbCode');
  const lbCity     = view('lbCity');
  const lbRounds   = view('lbRounds');
  const lbStatus   = view('lbStatus');
  const lbPlayers  = view('lbPlayers');
  const btnStart   = view('btnStart');

  const vGame      = view('mp-game');
  const gRoundNo   = view('gRoundNo');
  const guessLat   = view('guessLat');
  const guessLon   = view('guessLon');
  const btnSendGuess = view('btnSendGuess');
  const roundResult  = view('roundResult');
  const btnNextRound = view('btnNextRound');
  const btnFinal     = view('btnFinal');

  const vFinal     = view('mp-final');
  const finalBoard = view('finalBoard');

  // ======= Flik-toggling =======
  function showOnly(sectionId) {
    document.querySelectorAll('section[id^="view"]').forEach(el => (el.style.display = 'none'));
    const v = document.getElementById(sectionId);
    if (v) v.style.display = 'block';
  }
  function setActive(btn) {
    document.querySelectorAll('nav button').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
  }
  tabPlay?.addEventListener('click', () => {
    setActive(tabPlay);
    showOnly('view-play');
  });
  navUtmana?.addEventListener('click', (e) => {
    e.preventDefault();
    setActive(navUtmana);
    showOnly('view-utmana');
  });

  // ======= Globalt MP-state =======
  const S = {
    code: null,
    nickname: null,
    city: null,
    rounds: 5,
    roundNo: 1,
    isHost: false,
    lobbyTimer: null
  };
  window._mpState = S; // tillgängligt för andra script vid behov

  // ======= Leaflet-lager & helpers =======
  let guessLayer = null;
  let solutionLayer = null;
  let lineLayer = null;
  let myLastGuess = null; // [lat, lon]

  function ensureLayers() {
    if (!window.L || !window.map) return false;
    if (!guessLayer)    guessLayer    = L.layerGroup().addTo(window.map);
    if (!solutionLayer) solutionLayer = L.layerGroup().addTo(window.map);
    if (!lineLayer)     lineLayer     = L.layerGroup().addTo(window.map);
    return true;
  }
  function clearRoundLayers() {
    myLastGuess = null;
    if (guessLayer) guessLayer.clearLayers();
    if (solutionLayer) solutionLayer.clearLayers();
    if (lineLayer) lineLayer.clearLayers();
  }
  function addGuessMarker(lat, lon, nickname) {
    if (!ensureLayers()) return;
    L.marker([lat, lon], { title: `Gissning${nickname ? ' – ' + nickname : ''}` })
      .addTo(guessLayer)
      .bindPopup(`Gissning${nickname ? ' – ' + nickname : ''}`);
  }
  function showSolutionMarker(lat, lon) {
    if (!ensureLayers()) return;
    L.marker([lat, lon], { title: 'Facit' })
      .addTo(solutionLayer)
      .bindPopup('Facit')
      .openPopup();
  }
  function drawLineGuessToSolution(guess, solution) {
    if (!ensureLayers() || !guess || !solution) return;
    L.polyline([guess, solution], { weight: 3, opacity: 0.85 }).addTo(lineLayer);
    try {
      const bounds = L.latLngBounds([guess, solution]);
      window.map.fitBounds(bounds.pad(0.2));
    } catch {}
  }

  // ======= API helper =======
  async function api(path, opts = {}) {
    const res = await fetch(path, {
      headers: { 'Content-Type': 'application/json', ...(opts.headers || {}) },
      ...opts
    });
    if (!res.ok) {
      let msg = '';
      try { msg = await res.text(); } catch {}
      throw new Error(msg || res.statusText);
    }
    return res.json();
  }

  // ======= Lobby =======
  async function refreshLobby() {
    if (!S.code) return;
    try {
      const data = await api(`/api/match/lobby?code=${encodeURIComponent(S.code)}`);
      lbCode.textContent = S.code;
      lbCity.textContent = data.city || S.city || '';
      lbRounds.textContent = data.rounds || S.rounds || '';
      lbStatus.textContent = data.status;

      lbPlayers.innerHTML = '';
      (data.players || []).forEach(p => {
        const li = document.createElement('li');
        li.textContent = p;
        lbPlayers.appendChild(li);
      });

      btnStart.style.display = (S.isHost && data.status === 'lobby') ? 'inline-block' : 'none';

      if (data.status === 'active') {
        clearInterval(S.lobbyTimer);
        S.roundNo = 1;
        enterRound();
      }
    } catch (e) {
      console.warn('lobby error', e);
    }
  }
  function enterLobby() {
    vAuth.style.display = 'none';
    vLobby.style.display = 'block';
    vGame.style.display = 'none';
    vFinal.style.display = 'none';
    refreshLobby();
    clearInterval(S.lobbyTimer);
    S.lobbyTimer = setInterval(refreshLobby, 2000);
  }

  // ======= Runda =======
  async function enterRound() {
    vLobby.style.display = 'none';
    vGame.style.display = 'block';
    vFinal.style.display = 'none';

    // Reset UI + markörer
    roundResult.innerHTML = '';
    btnNextRound.style.display = 'none';
    btnFinal.style.display = 'none';
    clearRoundLayers();

    gRoundNo.textContent = S.roundNo;

    // Hämta runda och centrera Leaflet
    const r = await api(`/api/match/round?code=${encodeURIComponent(S.code)}&round_no=${S.roundNo}`);
    if (window.map && r && r.round) {
      window.map.setView([r.round.lat, r.round.lon], 13);
    }

    guessLat.value = '';
    guessLon.value = '';
  }

  // ======= Skapa spel =======
  formCreate?.addEventListener('submit', async (e) => {
    e.preventDefault();
    try {
      const body = {
        host_name: hostName.value.trim() || 'Host',
        city: hostCity.value,
        rounds: Number(hostRounds.value || 5)
      };
      const data = await api('/api/match/create', { method: 'POST', body: JSON.stringify(body) });
      S.code = data.code;
      S.city = data.city;
      S.rounds = data.rounds;
      S.isHost = true;
      S.nickname = body.host_name;
      enterLobby();
    } catch (err) {
      alert('Kunde inte skapa spel: ' + err.message);
    }
  });

  // ======= Anslut =======
  formJoin?.addEventListener('submit', async (e) => {
    e.preventDefault();
    try {
      const body = {
        code: joinCode.value.trim(),
        nickname: joinNick.value.trim()
      };
      await api('/api/match/join', { method: 'POST', body: JSON.stringify(body) });
      S.code = body.code;
      S.nickname = body.nickname;
      S.isHost = false;
      enterLobby();
    } catch (err) {
      alert('Kunde inte ansluta: ' + err.message);
    }
  });

  // ======= Starta (host) =======
  btnStart?.addEventListener('click', async () => {
    try {
      await api(`/api/match/start?code=${encodeURIComponent(S.code)}`, { method: 'POST' });
      // lobby-poll växlar till enterRound() när status blir active
    } catch (e) {
      alert('Kunde inte starta spelet: ' + e.message);
    }
  });

  // ======= Skicka gissning =======
  async function sendGuess(lat, lon) {
    try {
      const payload = { code: S.code, nickname: S.nickname, lat: Number(lat), lon: Number(lon) };
      await api(`/api/match/guess?round_no=${S.roundNo}`, {
        method: 'POST',
        body: JSON.stringify(payload)
      });

      // Hämta rundresultat
      const res = await api(`/api/match/round_result?code=${encodeURIComponent(S.code)}&round_no=${S.roundNo}`);

      // Visa facit + linje (om vi har en egen gissning sparad)
      if (res && res.solution) {
        showSolutionMarker(res.solution.lat, res.solution.lon);
        if (myLastGuess) {
          drawLineGuessToSolution(myLastGuess, [res.solution.lat, res.solution.lon]);
        }
      }

      // Lista i UI
      const list = (res.leaderboard || [])
        .map((r, i) => `<li>${i + 1}. ${r.nickname} – ${r.distance_m} m</li>`).join('');
      roundResult.innerHTML =
        `<p>Facit: lat ${res.solution.lat.toFixed(5)}, lon ${res.solution.lon.toFixed(5)}</p>
         <h4>Runda ${res.round_no} – leaderboard</h4>
         <ol>${list}</ol>`;

      // Vidare-knappar
      if (S.roundNo < S.rounds) {
        btnNextRound.style.display = 'inline-block';
      } else {
        btnFinal.style.display = 'inline-block';
      }
    } catch (e) {
      alert('Kunde inte skicka gissning: ' + e.message);
    }
  }

  btnSendGuess?.addEventListener('click', () => {
    const lat = parseFloat(guessLat.value);
    const lon = parseFloat(guessLon.value);
    if (isNaN(lat) || isNaN(lon)) {
      alert('Fyll i lat och lon');
      return;
    }
    addGuessMarker(lat, lon, S.nickname);
    myLastGuess = [lat, lon];
    sendGuess(lat, lon);
  });

  btnNextRound?.addEventListener('click', async () => {
    S.roundNo += 1;
    await enterRound();
  });

  btnFinal?.addEventListener('click', async () => {
    try {
      const res = await api(`/api/match/final?code=${encodeURIComponent(S.code)}`);
      vGame.style.display = 'none';
      vFinal.style.display = 'block';
      finalBoard.innerHTML = (res.final || [])
        .map((r, i) => `<li>${i + 1}. ${r.nickname} – ${r.total_m} m</li>`).join('');
    } catch (e) {
      alert('Kunde inte hämta slutresultat: ' + e.message);
    }
  });

  // ======= Leaflet-karthook =======
  // I din kartinit (annan fil): 
  //   window.map = map;
  //   map.on('click', e => window.onMapClick(e.latlng.lat, e.latlng.lng));
  window.onMapClick = function (lat, lon) {
    guessLat.value = lat.toFixed(6);
    guessLon.value = lon.toFixed(6);
    addGuessMarker(lat, lon, S.nickname);
    myLastGuess = [lat, lon];
    // Vill du auto-skicka direkt vid klick? Avkommentera:
    // sendGuess(lat, lon);
  };

  // ======= Startläge: flik + vy =======
  if (location.hash === '#utmana') {
    setActive(navUtmana);
    showOnly('view-utmana');
  } else {
    setActive(tabPlay);
    showOnly('view-play');
  }

// === Leaflet-init ===
const map = L.map('map').setView([62.0, 15.0], 5);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
  maxZoom: 19
}).addTo(map);

// Gör kartan global så resten av multiplayer.js kan använda den
window.map = map;

// Koppla klick till multiplayer-hook
map.on('click', (e) => {
  if (window.onMapClick) {
    window.onMapClick(e.latlng.lat, e.latlng.lng);
  }
});


})();
