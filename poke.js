// Game of Claude, Pokémon theme (window.GAME_THEME === 'pokemon'; game.js is the default D&D theme).
// The trainer's level is the real XP level from the server (game.py). The Pokémon side lives in this
// browser (localStorage): your partner fights wild Pokémon (#1–150) while a session works, gains EXP,
// evolves at its level (stone and trade evolutions at fixed levels), and weakened Pokémon you don't own
// yet get a Poké Ball. Any caught Pokémon can be your partner, the avatar in the arena (Pokédex in the
// sheet). A sleeping Snorlax blocks the path while a session waits for approval. Sprites are not part
// of this repo: they load from the public PokeAPI sprite repo, with a drawn fallback when offline.
// Fan feature, not affiliated with Nintendo, Game Freak or The Pokémon Company.
(() => {
  if (window.GAME_THEME !== 'pokemon') return;
  const NS = 'http://www.w3.org/2000/svg';
  const SPRITE = 'https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/';
  const reduce = matchMedia('(prefers-reduced-motion: reduce)');
  const store = { get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
                  set(k, v) { try { localStorage.setItem(k, v); } catch (e) {} } };
  const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const fmt = n => n >= 1e6 ? (n / 1e6).toFixed(1) + 'M' : n >= 1e4 ? Math.round(n / 1e3) + 'k' : n >= 1e3 ? (n / 1e3).toFixed(1) + 'k' : String(n);
  const pick = a => a[Math.floor(Math.random() * a.length)];
  const rint = (a, b) => a + Math.floor(Math.random() * (b - a + 1));

  // ---------- Pokédex data (#1–150) ----------
  const NAMES = ['', ...('Bulbasaur|Ivysaur|Venusaur|Charmander|Charmeleon|Charizard|Squirtle|Wartortle|Blastoise|Caterpie|Metapod|Butterfree|' +
    'Weedle|Kakuna|Beedrill|Pidgey|Pidgeotto|Pidgeot|Rattata|Raticate|Spearow|Fearow|Ekans|Arbok|Pikachu|Raichu|Sandshrew|Sandslash|' +
    'Nidoran♀|Nidorina|Nidoqueen|Nidoran♂|Nidorino|Nidoking|Clefairy|Clefable|Vulpix|Ninetales|Jigglypuff|Wigglytuff|Zubat|Golbat|' +
    'Oddish|Gloom|Vileplume|Paras|Parasect|Venonat|Venomoth|Diglett|Dugtrio|Meowth|Persian|Psyduck|Golduck|Mankey|Primeape|Growlithe|' +
    'Arcanine|Poliwag|Poliwhirl|Poliwrath|Abra|Kadabra|Alakazam|Machop|Machoke|Machamp|Bellsprout|Weepinbell|Victreebel|Tentacool|' +
    'Tentacruel|Geodude|Graveler|Golem|Ponyta|Rapidash|Slowpoke|Slowbro|Magnemite|Magneton|Farfetch\'d|Doduo|Dodrio|Seel|Dewgong|' +
    'Grimer|Muk|Shellder|Cloyster|Gastly|Haunter|Gengar|Onix|Drowzee|Hypno|Krabby|Kingler|Voltorb|Electrode|Exeggcute|Exeggutor|' +
    'Cubone|Marowak|Hitmonlee|Hitmonchan|Lickitung|Koffing|Weezing|Rhyhorn|Rhydon|Chansey|Tangela|Kangaskhan|Horsea|Seadra|Goldeen|' +
    'Seaking|Staryu|Starmie|Mr. Mime|Scyther|Jynx|Electabuzz|Magmar|Pinsir|Tauros|Magikarp|Gyarados|Lapras|Ditto|Eevee|Vaporeon|' +
    'Jolteon|Flareon|Porygon|Omanyte|Omastar|Kabuto|Kabutops|Aerodactyl|Snorlax|Articuno|Zapdos|Moltres|Dratini|Dragonair|Dragonite|Mewtwo').split('|')];
  // primary type per Pokédex number, 10 per group
  const TYPE = ['', ...('g g g f f f w w w b  b b b b b fl fl fl n n  fl fl p p e e gr gr p p  p p p p n n f f n n  p p g g g b b b b gr ' +
    'gr n n w w fi fi f f w  w w ps ps ps fi fi fi g g  g w w r r r f f w w  e e n fl fl w i p p w  i gh gh gh r ps ps w w e ' +
    'e g g gr gr fi fi n p p  gr gr n g n w w w w w  w ps b i e f b n w w  i n n w e f n r r r  r fl n i e f d d d ps').trim().split(/\s+/)];
  const TN = { g: 'grass', f: 'fire', w: 'water', b: 'bug', fl: 'flying', n: 'normal', p: 'poison', e: 'electric', gr: 'ground',
    fi: 'fighting', ps: 'psychic', r: 'rock', i: 'ice', gh: 'ghost', d: 'dragon' };
  const TC = { g: '#78c850', f: '#f08030', w: '#6890f0', b: '#a8b820', fl: '#a890f0', n: '#a8a878', p: '#a040a0', e: '#f8d030', gr: '#e0c068',
    fi: '#c03028', ps: '#f85888', r: '#b8a038', i: '#98d8d8', gh: '#705898', d: '#7038f8' };
  // evolutions: from → [to, level]; S = stone (here: level 30), T = trade (here: level 36); Eevee picks one at random
  const S_LV = 30, T_LV = 36;
  const EVO = { 1: [2, 16], 2: [3, 32], 4: [5, 16], 5: [6, 36], 7: [8, 16], 8: [9, 36], 10: [11, 7], 11: [12, 10], 13: [14, 7], 14: [15, 10],
    16: [17, 18], 17: [18, 36], 19: [20, 20], 21: [22, 20], 23: [24, 22], 25: [26, 'S'], 27: [28, 22], 29: [30, 16], 30: [31, 'S'],
    32: [33, 16], 33: [34, 'S'], 35: [36, 'S'], 37: [38, 'S'], 39: [40, 'S'], 41: [42, 22], 43: [44, 21], 44: [45, 'S'], 46: [47, 24],
    48: [49, 31], 50: [51, 26], 52: [53, 28], 54: [55, 33], 56: [57, 28], 58: [59, 'S'], 60: [61, 25], 61: [62, 'S'], 63: [64, 16],
    64: [65, 'T'], 66: [67, 28], 67: [68, 'T'], 69: [70, 21], 70: [71, 'S'], 72: [73, 30], 74: [75, 25], 75: [76, 'T'], 77: [78, 40],
    79: [80, 37], 81: [82, 30], 84: [85, 31], 86: [87, 34], 88: [89, 38], 90: [91, 'S'], 92: [93, 25], 93: [94, 'T'], 96: [97, 26],
    98: [99, 28], 100: [101, 30], 102: [103, 'S'], 104: [105, 28], 109: [110, 35], 111: [112, 42], 116: [117, 32], 118: [119, 33],
    120: [121, 'S'], 129: [130, 20], 133: [[134, 135, 136], 'S'], 138: [139, 40], 140: [141, 40], 147: [148, 30], 148: [149, 55] };
  const evoLv = e => e[1] === 'S' ? S_LV : e[1] === 'T' ? T_LV : e[1];
  const PRE = {}, MIN = {};   // pre-evolution, lowest level it shows up in the wild
  for (const [from, e] of Object.entries(EVO)) for (const to of [].concat(e[0])) { PRE[to] = +from; MIN[to] = evoLv(e); }
  const stage = id => PRE[id] ? 1 + stage(PRE[id]) : 0;
  const LEGEND = new Set([144, 145, 146, 150]);
  const RARE = new Set([83, 106, 107, 108, 113, 115, 122, 123, 124, 125, 126, 127, 128, 131, 132, 137, 138, 140, 142, 143, 147]);
  const IDS = Array.from({ length: 150 }, (_, i) => i + 1);
  const power = id => id === 129 ? .5 : LEGEND.has(id) ? 1.35 : RARE.has(id) ? 1.05 : [.85, 1, 1.15][stage(id)];
  // encounter rarity per evolution family (by its first form); evolved forms are rarer still
  const TIERS = [
    { name: 'common', w: 1, c: .35 },
    { name: 'uncommon', w: .3, c: .25, ids: [25, 35, 37, 58, 63, 77, 83, 95, 102, 104, 106, 107, 108, 111, 114, 115, 122, 123, 124, 125, 126, 127, 128] },
    { name: 'rare', w: .06, c: .12, ids: [1, 4, 7, 113, 132, 133, 137, 138, 140, 147] },
    { name: 'very rare', w: .012, c: .06, ids: [131, 142, 143] },
    { name: 'legendary', w: .002, c: .05, ids: [144, 145, 146] },
    { name: 'mythic', w: .001, c: .04, ids: [150] },
  ];
  const first = id => PRE[id] ? first(PRE[id]) : id;
  const TIER_OF = {};
  TIERS.forEach((t, i) => (t.ids || []).forEach(id => { TIER_OF[id] = i; }));
  const tier = id => TIERS[TIER_OF[first(id)] || 0];
  const rarity = id => tier(id).w * [1, .3, .08][stage(id)];
  const rarityName = id => {
    const t = tier(id).name, r = rarity(id);
    return t === 'legendary' || t === 'mythic' ? t : r >= .3 ? 'common' : r >= .06 ? 'uncommon' : r >= .012 ? 'rare' : 'very rare';
  };
  const catchRate = id => tier(id).c * [1, .6, .35][stage(id)];
  const yieldExp = id => LEGEND.has(id) ? 270 : RARE.has(id) ? 160 : [64, 142, 220][stage(id)];
  // battles end every ~10 s while Claude works, so EXP is 1/25 of the games' formula: first evolution (Lv 16) after ~3 h of work
  const winExp = (id, L) => Math.max(1, Math.round(yieldExp(id) * L / 7 / 25));
  // super effective (a hits these harder); RESIST and the reverse of SUPER count as not very effective
  const SUPER = { f: 'g b i', w: 'f r gr', g: 'w r gr', e: 'w fl', i: 'g fl gr d', fi: 'n r i', p: 'g b', gr: 'f e r p', fl: 'g fi b',
    ps: 'fi p', b: 'g ps p', r: 'f i fl b', gh: 'gh ps', d: 'd' };
  const RESIST = { e: 'gr', n: 'gh r', fi: 'gh fl ps', gh: 'n', gr: 'fl', ps: 'ps' };
  const has = (m, a, b) => (m[a] || '').split(' ').includes(b);
  const eff = (a, d) => has(SUPER, a, d) ? 1.25 : has(RESIST, a, d) || has(SUPER, d, a) ? .8 : 1;   // softer than the games: no switching here
  const MOVES = { g: ['Vine Whip', 'Razor Leaf'], f: ['Ember', 'Flamethrower'], w: ['Water Gun', 'Surf'], b: ['Leech Life', 'Twineedle'],
    fl: ['Gust', 'Wing Attack'], n: ['Tackle', 'Body Slam'], p: ['Poison Sting', 'Sludge'], e: ['Thunder Shock', 'Thunderbolt'],
    gr: ['Dig', 'Earthquake'], fi: ['Karate Chop', 'Low Kick'], ps: ['Confusion', 'Psychic'], r: ['Rock Throw', 'Rock Slide'],
    i: ['Aurora Beam', 'Ice Beam'], gh: ['Lick', 'Night Shade'], d: ['Twister', 'Dragon Rage'] };
  const move = (id, L) => id === 129 ? { name: 'Splash', pow: 10 } : { name: MOVES[TYPE[id]][L >= 25 ? 1 : 0], pow: L >= 25 ? 80 : 40 };
  const KIND_TYPES = { shell: 'f fi r gr', edit: 'g n b', read: 'ps w i', web: 'fl e', agent: 'gh p', mcp: 'e r' };
  const STARTERS = [1, 4, 7, 25];
  const BALLS = [{ name: 'Poké Ball', lv: 1, mult: 1, top: '#e83030' }, { name: 'Great Ball', lv: 5, mult: 1.5, top: '#3070e0' },
                 { name: 'Ultra Ball', lv: 12, mult: 2, top: '#26262b' }];
  const toolKind = t => !t ? 'other' : t === 'Bash' ? 'shell' : /^(Edit|Write|MultiEdit|NotebookEdit)$/.test(t) ? 'edit'
    : /^(Read|Grep|Glob|LS)$/.test(t) ? 'read' : /^Web/.test(t) ? 'web' : /^(Agent|Task|SendMessage)$/.test(t) ? 'agent' : /^mcp__/.test(t) ? 'mcp' : 'other';
  const LINES = {
    battle: ['Go, {p}!', '{p}, use {m}!', 'Ship it, {p}!', 'Green build, {p}!'],
    idle: ['Awaiting orders!', 'Your move, trainer!', '{p} is ready!'],
    rest: ['Zzz…'],
    ko: ['{p} needs a rest…', 'Nurse, please!'],
    gate: ['Snorlax blocks the path!', 'Approve to wake it up!', 'Play the Poké Flute (approve)!'],
  };

  // ---------- Save: on disk next to the XP ledger (server.py /api/pokemon, pokesave.py); localStorage is
  // the cache and the fallback (static snapshot, server down) ----------
  const KEY = 'pokeSave', REMOTE = location.protocol.startsWith('http');
  const blank = () => ({ v: 1, partner: null, box: [], seen: {}, w: 0, l: 0 });
  const read = () => { try { const p = JSON.parse(store.get(KEY) || 'null'); return p && Array.isArray(p.box) ? Object.assign(blank(), p) : blank(); } catch (e) { return blank(); } };
  const P = read();
  let lastU = 0;
  const uid = () => (lastU = Math.max(lastU + 1, Date.now() * 100 + rint(0, 99)));   // unique across browsers, so saves merge cleanly
  P.box.forEach(m => { if (m.u < 1e9) { const u = uid(); if (P.partner === m.u) P.partner = u; m.u = u; } });   // older saves numbered them 1, 2, 3…
  function mergeIn(o) {   // same rules as pokesave.merge: every Pokémon is kept, the copy with more EXP wins (it may have evolved)
    const mine = new Map(P.box.map(m => [m.u, m]));
    for (const m of o.box || []) { const x = mine.get(m.u); if (!x) P.box.push({ ...m }); else if (m.exp > x.exp) Object.assign(x, m); }
    Object.assign(P.seen, o.seen); P.w = Math.max(P.w, o.w || 0); P.l = Math.max(P.l, o.l || 0);
    if (!P.box.some(m => m.u === P.partner) && o.partner) P.partner = o.partner;
  }
  let pushT = 0;
  function save() {   // merge with what another dashboard tab may have written meanwhile, then sync to disk
    mergeIn(read());
    store.set(KEY, JSON.stringify(P));
    if (REMOTE) { clearTimeout(pushT); pushT = setTimeout(push, 1500); }
  }
  async function push() {
    try {
      const r = await fetch('/api/pokemon', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Game-Of-Claude': '1' }, body: JSON.stringify(P) });
      if (r.ok) { mergeIn(await r.json()); store.set(KEY, JSON.stringify(P)); }
    } catch (e) {}   // server down: the next save pushes the cached copy
  }
  async function pull() {   // on start: merge the disk save in (nothing is dropped) and upload a browser-only save
    try {
      const r = await fetch('/api/pokemon');
      if (!r.ok) return;
      const d = await r.json();
      if (d.partner && d.box.some(m => m.u === d.partner)) P.partner = d.partner;   // the partner chosen last, in any browser
      mergeIn(d); store.set(KEY, JSON.stringify(P));
      push();
      if (S.scene) { S.phhp = pmax(); S.wild = null; S.busy = false; setScene(pickScene(S.att), true); }
      if (sheetOpen()) openSheet();
    } catch (e) {}
  }
  const partner = () => P.box.find(m => m.u === P.partner) || null;
  const caught = id => P.box.some(m => m.id === id);
  const lvOf = m => Math.max(1, Math.floor(Math.cbrt(m.exp) + 1e-9));   // medium-fast curve: Lv³ EXP
  const trainerLv = () => S.game?.level || 1;
  const levelCap = () => Math.min(100, 15 + 5 * trainerLv());
  const ball = () => [...BALLS].reverse().find(b => trainerLv() >= b.lv);
  function addMon(id, L) { const m = { u: uid(), id, exp: L ** 3, at: Date.now() }; P.box.push(m); P.seen[id] = 1; return m; }

  // ---------- Sound (WebAudio, synthesized) ----------
  let actx = null;
  const soundOn = () => store.get('gameSound') === '1';
  function tone(f, t, dur, type = 'square', vol = .05) {
    actx ??= new (window.AudioContext || window.webkitAudioContext)();
    const o = actx.createOscillator(), g = actx.createGain(), t0 = actx.currentTime + t;
    o.type = type; o.frequency.setValueAtTime(f, t0); o.frequency.exponentialRampToValueAtTime(Math.max(40, f * .5), t0 + dur);
    g.gain.setValueAtTime(vol, t0); g.gain.exponentialRampToValueAtTime(.0001, t0 + dur);
    o.connect(g).connect(actx.destination); o.start(t0); o.stop(t0 + dur);
  }
  const SFX = {
    hit: big => soundOn() && (tone(big ? 880 : 520, 0, .09), tone(160, .03, .12, 'sawtooth', .03)),
    hurt: () => soundOn() && tone(180, 0, .14, 'sawtooth', .04),
    faint: () => soundOn() && [392, 330, 262].forEach((f, i) => tone(f, i * .07, .12, 'square', .04)),
    lose: () => soundOn() && [330, 294, 262, 196].forEach((f, i) => tone(f, i * .18, .3, 'triangle', .05)),
    level: () => soundOn() && [523, 659, 784, 1047].forEach((f, i) => tone(f, i * .1, .22, 'triangle', .07)),
    spawn: () => soundOn() && [330, 440, 554].forEach((f, i) => tone(f, i * .08, .1, 'triangle', .035)),
    throw: () => soundOn() && tone(900, 0, .25, 'sine', .04),
    wobble: () => soundOn() && tone(300, 0, .06, 'square', .03),
    gotcha: () => soundOn() && [784, 988, 1175, 1568].forEach((f, i) => tone(f, i * .09, .16, 'square', .04)),
    evolve: () => soundOn() && [392, 523, 659, 784, 1047, 1319].forEach((f, i) => tone(f, i * .14, .3, 'triangle', .06)),
    snore: () => soundOn() && tone(110, 0, .6, 'sawtooth', .03),
  };

  // ---------- CSS (the shared arena/sheet styles come from game.js) ----------
  document.head.insertAdjacentHTML('beforeend', `<style>
.scene .suck { animation: p-suck .35s forwards; transform-box: fill-box; transform-origin: center bottom; }
@keyframes p-suck { 50% { filter: brightness(3); } to { opacity: 0; transform: scale(.1); } }
.scene .evo { animation: p-evo .25s steps(2) infinite; }
@keyframes p-evo { 50% { filter: brightness(0) invert(1); } }
.scene .zz { animation: p-zz 1.8s ease-in-out infinite; transform-box: fill-box; transform-origin: center bottom; }
@keyframes p-zz { 50% { transform: scaleY(.96); } }
@media (prefers-reduced-motion: reduce) { .scene .evo, .scene .zz, .scene .suck { animation: none; } }
.sheet .dex { display: grid; grid-template-columns: repeat(auto-fill, minmax(66px, 1fr)); gap: 4px; }
.sheet .dex button { display: grid; justify-items: center; padding: 2px 2px 4px; border: 1px solid var(--line); border-radius: 6px; background: #0e0e0d;
  color: var(--muted); font: 9px var(--mono); min-width: 0; }
.sheet .dex button span { max-width: 100%; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.sheet img.spr { image-rendering: pixelated; }
.sheet .dex img, .sheet .dex .q { width: 48px; height: 48px; }
.sheet .q { display: grid; place-items: center; font: 700 14px var(--mono); }
.sheet .dex .q.unk { opacity: .35; }
.sheet .dex .seen img { filter: brightness(0) invert(.25); }
.sheet .dex .own { color: var(--ink); border-color: var(--yellow-dim); cursor: pointer; }
.sheet .dex .own:hover { border-color: var(--yellow); }
.sheet .dex .cur { background: #ffd10018; border-color: var(--yellow); }
.sheet .box { display: grid; gap: 4px; max-height: 420px; overflow: auto; }
.sheet .mon { display: grid; grid-template-columns: 40px 1fr auto; gap: 8px; align-items: center; padding: 2px 6px 2px 2px; border: 1px solid var(--line);
  border-radius: 6px; font-size: 13px; background: #0e0e0d; }
.sheet .mon img, .sheet .mon .q { width: 40px; height: 40px; }
.sheet .mon small { display: block; color: var(--muted); font: 10px var(--mono); }
.sheet .mon.cur { border-color: var(--yellow); background: #ffd1000d; }
.sheet .mon .tag { font: 700 11px var(--mono); color: var(--yellow); }
.sheet .tchip { display: inline-block; font: 700 9px var(--mono); padding: 0 5px; border-radius: 3px; color: #111; text-transform: uppercase; margin-left: 4px; vertical-align: 1px; }
.sheet .pk { display: grid; grid-template-columns: repeat(2, 1fr); gap: 8px; }
.sheet .pk button { display: grid; justify-items: center; padding: 8px; border: 1px solid var(--line); border-radius: 8px; background: var(--panel2); color: var(--ink);
  font: 700 13px system-ui, sans-serif; cursor: pointer; }
.sheet .pk button:hover, .sheet .pk button:focus-visible { border-color: var(--yellow); }
.sheet .pk img, .sheet .pk .q { width: 96px; height: 96px; }
.sheet .partner { display: block; width: 160px; height: 160px; margin: 0 auto; }
.sheet .partner.q { font-size: 28px; }
.ach.badges div.on::before { content: "🏅 "; }
</style>`);

  // ---------- Sprites ----------
  let spritesOk = null;   // null = untested, false = unreachable (offline, proxy): draw the fallback
  const probe = new Image();
  probe.onload = () => { spritesOk = true; };
  probe.onerror = () => { spritesOk = false; if (S.scene) draw(); if (sheetOpen()) openSheet(); };
  probe.src = SPRITE + '25.png';
  const url = (id, back) => `${SPRITE}${back ? 'back/' : ''}${id}.png`;
  const img = (id, cls = '') => spritesOk === false ? `<span class="q ${cls}" style="color:${TC[TYPE[id]]}">${esc(NAMES[id].slice(0, 3))}</span>`
    : `<img class="spr ${cls}" src="${url(id)}" alt="" loading="lazy" onerror="this.style.visibility='hidden'">`;
  // feet at (cx, by); front sprites face left, back sprites show the partner from behind
  function spr(id, cx, by, size, { back = false, flip = false } = {}) {
    const inner = spritesOk === false
      ? `<circle cy="${-size * .32}" r="${size * .28}" fill="${TC[TYPE[id]]}" stroke="#121211" stroke-width="1"/><text y="${-size * .28}" font-size="${size * .14}" fill="#111">${esc(NAMES[id].slice(0, 5).toUpperCase())}</text>`
      : `<image href="${url(id, back)}" x="${-size / 2}" y="${-size * .86}" width="${size}" height="${size}" style="image-rendering:pixelated"${flip ? ' transform="scale(-1 1)"' : ''}/>`;
    return `<g transform="translate(${cx} ${by})">${inner}</g>`;
  }
  const ballSvg = (b, r = 4) => `<circle r="${r}" fill="#f4f4f0" stroke="#111" stroke-width=".7"/><path d="M${-r} 0A${r} ${r} 0 0 1 ${r} 0Z" fill="${b.top}" stroke="#111" stroke-width=".7"/>` +
    (b.mult === 2 ? `<path d="M${-r * .55} ${-r * .8}v${r * .65}M${r * .55} ${-r * .8}v${r * .65}" stroke="#ffd100" stroke-width="${r * .3}"/>` : '') +
    (b.mult === 1.5 ? `<path d="M${-r * .8} ${-r * .4}l${r * .4} ${-r * .35}M${r * .8} ${-r * .4}l${-r * .4} ${-r * .35}" stroke="#e83030" stroke-width="${r * .28}"/>` : '') +
    `<path d="M${-r} 0H${r}" stroke="#111" stroke-width=".9"/><circle r="${r * .32}" fill="#f4f4f0" stroke="#111" stroke-width=".6"/>`;
  const trainer = (pose = 'stand') => `<g class="fig"><circle cx="0" cy="-46" r="5.5"/><path d="M0 -40V-20${pose === 'sit' ? 'L9 -16L10 0M0 -20L6 -14L12 -12' : 'L-6 0M0 -20L6 0'}"/>` +
    `<path d="M0 -36L-6 -28"/><path d="M0 -36L8 -31"/></g><path d="M-6 -47a6 6 0 0 1 12 0z" fill="#e83030"/><path d="M4 -48.5h6" stroke="#e83030" stroke-width="2" stroke-linecap="round"/>` +
    '<path d="M-1.5 -52.5h3" stroke="#f4f4f0" stroke-width="1.6"/>';

  // ---------- State ----------
  const S = { scene: null, wild: null, wl: 1, hp: 0, max: 1, phhp: null, foeAt: 0, stay: 30000, busy: false, ko: 0, lastHit: 0, turn: 0, throws: 0,
    lastThrow: -9, sayT: 0, rare: 0, xp: null, level: null, game: null, att: [], evolving: false };
  let root, svg, layer;
  const hpMax = (id, L) => Math.floor(2 * 60 * power(id) * L / 100) + L + 10;
  const pmax = () => { const m = partner(); return m ? Math.round(hpMax(m.id, lvOf(m)) * 1.4) : 1; };   // a trained partner is sturdier than wild ones
  function dmgCalc(a, aL, d, dL, pow) {   // the classic formula, with a species power factor in place of attack/defense stats
    const e = eff(TYPE[a], TYPE[d]), crit = Math.random() < .1;
    const n = ((2 * aL / 5 + 2) * pow * power(a) / power(d) / 50 + 2) * e * (crit ? 1.5 : 1) * (.6 + Math.random() * .65);   // wide spread: upsets happen
    return { dmg: Math.max(1, Math.round(n)), e, crit };
  }

  const backdrop = () => '<defs><linearGradient id="p-sky" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#132131"/><stop offset="1" stop-color="#1f3a33"/></linearGradient>' +
    '<linearGradient id="p-ground" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#244a2a"/><stop offset="1" stop-color="#16301b"/></linearGradient>' +
    '<radialGradient id="p-vig" cx=".5" cy=".55" r=".72"><stop offset=".6" stop-color="#000" stop-opacity="0"/><stop offset="1" stop-color="#000" stop-opacity=".55"/></radialGradient>' +
    '<radialGradient id="p-glow"><stop offset="0" stop-color="#ffb020" stop-opacity=".35"/><stop offset="1" stop-color="#ffb020" stop-opacity="0"/></radialGradient></defs>' +
    '<rect width="200" height="96" fill="url(#p-sky)"/>' + [[18, 10], [44, 20], [92, 8], [128, 18], [176, 12], [160, 28], [66, 6]].map(([x, y]) => `<circle cx="${x}" cy="${y}" r=".7" fill="#ecebe6" opacity=".6"/>`).join('') +
    '<path d="M0 60Q30 44 62 56T124 52T200 54V96H0Z" fill="#1a3324"/><path d="M0 66Q50 58 100 64T200 62V96H0Z" fill="url(#p-ground)"/>' +
    [8, 24, 92, 108, 182, 196].map(x => `<path d="M${x - 5} 96L${x - 3} 84L${x - 1} 92L${x + 1} 82L${x + 3} 91L${x + 5} 85L${x + 6} 96Z" fill="#2f6b34"/>`).join('') +
    '<rect width="200" height="96" fill="url(#p-vig)"/>';

  function mount() {
    root = document.getElementById('arena');
    if (!root) return false;
    root.tabIndex = 0; root.setAttribute('role', 'button'); root.title = 'Trainer card & Pokédex';
    root.innerHTML = `<div class="hud"><b id="gLv">LV 1</b><span class="tt" id="gTitle">…</span><span class="xpn" id="gXp"></span></div>
      <div class="xpbar"><i id="gBar" style="width:0"></i></div>
      <svg class="scene" viewBox="0 0 200 96">${backdrop()}<g id="gWorld"></g><g id="gFoe"></g><g id="gTop"></g><text id="gSay" class="say" x="58" y="22"></text><g id="gFx"></g></svg>
      <div class="cap" id="gCap">…</div><div class="banner" id="gBanner"></div>`;
    svg = root.querySelector('svg'); layer = root.querySelector('#gFx');
    root.onclick = openSheet;
    root.onkeydown = e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openSheet(); } };
    return true;
  }

  // ---------- Scene ----------
  function pickScene(att) {
    const gate = att.find(s => s.status === 'approval');
    if (gate) return { kind: 'gate', target: gate };
    if (!partner()) return { kind: 'start' };
    if (S.ko) return Date.now() - S.ko < 2600 && S.scene ? S.scene : { kind: 'rest', ko: true };
    const work = att.filter(s => s.status === 'working').sort((a, b) => a.idleSec - b.idleSec);
    const wait = att.filter(s => s.status === 'waiting').length;
    if (work.length) return { kind: 'battle', target: work[0], wait };
    if (wait) return { kind: 'idle', wait };
    return { kind: 'rest' };
  }
  const pname = () => partner() ? NAMES[partner().id] : 'partner';
  const line = (k, m = '') => pick(LINES[k]).replace('{p}', pname()).replace('{m}', m);
  function setCap() {
    const sc = S.scene, c = document.getElementById('gCap'), t = sc.target, where = t ? t.title || t.project : '';
    c.textContent = sc.kind === 'gate' ? `😴 Snorlax blocks the path · approval needed · ${where}`
      : sc.kind === 'start' ? '🎒 click to choose your starter Pokémon'
      : sc.kind === 'battle' ? `⚔ ${pname()} vs ${S.wild ? `wild ${NAMES[S.wild]} Lv ${S.wl}` : '…'} · ${where}${sc.wait ? ` · 💬 ${sc.wait} waiting` : ''}`
      : sc.kind === 'idle' ? `💬 ${sc.wait} session${sc.wait > 1 ? 's' : ''} await${sc.wait > 1 ? '' : 's'} your orders`
      : sc.ko ? `🏥 ${pname()} is healing at the Pokémon Center…` : '🏥 resting · no open sessions';
    root.className = `arena s-${sc.ko ? 'ko' : sc.kind === 'start' ? 'idle' : sc.kind}`;
  }

  function draw() {
    const sc = S.scene, w = svg.querySelector('#gWorld'), m = partner();
    let h = '';
    if (sc.kind === 'rest') {   // a little Pokémon Center, the partner napping in front of it
      h += '<circle cx="150" cy="60" r="34" fill="url(#p-glow)"/><g transform="translate(150 76)"><rect x="-26" y="-26" width="52" height="26" fill="#ecebe6" stroke="#121211" stroke-width="1"/>' +
        '<path d="M-30 -26L0 -40L30 -26Z" fill="#e83030" stroke="#121211" stroke-width="1"/><rect x="-6" y="-14" width="12" height="14" fill="#5ab0ff" stroke="#121211" stroke-width=".8"/>' +
        '<circle cy="-31" r="4.5" fill="#f4f4f0" stroke="#121211" stroke-width=".8"/><path d="M-2.5 -31h5M0 -33.5v5" stroke="#e83030" stroke-width="1.6"/>' +
        '<rect x="-21" y="-20" width="9" height="7" fill="#ffd100" opacity=".8"/><rect x="12" y="-20" width="9" height="7" fill="#ffd100" opacity=".8"/></g>';
      h += `<g transform="translate(30 90)">${trainer('sit')}</g>`;
      if (m) h += `<g class="zz" opacity=".9">${spr(m.id, 78, 92, 44, { flip: true })}</g>`;
      h += '<g fill="#8d8a82">' + [0, 1, 2].map(i => `<text x="${92 + i * 6}" y="${58 - i * 7}" font-size="${6 + i * 1.5}" opacity="0">z<animate attributeName="opacity" values="0;1;0" dur="2.4s" begin="${i * .8}s" repeatCount="indefinite"/></text>`).join('') + '</g>';
    } else {
      h += `<g transform="translate(16 92) scale(.8)">${trainer()}</g>`;
      if (sc.kind === 'battle') h += '<ellipse cx="62" cy="90" rx="26" ry="4" fill="#3d6b3a" opacity=".7"/><ellipse cx="150" cy="78" rx="24" ry="4" fill="#3d6b3a" opacity=".7"/>';
      if (m) h += `<g class="mine"><animateTransform class="lunge" attributeName="transform" type="translate" values="0 0;14 -3;0 0" keyTimes="0;.35;1" dur=".45s" begin="indefinite"/>` +
        `<animateTransform class="flinch" attributeName="transform" type="translate" values="0 0;-5 0;0 0" dur=".3s" begin="indefinite"/>` +
        `<animateTransform class="fall" attributeName="transform" type="translate" values="0 0;0 40" dur=".6s" fill="freeze" begin="indefinite"/>` +
        `<g class="${S.evolving ? 'evo' : ''}">${sc.kind === 'battle' ? spr(m.id, 62, 98, 62, { back: true }) : spr(m.id, 58, 92, 50, { flip: true })}</g></g>`;
      if (sc.kind === 'idle' || sc.kind === 'start') {
        const wide = sc.kind === 'start';
        h += `<g transform="translate(90 30)"><path d="M-4 0h${wide ? 66 : 40}a4 4 0 0 1 4 4v8a4 4 0 0 1-4 4h-${wide ? 56 : 30}l-6 6v-6h-4a4 4 0 0 1-4-4v-8a4 4 0 0 1 4-4z" fill="#ffd100"/>` +
          `<text x="${wide ? 29 : 16}" y="10.5" fill="#111" font-size="7">${wide ? 'PICK A STARTER!' : '!  ORDERS?'}</text><animateTransform attributeName="transform" type="translate" values="90 30;90 27;90 30" dur="1.2s" repeatCount="indefinite"/></g>`;
      }
    }
    w.innerHTML = h;
    svg.querySelector('#gSay').textContent = '';
    drawFoe(); drawTop();
    if (reduce.matches) svg.pauseAnimations(); else svg.unpauseAnimations();
  }
  function drawFoe() {
    const g = svg.querySelector('#gFoe'), sc = S.scene;
    let h = '';
    if (sc.kind === 'gate') h = `<g class="zz">${spr(143, 152, 96, 78)}</g><g fill="#8d8a82">` + [0, 1, 2].map(i => `<text x="${172 + i * 7}" y="${40 - i * 7}" font-size="${7 + i * 1.5}" opacity="0">Z<animate attributeName="opacity" values="0;1;0" dur="2.4s" begin="${i * .8}s" repeatCount="indefinite"/></text>`).join('') + '</g>';
    else if (sc.kind === 'battle' && S.wild) h = `<g class="enemy spawn${S.hp <= 0 ? ' dead' : ''}"><animateTransform class="lunge" attributeName="transform" type="translate" values="0 0;-12 3;0 0" keyTimes="0;.35;1" dur=".45s" begin="indefinite"/>` +
      `<animateTransform class="shake" attributeName="transform" type="translate" values="0 0;4 0;-3 0;2 0;0 0" dur=".3s" begin="indefinite"/>${spr(S.wild, 150, 84, LEGEND.has(S.wild) ? 64 : 56)}</g>`;
    g.innerHTML = h;
  }
  function drawTop() {
    const g = svg.querySelector('#gTop'), sc = S.scene, m = partner();
    if (!g || !sc) return;
    let h = '';
    if (m) {
      const max = pmax(), r = Math.max(0, S.phhp / max), hc = r > .5 ? '#3ddc84' : r > .25 ? '#ffb020' : '#ff4d4f';
      h += `<text class="lbl" x="8" y="7.5" fill="#8d8a82" style="text-anchor:start">${esc(NAMES[m.id].toUpperCase())} Lv${lvOf(m)} · HP ${Math.max(0, Math.ceil(S.phhp))}/${max}</text>` +
        `<rect x="8" y="10" width="44" height="3" rx="1.5" fill="#2c2b28"/><rect x="8" y="10" width="${(44 * r).toFixed(1)}" height="3" rx="1.5" fill="${hc}"/>`;
    }
    if (sc.kind === 'gate') h += '<text class="lbl" x="150" y="7.5" fill="#ff4d4f">SNORLAX</text><text class="lbl" x="150" y="13.5" fill="#8d8a82" font-size="4.6">ASLEEP · NEEDS APPROVAL</text>';
    else if (sc.kind === 'battle' && S.wild) {
      const c = TC[TYPE[S.wild]];
      h += `<text class="lbl" x="150" y="7.5" fill="${c}">${caught(S.wild) ? '✓ ' : ''}${esc(NAMES[S.wild].toUpperCase())}</text>` +
        `<rect x="128" y="10" width="44" height="3" rx="1.5" fill="#2c2b28"/><rect x="128" y="10" width="${(44 * Math.max(0, S.hp / S.max)).toFixed(1)}" height="3" rx="1.5" fill="${c}"/>` +
        `<text class="lbl" x="175" y="13.2" fill="#8d8a82" style="text-anchor:start" font-size="5">Lv${S.wl}</text>`;
    }
    g.innerHTML = h;
  }

  const begin = (sel, el = svg) => { if (!reduce.matches) el.querySelectorAll(sel).forEach(a => a.beginElement?.()); };
  function float(x, y, text, cls = '', sub = '', rise = 16) {
    const t = document.createElementNS(NS, 'text');
    t.setAttribute('x', x); t.setAttribute('y', y); t.setAttribute('class', 'dmg ' + cls);
    t.innerHTML = esc(text) + (sub ? `<tspan class="sub" x="${x}" dy="6">${esc(sub)}</tspan>` : '') +
      `<animate attributeName="y" from="${y}" to="${y - rise}" dur="1.1s" begin="indefinite" fill="freeze"/><animate attributeName="opacity" values="1;1;0" dur="1.1s" begin="indefinite" fill="freeze"/>`;
    layer.append(t); begin('animate', t);
    setTimeout(() => t.remove(), 1200);
  }
  function fx(html, ms, cls = '') { const g = document.createElementNS(NS, 'g'); if (cls) g.setAttribute('class', cls); g.innerHTML = html; layer.append(g); setTimeout(() => g.remove(), ms); return g; }
  function ribbon(t1, t2, color) {
    layer.querySelectorAll('.ribbon').forEach(r => r.remove());
    fx(`<rect x="22" y="23" width="156" height="17" rx="2" fill="#0d1a24" stroke="${color}" stroke-width=".8" opacity=".94"/>` +
      `<text x="100" y="31" fill="${color}" font-size="6.2">${esc(t1)}</text><text x="100" y="37.4" fill="#ecebe6" font-size="4.4">${esc(t2)}</text>`, 2300, 'ribbon');
  }
  function banner(big, small, lose = false) {
    const b = document.getElementById('gBanner');
    b.innerHTML = `<div>${esc(big)}<small>${esc(small)}</small></div>`;
    b.className = 'banner' + (lose ? ' lose' : ''); void b.offsetWidth; b.classList.add('on');
  }
  function speak(text, who = 'me') {
    const t = svg.querySelector('#gSay');
    if (!t) return;
    t.setAttribute('x', who === 'me' ? 58 : 194); t.style.textAnchor = who === 'me' ? 'middle' : 'end';
    t.textContent = text; S.sayT = Date.now();
  }

  // ---------- Encounters ----------
  // wild level near the partner's; evolved forms only from their evolution level, legendaries from trainer LV 8 and Lv 50 (Mewtwo 70)
  function nextWild() {
    const L = lvOf(partner()), wl = Math.max(2, Math.min(100, L + rint(-3, 2) + (Math.random() < .08 ? 4 : 0)));
    const kind = KIND_TYPES[toolKind(S.scene?.target?.lastTool)] || '', rare = S.rare;
    const ok = id => id !== S.wild && (MIN[id] || 0) <= wl && (!LEGEND.has(id) || (trainerLv() >= 8 && wl >= (id === 150 ? 70 : 50)));
    const list = IDS.filter(ok);
    // a lure (level-up, big deed) makes everything but common ones 5× likelier, legendaries only 2×
    const wts = list.map(id => rarity(id) * (rare ? (LEGEND.has(id) ? 2 : rarity(id) < .3 ? 5 : 1) : 1) *
      (kind.split(' ').includes(TYPE[id]) ? 3 : 1) * (caught(id) ? 1 : 1.5));
    let r = Math.random() * wts.reduce((a, b) => a + b, 0);
    S.rare = 0;
    return { id: list.find((x, i) => (r -= wts[i]) < 0) || list[0], wl };
  }
  function spawn() {
    const { id, wl } = nextWild(), fresh = !P.seen[id];
    S.wild = id; S.wl = wl; S.max = S.hp = hpMax(id, wl);
    S.foeAt = Date.now(); S.stay = 25000 + Math.random() * 20000; S.turn = 0; S.throws = 0; S.lastThrow = -9;
    P.seen[id] = 1; save();
    drawFoe(); drawTop(); setCap();
    const rn = rarityName(id);
    ribbon(`A WILD ${NAMES[id].toUpperCase()} APPEARED!`, `Lv ${wl} · ${TN[TYPE[id]].toUpperCase()}${rn === 'common' ? '' : ` · ${rn === 'uncommon' ? '' : '★ '}${rn.toUpperCase()}`}${fresh ? ' · NEW POKÉDEX ENTRY' : caught(id) ? ' · ✓ CAUGHT' : ''}`, TC[TYPE[id]]);
    SFX.spawn();
    const t = svg.querySelector('#gSay'); if (t) t.textContent = '';
    setTimeout(() => { if (S.wild === id && S.scene?.kind === 'battle') speak(`${NAMES[id]}!`, 'foe'); }, 2400);
  }
  function flee() {
    S.busy = true; svg.querySelector('.enemy')?.classList.add('flee');
    float(150, 44, `${NAMES[S.wild]} fled!`, 'miss');
    setTimeout(() => { S.busy = false; if (S.scene?.kind === 'battle' && !S.ko) spawn(); else S.wild = null; }, 700);
  }

  // one round: the partner attacks; power = real XP gained since the last update (always hits)
  function attack(power = 0) {
    const m = partner();
    if (!m || !S.scene || S.scene.kind !== 'battle' || !S.wild || S.busy || S.ko || S.evolving) return;
    if (!power && Date.now() - S.foeAt < 1500) return;   // let the "A wild … appeared" ribbon breathe
    const en = svg.querySelector('.enemy');
    if (!en || en.classList.contains('dead')) return;
    const L = lvOf(m), mv = move(m.id, L), r = dmgCalc(m.id, L, S.wild, S.wl, mv.pow), miss = !power && Math.random() < .06;
    const dmg = r.dmg + power;
    begin('.mine > .lunge');
    setTimeout(() => {
      if (!en.isConnected || en.classList.contains('dead')) return;
      if (miss) return float(146, 46, 'MISS', 'miss', mv.name.toUpperCase(), 12);
      en.classList.remove('hit'); void en.getBBox(); en.classList.add('hit'); begin('.enemy > .shake');
      SFX.hit(r.e > 1 || r.crit || power > 0);
      const sub = [power ? 'CLAUDE POWER' : mv.name.toUpperCase(), r.e > 1 ? 'SUPER EFFECTIVE!' : r.e < 1 ? 'NOT VERY EFFECTIVE' : '', r.crit ? 'CRIT' : ''].filter(Boolean).join(' · ');
      float(146, 46, `-${dmg}`, r.crit || r.e > 1 ? 'crit' : '', sub, 12);
      S.hp -= dmg; drawTop();
      if (S.hp <= 0) return faint(en);
      // weakened and not in your Pokédex yet: throw a ball (max 3 per encounter)
      if (!caught(S.wild) && S.throws < 3 && S.hp / S.max <= .5 && S.turn - S.lastThrow >= 2) { S.lastThrow = S.turn; setTimeout(() => throwBall(en), 650); }
    }, 170);
    S.turn++; setTimeout(() => counter(en), 700);   // the wild Pokémon strikes back
    if (Date.now() - S.sayT > 6000 && Date.now() - S.foeAt > 2400 && Math.random() < .25) speak(line('battle', mv.name));
  }
  function counter(en) {
    const m = partner();
    if (!m || !en.isConnected || en.classList.contains('dead') || S.ko || S.busy || S.scene?.kind !== 'battle') return;
    begin('.enemy > .lunge');
    setTimeout(() => {
      if (S.ko || S.busy) return;
      const mv = move(S.wild, S.wl);
      if (Math.random() < .08) return float(54, 66, 'MISS', 'miss');
      const r = dmgCalc(S.wild, S.wl, m.id, lvOf(m), mv.pow);
      begin('.mine > .flinch'); SFX.hurt();
      float(54, 66, `-${r.dmg}`, 'hurt', mv.name.toUpperCase() + (r.e > 1 ? ' · SUPER EFFECTIVE!' : ''));
      S.phhp -= r.dmg; S.lastHit = Date.now(); drawTop();
      if (S.phhp <= 0) lose();
    }, 170);
  }
  function gainExp(n) {
    const m = partner(); if (!m || n <= 0) return;
    const before = lvOf(m);
    m.exp = Math.max(m.exp, Math.min(m.exp + n, (levelCap() + 1) ** 3 - 1));   // the trainer's level caps how far partners grow
    const after = lvOf(m);
    if (after > before) {
      S.phhp = Math.round(S.phhp * pmax() / Math.round(hpMax(m.id, before) * 1.4));
      setTimeout(() => { float(60, 50, `Lv ${after}!`, 'xp', 'LEVEL UP'); SFX.level(); }, 500);
    }
    save(); drawTop();
    const e = EVO[m.id];
    if (e && after >= evoLv(e)) setTimeout(() => evolve(m, e), 1400);
  }
  function faint(en) {
    S.busy = true; en.classList.add('dead'); SFX.faint();
    P.w++;
    const exp = winExp(S.wild, S.wl);
    float(150, 44, `${NAMES[S.wild]} fainted`, 'xp');
    setTimeout(() => float(150, 56, `+${exp} EXP`, 'loot'), 250);
    gainExp(exp);
    S.phhp = Math.min(pmax(), S.phhp + Math.round(pmax() * .25)); drawTop();   // a berry after each win
    setTimeout(() => { S.busy = false; if (S.scene?.kind === 'battle' && !S.ko && !S.evolving) spawn(); else S.wild = null; }, 1100);
  }
  function throwBall(en) {
    if (S.busy || S.ko || S.evolving || !en.isConnected || en.classList.contains('dead') || S.scene?.kind !== 'battle') return;
    S.busy = true; S.throws++;
    const b = ball(), id = S.wild, wl = S.wl;
    const chance = Math.min(.95, Math.max(.02, catchRate(id) * b.mult * (1.5 - S.hp / S.max)));
    const ok = Math.random() < chance, wobbles = ok ? 3 : rint(0, 2), wait = 560 + Math.max(1, wobbles) * 700 + 200;
    const g = fx(`<g>${ballSvg(b)}<animateMotion path="M20 60 Q86 -6 150 54" dur=".55s" fill="freeze" begin="indefinite"/></g>`, wait + 2000);
    begin('animateMotion', g); SFX.throw();
    speak(`Go, ${b.name}!`);
    setTimeout(() => {
      en.classList.add('suck');
      g.innerHTML = `<g transform="translate(150 74)"><g>${ballSvg(b)}<animateTransform attributeName="transform" type="rotate" values="0;-28;0;28;0" dur=".7s" begin="indefinite" repeatCount="${Math.max(1, wobbles)}"/></g></g>`;
      if (wobbles) { begin('animateTransform', g); for (let i = 0; i < wobbles; i++) setTimeout(SFX.wobble, i * 700 + 150); }
    }, 560);
    setTimeout(() => {
      if (S.wild !== id) { g.remove(); S.busy = false; return; }
      if (!ok) {
        g.remove(); en.classList.remove('suck');
        float(150, 44, 'It broke free!', 'miss', `${b.name.toUpperCase()} · ${Math.round(chance * 100)}%`);
        S.busy = false;
        return;
      }
      g.insertAdjacentHTML('beforeend', '<g fill="#ffd100">' + [[-8, -6], [8, -7], [0, -11]].map(([x, y]) =>
        `<path transform="translate(${150 + x} ${74 + y})" d="M0 -2.5L.7 -.7L2.5 0L.7 .7L0 2.5L-.7 .7L-2.5 0L-.7 -.7Z"/>`).join('') + '</g>');
      addMon(id, wl); P.w++;
      SFX.gotcha();
      banner('GOTCHA!', `${NAMES[id]} was caught! · Lv ${wl} · Pokédex ${new Set(P.box.map(x => x.id)).size}/150`);
      gainExp(winExp(id, wl));
      setTimeout(() => { g.remove(); S.busy = false; S.wild = null; if (S.scene?.kind === 'battle' && !S.ko && !S.evolving) spawn(); }, 1800);
    }, wait);
  }
  // the partner faints: cosmetic only, real XP is never touched
  function lose() {
    S.phhp = 0; S.ko = Date.now(); S.busy = true; drawTop();
    P.l++; save();
    if (reduce.matches) svg.querySelector('.mine')?.setAttribute('opacity', '0'); else begin('.mine > .fall');
    SFX.lose();
    banner(`${pname().toUpperCase()} FAINTED`, `vs wild ${NAMES[S.wild]} Lv ${S.wl} · off to the Pokémon Center`, true);
    setTimeout(() => { S.busy = false; S.wild = null; setScene(pickScene(S.att), true); }, 2600);
  }
  function evolve(m, e) {
    if (S.evolving || partner() !== m || EVO[m.id] !== e) return;
    const to = Array.isArray(e[0]) ? pick(e[0]) : e[0], from = m.id;
    S.evolving = true;
    if (S.scene) draw();
    banner(`What? ${NAMES[from]} is evolving!`, e[1] === 'S' ? 'an evolution stone glows…' : e[1] === 'T' ? 'a trade evolution…' : `Lv ${evoLv(e)}`);
    SFX.evolve();
    setTimeout(() => {
      m.id = to; P.seen[to] = 1; save();
      S.evolving = false; S.phhp = pmax();
      if (S.scene) { draw(); setCap(); }
      banner('CONGRATULATIONS!', `${NAMES[from]} evolved into ${NAMES[to]}!`);
      SFX.level();
      if (sheetOpen()) openSheet();
      if (S.scene?.kind === 'battle' && !S.busy && !S.ko) spawn();
    }, 3200);
  }

  function setScene(sc, force = false) {
    const same = !force && S.scene && S.scene.kind === sc.kind && !!S.scene.ko === !!sc.ko;
    S.scene = sc;
    if (!same) {
      draw();
      if (sc.kind === 'battle' && !S.busy && !S.evolving && (!S.wild || S.hp <= 0)) spawn();
      if (sc.kind === 'gate') { SFX.snore(); speak(pick(LINES.gate)); }
      else if (sc.kind === 'idle') speak(line('idle'));
      else if (sc.kind === 'rest') { speak(sc.ko ? line('ko') : LINES.rest[0]); if (!S.busy) S.wild = null; }   // the wild one wanders off
    }
    setCap();
  }

  function trainerUp(from, to, g) {
    const nb = BALLS.find(b => b.lv > from && b.lv <= to);
    banner(`TRAINER LV ${to}!`, `${g.title} · level cap ${levelCap()}${nb ? ` · 🔓 ${nb.name}` : ''}${to >= 8 && from < 8 ? ' · legendaries roam' : ''}`);
    SFX.level();
    S.rare = Date.now();   // a level-up lures out a rare Pokémon
  }

  // ---------- Update from a snapshot ----------
  function update(d) {
    const g = d.game;
    if (!g || (!root && !mount())) return;
    S.game = g;
    S.att = d.attention || [];
    document.getElementById('gLv').textContent = `LV ${g.level}`;
    document.getElementById('gTitle').textContent = `Trainer · ${g.title}`;
    document.getElementById('gXp').textContent = `${fmt(g.xp - g.levelXp)} / ${fmt(g.nextXp - g.levelXp)} XP`;
    document.getElementById('gBar').style.width = ((g.xp - g.levelXp) / (g.nextXp - g.levelXp) * 100).toFixed(1) + '%';
    if (S.phhp === null) S.phhp = pmax();
    setScene(pickScene(S.att));
    if (S.xp !== null && g.xp > S.xp) {
      const gain = g.xp - S.xp;
      float(100, 66, `+${gain} XP`, 'xp');
      attack(gain);
      gainExp(gain);   // real XP counts 1:1
      if (gain >= 50) S.rare = Date.now();   // a big deed draws out a rare one
    }
    const seen = +store.get('pokeTrainerLevel') || 0;
    if (S.level !== null ? g.level > S.level : seen && g.level > seen) trainerUp(S.level ?? seen, g.level, g);
    store.set('pokeTrainerLevel', g.level);
    S.xp = g.xp; S.level = g.level;
    if (sheetOpen()) openSheet();
  }

  setInterval(() => {
    if (document.hidden || !S.scene || !svg) return;
    const now = Date.now(), sc = S.scene, max = pmax();
    if (S.rare && now - S.rare > 120000) S.rare = 0;
    // healing: full at the Pokémon Center, slowly while waiting, a trickle in battle after a quiet spell
    const heal = sc.kind === 'rest' ? .34 : sc.kind !== 'battle' ? .1 : now - S.lastHit > 9000 ? .03 : 0;
    if (heal && !S.busy && S.phhp < max) { S.phhp = Math.min(max, S.phhp + Math.ceil(max * heal)); drawTop(); }
    if (S.ko && now - S.ko > 2600 + 4200 && S.phhp >= max) { S.ko = 0; setScene(pickScene(S.att)); }
    else if (sc.kind === 'battle' && !S.busy && S.wild) {
      if (now - S.foeAt > S.stay && S.hp > 0) flee();
      else attack();
    }
    if (S.sayT && now - S.sayT > 3500) { const t = svg.querySelector('#gSay'); if (t) t.textContent = ''; S.sayT = 0; }
  }, 1400);

  // ---------- Trainer card, party and Pokédex ----------
  const sheetOpen = () => !!document.querySelector('.sheet-bg');
  function closeSheet() { document.querySelector('.sheet-bg')?.remove(); root?.focus(); }
  const chip = id => `<span class="tchip" style="background:${TC[TYPE[id]]}">${TN[TYPE[id]]}</span>`;
  const no = id => '#' + String(id).padStart(3, '0');
  function choose(u) {   // make a caught Pokémon the partner: the avatar in the arena
    P.partner = u; save();
    S.phhp = pmax(); S.ko = 0; S.wild = null; S.busy = false; S.evolving = false;
    if (S.scene) setScene(pickScene(S.att), true);
    openSheet();
  }
  function openSheet() {
    const g = S.game; if (!g) return;
    const m = partner(), owned = new Set(P.box.map(x => x.id)), seenN = Object.keys(P.seen).length, nb = BALLS.find(b => b.lv > g.level);
    const scroll = document.querySelector('.sheet')?.scrollTop;
    document.querySelector('.sheet-bg')?.remove();
    let left;
    if (m) {
      const L = lvOf(m), e = EVO[m.id], cap = levelCap(), next = (L + 1) ** 3;
      left = `${img(m.id, 'partner')}
        <div class="lv">Lv ${L}</div><div style="font-weight:700;margin-top:4px">${esc(NAMES[m.id])}${chip(m.id)} <small style="color:var(--muted)">${no(m.id)}</small></div>
        <div class="xpbar"><i style="width:${L >= cap ? 100 : ((m.exp - L ** 3) / (next - L ** 3) * 100).toFixed(1)}%"></i></div>
        <div class="kv"><span>EXP</span><span>${m.exp.toLocaleString()}</span><span>next level</span><span>${L >= cap ? `capped at Lv ${cap}` : (next - m.exp).toLocaleString() + ' EXP'}</span>
          <span>level cap</span><span>Lv ${cap}</span><span>HP</span><span>${Math.max(0, Math.ceil(S.phhp ?? pmax()))} / ${pmax()}</span>
          <span>move</span><span>${esc(move(m.id, L).name)}</span>
          <span>evolves</span><span>${e ? `${[].concat(e[0]).map(x => esc(NAMES[x])).join(' / ')} · Lv ${evoLv(e)}` : '—'}</span></div>`;
    } else left = '<div class="lv" style="font-size:22px">No partner yet</div><p style="color:var(--muted);font-size:13px">Choose a starter. Wild Pokémon appear while a Claude session works.</p>';
    const box = [...P.box].sort((a, b) => b.exp - a.exp);
    document.body.insertAdjacentHTML('beforeend', `<div class="sheet-bg"><div class="sheet" role="dialog" aria-modal="true" aria-label="Trainer card">
      <header><h3>Game of <span>Claude</span></h3><span style="font:12px var(--mono);color:var(--muted)">Pokédex ${owned.size}/150 caught · ${seenN} seen · ⚔ ${P.w}W / ${P.l}L · 🔥 ${g.streak}-day streak</span>
        <label class="thm"><select id="gTheme" aria-label="Theme"><option value="dnd">Dungeons &amp; Dragons</option><option value="pokemon" selected>Pokémon</option></select></label>
        <button class="x" type="button" aria-label="Close">✕</button></header>
      <div class="grid">
        <section><h4>Partner</h4>${left}
          <h4 style="margin-top:16px">Trainer</h4>
          <div class="kv"><span>Level</span><span>LV ${g.level}</span><span>Title</span><span>${esc(g.title)}</span><span>XP</span><span>${g.xp.toLocaleString()}</span>
            <span>next level</span><span>${(g.nextXp - g.xp).toLocaleString()} XP</span><span>XP today</span><span>+${g.xpToday.toLocaleString()}</span>
            <span>Ball</span><span>${ball().name}</span>${nb ? `<span>next ball</span><span>${nb.name} · LV ${nb.lv}</span>` : ''}
            <span>Legendaries</span><span>${g.level >= 8 ? 'roaming (Lv 50+)' : 'from trainer LV 8'}</span></div>
          <button class="btn snd" type="button" id="gSnd">${soundOn() ? '🔊 Sound on' : '🔈 Sound off'}</button>
        </section>
        <section class="wide2">${m ? `<h4>Your Pokémon (${box.length}) · choose your partner</h4><div class="box">${box.map(x => `
          <div class="mon${x === m ? ' cur' : ''}">${img(x.id)}<span>${esc(NAMES[x.id])}${chip(x.id)}<small>${no(x.id)} · Lv ${lvOf(x)}</small></span>
            ${x === m ? '<span class="tag">PARTNER</span>' : `<button class="btn sm" type="button" data-u="${x.u}">Choose</button>`}</div>`).join('')}</div>`
          : `<h4>Choose your starter</h4><div class="pk">${STARTERS.map(id => `<button type="button" data-start="${id}">${img(id)}<span>${esc(NAMES[id])}${chip(id)}</span></button>`).join('')}</div>`}
        </section>
        <section style="grid-column:1/-1"><h4>Pokédex · ${owned.size} caught · ${seenN} seen · click a caught one to make it your partner</h4><div class="dex">${IDS.map(id => {
          const own = owned.has(id), seen = own || P.seen[id];
          return `<button type="button" class="${own ? 'own' : seen ? 'seen' : ''}${m && m.id === id ? ' cur' : ''}"${own ? ` data-dex="${id}"` : ' disabled'} title="${seen ? `${esc(NAMES[id])} · ${TN[TYPE[id]]} · ${rarityName(id)}` : 'not seen yet'}">` +
            `${seen ? img(id) : '<span class="q unk">?</span>'}<span>${no(id)} ${seen ? esc(NAMES[id]) : ''}</span></button>`; }).join('')}</div></section>
        <section style="grid-column:1/-1"><h4>Badges</h4><div class="ach badges">${g.achievements.map(a =>
          `<div class="${a.on ? 'on' : ''}">${esc(a.name)}<small>${esc(a.desc)}</small></div>`).join('')}</div></section>
      </div><p style="padding:0 18px 12px;font-size:11px;color:var(--muted)">Pokémon progress is saved next to the XP ledger (pokemon.json), with a copy in this browser. Fan feature, not affiliated with Nintendo, Game Freak or The Pokémon Company; sprites load from the PokeAPI sprite repo.</p></div></div>`);
    const bg = document.querySelector('.sheet-bg');
    if (scroll) bg.querySelector('.sheet').scrollTop = scroll;
    bg.onclick = e => {
      if (e.target === bg) return closeSheet();
      const st = e.target.closest('[data-start]'), u = e.target.closest('[data-u]'), dx = e.target.closest('[data-dex]');
      if (st) return choose(addMon(+st.dataset.start, 5).u);
      if (u) return choose(+u.dataset.u);
      if (dx) { const best = P.box.filter(x => x.id === +dx.dataset.dex).sort((a, b) => b.exp - a.exp)[0]; if (best && best !== partner()) choose(best.u); }
    };
    bg.querySelector('.x').onclick = closeSheet;
    bg.querySelector('#gTheme').onchange = e => window.setGameTheme?.(e.target.value);
    bg.querySelector('#gSnd').onclick = () => { store.set('gameSound', soundOn() ? '0' : '1'); SFX.level(); openSheet(); };
    if (!scroll) bg.querySelector('.x').focus();
  }
  addEventListener('keydown', e => { if (e.key === 'Escape' && sheetOpen()) closeSheet(); });

  window.GAME = { update, open: openSheet };
  if (REMOTE) pull();
})();
