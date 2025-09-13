// static/js/multiplayer.js
(function () {
  const view = id => document.getElementById(id);
  const $ = sel => document.querySelector(sel);

  // Views
  const vUtmana = view('view-utmana');
const navUtmana = view('tabUtmana');

  // Forms & fields
  const formCreate = view('formCreate');
  const hostName = view('hostName');
  const hostCity = view('hostCity');
  const hostRounds = view('hostRounds');

  const formJoin = view('formJoin');
  const joinCode = view('joinCode');
  const joinNick = view('joinNick');

  // Lobby
  const vLobby = view('mp-lobby');
  const lbCode = view('lbCode');
  const lbCity = view('lbCity');
  const lbRounds = view('lbRounds');
  const lbStatus = view('lbStatus');
  const lbPlayers = view('lbPlayers');
  const btnStart = view('btnStart');

  // Game
  const vGame = view('mp-game');
  const gRoundNo = view('gRoundNo');
  const guessLat = view('guessLat');
  const guessLon = view('guessLon');
  const btnSendGuess = view('btnSendGuess');
  const roundResult = view('roundResult');
  const btnNextRound = view('btnNextRound');
  const btnFinal = view('btnFinal');

  // Final
  const vFinal = view('mp-final');
  const finalBoard = view('finalBoard');

  // Global state
  const S = {
    code: null,
    nickname: null,
    city: null,
    rounds: 5,
    roundNo: 1,
    isHost: false,
    lobbyTimer: null
  };

  // Simple router: show only Utmana view
  function showUtmana() {
    // göm alla dina andra views om du har; här visar vi bara denna
    document.querySelectorAll('section[id^="view"]').forEach(el => el.style.display = 'none');
    vUtmana.style.display = 'block';
    // startläge: auth synlig, andra dolda
    view('mp-auth').style.display = 'block';
    vLobby.style.display = 'none';
    vGame.style.display = 'none';
    vFinal.style.display = 'none';
  }

  navUtmana?.addEventListener('click', (e) => {
    e.preventDefault();
    showUtmana();
  });

  // --- API helpers ---
  async function api(path, opts = {}) {
    const res = await fetch(path, {
      headers: { 'Content-Type': 'application/json', ...(opts.headers || {}) },
      ...opts
    });
    if (!res.ok) {
      const msg = await res.text();
      throw new Error(msg || res.statusText);
    }
    return res.json();
  }

  // --- Lobby refresh ---
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

      // visa Start endast för host i lobby
      btnStart.style.display = (S.isHost && data.status === 'lobby') ? 'inline-block' : 'none';

      if (data.status === 'active') {
        // spelet har startat – gå till runda 1
        clearInterval(S.lobbyTimer);
        S.roundNo = 1;
        enterRound();
      }
    } catch (e) {
      console.warn('lobby error', e);
    }
  }

  // --- Enter Lobby ---
  function enterLobby() {
    view('mp-auth').style.display = 'none';
    vLobby.style.display = 'block';
    vGame.style.display = 'none';
    vFinal.style.display = 'none';
    refreshLobby();
    clearInterval(S.lobbyTimer);
    S.lobbyTimer = setInterval(refreshLobby, 2000);
  }

  // --- Enter Round ---
  async function enterRound() {
    vLobby.style.display = 'none';
    vGame.style.display = 'block';
    vFinal.style.display = 'none';
    roundResult.innerHTML = '';
    btnNextRound.style.display = 'none';
    btnFinal.style.display = 'none';

    gRoundNo.textContent = S.roundNo;
    // hämta runda (lat/lon behövs för din karta)
    const r = await api(`/api/match/round?code=${encodeURIComponent(S.code)}&round_no=${S.roundNo}`);
    // Om du vill centrera karta, använd r.round.lat/lon här.

    // nolla ev. inputfält
    guessLat.value = '';
    guessLon.value = '';
  }

  // --- Skapa spel ---
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

  // --- Anslut ---
  formJoin?.addEventListener('submit', async (e) => {
    e.preventDefault();
    try {
      const body = {
        code: joinCode.value.trim(),
        nickname: joinNick.value.trim()
      };
      const data = await api('/api/match/join', { method: 'POST', body: JSON.stringify(body) });
      S.code = body.code;
      S.nickname = body.nickname;
      S.isHost = false;
      enterLobby();
    } catch (err) {
      alert('Kunde inte ansluta: ' + err.message);
    }
  });

  // --- Starta (host) ---
  btnStart?.addEventListener('click', async () => {
    try {
      await api(`/api/match/start?code=${encodeURIComponent(S.code)}`, { method: 'POST' });
      // nästa lobby-refresh triggar active -> enterRound()
    } catch (e) {
      alert('Kunde inte starta spelet: ' + e.message);
    }
  });

  // --- Skicka gissning ---
  async function sendGuess(lat, lon) {
    try {
      const payload = {
        code: S.code,
        nickname: S.nickname,
        lat: Number(lat),
        lon: Number(lon)
      };
      await api(`/api/match/guess?round_no=${S.roundNo}`, {
        method: 'POST',
        body: JSON.stringify(payload)
      });

      // hämta rundresultat (leaderboard per runda)
      const res = await api(`/api/match/round_result?code=${encodeURIComponent(S.code)}&round_no=${S.roundNo}`);
      const list = (res.leaderboard || []).map((r, i) =>
        `<li>${i + 1}. ${r.nickname} – ${r.distance_m} m</li>`).join('');
      roundResult.innerHTML =
        `<p>Facit: lat ${res.solution.lat.toFixed(5)}, lon ${res.solution.lon.toFixed(5)}</p>
         <h4>Runda ${res.round_no} – leaderboard</h4>
         <ol>${list}</ol>`;

      // visa vidare-knappar
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

  // --- Karthook ---
  // Anropa window.onMapClick(lat, lon) från din befintliga kartkod när användaren klickar.
  window.onMapClick = function (lat, lon) {
    guessLat.value = lat.toFixed(6);
    guessLon.value = lon.toFixed(6);
    // Skicka direkt (eller låt användaren trycka på knappen)
    // sendGuess(lat, lon);
  };

  // Auto: om sidan laddas och hash = #utmana, öppna direkt
  if (location.hash === '#utmana') showUtmana();

})();
