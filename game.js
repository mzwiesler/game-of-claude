// Game of Claude: the hero in the top-left arena. XP, levels and unlocks come from the server
// (game.py, derived from the transcripts); this file only draws and animates them.
// The arena is a dungeon that mirrors the live sessions: while a session works the hero fights a
// rotating bestiary of fantasy foes (d20 rolls, levels, HP on both sides; the hero can lose, which
// is purely cosmetic), the Permission Gate (a portcullis with a red rune lock) appears when a
// session waits for approval, the hero waits for orders when sessions wait for you and rests at the
// campfire when nothing is open. Click it for the character sheet.
// Inline SVG + SMIL duels; sounds are synthesized with WebAudio. The arena/sheet CSS below is shared
// with the Pokémon theme (poke.js); the rest only runs when the D&D theme is selected.
(() => {
  const NS = 'http://www.w3.org/2000/svg';
  const reduce = matchMedia('(prefers-reduced-motion: reduce)');
  const store = { get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
                  set(k, v) { try { localStorage.setItem(k, v); } catch (e) {} } };
  const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const fmt = n => n >= 1e6 ? (n / 1e6).toFixed(1) + 'M' : n >= 1e4 ? Math.round(n / 1e3) + 'k' : n >= 1e3 ? (n / 1e3).toFixed(1) + 'k' : String(n);
  const pick = a => a[Math.floor(Math.random() * a.length)];
  const die = n => 1 + Math.floor(Math.random() * n);
  const dice = (n, d) => { let s = 0; for (let i = 0; i < n; i++) s += die(d); return s; };

  // ---------- CSS ----------
  document.head.insertAdjacentHTML('beforeend', `<style>
.arena { width: 300px; max-width: 100%; flex: none; border: 1px solid var(--yellow-dim); border-radius: 8px; background: #121211;
  box-shadow: 0 0 24px #ffd10022; overflow: hidden; cursor: pointer; position: relative; }
.arena:hover, .arena:focus-visible { border-color: var(--yellow); outline: none; }
.arena .hud { display: flex; align-items: baseline; gap: 8px; padding: 6px 10px 0; font: 11px var(--mono); color: var(--muted); }
.arena .hud b { font: 800 13px var(--mono); color: var(--yellow); white-space: nowrap; }
.arena .hud .tt { color: var(--ink); font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.arena .hud .xpn { margin-left: auto; white-space: nowrap; }
.xpbar { height: 4px; margin: 5px 10px 0; background: var(--line); border-radius: 2px; overflow: hidden; }
.xpbar i { display: block; height: 100%; background: linear-gradient(90deg, var(--yellow-dim), var(--yellow)); box-shadow: 0 0 6px var(--yellow); transition: width .8s cubic-bezier(.2,.9,.2,1); }
.arena svg.scene { display: block; width: 100%; height: auto; margin-top: 4px; }
.arena .cap { padding: 3px 10px 7px; font: 700 10px var(--mono); letter-spacing: .05em; text-transform: uppercase; color: var(--muted);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.arena.s-gate { border-color: var(--bad); box-shadow: 0 0 24px #ff4d4f33; }
.arena.s-gate .cap { color: var(--bad); }
.arena.s-idle .cap { color: var(--yellow); }
.arena.s-battle .cap { color: var(--ok); }
.arena.s-ko .cap { color: var(--warn); }
.scene .fig { fill: none; stroke: var(--ink); stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; }
.scene text { font: 700 7px ui-monospace, monospace; text-anchor: middle; }
.scene .say { fill: var(--ink); font-size: 6.5px; paint-order: stroke; stroke: #121211; stroke-width: 2px; }
.scene .lbl { font-size: 5.5px; paint-order: stroke; stroke: #121211; stroke-width: 1.6px; }
.scene .dmg { fill: var(--ink); font-size: 9px; paint-order: stroke; stroke: #121211; stroke-width: 2px; }
.scene .dmg .sub { font-size: 5px; fill: var(--muted); }
.scene .dmg.crit { fill: var(--bad); font-size: 11px; }
.scene .dmg.xp { fill: var(--yellow); }
.scene .dmg.loot { fill: var(--warn); font-size: 7px; }
.scene .dmg.miss { fill: var(--muted); font-size: 7px; }
.scene .dmg.hurt { fill: #ff6b6b; font-size: 8px; }
.scene .dmg.heal { fill: var(--ok); font-size: 7px; }
.scene .d20 text { font-size: 5.5px; fill: #121211; stroke: none; }
.scene .hit { animation: g-hit .32s; }
@keyframes g-hit { 30% { filter: brightness(2.5) drop-shadow(0 0 4px #fff); opacity: .6; } }
.scene .dead { opacity: 0; transition: opacity .7s; }
.scene .spawn { animation: g-spawn .6s both; }
@keyframes g-spawn { from { opacity: 0; } }
.scene .flee { animation: g-flee .6s forwards; }
@keyframes g-flee { to { opacity: 0; transform: translateX(30px); } }
.scene .ribbon { animation: g-ribbon 2.3s ease-out both; }
@keyframes g-ribbon { 0% { opacity: 0; } 10%, 78% { opacity: 1; } 100% { opacity: 0; } }
.scene .fire { animation: g-fire .7s ease-out both; }
@keyframes g-fire { 0% { opacity: 0; } 25% { opacity: 1; } 100% { opacity: 0; } }
@media (prefers-reduced-motion: reduce) { .scene .flee, .scene .ribbon, .scene .fire, .scene .spawn, .scene .hit { animation: none; } }
.arena .banner { position: absolute; inset: 0; display: grid; place-items: center; pointer-events: none; opacity: 0; }
.arena .banner.on { animation: g-banner 2.8s ease-out; }
.arena .banner div { font: 900 22px system-ui, sans-serif; letter-spacing: .08em; color: #111; background: var(--yellow); padding: 4px 14px;
  border-radius: 6px; box-shadow: 0 0 30px var(--yellow); text-align: center; }
.arena .banner.lose div { background: #2a0d0e; color: var(--bad); border: 1px solid var(--bad); box-shadow: 0 0 30px #ff4d4f66; font-size: 18px; }
.arena .banner small { display: block; font: 700 10px var(--mono); letter-spacing: .04em; }
.arena .banner.lose small { color: var(--ink); }
@keyframes g-banner { 0% { opacity: 0; transform: scale(.4); } 12% { opacity: 1; transform: scale(1.12); } 20%, 80% { opacity: 1; transform: scale(1); } 100% { opacity: 0; } }
@media (prefers-reduced-motion: reduce) { .arena .banner.on { animation: none; opacity: 1; } }

.sheet-bg { position: fixed; inset: 0; z-index: 100; background: #000a; display: grid; place-items: center; padding: 16px; animation: g-spawn .2s; }
.sheet { width: min(980px, 100%); max-height: calc(100vh - 32px); overflow: auto; background: var(--panel); border: 1px solid var(--yellow-dim);
  border-radius: 10px; box-shadow: 0 0 60px #ffd10022; }
.sheet > header { display: flex; gap: 16px; align-items: center; padding: 16px 18px; border-bottom: 1px solid var(--line);
  background: linear-gradient(90deg, #ffd1001a, transparent 60%); flex-wrap: wrap; }
.sheet h3 { margin: 0; font-size: 20px; letter-spacing: .06em; text-transform: uppercase; }
.sheet h3 span { color: var(--yellow); }
.sheet .x { margin-left: auto; background: none; border: 1px solid var(--line); color: var(--muted); border-radius: 6px; font-size: 16px; width: 32px; height: 32px; cursor: pointer; }
.sheet .x:hover { color: var(--ink); border-color: var(--yellow-dim); }
.sheet .grid { display: grid; grid-template-columns: 260px 1fr 1fr; gap: 0; }
@media (max-width: 820px) { .sheet .grid { grid-template-columns: 1fr; } }
.sheet section { padding: 14px 18px; border-right: 1px solid var(--line); border-bottom: 1px solid var(--line); min-width: 0; }
.sheet h4 { margin: 0 0 10px; font-size: 11px; letter-spacing: .12em; text-transform: uppercase; color: var(--muted); }
.sheet .big { display: block; width: 100%; max-width: 220px; margin: 0 auto; }
.sheet .lv { font: 800 34px var(--mono); color: var(--yellow); line-height: 1; }
.sheet .kv { display: grid; grid-template-columns: 1fr auto; gap: 5px 12px; font: 12px var(--mono); }
.sheet .kv span:nth-child(odd) { color: var(--muted); }
.sheet .kv span:nth-child(even) { text-align: right; font-variant-numeric: tabular-nums; }
.sheet .xpbar { margin: 8px 0 4px; height: 6px; }
.sheet ul { list-style: none; margin: 0; padding: 0; display: grid; gap: 6px; }
.sheet li { display: grid; grid-template-columns: 38px 1fr; gap: 8px; align-items: center; font-size: 13px; }
.sheet li small { display: block; color: var(--muted); font-size: 11px; }
.sheet li .lvl { font: 700 10px var(--mono); text-align: center; padding: 2px 0; border-radius: 4px; border: 1px solid var(--yellow-dim); color: var(--yellow); }
.sheet li.off { opacity: .38; }
.sheet li.off .lvl { border-color: var(--line); color: var(--muted); }
.sheet li.next { opacity: 1; } .sheet li.next .lvl { border-color: var(--yellow); }
.sheet .abil { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px 8px; }
.sheet .abil div { border: 1px solid var(--line); border-radius: 8px; text-align: center; padding: 5px 2px 0; background: var(--panel2); min-width: 0; }
.sheet .abil b { display: block; font: 700 10px var(--mono); letter-spacing: .14em; color: var(--muted); }
.sheet .abil .sc { display: block; font: 800 22px var(--mono); color: var(--ink); line-height: 1.15; }
.sheet .abil .md { display: inline-block; min-width: 30px; font: 700 11px var(--mono); border: 1px solid var(--yellow-dim); color: var(--yellow);
  background: var(--panel); border-radius: 10px; padding: 0 6px; position: relative; top: 8px; }
.sheet .abil small { display: block; font-size: 10px; color: var(--muted); margin-top: 11px; padding: 0 2px 6px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.ach { display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: 8px; }
.ach div { border: 1px solid var(--line); border-radius: 6px; padding: 8px; font-size: 12px; font-weight: 700; }
.ach div small { display: block; font-weight: 400; color: var(--muted); font-size: 11px; margin-top: 2px; }
.ach div.on { border-color: var(--yellow-dim); background: #ffd1000d; }
.ach div.on::before { content: "🏆 "; }
.ach div:not(.on) { opacity: .45; } .ach div:not(.on)::before { content: "🔒 "; }
.bst { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 8px; }
.bst div { border: 1px solid var(--line); border-radius: 6px; padding: 6px 8px 6px 4px; display: grid; grid-template-columns: 44px 1fr; gap: 6px;
  align-items: center; font-size: 12px; font-weight: 700; background: #0e0e0d; }
.bst svg { width: 44px; height: 38px; }
.bst small { display: block; font: 400 10px var(--mono); color: var(--muted); margin-top: 1px; }
.bst small b { color: var(--ok); font-weight: 700; } .bst small i { color: var(--bad); font-style: normal; font-weight: 700; }
.bst div.off { opacity: .42; } .bst div.off svg { filter: grayscale(1) brightness(.7); }
.sheet .src { display: grid; grid-template-columns: 1fr auto auto; gap: 4px 12px; font: 12px var(--mono); }
.sheet .src span:nth-child(3n+1) { color: var(--muted); }
.sheet .src span:nth-child(3n) { color: var(--yellow); text-align: right; }
.sheet .src span:nth-child(3n+2) { text-align: right; }
.sheet .log { font: 12px var(--mono); display: grid; gap: 4px; }
.sheet .log div { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.sheet .log b { color: var(--yellow); }
.sheet .snd { margin-top: 12px; }
.sheet .wide2 { grid-column: span 2; } @media (max-width: 820px) { .sheet .wide2 { grid-column: auto; } }
.sheet .thm { margin-left: auto; display: inline-flex; } .sheet .thm + .x { margin-left: 0; }
.sheet .thm select { background: var(--panel2); color: var(--ink); border: 1px solid var(--line); border-radius: 6px; font: 12px var(--mono); padding: 3px 6px; }
</style>`);
  if ((window.GAME_THEME || 'dnd') !== 'dnd') return;

  // ---------- Sound (WebAudio, synthesized) ----------
  let actx = null;
  const soundOn = () => S.unlocked.has('sound') && store.get('gameSound') === '1';
  function tone(f, t, dur, type = 'square', vol = .05) {
    actx ??= new (window.AudioContext || window.webkitAudioContext)();
    const o = actx.createOscillator(), g = actx.createGain(), t0 = actx.currentTime + t;
    o.type = type; o.frequency.setValueAtTime(f, t0); o.frequency.exponentialRampToValueAtTime(Math.max(40, f * .5), t0 + dur);
    g.gain.setValueAtTime(vol, t0); g.gain.exponentialRampToValueAtTime(.0001, t0 + dur);
    o.connect(g).connect(actx.destination); o.start(t0); o.stop(t0 + dur);
  }
  const SFX = {
    hit: crit => soundOn() && (tone(crit ? 880 : 520, 0, .09), tone(crit ? 220 : 160, .03, .12, 'sawtooth', .03)),
    block: () => soundOn() && tone(1400, 0, .05, 'triangle', .04),
    hurt: () => soundOn() && tone(180, 0, .14, 'sawtooth', .04),
    defeat: () => soundOn() && [392, 330, 262].forEach((f, i) => tone(f, i * .07, .12, 'square', .04)),
    lose: () => soundOn() && [330, 294, 262, 196].forEach((f, i) => tone(f, i * .18, .3, 'triangle', .05)),
    level: () => soundOn() && [523, 659, 784, 1047].forEach((f, i) => tone(f, i * .1, .22, 'triangle', .07)),
    gate: () => soundOn() && [660, 440].forEach((f, i) => tone(f, i * .18, .16, 'square', .035)),
    dice: () => soundOn() && [0, .04, .085, .14].forEach(t => tone(1500 + Math.random() * 900, t, .025, 'triangle', .03)),
    spawn: () => soundOn() && [330, 440].forEach((f, i) => tone(f, i * .09, .12, 'triangle', .035)),
    roar: () => soundOn() && (tone(150, 0, .7, 'sawtooth', .06), tone(98, .05, .8, 'square', .035), tone(230, .12, .45, 'sawtooth', .02)),
    puff: () => soundOn() && tone(700, 0, .08, 'sawtooth', .02),
  };

  // ---------- Hero (local coordinates: feet at 0,0, facing right) ----------
  const anim = (attr, values, dur, extra = '') => `<animateTransform attributeName="transform" type="${attr}" values="${values}" dur="${dur}s" repeatCount="indefinite" ${extra}/>`;
  const saber = (x1, y1, x2, y2, c) => `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="${c}" stroke-width="3.2" stroke-linecap="round" style="filter:drop-shadow(0 0 3px ${c})"/>` +
    `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="#fff" stroke-width="1.1" stroke-linecap="round"/>`;
  const wood = (x1, y1, x2, y2) => `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="#a0703c" stroke-width="2.6" stroke-linecap="round"/>` +
    `<line x1="${x1 + 2}" y1="${y1 + 3}" x2="${x1 - 2}" y2="${y1 - 2}" stroke="#a0703c" stroke-width="2" stroke-linecap="round"/>`;

  function hero(u, pose = 'fight') {
    const blade = u.has('blade') ? saber(9, -32, 25, -50, '#ffd100') : wood(9, -32, 22, -45);
    let h = '';
    if (u.has('aura')) h += `<ellipse cx="0" cy="-26" rx="19" ry="30" fill="url(#g-aura)"><animate attributeName="opacity" values=".55;1;.55" dur="2.2s" repeatCount="indefinite"/></ellipse>`;
    if (u.has('wings')) h += `<g fill="#ecebe6" opacity=".55">${anim('scale', '1 1;.75 1;1 1', .8)}` +
      '<path d="M-1 -37Q-24 -58 -24 -28Q-15 -33 -1 -31Z"/><path d="M-1 -37Q-30 -48 -22 -20Q-14 -27 -1 -31Z" opacity=".6"/></g>';
    if (u.has('cape')) h += `<path d="M-1 -39Q-13 -30 -13 -14L-7 -16L-3 -13Z" fill="#a67c00" opacity=".9">${anim('skewX', '0;-8;3;0', 1.6)}</path>`;
    const back = u.has('twin') ? `<g>${anim('rotate', '0 0 -36;8 0 -36;0 0 -36', 1.1)}<path class="fig" d="M0 -36L-7 -29"/>${saber(-7, -29, -2, -50, '#5ab0ff')}</g>`
      : u.has('shield') ? '<path class="fig" d="M0 -36L-6 -29"/><path d="M-13 -35h9v9q0 6-4.5 8q-4.5-2-4.5-8z" fill="#1f1f1d" stroke="#ffd100" stroke-width="1.3"/><path d="M-8.5 -33v12M-12 -29h7" stroke="#ffd100" stroke-width=".8"/>'
      : '<path class="fig" d="M0 -36L-6 -28"/>';
    const legs = pose === 'sit' ? 'M0 -20L9 -16L10 0M0 -20L6 -14L12 -12' : 'M0 -20L-6 0M0 -20L6 0';
    h += `<g class="fig"><circle cx="0" cy="-46" r="5.5"/><path d="M0 -40V-20${legs}"/></g>` + back;
    if (u.has('crown')) h += '<path d="M-6 -50l1.5-6 2.5 3.5 2-5 2 5 2.5-3.5 1.5 6z" fill="#ffd100" stroke="#a67c00" stroke-width=".6"/>';
    else if (u.has('helmet')) h += '<path d="M-6.5 -47a6.5 6.5 0 0 1 13 0v1.5h-13z" fill="#8d8a82"/><path d="M0 -53.5v-3" stroke="#ff4d4f" stroke-width="2" stroke-linecap="round"/>';
    h += `<g class="arm"><animateTransform class="swing" attributeName="transform" type="rotate" values="0 0 -36;-80 0 -36;35 0 -36;0 0 -36" keyTimes="0;.35;.7;1" dur=".5s" begin="indefinite"/>` +
      `<path class="fig" d="M0 -36L9 -32"/>${pose === 'sit' ? '' : blade}</g>`;
    if (pose === 'sit') h += u.has('blade') ? saber(-17, 0, -17, -24, '#ffd100') : wood(-17, -18, -17, 0);  // planted next to the hero
    return h;
  }
  const defs = '<defs><radialGradient id="g-aura"><stop offset="0" stop-color="#ffd100" stop-opacity=".45"/><stop offset="1" stop-color="#ffd100" stop-opacity="0"/></radialGradient></defs>';

  // Dragon familiar (unlock id 'drone' kept for server compatibility): a little golden dragon, centred at 0,0, facing right.
  const flap = (x, y, d, fill, dur = .36) => `<g transform="translate(${x} ${y})"><g>${anim('scale', '1 1;1 .25;1 1', dur)}<path d="${d}" fill="${fill}" stroke="#a67c00" stroke-width=".5" stroke-linejoin="round"/></g></g>`;
  const familiar = () => `<g class="fam">${anim('translate', '0 0;0 -2.5;0 0', 1.6)}` +
    '<path d="M-4 1Q-10 3 -11 -1Q-12 -4 -9.5 -4.5" fill="none" stroke="#ffd100" stroke-width="1.4" stroke-linecap="round"/><path d="M-9.8 -4.2l-1.6 -2.4 2.8 .6z" fill="#ffd100"/>' +
    flap(-1, -2, 'M0 0L-4 -8L4 -4Z', '#a67c00') +
    '<ellipse cx="0" cy="0" rx="5" ry="3" fill="#ffd100"/><path d="M-3 2.5v2M2 2.5v2" stroke="#a67c00" stroke-width="1" stroke-linecap="round"/>' +
    '<path d="M3 -1Q5 -4 6 -5" stroke="#ffd100" stroke-width="2.4" stroke-linecap="round"/><path d="M4.6 -7.4L11.5 -5.2L5 -3.4Z" fill="#ffd100"/>' +
    '<path d="M5.4 -7l-1.8 -2.6M6.6 -7.1l-.6 -2.8" stroke="#a67c00" stroke-width=".9" stroke-linecap="round"/>' +
    '<circle cx="7.4" cy="-5.6" r=".9" fill="#ff4d4f" style="filter:drop-shadow(0 0 1.5px #ff4d4f)"><animate attributeName="opacity" values="1;.4;1" dur="1.8s" repeatCount="indefinite"/></circle>' +
    flap(0, -2, 'M0 0L-2 -10L7 -5Z', '#ffd100') + '</g>';
  const FAM = { x: 30, y: 40 };
  const famScale = () => (S.game?.level || 1) >= 20 ? 1.45 : 1.25;

  // ---------- Bestiary (local coordinates: feet at 0,0, facing left) ----------
  const st = (c, w = 2) => `stroke="${c}" stroke-width="${w}" stroke-linecap="round" stroke-linejoin="round"`;
  const eyes = (x, y, c = '#111', d = 2.5, r = 1.2) => `<circle cx="${x - d}" cy="${y}" r="${r}" fill="${c}"/><circle cx="${x + d}" cy="${y}" r="${r}" fill="${c}"/>`;
  const STEEL = '#c9c6bd', WOOD = '#a0703c', DARK = '#121211', CLOTH = '#5a4a3a';
  // tier: which hero levels meet it; hp/dmg: multipliers on the level-scaled base; tools: tool kinds that lure it (more likely then)
  const FOES = {
    rat: { name: 'Giant Rat', tier: 1, cr: '1/8', hp: .75, dmg: .8, color: '#b08968', s: 1.35, top: -19, tools: ['read', 'agent'],
      lines: ['Squeak! Cheese tax!', 'This cellar is OURS!', 'Nibble nibble…'],
      draw: c => `<g>${anim('translate', '0 0;-1.5 0;0 0', .4)}<path d="M14 -5Q26 -3 28 -12Q29 -17 25 -18" fill="none" ${st(c, 1.3)}/>` +
        `<path d="M-9 -7Q-6 -17 5 -17Q15 -16 16 -6Q15 0 6 0H-4Q-10 0 -9 -7Z" fill="${c}"/><path d="M-6 -13L-20 -8L-7 -4Z" fill="${c}"/>` +
        `<circle cx="-6" cy="-14" r="3" fill="${c}" stroke="${DARK}" stroke-width=".8"/><circle cx="-12" cy="-9.6" r="1.1" fill="#ff4d4f"/>` +
        `<path d="M-19 -8l-4 -2M-19 -8l-4 1" ${st('#ecebe6', .4)}/><path d="M-19.5 -7.5l1 2.2 1 -1.8" fill="#fff"/><path d="M-3 0v1.5M10 0v1.5" ${st(c, 1.4)}/></g>` },
    kobold: { name: 'Kobold', tier: 1, cr: '1/8', hp: .8, dmg: .9, color: '#ff8a5a', s: 1.15, top: -38, tools: ['shell'],
      lines: ['For the great dragon!', 'Traps! Traps everywhere!', 'Shiny! Mine!'],
      draw: c => `<g ${st(c)} fill="none"><path d="M0 -25V-12L-5 0M0 -12L5 0"/><path d="M0 -12Q9 -10 13 -2"/><path d="M0 -21L-8 -18"/></g>` +
        `<line x1="-9" y1="-44" x2="-8" y2="0" stroke="${WOOD}" stroke-width="1.8" stroke-linecap="round"/><path d="M-9.2 -43l-2 -1 2.2 -6 2 6z" fill="${STEEL}"/>` +
        `<path d="M4 -30Q4 -35 -1 -35Q-5 -35 -7 -32L-13 -30L-7 -27Q-2 -25 2 -26Q4 -27 4 -30Z" fill="${c}"/><path d="M1 -34L4 -39M3 -33L7 -36" ${st(c, 1.3)}/>` +
        `<circle cx="-4" cy="-31.5" r="1" fill="#ffd100"/>` },
    bandit: { name: 'Bandit', tier: 1, cr: '1/8', hp: .9, dmg: 1, color: '#c9a36b', top: -52, tools: ['read', 'web'],
      lines: ['Your gold or your life!', 'Nothing personal, friend.', 'This road has a toll.'],
      draw: c => `<path d="M-7 -38L-10 -14H8L6 -38Z" fill="${c}" fill-opacity=".3" ${st(c, 1.3)}/><g ${st(c)} fill="none"><path d="M-3 -14L-6 0M3 -14L6 0"/><path d="M-3 -32L-10 -26"/></g>` +
        `<path d="M-10 -26L-19 -31" stroke="${STEEL}" stroke-width="1.6" stroke-linecap="round"/><path d="M-11.5 -24l2.6 -3.6" stroke="${WOOD}" stroke-width="1.6" stroke-linecap="round"/>` +
        `<path d="M-6.5 -39Q-8 -53 0 -53Q8 -53 6.5 -39Z" fill="${c}"/><circle cx="-1" cy="-44" r="4" fill="${DARK}"/>${eyes(-1.5, -45, '#ecebe6', 1.7, .75)}` +
        `<path d="M-4.8 -42.4h7.6" stroke="${CLOTH}" stroke-width="2"/>` },
    goblin: { name: 'Goblin', tier: 1, cr: '1/4', hp: .9, dmg: 1, color: '#3ddc84', top: -42, tools: ['shell', 'edit'],
      lines: ['Stab first, ask never!', 'Your loot is my loot!', 'Goblins rule this hall!'],
      draw: c => `<g ${st(c)} fill="none"><circle cx="0" cy="-36" r="6"/><path d="M-5 -39L-12 -44L-6 -35M5 -39L12 -44L6 -35"/><path d="M0 -30V-14L-6 0M0 -14L6 0M0 -26L-9 -22"/></g>` +
        `<path d="M-4 -16h8l-1 5h-6z" fill="${WOOD}"/><line x1="-9" y1="-22" x2="-15" y2="-36" stroke="${WOOD}" stroke-width="3.5" stroke-linecap="round"/>` +
        `${eyes(-1, -37, '#ffd100')}<path d="M-4 -33.5l1 1.4 1 -1.4 1 1.4 1 -1.4" fill="none" ${st(c, .7)}/>` },
    zombie: { name: 'Zombie', tier: 1, cr: '1/4', hp: 1.1, dmg: .9, color: '#7fb5a0', top: -46, tools: ['agent'],
      lines: ['Braaains… and coffee…', 'Uuurgh…', 'Join… the… horde…'],
      draw: c => `<g>${anim('rotate', '-4 0 0;3 0 0;-4 0 0', 1.8)}<g ${st(c)} fill="none"><path d="M1 -36V-18L-5 -8L-4 0M1 -18L6 -9L8 0"/><path d="M0 -31L-14 -32M1 -28L-13 -26"/></g>` +
        `<path d="M-4 -35H6L5 -20L2 -22L-1 -19L-3 -21Z" fill="${CLOTH}"/><circle cx="-1" cy="-41" r="5.5" fill="${c}"/>` +
        `<circle cx="-4" cy="-41.5" r="1" fill="${DARK}"/><circle cx="-.5" cy="-42" r="1.3" fill="#ffd100"/><path d="M-4.5 -38h3.5" stroke="${DARK}" stroke-width=".9"/></g>` },
    skeleton: { name: 'Skeleton Warrior', tier: 2, cr: '1/2', hp: 1, dmg: 1, color: '#e6e2d3', top: -50, tools: ['edit', 'agent'],
      lines: ['Rattle my bones? Try!', 'I had a body once.', 'Clack clack clack!'],
      draw: c => `<circle cx="7" cy="-29" r="6.5" fill="#3a3530" stroke="#8d8a82" stroke-width="1.3"/><g ${st(c, 1.7)} fill="none"><path d="M0 -38V-20"/>` +
        `<path d="M-5 -34h10M-5 -30.5h10M-4 -27h8"/><path d="M-4 -20h8L0 -17Z"/><path d="M-3 -19L-6 -10L-5 0M3 -19L6 -10L6 0"/><path d="M-1 -35L-7 -28L-11 -30"/><path d="M1 -35L6 -30"/></g>` +
        `<path d="M-11 -30L-22 -47" stroke="#9a978e" stroke-width="2" stroke-linecap="round"/><path d="M-13.5 -27.5l5 -4.5" stroke="${WOOD}" stroke-width="1.5" stroke-linecap="round"/>` +
        `<circle cx="0" cy="-44" r="5.5" fill="${c}"/><path d="M-3.2 -40h5.6v3h-5.6z" fill="${c}"/><circle cx="-2.4" cy="-44.5" r="1.4" fill="${DARK}"/><circle cx="1.8" cy="-44.5" r="1.4" fill="${DARK}"/>` +
        `<circle cx="-2.4" cy="-44.5" r=".55" fill="#ff4d4f"/><path d="M-1.5 -40v3M.5 -40v3" stroke="${DARK}" stroke-width=".5"/>` },
    orc: { name: 'Orc', tier: 2, cr: '1/2', hp: 1.05, dmg: 1.1, color: '#a3b86c', top: -51, tools: ['shell'],
      lines: ['Blood for the clan!', 'You look crunchy!', 'Strength is law!'],
      draw: c => `<g ${st(c, 3.2)} fill="none"><path d="M-4 -20L-7 0M4 -20L7 0"/><path d="M-7 -36L-13 -26"/><path d="M7 -36L12 -26"/></g>` +
        `<path d="M-9 -38H9L6 -18H-6Z" fill="${c}"/><path d="M-6 -22H6L7 -15H-7Z" fill="${CLOTH}"/>` +
        `<line x1="-13" y1="-24" x2="-15" y2="-56" stroke="${WOOD}" stroke-width="2.4" stroke-linecap="round"/><path d="M-15 -55Q-26 -54 -25 -42L-14.5 -46Z" fill="${STEEL}"/>` +
        `<circle cx="0" cy="-45" r="6.5" fill="${c}"/><path d="M-6 -48h7" stroke="${DARK}" stroke-width="1.2"/>${eyes(-3, -46, '#ff4d4f', 2.2, 1)}` +
        `<path d="M-4.5 -41.5v-2.5M-.5 -41.5v-2.5" stroke="#fff" stroke-width="1.2" stroke-linecap="round"/>` },
    spider: { name: 'Giant Spider', tier: 2, cr: '1', hp: .9, dmg: 1.1, color: '#c08bff', top: -50, tools: ['web', 'agent'],
      lines: ['Caught in my web!', 'Eight legs, no mercy.', 'Stay a while… forever.'],
      draw: c => `<line x1="0" y1="-72" x2="0" y2="-46" stroke="${c}" stroke-width=".7"/><g>${anim('translate', '0 0;0 -5;0 0', 1.8)}<g ${st(c, 1.6)} fill="none">` +
        [-1, 1].map(s => [0, 1, 2, 3].map(i => `<path d="M${s * 3} -36Q${s * 12} ${-48 + i * 6} ${s * 17} ${-30 + i * 7}"/>`).join('')).join('') +
        `</g><circle cx="0" cy="-34" r="9" fill="${c}"/><path d="M-2.5 -38h5l-5 6h5z" fill="#ff4d4f"/><circle cx="0" cy="-46" r="5" fill="${c}"/>` +
        `${eyes(-1, -47, '#ff4d4f', 1.6, .9)}${eyes(-1, -44.6, '#ff4d4f', 2.6, .6)}<path d="M-2.5 -42l-.6 2.4M1 -42l.6 2.4" ${st(DARK, .9)}/></g>` },
    mimic: { name: 'Mimic Chest', tier: 2, cr: '2', hp: 1, dmg: 1.2, color: '#e0a040', s: 1.15, top: -32, tools: ['edit'],
      lines: ['Open me. I dare you.', 'Not a chest. Surprise!', 'Treasure? Teeth!'],
      draw: c => `<path d="M-10 -15Q-22 -14 -24 -6Q-26 -2 -21 -3" fill="none" stroke="#ff4d4f" stroke-width="2.5" stroke-linecap="round"/>` +
        `<rect x="-16" y="-16" width="32" height="16" rx="1.5" fill="#6b4a2a" stroke="${c}" stroke-width="1.4"/><path d="M-16 -9H16M-6 -16V0M6 -16V0" stroke="${c}" stroke-width="1"/>` +
        `<path d="M-14 -16l2 -3 2 3 2 -3 2 3 2 -3 2 3 2 -3 2 3 2 -3 2 3 2 -3 2 3" fill="#ecebe6"/><circle cx="0" cy="-10" r="1.6" fill="${c}"/>` +
        `<g>${anim('rotate', '0 16 -17;16 16 -17;5 16 -17;0 16 -17', 1.3)}<path d="M-16 -18Q-16 -29 0 -29Q16 -29 16 -18Z" fill="#6b4a2a" stroke="${c}" stroke-width="1.4"/>` +
        `<path d="M-14 -18l2 3 2 -3 2 3 2 -3 2 3 2 -3 2 3 2 -3 2 3 2 -3 2 3 2 -3" fill="#ecebe6"/>${eyes(-5, -23, '#ffd100', 2.6, 1.7)}${eyes(-5.6, -23, DARK, 2.6, .7)}</g>` },
    ogre: { name: 'Ogre', tier: 2, cr: '2', hp: 1.2, dmg: 1.15, color: '#d4956a', s: 1.1, top: -46, tools: ['shell'],
      lines: ['Ogre smash tiny man!', 'You fit in stew pot.', 'Hungry!'],
      draw: c => `<g ${st(c, 3.6)} fill="none"><path d="M-5 -14L-7 0M5 -14L7 0"/><path d="M-9 -34L-15 -22"/><path d="M9 -34L13 -22"/></g>` +
        `<ellipse cx="0" cy="-24" rx="12" ry="13" fill="${c}"/><path d="M-11 -18Q0 -12 11 -18L10 -11H-10Z" fill="${CLOTH}"/>` +
        `<path d="M-15 -22L-23 -43" stroke="#8a5a2c" stroke-width="4.5" stroke-linecap="round"/><circle cx="-23.5" cy="-44" r="3.6" fill="#8a5a2c"/>` +
        `<circle cx="-1" cy="-41" r="5" fill="${c}"/>${eyes(-3, -42, DARK, 1.8, .9)}<path d="M-5.5 -38.5h4" stroke="${DARK}" stroke-width=".8"/><path d="M-5 -38.7v-1.4" stroke="#fff" stroke-width=".9"/>` },
    knight: { name: 'Black Knight', tier: 3, cr: '3', hp: 1.1, dmg: 1.1, color: '#9aa6b8', top: -56, tools: ['edit', 'mcp'],
      lines: ['Face me, if you dare!', 'My blade knows no rest.', 'Kneel, pretender!'],
      draw: c => `<path d="M-1 -40Q12 -32 12 -12L6 -14L2 -12Z" fill="#7a1f22"/><g ${st(c, 2.4)} fill="none"><path d="M0 -38V-20L-6 0M0 -20L6 0"/><path d="M0 -34L-9 -30"/></g>` +
        `<path d="M-5 -38H5L4 -22H-4Z" fill="#26262b" stroke="${c}" stroke-width="1"/><path d="M-9 -30L-26 -53" stroke="#d8dde6" stroke-width="2.2" stroke-linecap="round"/>` +
        `<path d="M-11.6 -27.4l5.2 -4.4" stroke="${c}" stroke-width="1.8" stroke-linecap="round"/>` +
        `<path d="M-6 -42V-49a6 6 0 0 1 12 0V-42Z" fill="#26262b" stroke="${c}" stroke-width="1.2"/><path d="M-6 -46.5h6" stroke="#ff4d4f" stroke-width="1.2" style="filter:drop-shadow(0 0 1.5px #ff4d4f)"/>` +
        `<path d="M2 -54Q8 -59 12 -53" stroke="#ff4d4f" stroke-width="2" fill="none" stroke-linecap="round"/>` },
    minotaur: { name: 'Minotaur', tier: 3, cr: '3', hp: 1.15, dmg: 1.2, color: '#c2703d', top: -60, tools: ['edit'],
      lines: ['Lost in my maze?', 'I see red!', 'Horns first!'],
      draw: c => `<g ${st(c, 3)} fill="none"><path d="M-4 -22L-6 -10L-8 0M4 -22L6 -10L5 0"/><path d="M-7 -40L-14 -32"/><path d="M7 -40L11 -30"/></g>` +
        `<path d="M-10 0h4M3 0h4" stroke="#3a3530" stroke-width="2.4" stroke-linecap="round"/><path d="M-10 -42H10L6 -21H-6Z" fill="${c}"/><path d="M-6 -24H6L7 -17H-7Z" fill="${CLOTH}"/>` +
        `<line x1="-14" y1="-28" x2="-14" y2="-64" stroke="${WOOD}" stroke-width="2"/><path d="M-14 -61Q-23 -65 -23 -53Q-19 -55 -14 -55Q-9 -55 -5 -53Q-5 -65 -14 -61Z" fill="${STEEL}"/>` +
        `<path d="M-6 -46Q-7 -54 0 -54Q6 -54 5 -46L2 -42H-3Z" fill="${c}"/><path d="M-5 -45Q-10 -45 -10 -48L-5 -49Z" fill="${c}"/>` +
        `<path d="M-5 -52Q-12 -54 -12 -60M4 -52Q10 -55 9 -61" fill="none" stroke="#ecebe6" stroke-width="1.8" stroke-linecap="round"/>` +
        `<circle cx="-3" cy="-49.5" r="1" fill="#ff4d4f"/><circle cx="-9" cy="-45.6" r="1.3" fill="none" stroke="#ffd100" stroke-width=".6"/>` },
    basilisk: { name: 'Basilisk', tier: 3, cr: '3', hp: 1, dmg: 1.15, color: '#c9d14a', top: -48, tools: ['read'],
      lines: ["Don't look me in the eye.", 'Stone cold.', 'Hsss… statue time.'],
      draw: c => `<path d="M24 -2Q10 4 2 -4Q-6 -12 4 -20Q14 -28 6 -36Q0 -42 -8 -40" fill="none" stroke="${c}" stroke-width="5.5" stroke-linecap="round"/>` +
        `<path d="M24 -2Q10 4 2 -4Q-6 -12 4 -20Q14 -28 6 -36" fill="none" stroke="${DARK}" stroke-width=".8" stroke-dasharray="1.5 2" opacity=".6"/>` +
        `<path d="M-5 -44Q-14 -46 -19 -40L-7 -36Z" fill="${c}"/><path d="M-6 -44l1.6 -5.5 1.8 4 1.8 -5 1.4 6" fill="${c}"/>` +
        `<circle cx="-11" cy="-41.6" r="1.4" fill="#ffd100" style="filter:drop-shadow(0 0 2px #ffd100)"><animate attributeName="r" values="1.2;2;1.2" dur="1.4s" repeatCount="indefinite"/></circle>` +
        `<path d="M-19 -39.5l-4 -1M-19 -39.5l-4 1.5" ${st('#ff4d4f', .8)}/>` },
    cube: { name: 'Gelatinous Cube', tier: 3, cr: '2', hp: 1.25, dmg: .9, color: '#4fd1c5', s: 1.1, top: -38, tools: ['edit', 'mcp'],
      lines: ['*wobble*', '*slurp*', '*absorbs your boots*'],
      draw: c => `<g>${anim('scale', '1 1;1.04 .95;1 1', 1.6)}<path d="M-16 0V-32L-8 -38H22V-6L14 0Z" fill="${c}" fill-opacity=".22" stroke="${c}" stroke-width="1.4" stroke-linejoin="round"/>` +
        `<path d="M-16 -32H14V0M14 -32L22 -38" fill="none" stroke="${c}" stroke-width="1" stroke-opacity=".7"/><circle cx="-3" cy="-14" r="3.6" fill="#ecebe6" fill-opacity=".55"/>` +
        `<circle cx="-4.3" cy="-14.5" r=".8" fill="${DARK}"/><circle cx="-1.7" cy="-14.5" r=".8" fill="${DARK}"/><line x1="4" y1="-27" x2="10" y2="-8" stroke="${STEEL}" stroke-width="1.2" opacity=".6"/>` +
        `<circle cx="-9" cy="-25" r="1.3" fill="#ffd100" opacity=".7"/><circle cx="7" cy="-4" r="1" fill="#fff" opacity=".5"/><circle cx="-10" cy="-6" r=".8" fill="#fff" opacity=".5"/></g>` },
    golem: { name: 'Stone Golem', tier: 3, cr: '4', hp: 1.3, dmg: 1.05, color: '#3ddcc8', top: -50, tools: ['mcp'],
      lines: ['INTRUDER DETECTED.', 'RUNES ACTIVE.', 'I. AM. THE. WALL.'],
      draw: c => `<g fill="#2a2926" stroke="${c}" stroke-width="1.5">` +
        '<rect x="-7" y="-50" width="14" height="11" rx="2"/><rect x="-11" y="-38" width="22" height="22" rx="3"/><rect x="-11" y="-15" width="8" height="15" rx="2"/><rect x="3" y="-15" width="8" height="15" rx="2"/>' +
        `<rect x="-19" y="-36" width="7" height="17" rx="2"/></g>${eyes(0, -45, c)}<path d="M0 -33l4 5 -4 5 -4 -5z" fill="none" stroke="${c}" stroke-width="1.2">` +
        `<animate attributeName="stroke-opacity" values=".3;1;.3" dur="1.6s" repeatCount="indefinite"/></path><path d="M-8 -24l3 -2M5 -34l3 2" stroke="${c}" stroke-width=".7" opacity=".6"/>` },
    troll: { name: 'Troll', tier: 4, cr: '5', hp: 1.2, dmg: 1.1, color: '#6fae8c', regen: true, top: -56, tools: ['shell'],
      lines: ['Cut me, I grow back.', 'Troll hungry!', 'Fire? No fire? Good.'],
      draw: c => `<g ${st(c, 3)} fill="none"><path d="M-2 -24L-6 -12L-8 0M4 -24L7 -12L7 0"/><path d="M-6 -44Q-14 -32 -16 -8"/><path d="M6 -44Q12 -34 13 -16"/></g>` +
        `<path d="M-16 -8l-3 3M-16 -8l-1 4M-16 -8l2 3" ${st(c, 1)}/><path d="M-8 -48Q0 -55 9 -46L6 -22H-4Z" fill="${c}"/><path d="M-6 -24H5L6 -17H-7Z" fill="${CLOTH}"/>` +
        `<circle cx="-7" cy="-50" r="6" fill="${c}"/><path d="M-11 -51Q-18 -48 -13 -45Z" fill="${c}"/>${eyes(-8, -52.5, '#ffd100', 2, 1)}` +
        `<path d="M-6 -56l-1 -4M-3 -55.5l1 -4M-9 -55l-2.5 -3" ${st(c, 1.1)}/><path d="M-10 -46.5h4" stroke="${DARK}" stroke-width=".8"/>` },
    wraith: { name: 'Wraith', tier: 4, cr: '5', hp: .95, dmg: 1.25, color: '#a7a3ff', top: -60, tools: ['read', 'web'],
      lines: ['Your warmth… give it.', 'Cold… so cold…', 'Join the shadows.'],
      draw: c => `<g>${anim('translate', '0 -4;0 -8;0 -4', 2.2)}<g><animate attributeName="opacity" values=".95;.55;.95" dur="1.7s" repeatCount="indefinite"/>` +
        `<path d="M0 -58Q-11 -56 -11 -40L-14 -8L-9 -12L-6 -4L-2 -11L2 -3L5 -11L9 -6L11 -14L10 -40Q10 -56 0 -58Z" fill="${c}" fill-opacity=".32" stroke="${c}" stroke-width="1.4" stroke-linejoin="round"/>` +
        `<path d="M-6 -45Q0 -54 6 -45V-39H-6Z" fill="${DARK}"/>${eyes(-1, -44, '#7df9ff', 2, 1)}` +
        `<path d="M-9 -34Q-16 -34 -20 -30M-20 -30l-3 -2M-20 -30l-3 1M-20 -30l-2 3" ${st(c, 1.4)} fill="none"/></g></g>` },
    wyvern: { name: 'Wyvern', tier: 4, cr: '6', hp: 1.05, dmg: 1.2, color: '#5ab0ff', top: -60, tools: ['web'],
      lines: ['Skreee!', 'Stinger ready!', 'From above!'],
      draw: c => `<g>${anim('translate', '0 -6;0 -10;0 -6', 1.2)}` +
        `<g transform="translate(3 -33)"><g>${anim('scale', '1 1;1 .4;1 1', .7)}<path d="M0 0L12 -27L22 -8L16 -9L10 -2Z" fill="${c}" fill-opacity=".3" stroke="${c}" stroke-width="1"/></g></g>` +
        `<path d="M8 -26Q22 -20 26 -8Q27 -3 30 -5" fill="none" stroke="${c}" stroke-width="2.4" stroke-linecap="round"/><path d="M29 -7l4.5 -.5 -2.5 4z" fill="#ffd100"/>` +
        `<ellipse cx="2" cy="-28" rx="10" ry="6" fill="${c}"/><path d="M-5 -31Q-12 -40 -13 -46" fill="none" stroke="${c}" stroke-width="3.6" stroke-linecap="round"/>` +
        `<path d="M-11 -50L-25 -46L-12 -42Z" fill="${c}"/><path d="M-11 -49l4 -4.5" ${st(c, 1.2)}/><circle cx="-15" cy="-47" r=".9" fill="#ffd100"/>` +
        `<path d="M0 -23L-2 -14L-5 -12M6 -23L7 -14L4 -12" ${st(c, 1.6)} fill="none"/>` +
        `<g transform="translate(0 -32)"><g>${anim('scale', '1 1;1 .4;1 1', .7)}<path d="M0 0L-8 -28L9 -21L18 -8L8 -5Z" fill="${c}" fill-opacity=".55" stroke="${c}" stroke-width="1.2" stroke-linejoin="round"/></g></g></g>` },
    eye: { name: 'Floating Eye', tier: 4, cr: '7', hp: 1, dmg: 1.3, color: '#ff6ac1', top: -66, tools: ['read', 'web'],
      lines: ['I see everything.', 'Many eyes, one verdict.', 'Stare-down time!'],
      draw: c => `<ellipse cx="0" cy="-1" rx="10" ry="1.6" fill="#000" opacity=".45"/><g>${anim('translate', '0 0;0 -4;0 0', 2)}` +
        [[-11, -60], [-4, -65], [5, -64], [12, -58]].map(([x, y]) => `<path d="M${x * .4} -48Q${x * .9} ${y + 8} ${x} ${y}" fill="none" ${st(c, 1.4)}/><circle cx="${x}" cy="${y}" r="2.1" fill="${c}"/><circle cx="${x - .5}" cy="${y}" r=".8" fill="${DARK}"/>`).join('') +
        `<circle cx="0" cy="-38" r="13" fill="${c}"/><circle cx="-3" cy="-41" r="6" fill="#ecebe6"/>` +
        `<circle cx="-5" cy="-41" r="3" fill="${DARK}"><animate attributeName="cx" values="-5;-3;-6;-5" dur="3s" repeatCount="indefinite"/></circle>` +
        `<path d="M-10 -31Q-2 -24 8 -30Q-1 -28 -10 -31Z" fill="${DARK}"/><path d="M-8 -30.5l1 1.6 1 -1.4 1 1.8 1 -1.6 1 1.8 1 -1.6 1 1.4 1 -1.6" fill="none" stroke="#fff" stroke-width=".6"/></g>` },
    lich: { name: 'Lich', tier: 5, cr: '12', hp: 1.1, dmg: 1.35, color: '#b6ff5e', top: -62, tools: ['shell', 'agent'],
      lines: ['Death is a detail.', 'Kneel before undeath.', 'I have outlived kings.'],
      draw: c => `<g>${anim('translate', '0 -2;0 -5;0 -2', 2.4)}<path d="M-8 -36L-12 -4Q0 0 10 -4L7 -36Z" fill="#2b2240" stroke="#7d6ab0" stroke-width="1.2"/>` +
        `<path d="M-6 -36Q0 -31 6 -36" fill="none" stroke="#7d6ab0" stroke-width="1.2"/><path d="M-6 -32L-14 -26" stroke="#ecebe6" stroke-width="1.6" stroke-linecap="round"/>` +
        `<line x1="-15" y1="-2" x2="-15" y2="-54" stroke="#6b4a2a" stroke-width="2"/>` +
        `<circle cx="-15" cy="-57" r="4" fill="${c}" style="filter:drop-shadow(0 0 4px ${c})"><animate attributeName="r" values="3.4;4.4;3.4" dur="1.3s" repeatCount="indefinite"/></circle>` +
        `<circle cx="0" cy="-42" r="5.5" fill="#ecebe6"/><circle cx="-2.4" cy="-42.5" r="1.3" fill="${c}"/><circle cx="1.6" cy="-42.5" r="1.3" fill="${c}"/>` +
        `<path d="M-2 -38.6h3.4" stroke="${DARK}" stroke-width=".7"/><path d="M-5 -46l1 -6 2 3 2 -4 2 4 2 -3 1 6z" fill="#ffd100"/></g>` },
    dragon: { name: 'Red Dragon', tier: 5, cr: '17', hp: 1.5, dmg: 1.1, color: '#ff4d4f', boss: true, top: -58, tools: [], box: '-46 -74 100 78',
      lines: ['BURN, LITTLE KNIGHT!', 'My hoard! MINE!', 'I have slept long enough.'],
      draw: c => `<g transform="translate(8 -40)"><g>${anim('rotate', '0;-9;0', 1.6)}<path d="M0 0L13 -26L28 -24L38 -10L27 -8L19 0Z" fill="#7a1f22" stroke="${c}" stroke-width="1"/></g></g>` +
        `<path d="M14 -14Q32 -8 37 -3Q42 1 44 -6" fill="none" stroke="${c}" stroke-width="4" stroke-linecap="round"/><path d="M42 -8l5 -2 -2 6z" fill="${c}"/>` +
        `<path d="M10 -22Q20 -18 15 -6L17 0H8L9 -8Z" fill="${c}"/><ellipse cx="5" cy="-23" rx="16" ry="10.5" fill="${c}"/>` +
        `<path d="M-9 -17Q4 -9 18 -15" stroke="#ffb020" stroke-width="2" stroke-dasharray="2 1.5" fill="none"/><path d="M-4 -16L-8 -4L-13 0M-8 -4L-11 1" ${st(c, 3.2)} fill="none"/>` +
        `<path d="M-6 -28Q-14 -40 -22 -46" stroke="${c}" stroke-width="7" stroke-linecap="round" fill="none"/>` +
        `<path d="M-9 -34l-3 -4 4 1M-14 -40l-3.5 -3.5 4.5 .5" fill="${c}" stroke="${c}" stroke-width="1"/>` +
        `<path d="M-19 -52L-31 -50L-40 -46L-30 -44.5L-38 -40.5L-24 -40L-17 -43Z" fill="${c}"/>` +
        `<path d="M-20 -51Q-18 -60 -11 -62M-23 -51Q-24 -58 -19 -63" stroke="#ecebe6" stroke-width="1.6" fill="none" stroke-linecap="round"/>` +
        `<circle cx="-26" cy="-48" r="1.4" fill="#ffd100" style="filter:drop-shadow(0 0 2px #ffd100)"/><path d="M-38 -43.5l-3 1 3 1z" fill="#ffd100"><animate attributeName="opacity" values="1;.2;1" dur=".8s" repeatCount="indefinite"/></path>` +
        `<path d="M-36 -46l-1.5 -1.5 1.8 .2z" fill="#ecebe6"/>` +
        `<g transform="translate(2 -32)"><g>${anim('scale', '1 1;1 .55;1 1', 1.6)}<path d="M0 0L6 -34L21 -37L33 -26L40 -12L28 -13L22 -5L12 -7Z" fill="${c}" fill-opacity=".45" stroke="${c}" stroke-width="1.4" stroke-linejoin="round"/>` +
        `<path d="M6 -34L12 -7M21 -37L22 -5M33 -26L28 -13" stroke="${c}" stroke-width=".8"/></g></g>` },
  };
  Object.entries(FOES).forEach(([id, f]) => f.id = id);
  const XP_BY_CR = { '1/8': 25, '1/4': 50, '1/2': 100, 1: 200, 2: 450, 3: 700, 4: 1100, 5: 1800, 6: 2300, 7: 2900, 12: 8400, 17: 18000 };
  const GATE = { name: 'Permission Gate', color: '#ff4d4f', top: -66,
    lines: ['Halt! The rune demands approval.', 'Allow this tool call?', 'Commander, I need your OK!'],
    draw: c => `<path d="M-25 0V-48Q-25 -71 0 -71Q25 -71 25 -48V0" fill="#1c1b19" stroke="#4a4740" stroke-width="3"/>` +
      `<path d="M-25 -48h5M20 -48h5M-24 -30h4M20 -30h4M-24 -12h4M20 -12h4M-12 -66l2 4M12 -66l-2 4M0 -71v5" stroke="#2c2b28" stroke-width="1"/>` +
      `<path d="M-19 0V-48Q-19 -65 0 -65Q19 -65 19 -48V0Z" fill="#080807"/>` +
      `<g stroke="${c}" stroke-width="1.6">` + [[-14, -59], [-7, -63], [0, -64], [7, -63], [14, -59]].map(([x, y]) => `<line x1="${x}" y1="${y}" x2="${x}" y2="-3"/>`).join('') +
      [-52, -36, -18].map(y => `<line x1="-18" y1="${y}" x2="18" y2="${y}"/>`).join('') + '</g>' +
      `<g fill="${c}">` + [-14, -7, 0, 7, 14].map(x => `<path d="M${x - 1.6} -3h3.2l-1.6 3z"/>`).join('') + '</g>' +
      `<circle cx="0" cy="-30" r="7" fill="${DARK}" stroke="${c}" stroke-width="1.6" style="filter:drop-shadow(0 0 4px ${c})"><animate attributeName="stroke-opacity" values=".35;1;.35" dur="1s" repeatCount="indefinite"/></circle>` +
      `<path d="M0 -35V-25M-3.5 -32.5L0 -30L3.5 -32.5M-3 -27h6" stroke="${c}" stroke-width="1.2" fill="none" stroke-linecap="round"><animate attributeName="opacity" values=".5;1;.5" dur="1s" repeatCount="indefinite"/></path>` +
      `<path d="M-19 0V-48Q-19 -65 0 -65Q19 -65 19 -48V0" fill="none" stroke="${c}" stroke-opacity=".5" style="filter:drop-shadow(0 0 4px ${c})"><animate attributeName="stroke-opacity" values=".15;.9;.15" dur="1s" repeatCount="indefinite"/></path>` };
  const toolKind = t => !t ? 'other' : t === 'Bash' ? 'shell' : /^(Edit|Write|MultiEdit|NotebookEdit)$/.test(t) ? 'edit'
    : /^(Read|Grep|Glob|LS)$/.test(t) ? 'read' : /^Web/.test(t) ? 'web' : /^(Agent|Task|SendMessage)$/.test(t) ? 'agent' : /^mcp__/.test(t) ? 'mcp' : 'other';
  const HERO_LINES = {
    battle: ['For the codebase!', 'Roll for initiative!', 'Ship it!', 'Green build or bust!', 'By my +1 keyboard!', 'Refactor time!'],
    win: ['Another one down.', 'Loot secured!', 'Next!'],
    idle: ['Awaiting orders!', 'Your move, commander!', 'Ready when you are.', 'Ping me!'],
    rest: ['Zzz…', 'Short rest…', 'Recharging spell slots…'],
    ko: ['Ouch… next time.', 'Just a flesh wound.', 'Healing up…'],
  };

  // ---------- Rules (5e-flavoured, balanced in a simulation: equal level ≈ 85% wins, +5…+10 elites ≈ 35–55%, the boss mostly wins) ----------
  const heroLv = () => S.game?.level || 1;
  const heroDice = () => { const L = heroLv(); return { n: 1 + Math.floor(L / 10), d: S.unlocked.has('blade') ? 8 : 6, m: 1 + Math.floor(L / 6) }; };
  const avgDmg = D => D.n * (D.d + 1) / 2 + D.m;
  const heroMaxHp = () => { const u = S.unlocked; return Math.round(5 * avgDmg(heroDice()) * (1 + (u.has('shield') ? .04 : 0) + (u.has('helmet') ? .03 : 0) + (u.has('aura') ? .03 : 0))) + 6; };
  const heroAC = () => 11 + Math.floor(heroLv() / 3) + (S.unlocked.has('shield') ? 1 : 0) + (S.unlocked.has('helmet') ? 1 : 0);
  const heroAtk = () => 2 + Math.floor(heroLv() / 3);
  const foePow = rel => Math.pow(1.03, rel);
  const famBonus = () => Math.round(Math.max(2, .1 * avgDmg(heroDice())) * (heroLv() >= 20 ? 1.5 : 1));

  // ---------- Bestiary record (wins/losses per foe; persisted per browser) ----------
  const REC = (() => { try { const r = JSON.parse(store.get('gameBestiary') || '{}'); return r && typeof r === 'object' ? r : {}; } catch (e) { return {}; } })();
  const NOW = {};
  function record(id, won) {   // re-read first so two open dashboard tabs don't overwrite each other's tallies
    try { Object.assign(REC, JSON.parse(store.get('gameBestiary') || '{}') || {}); } catch (e) {}
    for (const r of [REC, NOW]) { const e = r[id] = Array.isArray(r[id]) ? r[id] : [0, 0]; e[won ? 0 : 1]++; }
    store.set('gameBestiary', JSON.stringify(REC));
  }
  const tally = r => Object.values(r).reduce((a, e) => [a[0] + (e[0] || 0), a[1] + (e[1] || 0)], [0, 0]);

  // ---------- State ----------
  const S = { scene: null, foe: null, flv: 1, elite: false, hp: 0, max: 1, prev: null, foeAt: 0, stay: 30000, boss: 0, busy: false,
    hhp: null, hmax: 1, ko: 0, lvlT: 0, lastHit: 0, xp: null, level: null, game: null, unlocked: new Set(), turn: 0, sayT: 0, att: [] };
  let root, svg, layer;

  const backdrop = () => {
    const vx = 100, lines = [-80, -40, 0, 40, 80, 120, 160, 200, 240, 280].map(x => `M${vx + (x - vx) * .45} 72L${x} 96`).join('');
    const torch = x => `<g transform="translate(${x} 34)"><circle r="24" fill="url(#g-torch)"><animate attributeName="opacity" values=".75;1;.65;.95;.75" dur="1.3s" repeatCount="indefinite"/></circle>` +
      '<path d="M-1.6 0h3.2l-1 10h-1.2z" fill="#6b4a2a"/><path d="M-3.5 .5h7" stroke="#8d8a82" stroke-width="1.2"/>' +
      '<path d="M0 -9Q-3.5 -4 -2.6 -1Q0 1 2.6 -1Q3.5 -4 0 -9Z" fill="#ff8a5a"><animate attributeName="d" values="M0 -9Q-3.5 -4 -2.6 -1Q0 1 2.6 -1Q3.5 -4 0 -9Z;M.8 -10Q-3 -4 -2.6 -1Q0 1 2.6 -1Q3.8 -5 .8 -10Z;M-.6 -8.5Q-3.6 -4 -2.6 -1Q0 1 2.6 -1Q3.2 -4 -.6 -8.5Z;M0 -9Q-3.5 -4 -2.6 -1Q0 1 2.6 -1Q3.5 -4 0 -9Z" dur=".7s" repeatCount="indefinite"/></path>' +
      '<path d="M0 -5Q-1.6 -2.5 -1.1 -1Q0 0 1.1 -1Q1.6 -2.5 0 -5Z" fill="#ffd100"/></g>';
    return '<defs><pattern id="g-brick" width="20" height="10" patternUnits="userSpaceOnUse"><rect width="20" height="10" fill="#181715"/>' +
      '<path d="M0 .5H20M0 5.5H20M5 .5V5.5M15 5.5V10" stroke="#262522" stroke-width="1"/></pattern>' +
      '<radialGradient id="g-torch"><stop offset="0" stop-color="#ffb020" stop-opacity=".3"/><stop offset="1" stop-color="#ffb020" stop-opacity="0"/></radialGradient>' +
      '<radialGradient id="g-vig" cx=".5" cy=".55" r=".72"><stop offset=".55" stop-color="#000" stop-opacity="0"/><stop offset="1" stop-color="#000" stop-opacity=".65"/></radialGradient>' +
      '<linearGradient id="g-floor" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#1f1e1b"/><stop offset="1" stop-color="#141412"/></linearGradient></defs>' +
      '<rect width="200" height="72" fill="url(#g-brick)"/><rect y="72" width="200" height="24" fill="url(#g-floor)"/>' +
      `<path d="M0 72.5H200" stroke="#2f2e2a" stroke-width="1.2"/><path d="M0 76.5H200M0 82H200M0 89.5H200${lines}" stroke="#262522" stroke-width=".7"/>` +
      torch(8) + torch(192) + '<rect width="200" height="96" fill="url(#g-vig)"/>';
  };

  function mount() {
    root = document.getElementById('arena');
    if (!root) return false;
    root.tabIndex = 0;
    root.setAttribute('role', 'button');
    root.title = 'Character sheet';
    root.innerHTML = `<div class="hud"><b id="gLv">LV 1</b><span class="tt" id="gTitle">…</span><span class="xpn" id="gXp"></span></div>
      <div class="xpbar"><i id="gBar" style="width:0"></i></div>
      <svg class="scene" viewBox="0 0 200 96">${defs}${backdrop()}<g id="gWorld"></g><g id="gFoe"></g><g id="gTop"></g><text id="gSay" class="say" x="58" y="22"></text><g id="gFx"></g></svg>
      <div class="cap" id="gCap">…</div><div class="banner" id="gBanner"></div>`;
    svg = root.querySelector('svg');
    layer = root.querySelector('#gFx');
    root.onclick = openSheet;
    root.onkeydown = e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openSheet(); } };
    return true;
  }

  // ---------- Scene ----------
  function pickScene(att) {
    const gate = att.find(s => s.status === 'approval');
    if (gate) return { kind: 'gate', target: gate };
    if (S.ko) return Date.now() - S.ko < 2600 && S.scene ? S.scene : { kind: 'rest', ko: true };   // fall first, then respawn at the campfire
    const work = att.filter(s => s.status === 'working').sort((a, b) => a.idleSec - b.idleSec);
    const wait = att.filter(s => s.status === 'waiting').length;
    if (work.length) return { kind: 'battle', target: work[0], wait };
    if (wait) return { kind: 'idle', wait };
    return { kind: 'rest' };
  }
  function setCap() {
    const sc = S.scene, c = document.getElementById('gCap'), t = sc.target;
    const where = t ? t.title || t.project : '';
    c.textContent = sc.kind === 'gate' ? `⛔ approval needed · ${where}`
      : sc.kind === 'battle' ? `⚔ vs ${S.foe ? FOES[S.foe].name : '…'}${S.foe ? ` LV ${S.flv}` : ''} · ${where}${sc.wait ? ` · 💬 ${sc.wait} waiting` : ''}`
      : sc.kind === 'idle' ? `💬 ${sc.wait} session${sc.wait > 1 ? 's' : ''} await${sc.wait > 1 ? '' : 's'} your orders`
      : sc.ko ? '🔥 respawning at the campfire…' : '🔥 resting · no open sessions';
    root.className = `arena s-${sc.ko ? 'ko' : sc.kind}`;
  }

  function draw() {
    const u = S.unlocked, sc = S.scene, w = svg.querySelector('#gWorld');
    let h = '';
    if (sc.kind === 'rest') {
      h += '<circle cx="104" cy="80" r="34" fill="url(#g-torch)"><animate attributeName="opacity" values=".8;1;.8" dur=".9s" repeatCount="indefinite"/></circle>';
      h += '<g transform="translate(104 88)"><path d="M-8 0L8 0M-6 -1L6 -3M-6 -3L6 -1" stroke="#a0703c" stroke-width="2.2" stroke-linecap="round"/>' +
        '<path d="M-5 -2Q-6 -10 0 -17Q2 -10 5 -8Q6 -4 5 -2Z" fill="#ff8a5a"><animate attributeName="d" values="M-5 -2Q-6 -10 0 -17Q2 -10 5 -8Q6 -4 5 -2Z;M-5 -2Q-4 -12 1 -19Q3 -11 5 -9Q7 -4 5 -2Z;M-5 -2Q-6 -10 0 -17Q2 -10 5 -8Q6 -4 5 -2Z" dur=".6s" repeatCount="indefinite"/></path>' +
        '<path d="M-2.5 -2Q-3 -7 0 -11Q1 -7 2.5 -5Q3 -3 2.5 -2Z" fill="#ffd100"/><path d="M-10 0.5h20" stroke="#4a4740" stroke-width="2" stroke-dasharray="3 1.5" stroke-linecap="round"/></g>';
      h += `<ellipse cx="72" cy="88.6" rx="11" ry="1.8" fill="#000" opacity=".5"/><g transform="translate(70 88)">${hero(u, 'sit')}</g>`;
      if (u.has('drone')) h += `<g transform="translate(132 76) scale(${famScale()})"><g transform="scale(-1 1)">${familiar()}</g></g>`;  // the familiar warms itself on the other side
      h += '<g fill="#8d8a82">' + [0, 1, 2].map(i => `<text x="${78 + i * 6}" y="${50 - i * 7}" font-size="${6 + i * 1.5}" opacity="0">z<animate attributeName="opacity" values="0;1;0" dur="2.4s" begin="${i * .8}s" repeatCount="indefinite"/></text>`).join('') + '</g>';
    } else {
      const fly = u.has('wings') ? anim('translate', '0 -6;0 -9;0 -6', 1.4) : '';
      h += `<ellipse cx="54" cy="88.6" rx="9" ry="1.6" fill="#000" opacity=".5"/>`;
      h += `<g transform="translate(54 88)"><g class="hero-k"><animateTransform class="fall" attributeName="transform" type="rotate" values="0;-88" dur=".6s" fill="freeze" begin="indefinite"/>` +
        `<g>${fly}<g class="hero-b"><animateTransform class="lunge" attributeName="transform" type="translate" values="0 0;18 0;0 0" keyTimes="0;.35;1" dur=".5s" begin="indefinite"/>` +
        `<animateTransform class="flinch" attributeName="transform" type="translate" values="0 0;-5 0;0 0" dur=".3s" begin="indefinite"/>${hero(u)}</g></g></g></g>`;
      if (u.has('drone')) h += `<g transform="translate(${FAM.x} ${FAM.y}) scale(${famScale()})">${familiar()}</g>`;
      if (sc.kind === 'idle') h += '<g transform="translate(90 34)"><path d="M-4 0h40a4 4 0 0 1 4 4v8a4 4 0 0 1-4 4h-30l-6 6v-6h-4a4 4 0 0 1-4-4v-8a4 4 0 0 1 4-4z" fill="#ffd100"/>' +
        '<text x="16" y="10.5" fill="#111" font-size="7">!  ORDERS?</text><animateTransform attributeName="transform" type="translate" values="90 34;90 31;90 34" dur="1.2s" repeatCount="indefinite"/></g>';
    }
    w.innerHTML = h;
    svg.querySelector('#gSay').textContent = '';
    drawFoe(); drawTop();
    if (reduce.matches) svg.pauseAnimations(); else svg.unpauseAnimations();
  }

  // the enemy (or the gate) on the right
  function drawFoe() {
    const g = svg.querySelector('#gFoe'), sc = S.scene;
    const F = sc.kind === 'gate' ? GATE : sc.kind === 'battle' && S.foe ? FOES[S.foe] : null;
    let h = '';
    if (F) {
      h += `<ellipse cx="150" cy="88.6" rx="${F.boss ? 24 : 11}" ry="1.8" fill="#000" opacity=".5"/>`;
      h += `<g transform="translate(150 88)${F.s ? ` scale(${F.s})` : ''}"><g class="enemy spawn${F !== GATE && S.hp <= 0 ? ' dead' : ''}">` +
        `<animateTransform class="lunge" attributeName="transform" type="translate" values="0 0;-14 0;0 0" keyTimes="0;.35;1" dur=".45s" begin="indefinite"/>` +
        `<animateTransform class="shake" attributeName="transform" type="translate" values="0 0;4 0;-3 0;2 0;0 0" dur=".3s" begin="indefinite"/>${F.draw(F.color)}</g></g>`;
    }
    g.innerHTML = h;
  }
  // HP bars + labels along the top edge (hero left, foe right): redrawn whenever HP changes
  function drawTop() {
    const g = svg.querySelector('#gTop'), sc = S.scene;
    if (!g || !sc) return;
    const r = Math.max(0, S.hhp / S.hmax), hc = r > .5 ? '#3ddc84' : r > .25 ? '#ffb020' : '#ff4d4f';
    let h = `<text class="lbl" x="8" y="7.5" fill="#8d8a82" style="text-anchor:start">HERO · HP ${Math.max(0, Math.ceil(S.hhp))}/${S.hmax}</text>` +
      `<rect x="8" y="10" width="44" height="3" rx="1.5" fill="#2c2b28"/><rect x="8" y="10" width="${(44 * r).toFixed(1)}" height="3" rx="1.5" fill="${hc}"/>`;
    if (sc.kind === 'gate') h += `<text class="lbl" x="150" y="7.5" fill="#ff4d4f">${esc(GATE.name.toUpperCase())}</text><text class="lbl" x="150" y="13.5" fill="#8d8a82" font-size="4.6">SEALED · NEEDS APPROVAL</text>`;
    else if (sc.kind === 'battle' && S.foe) {
      const F = FOES[S.foe], w = F.boss ? 52 : 44, x = 150 - w / 2, lc = S.elite ? (F.boss ? '#ff4d4f' : '#ffb020') : '#8d8a82';
      h += `<text class="lbl" x="150" y="7.5" fill="${F.color}">${S.elite ? '☠ ' : ''}${esc(F.name.toUpperCase())}</text>` +
        `<rect x="${x}" y="10" width="${w}" height="3" rx="1.5" fill="#2c2b28"/><rect x="${x}" y="10" width="${(w * Math.max(0, S.hp / S.max)).toFixed(1)}" height="3" rx="1.5" fill="${F.color}"/>` +
        `<text class="lbl" x="${x + w + 3}" y="13.2" fill="${lc}" style="text-anchor:start" font-size="5">LV ${S.flv}</text>`;
    }
    g.innerHTML = h;
  }

  const begin = (sel, el = svg) => { if (!reduce.matches) el.querySelectorAll(sel).forEach(a => a.beginElement?.()); };
  function float(x, y, text, cls = '', sub = '', rise = 16) {
    const t = document.createElementNS(NS, 'text');
    t.setAttribute('x', x); t.setAttribute('y', y); t.setAttribute('class', 'dmg ' + cls);
    t.innerHTML = esc(text) + (sub ? `<tspan class="sub" x="${x}" dy="6">${esc(sub)}</tspan>` : '') +
      `<animate attributeName="y" from="${y}" to="${y - rise}" dur="1.1s" begin="indefinite" fill="freeze"/><animate attributeName="opacity" values="1;1;0" dur="1.1s" begin="indefinite" fill="freeze"/>`;
    layer.append(t);
    begin('animate', t);
    setTimeout(() => t.remove(), 1200);
  }
  function d20(roll) {   // the attack roll as a little die next to the hero
    const g = document.createElementNS(NS, 'g'), x = 88, y = 44, c = roll === 20 ? '#ffd100' : roll === 1 ? '#ff4d4f' : '#ecebe6';
    const pts = [0, 1, 2, 3, 4, 5].map(i => `${(x + 5.4 * Math.cos(Math.PI / 6 + i * Math.PI / 3)).toFixed(1)},${(y + 5.4 * Math.sin(Math.PI / 6 + i * Math.PI / 3)).toFixed(1)}`).join(' ');
    g.setAttribute('class', 'd20');
    g.innerHTML = `<polygon points="${pts}" fill="${c}" stroke="#121211" stroke-width=".8"/><path d="M${x} ${y - 5.4}L${x - 4.7} ${y + 2.7}H${x + 4.7}Z" fill="none" stroke="#121211" stroke-width=".35" opacity=".5"/>` +
      `<text x="${x}" y="${y + 2}">${roll}</text><animateTransform attributeName="transform" type="translate" values="0 0;0 -6" dur="1s" begin="indefinite" fill="freeze"/>` +
      '<animate attributeName="opacity" values="1;1;0" dur="1s" begin="indefinite" fill="freeze"/>';
    layer.append(g); begin('animate, animateTransform', g);
    setTimeout(() => g.remove(), 1050);
  }
  function fx(html, ms, cls = '') { const g = document.createElementNS(NS, 'g'); if (cls) g.setAttribute('class', cls); g.innerHTML = html; layer.append(g); setTimeout(() => g.remove(), ms); return g; }
  // the familiar's fire bolt from its snout to the foe
  function bolt(x2, y2) {
    const s = famScale(), x1 = FAM.x + 11 * s, y1 = FAM.y - 5 * s, big = heroLv() >= 20;
    if (reduce.matches) return fx(`<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="#ff8a5a" stroke-width="1.6"/>`, 160);
    const g = fx([0, 1, 2].map(i => `<circle r="${(big ? 3 : 2.2) - i * .6}" cx="${x1}" cy="${y1}" fill="${i ? '#ff8a5a' : '#ffd100'}" opacity="${1 - i * .28}">` +
      `<animate attributeName="cx" from="${x1}" to="${x2}" dur=".28s" begin="indefinite" fill="freeze"/><animate attributeName="cy" from="${y1}" to="${y2}" dur=".28s" begin="indefinite" fill="freeze"/></circle>`).join('') +
      `<circle cx="${x2}" cy="${y2}" r="0" fill="#ffb020" opacity=".8"><animate attributeName="r" values="0;${big ? 7 : 5};0" dur=".25s" begin="indefinite" fill="freeze"/></circle>`, 600);
    g.querySelectorAll('circle').forEach((c, i) => c.querySelectorAll('animate').forEach(a => a.beginElementAt?.(i < 3 ? i * .04 : .28)));
    SFX.puff();
  }
  function breath() {   // dragon fire at the hero
    fx('<path d="M110 43Q90 33 60 38Q55 50 62 60Q90 57 110 46Z" fill="#ff8a5a" opacity=".85"/><path d="M110 44Q92 39 70 44Q72 52 110 45.5Z" fill="#ffd100"/>' +
      '<circle cx="66" cy="44" r="2" fill="#ffd100"/><circle cx="72" cy="56" r="1.5" fill="#ff8a5a"/>', 700, 'fire');
    SFX.roar();
  }
  function ribbon(F, why) {
    const t1 = why === 'boss' ? 'A DRAGON DESCENDS!' : why === 'challenger' ? `${F.name.toUpperCase()} ENTERS!` : `A WILD ${F.name.toUpperCase()} APPEARS!`;
    const you = die(20) + Math.floor(heroLv() / 6), them = die(20) + F.tier;
    layer.querySelectorAll('.ribbon').forEach(r => r.remove());
    fx(`<rect x="22" y="23" width="156" height="17" rx="2" fill="#1c140b" stroke="${F.color}" stroke-width=".8" opacity=".94"/>` +
      `<text x="100" y="31" fill="${F.color}" font-size="6.2">${esc(t1)}</text>` +
      `<text x="100" y="37.4" fill="#ecebe6" font-size="4.4">${S.elite && !F.boss ? '☠ ELITE · ' : ''}LV ${S.flv} · CR ${F.cr} · INITIATIVE ${you} VS ${them}</text>`, 2300, 'ribbon');
  }
  function speak(text, who = 'hero') {
    const t = svg.querySelector('#gSay');
    if (!t || !S.unlocked.has('cry')) return;
    t.setAttribute('x', who === 'hero' ? 58 : 194); t.style.textAnchor = who === 'hero' ? 'middle' : 'end';
    t.textContent = text; S.sayT = Date.now();
  }
  const foeY = F => Math.max(44, 88 + F.top * (F.s || 1) + 14);   // below the foe's speech line even after the float rises

  // ---------- Encounters ----------
  function nextFoe() {
    const t = Math.min(5, heroLv() >= 30 ? 5 : heroLv() >= 20 ? 4 : heroLv() >= 12 ? 3 : heroLv() >= 5 ? 2 : 1);
    const up = t < 5 && Math.random() < .15, kind = toolKind(S.scene?.target?.lastTool);
    let pool = Object.values(FOES).filter(f => !f.boss && (up ? f.tier === t + 1 : f.tier === t || f.tier === t - 1) && f.id !== S.foe && f.id !== S.prev);
    if (!pool.length) pool = Object.values(FOES).filter(f => !f.boss && f.id !== S.foe);
    const wts = pool.map(f => f.tools.includes(kind) ? 3 : 1);
    if (t >= 5 && S.foe !== 'dragon') { pool.push(FOES.dragon); wts.push(.4); }
    let r = Math.random() * wts.reduce((a, b) => a + b, 0);
    return pool.find((f, i) => (r -= wts[i]) < 0)?.id || pool[0].id;
  }
  function spawn(id, why = 'wild') {
    const F = FOES[id], L = heroLv();
    S.elite = F.boss || Math.random() < .15;
    S.flv = F.boss ? L + 8 : S.elite ? L + 5 + Math.floor(Math.random() * 6) : Math.max(1, L + Math.floor(Math.random() * 7) - 3);
    S.prev = S.foe; S.foe = id;
    S.max = S.hp = Math.max(4, Math.round(F.hp * 4 * avgDmg(heroDice()) * foePow(S.flv - L)));
    S.foeAt = Date.now(); S.stay = F.boss ? 90000 : 20000 + Math.random() * 20000; S.turn = 0;
    if (F.boss) S.boss = 0;
    drawFoe(); drawTop(); setCap();
    ribbon(F, F.boss ? 'boss' : why);
    if (F.boss) SFX.roar(); else { SFX.spawn(); SFX.dice(); }
    const t = svg.querySelector('#gSay'); if (t) t.textContent = '';
    setTimeout(() => { if (S.foe === id && S.scene?.kind === 'battle') speak(pick(F.lines), 'foe'); }, 2400);
  }
  function challenger(id) {   // the current foe leaves, a new one enters
    const en = svg.querySelector('.enemy');
    S.busy = true;
    en?.classList.add('flee');
    setTimeout(() => { S.busy = false; if (S.scene?.kind === 'battle' && !S.ko) spawn(id, id === 'dragon' ? 'boss' : 'challenger'); else S.foe = null; }, 600);
  }

  // one round: the hero attacks; power = real XP gained since the last update (always hits, can turn a fight)
  function attack(power = 0) {
    if (!S.scene || S.scene.kind !== 'battle' || !S.foe || S.busy || S.ko) return;
    if (!power && Date.now() - S.foeAt < 1500) return;   // let the "A wild … appears" ribbon breathe
    const u = S.unlocked, en = svg.querySelector('.enemy'), F = FOES[S.foe], rel = S.flv - heroLv();
    if (!en || en.classList.contains('dead')) return;
    begin('.hero-b > .lunge'); begin('.arm .swing');
    const D = heroDice();
    let dmg, sub = '', crit = false, miss = false, roll = 0;
    if (power) { crit = u.has('crit') && power >= 25; dmg = power + dice(D.n, D.d) + D.m; sub = 'POWER STRIKE'; }
    else {
      roll = die(20); d20(roll);
      crit = roll === 20 && u.has('crit');
      // needs 9 + rel/3 on the die (+1 vs the boss), so equal-level hits land ~60% of the time
      miss = roll === 1 || (roll !== 20 && roll < 9 + Math.round(rel / 3) + (F.boss ? 1 : 0));
      const n = crit ? D.n * 2 : D.n;
      dmg = dice(n, D.d) + D.m; sub = `${n}d${D.d}+${D.m}`;
      if (roll === 20 || roll === 1) SFX.dice();
    }
    if (crit && power) dmg *= 2;   // a rolled crit already doubled its dice
    if (u.has('twin')) dmg += Math.max(2, Math.round(.1 * avgDmg(D)));
    const y = foeY(F);
    setTimeout(() => {
      if (!en.isConnected || en.classList.contains('dead')) return;
      if (miss) {
        float(146, y, roll === 1 ? 'FUMBLE' : 'MISS', 'miss', '', 12);
        if (roll === 1) float(54, 30, 'oops', 'miss', '', 8);
      } else {
        en.classList.remove('hit'); void en.getBBox(); en.classList.add('hit'); begin('.enemy > .shake');
        SFX.hit(crit);
        float(146, y, crit ? `CRIT ${dmg}!` : `-${dmg}`, crit ? 'crit' : '', sub, 12);
        if (u.has('drone')) { bolt(146, y + 8); dmg += famBonus(); }
        if (u.has('lightning') && power >= 40) fx('<polyline points="146,0 140,20 152,30 142,50 150,58 146,74" fill="none" stroke="#fff" stroke-width="2" style="filter:drop-shadow(0 0 5px #ffd100)"/>', 320);
        S.hp -= dmg; drawTop();
        if (S.hp <= 0) return win(en, F);
      }
    }, 170);
    // every other turn the foe strikes back: d20 vs the hero's AC, scaled with its level
    if (++S.turn % 2 === 0) setTimeout(() => counter(en, F), 700);
    if (Date.now() - S.sayT > 6000 && Date.now() - S.foeAt > 2400 && Math.random() < .3) Math.random() < .5 ? speak(pick(HERO_LINES.battle)) : speak(pick(F.lines), 'foe');
  }
  function counter(en, F) {
    if (!en.isConnected || en.classList.contains('dead') || S.ko || S.scene?.kind !== 'battle') return;
    const u = S.unlocked, rel = S.flv - heroLv();
    begin('.enemy > .lunge');
    if (F.boss) breath();
    setTimeout(() => {
      if (S.ko) return;
      const roll = die(20), need = 10 - Math.round(rel / 3) + (u.has('shield') ? 1 : 0) + (u.has('helmet') ? 1 : 0) - (F.boss ? 1 : 0);
      if (roll === 1 || (roll !== 20 && roll < need)) { float(44, 66, 'MISS', 'miss'); return; }
      if ((u.has('shield') || u.has('twin')) && Math.random() < .15) { float(44, 66, 'BLOCK', 'xp'); SFX.block(); return; }
      const dmg = Math.max(1, Math.round(F.dmg * 1.2 * avgDmg(heroDice()) * foePow(rel) * (.7 + Math.random() * .6) * (roll === 20 ? 2 : 1)));
      begin('.hero-b > .flinch'); SFX.hurt();
      float(44, 66, `-${dmg}`, 'hurt', roll === 20 ? 'CRIT' : '');
      S.hhp -= dmg; S.lastHit = Date.now(); drawTop();
      if (S.hhp <= 0) lose(F);
      else if (F.regen && S.hp < S.max) { S.hp = Math.min(S.max, S.hp + Math.ceil(S.max * .06)); drawTop(); float(156, foeY(F) + 10, 'REGEN', 'heal', '', 10); }
    }, 170);
  }
  function win(en, F) {
    S.busy = true;
    en.classList.add('dead');
    SFX.defeat();
    record(F.id, true);
    float(150, 44, 'DEFEATED', 'xp');
    setTimeout(() => float(150, 56, `+${XP_BY_CR[F.cr]} gp`, 'loot', 'loot'), 250);
    S.hhp = Math.min(S.hmax, S.hhp + Math.round(S.hmax * .25)); drawTop();   // second wind
    if (Math.random() < .3) setTimeout(() => speak(pick(HERO_LINES.win)), 400);
    setTimeout(() => {
      S.busy = false;
      if (S.scene?.kind === 'battle' && !S.ko) spawn(S.boss ? 'dragon' : nextFoe(), S.boss ? 'boss' : 'wild'); else S.foe = null;
    }, 1000);
  }
  // the hero falls: cosmetic only, real XP is never touched
  function lose(F) {
    S.hhp = 0; S.ko = Date.now(); S.busy = true; drawTop();
    record(F.id, false);
    const k = svg.querySelector('.hero-k');
    if (reduce.matches) k?.setAttribute('transform', 'rotate(-88)'); else begin('.hero-k > .fall');
    SFX.lose();
    const b = document.getElementById('gBanner');
    b.innerHTML = `<div>DEFEATED<small>by ${esc(F.name)}${S.elite ? ' ☠' : ''} LV ${S.flv}</small></div>`;
    b.className = 'banner lose'; void b.offsetWidth; b.classList.add('on');
    setTimeout(() => {   // respawn at the campfire with full HP, then a new encounter
      S.busy = false; S.foe = null; S.boss = 0;
      setScene(pickScene(S.att), true);
    }, 2600);
  }

  function setScene(sc, force = false) {
    const same = !force && S.scene && S.scene.kind === sc.kind && !!S.scene.ko === !!sc.ko;
    S.scene = sc;
    if (!same) {
      draw();
      if (sc.kind === 'battle' && !S.busy && (!S.foe || S.hp <= 0)) spawn(S.boss ? 'dragon' : nextFoe(), S.boss ? 'boss' : 'wild');
      if (sc.kind === 'gate') { SFX.gate(); speak(pick(GATE.lines), 'foe'); }
      else if (sc.kind === 'idle') speak(pick(HERO_LINES.idle));
      else if (sc.kind === 'rest') { speak(sc.ko ? pick(HERO_LINES.ko) : HERO_LINES.rest[0]); if (!S.busy) S.foe = null; }   // the foe wanders off while the hero camps
    }
    setCap();
  }

  function levelUp(from, to, g) {
    const fresh = g.unlocks.filter(x => x.level > from && x.level <= to);
    const b = document.getElementById('gBanner');
    b.innerHTML = `<div>LEVEL ${to}!<small>${esc(fresh.length ? '🔓 ' + fresh.map(x => x.name).join(' · ') : g.title)}</small></div>`;
    b.className = 'banner'; void b.offsetWidth; b.classList.add('on');
    SFX.level();
    S.lvlT = Date.now(); S.boss = Date.now();   // a level-up summons the dragon
    if (S.scene && S.scene.kind === 'battle') fx('<polyline points="146,0 140,20 152,30 142,50 150,58 146,74" fill="none" stroke="#fff" stroke-width="2" style="filter:drop-shadow(0 0 5px #ffd100)"/>', 320);
  }

  // ---------- Update from a snapshot ----------
  function update(d) {
    const g = d.game;
    if (!g || (!root && !mount())) return;
    S.game = g;
    S.att = d.attention || [];
    S.unlocked = new Set(g.unlocks.filter(x => x.on).map(x => x.id));
    document.getElementById('gLv').textContent = `LV ${g.level}`;
    document.getElementById('gTitle').textContent = g.title;
    document.getElementById('gXp').textContent = `${fmt(g.xp - g.levelXp)} / ${fmt(g.nextXp - g.levelXp)} XP`;
    document.getElementById('gBar').style.width = ((g.xp - g.levelXp) / (g.nextXp - g.levelXp) * 100).toFixed(1) + '%';
    const hmax = heroMaxHp();
    if (S.hhp === null) S.hhp = hmax; else if (hmax !== S.hmax) S.hhp = Math.round(S.hhp * hmax / S.hmax);
    S.hmax = hmax;
    const gearSig = [...S.unlocked].join() + (g.level >= 20);
    const sc = pickScene(S.att);
    if (S.gearSig !== gearSig) { S.gearSig = gearSig; S.scene = null; }  // new gear: redraw the hero
    setScene(sc);

    if (S.xp !== null && g.xp > S.xp) {
      const gain = g.xp - S.xp;
      float(100, 66, `+${gain} XP`, 'xp');
      attack(gain);
      if (gain >= 50 && S.foe !== 'dragon') S.boss = Date.now();   // a big deed draws the dragon out
    }
    const seen = +store.get('gameLevel') || 0;
    if (S.level !== null ? g.level > S.level : seen && g.level > seen) levelUp(S.level ?? seen, g.level, g);
    store.set('gameLevel', g.level);
    S.xp = g.xp; S.level = g.level;
    if (sheetOpen()) openSheet();
  }

  setInterval(() => {
    if (document.hidden || !S.scene || !svg) return;
    const now = Date.now(), sc = S.scene;
    if (S.boss && now - S.boss > 120000) S.boss = 0;
    // healing: full at the campfire, slowly while waiting, a trickle in battle after a quiet spell
    const heal = sc.kind === 'rest' ? .34 : sc.kind !== 'battle' ? .1 : now - S.lastHit > 9000 ? .03 : 0;
    if (heal && !S.busy && S.hhp < S.hmax) { S.hhp = Math.min(S.hmax, S.hhp + Math.ceil(S.hmax * heal)); drawTop(); }
    if (S.ko && now - S.ko > 2600 + 4200 && S.hhp >= S.hmax) { S.ko = 0; setScene(pickScene(S.att)); }
    else if (sc.kind === 'battle' && !S.busy && S.foe) {
      const F = FOES[S.foe];
      if (S.boss && !F.boss && now - S.lvlT > 2800) challenger('dragon');
      else if (now - S.foeAt > S.stay && S.hp > 0) challenger(nextFoe());
      else attack();
    }
    if (S.sayT && now - S.sayT > 3500) { const t = svg.querySelector('#gSay'); if (t) t.textContent = ''; S.sayT = 0; }
  }, 1400);

  // ---------- Character sheet ----------
  const sheetOpen = () => !!document.querySelector('.sheet-bg');
  function closeSheet() { document.querySelector('.sheet-bg')?.remove(); root?.focus(); }
  const score = (v, cap) => Math.max(8, Math.min(20, Math.round(8 + 12 * Math.log10(1 + v) / Math.log10(1 + cap))));
  const sgn = m => (m >= 0 ? '+' : '−') + Math.abs(m);
  const mini = F => `<svg viewBox="${F.box || '-30 -66 60 68'}" aria-hidden="true"><g transform="scale(${F.s || 1})">${F.draw(F.color)}</g></svg>`;
  function openSheet() {
    const g = S.game; if (!g) return;
    const u = S.unlocked, next = g.unlocks.find(x => !x.on);
    const src = Object.fromEntries(g.sources.map(s => [s.id, s.count]));
    const stats = [['STR', 'edits + commits', (src.edit || 0) + (src.commit || 0), 5000], ['DEX', 'tool calls', src.tool || 0, 50000],
      ['INT', 'k output tokens', src.kilotoken || 0, 20000], ['WIS', 'bugs slain', src.bugfix || 0, 300],
      ['CHA', 'pull requests', src.pr || 0, 100], ['CON', 'best streak (days)', g.bestStreak, 60]];
    const D = heroDice(), all = tally(REC), now = tally(NOW);
    const scroll = document.querySelector('.sheet')?.scrollTop;
    document.querySelector('.sheet-bg')?.remove();
    document.body.insertAdjacentHTML('beforeend', `<div class="sheet-bg"><div class="sheet" role="dialog" aria-modal="true" aria-label="Character sheet">
      <header><h3>Game of <span>Claude</span></h3><span style="font:12px var(--mono);color:var(--muted)">${g.achievements.filter(a => a.on).length}/${g.achievements.length} achievements · 🔥 ${g.streak}-day streak · ⚔ ${all[0]}W / ${all[1]}L</span>
        <label class="thm"><select id="gTheme" aria-label="Theme"><option value="dnd" selected>Dungeons &amp; Dragons</option><option value="pokemon">Pokémon</option></select></label>
        <button class="x" type="button" aria-label="Close">✕</button></header>
      <div class="grid">
        <section>
          <svg class="big scene" viewBox="-40 -66 80 70">${defs}<path d="M-36 0H36" stroke="#8d8a82" stroke-dasharray="2 3" opacity=".5"/>
            ${u.has('wings') ? `<g>${anim('translate', '0 -3;0 -6;0 -3', 1.4)}${hero(u)}</g>` : hero(u)}${u.has('drone') ? `<g transform="translate(-22 -44) scale(${famScale()})">${familiar()}</g>` : ''}</svg>
          <div class="lv">LV ${g.level}</div>
          <div style="font-weight:700;margin-top:4px">${esc(g.title)}</div>
          <div class="xpbar"><i style="width:${((g.xp - g.levelXp) / (g.nextXp - g.levelXp) * 100).toFixed(1)}%"></i></div>
          <div class="kv"><span>XP</span><span>${g.xp.toLocaleString()}</span><span>next level</span><span>${(g.nextXp - g.xp).toLocaleString()} XP</span>
            <span>XP today</span><span>+${g.xpToday.toLocaleString()}</span>
            ${g.nextTitle ? `<span>next title</span><span>LV ${g.nextTitle.level}</span>` : ''}
            ${next ? `<span>next unlock</span><span>${esc(next.name)} · LV ${next.level}</span>` : ''}</div>
          <h4 style="margin-top:16px">Ability scores</h4>
          <div class="abil">${stats.map(([k, l, v, cap]) => { const s = score(v, cap); return `<div title="${esc(l)}: ${fmt(v)}"><b>${k}</b><span class="sc">${s}</span><span class="md">${sgn(Math.floor((s - 10) / 2))}</span><small>${fmt(v)} ${esc(l)}</small></div>`; }).join('')}</div>
          <h4 style="margin-top:16px">Combat</h4>
          <div class="kv"><span>Hit points</span><span>${Math.max(0, Math.ceil(S.hhp ?? heroMaxHp()))} / ${heroMaxHp()}</span><span>Armor class</span><span>${heroAC()}</span>
            <span>Attack</span><span>${sgn(heroAtk())} to hit</span><span>Damage</span><span>${D.n}d${D.d}+${D.m}${u.has('drone') ? ` +${famBonus()} 🔥` : ''}</span>
            <span>Record</span><span>${all[0]}W / ${all[1]}L</span><span>This session</span><span>${now[0]}W / ${now[1]}L</span></div>
          ${u.has('sound') ? `<button class="btn snd" type="button" id="gSnd">${store.get('gameSound') === '1' ? '🔊 Sound on' : '🔈 Sound off'}</button>` : ''}
        </section>
        <section><h4>Unlocks</h4><ul>${g.unlocks.map(x => `<li class="${x.on ? '' : 'off'}${x === next ? ' next' : ''}"><span class="lvl">LV ${x.level}</span>
          <span>${x.on ? '' : '🔒 '}${esc(x.name)}<small>${esc(x.desc)}</small></span></li>`).join('')}</ul></section>
        <section><h4>XP sources</h4><div class="src">${g.sources.map(s => `<span>${esc(s.label)}</span><span>${fmt(s.count)} × ${s.each}</span><span>${fmt(s.xp)}</span>`).join('')}</div>
          <h4 style="margin-top:16px">Battle log</h4><div class="log">${g.feats.length ? g.feats.map(f =>
            `<div><b>+${f.xp}</b> ${esc(f.label.replace(/s$/, ''))} · ${esc(f.where)} · <span data-since="${f.at}" data-f="ago"></span></div>`).join('') : '<div>No heroic deeds yet.</div>'}</div></section>
        <section class="wide2" style="grid-column:1/-1"><h4>Bestiary · wins / losses (this browser)</h4><div class="bst">${Object.values(FOES).sort((a, b) => a.tier - b.tier).map(F => {
          const r = REC[F.id] || [0, 0], n = NOW[F.id] || [0, 0];
          return `<div class="${r[0] + r[1] ? '' : 'off'}" title="${esc(F.lines[0])}">${mini(F)}<span>${esc(F.name)}<small>CR ${F.cr}${F.boss ? ' · boss' : ''}</small>` +
            `<small><b>${r[0]}W</b> / <i>${r[1]}L</i>${n[0] + n[1] ? ` · today ${n[0]}/${n[1]}` : ''}</small></span></div>`; }).join('')}</div></section>
        <section class="wide2" style="grid-column:1/-1"><h4>Achievements</h4><div class="ach">${g.achievements.map(a =>
          `<div class="${a.on ? 'on' : ''}">${esc(a.name)}<small>${esc(a.desc)}</small></div>`).join('')}</div></section>
      </div></div></div>`);
    const bg = document.querySelector('.sheet-bg');
    if (reduce.matches) bg.querySelectorAll('svg').forEach(s => s.pauseAnimations?.());
    if (scroll) bg.querySelector('.sheet').scrollTop = scroll;
    bg.querySelectorAll('[data-since]').forEach(el => el.textContent = new Date(el.dataset.since).toLocaleTimeString());
    bg.onclick = e => { if (e.target === bg) closeSheet(); };
    bg.querySelector('.x').onclick = closeSheet;
    bg.querySelector('#gTheme').onchange = e => window.setGameTheme?.(e.target.value);
    const snd = bg.querySelector('#gSnd');
    if (snd) snd.onclick = () => { store.set('gameSound', store.get('gameSound') === '1' ? '0' : '1'); SFX.level(); openSheet(); };
    if (!scroll) bg.querySelector('.x').focus();
  }
  addEventListener('keydown', e => { if (e.key === 'Escape' && sheetOpen()) closeSheet(); });

  window.GAME = { update, open: openSheet };
})();
