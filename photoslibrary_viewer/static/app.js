/* photoslibrary-viewer – browser UI (no build step, no dependencies). */
"use strict";

// ------------------------------------------------------------------ i18n
const LANG = (navigator.language || "en").toLowerCase().startsWith("de") ? "de" : "en";
const T = {
  de: {
    library: "Mediathek", all: "Alle Fotos", favorites: "Favoriten", videos: "Videos", live: "Live Photos",
    edited: "Bearbeitet", hidden: "Ausgeblendet", collections: "Sammlungen", albums: "Alben", people: "Personen",
    myAlbums: "Meine Alben", search: "Suchen", searchFor: "Suche", items: n => `${fmtNum(n)} ${n === 1 ? "Objekt" : "Objekte"}`,
    photosVideos: (p, v) => `${fmtNum(p)} Fotos, ${fmtNum(v)} Videos`, nothing: "Hier ist nichts.",
    noResults: "Keine Treffer.", file: "Datei", dimensions: "Abmessungen", filesize: "Dateigröße", camera: "Kamera",
    lens: "Objektiv", exposure: "Aufnahme", duration: "Dauer", codec: "Codec", location: "Ort", showMap: "Auf Karte zeigen",
    keywords: "Schlagwörter", editedYes: "Ja, bearbeitete Fassung wird gezeigt", notPlayable: "Dieses Videoformat kann der Browser nicht abspielen. Original herunterladen?",
    missing: "Originaldatei fehlt in der Mediathek.", loadingError: "Konnte nicht geladen werden.", folder: "Ordner",
    albumsCount: n => `${fmtNum(n)} ${n === 1 ? "Album" : "Alben"}`, zoom: "Größe", readOnly: "nur lesend",
  },
  en: {
    library: "Library", all: "All Photos", favorites: "Favorites", videos: "Videos", live: "Live Photos",
    edited: "Edited", hidden: "Hidden", collections: "Collections", albums: "Albums", people: "People",
    myAlbums: "My Albums", search: "Search", searchFor: "Search", items: n => `${fmtNum(n)} ${n === 1 ? "item" : "items"}`,
    photosVideos: (p, v) => `${fmtNum(p)} photos, ${fmtNum(v)} videos`, nothing: "Nothing here.",
    noResults: "No results.", file: "File", dimensions: "Dimensions", filesize: "File size", camera: "Camera",
    lens: "Lens", exposure: "Exposure", duration: "Duration", codec: "Codec", location: "Location", showMap: "Show on map",
    keywords: "Keywords", editedYes: "Yes, showing the edited version", notPlayable: "Your browser cannot play this video format. Download the original?",
    missing: "Original file is missing from the library.", loadingError: "Could not be loaded.", folder: "Folder",
    albumsCount: n => `${fmtNum(n)} ${n === 1 ? "album" : "albums"}`, zoom: "Size", readOnly: "read-only",
  },
}[LANG];
document.documentElement.lang = LANG;

const LOCALE = LANG === "de" ? "de-DE" : undefined;
const fmtNum = n => n.toLocaleString(LOCALE);
// Asset timestamps arrive already shifted to the capture time zone, so they
// are always formatted as UTC.
const dtf = opts => new Intl.DateTimeFormat(LOCALE, { timeZone: "UTC", ...opts });
const fmtMonth = dtf({ month: "long", year: "numeric" });
const fmtDay = dtf({ weekday: "long", day: "numeric", month: "long", year: "numeric" });
const fmtShortDay = dtf({ day: "numeric", month: "short", year: "numeric" });
const fmtTime = dtf({ hour: "2-digit", minute: "2-digit" });
const fmtDur = s => { s = Math.round(s); const m = Math.floor(s / 60); return `${m}:${String(s % 60).padStart(2, "0")}`; };
const fmtBytes = b => b == null ? "" : b < 1e6 ? `${(b / 1e3).toFixed(0)} KB` : b < 1e9 ? `${(b / 1e6).toFixed(1)} MB` : `${(b / 1e9).toFixed(2)} GB`;

const FLAG_VIDEO = 1, FLAG_FAV = 2, FLAG_LIVE = 4;

// ------------------------------------------------------------------ helpers
const $ = id => document.getElementById(id);
const h = (tag, attrs = {}, ...kids) => {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null || v === false) continue;
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat()) if (kid != null) el.append(kid.nodeType ? kid : String(kid));
  return el;
};
const icon = d => { const s = document.createElementNS("http://www.w3.org/2000/svg", "svg"); s.setAttribute("viewBox", "0 0 24 24"); s.innerHTML = d; return s; };
const ICONS = {
  all: '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
  fav: '<path d="M12 20s-7-4.4-7-10a4 4 0 0 1 7-2.6A4 4 0 0 1 19 10c0 5.6-7 10-7 10z"/>',
  video: '<rect x="3" y="6" width="13" height="12" rx="2"/><path d="M16 10l5-3v10l-5-3"/>',
  live: '<circle cx="12" cy="12" r="3"/><circle cx="12" cy="12" r="6.5" stroke-dasharray="2 2"/><circle cx="12" cy="12" r="9.5"/>',
  edited: '<circle cx="6" cy="6" r="2"/><circle cx="18" cy="12" r="2"/><circle cx="9" cy="18" r="2"/><path d="M8 6h13M3 6h1M3 12h13M20 12h1M3 18h4M11 18h10"/>',
  hidden: '<path d="M3 3l18 18M10.6 6.1A9.8 9.8 0 0 1 12 6c5 0 9 6 9 6a15 15 0 0 1-3 3.4M6.5 7.6A15 15 0 0 0 3 12s4 6 9 6a9 9 0 0 0 3.5-.7"/>',
  album: '<rect x="3" y="5" width="18" height="15" rx="2"/><path d="M7 2h10"/>',
  folder: '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
  people: '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20a6.5 6.5 0 0 1 13 0"/><circle cx="17" cy="9" r="2.5"/><path d="M16 14.2A5 5 0 0 1 21.5 19"/>',
  caret: '<path d="M9 6l6 6-6 6"/>',
  play: '<path d="M7 5l12 7-12 7z" fill="currentColor"/>',
  heart: '<path d="M12 21s-8-5-8-11a4.5 4.5 0 0 1 8-2.9A4.5 4.5 0 0 1 20 10c0 6-8 11-8 11z"/>',
};
const store = {
  get(k, d) { try { const v = localStorage.getItem("plv." + k); return v == null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem("plv." + k, JSON.stringify(v)); } catch { /* private mode */ } },
};
const api = async path => {
  const r = await fetch(path);
  if (!r.ok) throw new Error(`${r.status} ${path}`);
  return r.json();
};

// ------------------------------------------------------------------ state
const state = {
  info: null, albums: [], albumIndex: new Map(), people: [], peopleIndex: new Map(),
  view: null, items: [], grouped: false, layout: null, rendered: new Map(),
  tile: store.get("tile", 160), lbIndex: -1, details: new Map(), openFolders: new Set(store.get("folders", [])),
};

const els = {
  app: $("app"), nav: $("nav"), scroller: $("scroller"), canvas: $("canvas"), empty: $("empty"),
  title: $("viewTitle"), count: $("viewCount"), datePill: $("datePill"), scrubber: $("scrubber"),
  zoom: $("zoom"), search: $("searchInput"),
};

// ------------------------------------------------------------------ boot
async function boot() {
  els.search.placeholder = T.search;
  els.zoom.value = state.tile;
  els.zoom.parentElement.title = T.zoom;
  try {
    const [info, albums, people] = await Promise.all([api("api/info"), api("api/albums"), api("api/people")]);
    state.info = info; state.albums = albums; state.people = people;
  } catch (e) {
    els.empty.hidden = false; els.empty.textContent = T.loadingError + " " + e.message; return;
  }
  indexAlbums(state.albums, null);
  for (const p of state.people) state.peopleIndex.set(p.id, p);
  document.title = state.info.title;
  $("libTitle").textContent = state.info.title;
  $("footInfo").textContent = `${T.photosVideos(state.info.assets - state.info.videos, state.info.videos)} · ${T.readOnly}`;
  buildNav();
  bindUi();
  route();
}

function indexAlbums(nodes, parent) {
  for (const n of nodes) {
    n.parent = parent;
    state.albumIndex.set(n.id, n);
    if (n.children) indexAlbums(n.children, n);
  }
}

// ------------------------------------------------------------------ routing
// #<view>            e.g. #library, #album:12, #person:4, #search:berlin
// #<view>@<assetId>  lightbox open on top of that view
function parseHash() {
  const raw = decodeURIComponent(location.hash.slice(1)) || "library";
  const at = raw.lastIndexOf("@");
  if (at > 0 && /^\d+$/.test(raw.slice(at + 1))) return { view: raw.slice(0, at), asset: +raw.slice(at + 1) };
  return { view: raw, asset: null };
}
const hashFor = (view, asset) => "#" + encodeURIComponent(view).replace(/%3A/g, ":") + (asset != null ? "@" + asset : "");

async function route() {
  const { view, asset } = parseHash();
  if (view !== state.view) await showView(view);
  if (asset != null) {
    const i = state.items.findIndex(it => it[0] === asset);
    if (i >= 0) openLightbox(i, false); else closeLightbox(false);
  } else closeLightbox(false);
}
window.addEventListener("hashchange", route);
const go = view => { location.hash = hashFor(view); els.app.classList.remove("nav-open"); };

// ------------------------------------------------------------------ navigation
function buildNav() {
  const i = state.info;
  const item = (view, ico, label, num) =>
    h("a", { class: "nav-item", href: hashFor(view), "data-view": view },
      icon(ICONS[ico]), h("span", { class: "label" }, label), num != null ? h("span", { class: "num" }, fmtNum(num)) : null);
  const groups = [
    h("div", { class: "nav-group" }, h("h2", {}, T.library),
      item("library", "all", T.all, i.assets),
      item("favorites", "fav", T.favorites, i.favorites),
      item("videos", "video", T.videos, i.videos),
      item("live", "live", T.live),
      item("edited", "edited", T.edited),
      i.hidden ? item("hidden", "hidden", T.hidden) : null),
    h("div", { class: "nav-group" }, h("h2", {}, T.collections),
      item("albums", "album", T.albums, i.albums),
      state.people.length ? item("people", "people", T.people, state.people.length) : null),
  ];
  if (state.albums.length) {
    groups.push(h("div", { class: "nav-group" }, h("h2", {}, T.myAlbums), albumTree(state.albums)));
  }
  els.nav.replaceChildren(...groups);
}

function albumTree(nodes) {
  return nodes.map(n => {
    if (!n.folder) {
      return h("a", { class: "nav-item", href: hashFor("album:" + n.id), "data-view": "album:" + n.id },
        icon(ICONS.album), h("span", { class: "label" }, n.title || "—"), h("span", { class: "num" }, fmtNum(n.count)));
    }
    const open = state.openFolders.has(n.id);
    const kids = h("div", { class: "nav-children" }, open ? albumTree(n.children) : []);
    const caret = icon(ICONS.caret); caret.classList.add("caret");
    const row = h("a", { class: "nav-item" + (open ? " open" : ""), href: hashFor("folder:" + n.id), "data-view": "folder:" + n.id },
      icon(ICONS.folder), h("span", { class: "label" }, n.title || "—"), caret);
    caret.addEventListener("click", e => { e.preventDefault(); e.stopPropagation(); toggleFolder(n, row, kids); });
    return h("div", {}, row, kids);
  });
}

function toggleFolder(n, row, kids, force) {
  const open = force ?? !state.openFolders.has(n.id);
  if (open) state.openFolders.add(n.id); else state.openFolders.delete(n.id);
  store.set("folders", [...state.openFolders]);
  row.classList.toggle("open", open);
  kids.replaceChildren(...(open ? albumTree(n.children) : []));
  markActive();
}

function markActive() {
  for (const a of els.nav.querySelectorAll(".nav-item")) a.classList.toggle("active", a.dataset.view === state.view);
}

// ------------------------------------------------------------------ views
const GROUPED = new Set(["library", "favorites", "videos", "live", "edited", "hidden", "person", "search"]);

async function showView(view) {
  state.view = view;
  const [kind, arg] = view.split(/:(.*)/s);
  markActive();
  els.scroller.scrollTop = 0;
  els.empty.hidden = true;
  if (kind === "albums" || kind === "folder") return showAlbumGrid(kind === "folder" ? state.albumIndex.get(+arg) : null);
  if (kind === "people") return showPeopleGrid();
  if (kind === "search") els.search.value = arg || ""; else if (document.activeElement !== els.search) els.search.value = "";
  const titles = { library: T.all, favorites: T.favorites, videos: T.videos, live: T.live, edited: T.edited, hidden: T.hidden };
  setTitle(titles[kind] || "", "");
  let data;
  try { data = await api("api/assets?view=" + encodeURIComponent(view)); }
  catch (e) { state.items = []; renderGrid(); els.empty.hidden = false; els.empty.textContent = T.loadingError; return; }
  if (state.view !== view) return; // user moved on meanwhile
  state.items = data.items;
  state.grouped = GROUPED.has(kind);
  const title = kind === "search" ? `${T.searchFor}: „${data.title}“` : data.title || titles[kind] || "";
  setTitle(title, T.items(state.items.length));
  renderGrid();
  if (!state.items.length) { els.empty.hidden = false; els.empty.textContent = kind === "search" ? T.noResults : T.nothing; }
}

function setTitle(title, count) {
  els.title.textContent = title; els.count.textContent = count;
  document.title = title ? `${title} – ${state.info.title}` : state.info.title;
}

// ---------- photo grid (virtualised) ----------
const GAP = 4, HEAD = 54, OVERSCAN = 900;

function computeLayout() {
  const width = els.canvas.clientWidth;
  const narrow = width < 600;
  const target = narrow ? Math.min(state.tile, 120) : state.tile;
  const cols = Math.max(narrow ? 3 : 2, Math.floor((width + GAP) / (target + GAP)));
  const size = (width - GAP * (cols - 1)) / cols;
  const rows = [], heads = [];
  let y = 0;
  const items = state.items;
  const pushRows = (start, end) => {
    for (let i = start; i < end; i += cols) { rows.push({ y, start: i, end: Math.min(i + cols, end) }); y += size + GAP; }
  };
  if (state.grouped) {
    let i = 0;
    while (i < items.length) {
      const d = new Date(items[i][1] * 1000);
      const key = d.getUTCFullYear() * 12 + d.getUTCMonth();
      let j = i;
      while (j < items.length) {
        const e = new Date(items[j][1] * 1000);
        if (e.getUTCFullYear() * 12 + e.getUTCMonth() !== key) break;
        j++;
      }
      heads.push({ y, label: fmtMonth.format(d), year: d.getUTCFullYear(), count: j - i, start: i });
      y += HEAD;
      pushRows(i, j);
      y += 6;
      i = j;
    }
  } else {
    y = 16;
    pushRows(0, items.length);
  }
  return { cols, size, rows, heads, height: y + 40 };
}

function renderGrid(keepIndex) {
  const anchor = keepIndex ?? null;
  els.canvas.replaceChildren();
  els.canvas.className = "canvas";
  state.rendered.clear();
  state.layout = computeLayout();
  els.canvas.style.height = state.layout.height + "px";
  buildScrubber();
  if (anchor != null) scrollToIndex(anchor, "start");
  paint();
}

function paint() {
  const L = state.layout;
  if (!L) return;
  const top = els.scroller.scrollTop - OVERSCAN, bottom = els.scroller.scrollTop + els.scroller.clientHeight + OVERSCAN;
  const wanted = new Set();
  // binary search first row
  let lo = 0, hi = L.rows.length;
  while (lo < hi) { const mid = (lo + hi) >> 1; if (L.rows[mid].y + L.size < top) lo = mid + 1; else hi = mid; }
  for (let r = lo; r < L.rows.length && L.rows[r].y < bottom; r++) {
    const row = L.rows[r];
    for (let i = row.start; i < row.end; i++) {
      const key = "t" + i;
      wanted.add(key);
      if (!state.rendered.has(key)) {
        const el = tile(i, row.y, (i - row.start) * (L.size + GAP), L.size);
        state.rendered.set(key, el);
        els.canvas.append(el);
      }
    }
  }
  for (const [k, hd] of L.heads.entries()) {
    if (hd.y + HEAD < top || hd.y > bottom) continue;
    const key = "h" + k;
    wanted.add(key);
    if (!state.rendered.has(key)) {
      const el = h("div", { class: "section-head", style: `top:${hd.y}px;height:${HEAD}px` }, hd.label, h("small", {}, fmtNum(hd.count)));
      state.rendered.set(key, el);
      els.canvas.append(el);
    }
  }
  for (const [k, el] of state.rendered) if (!wanted.has(k)) { el.remove(); state.rendered.delete(k); }
}

function tile(i, y, x, size) {
  const [id, , flags, dur] = state.items[i];
  const img = h("img", { alt: "", loading: "lazy", decoding: "async", draggable: "false" });
  img.addEventListener("load", () => img.classList.add("ok"), { once: true });
  img.src = "t/" + id;
  const el = h("a", { class: "tile", href: hashFor(state.view, id), style: `top:${y}px;left:${x}px;width:${size}px;height:${size}px`, "data-i": i }, img);
  if (flags & FLAG_VIDEO) el.append(h("span", { class: "badge" }, icon(ICONS.play), fmtDur(dur)));
  else if (flags & FLAG_LIVE) el.append(h("span", { class: "badge" }, icon(ICONS.live)));
  if (flags & FLAG_FAV) el.append(h("span", { class: "fav" }, icon(ICONS.heart)));
  return el;
}

function scrollToIndex(i, mode = "nearest") {
  const L = state.layout;
  if (!L || i < 0) return;
  const row = L.rows.find(r => i >= r.start && i < r.end);
  if (!row) return;
  const st = els.scroller.scrollTop, vh = els.scroller.clientHeight;
  if (mode === "start") els.scroller.scrollTop = Math.max(row.y - HEAD, 0);
  else if (row.y < st) els.scroller.scrollTop = row.y - HEAD;
  else if (row.y + L.size > st + vh) els.scroller.scrollTop = row.y + L.size - vh + 12;
}

function firstVisibleIndex() {
  const L = state.layout;
  if (!L || !L.rows.length) return null;
  const st = els.scroller.scrollTop;
  const row = L.rows.find(r => r.y + L.size > st);
  return row ? row.start : null;
}

function buildScrubber() {
  const L = state.layout;
  els.scrubber.replaceChildren();
  const years = [];
  for (const hd of L.heads) if (!years.length || years[years.length - 1].year !== hd.year) years.push(hd);
  const show = state.grouped && years.length > 1;
  els.app.classList.toggle("has-scrubber", show);
  if (!show) return;
  const room = Math.max(4, Math.floor((els.scroller.clientHeight - 20) / 18));
  const step = Math.ceil(years.length / room);
  years.forEach((hd, k) => {
    if (k % step && k !== years.length - 1) return;
    els.scrubber.append(h("button", { type: "button", onclick: () => { els.scroller.scrollTop = hd.y; } }, String(hd.year)));
  });
}

let pillTimer;
function updatePill() {
  const L = state.layout;
  if (!L || !state.grouped || !L.heads.length) return;
  const st = els.scroller.scrollTop + 10;
  let hd = L.heads[0];
  for (const x of L.heads) { if (x.y <= st) hd = x; else break; }
  els.datePill.textContent = hd.label;
  els.datePill.hidden = st < 40;
  clearTimeout(pillTimer);
  pillTimer = setTimeout(() => { els.datePill.hidden = true; }, 1100);
}

// ---------- album and people overviews ----------
function showAlbumGrid(folder) {
  const nodes = folder ? folder.children : state.albums;
  setTitle(folder ? folder.title : T.albums, T.albumsCount(countAlbums(nodes)));
  state.items = []; state.layout = null; state.rendered.clear();
  els.app.classList.remove("has-scrubber"); els.scrubber.replaceChildren();
  els.canvas.style.height = "";
  els.canvas.className = "canvas card-grid";
  els.canvas.style.gridTemplateColumns = `repeat(auto-fill, minmax(${Math.max(130, state.tile + 20)}px, 1fr))`;
  els.canvas.replaceChildren(...nodes.map(n => {
    const cover = h("div", { class: "cover" });
    if (n.key) cover.append(h("img", { src: "t/" + n.key, alt: "", loading: "lazy" }));
    else if (n.folder) cover.append(h("div", { class: "folder-icon" }, icon(ICONS.folder)));
    return h("a", { class: "card" + (n.folder ? " folder" : ""), href: hashFor((n.folder ? "folder:" : "album:") + n.id) },
      cover, h("h3", {}, n.title || "—"),
      h("p", {}, n.folder ? `${T.folder} · ${T.albumsCount(countAlbums(n.children))}` : T.items(n.count)));
  }));
  if (folder) expandTo(folder);
  if (!nodes.length) { els.empty.hidden = false; els.empty.textContent = T.nothing; }
}
const countAlbums = nodes => nodes.reduce((s, n) => s + (n.folder ? countAlbums(n.children) : 1), 0);

function expandTo(node) {
  const chain = [];
  for (let n = node; n; n = n.parent) if (n.folder) chain.unshift(n);
  let changed = false;
  for (const n of chain) if (!state.openFolders.has(n.id)) { state.openFolders.add(n.id); changed = true; }
  if (changed) { store.set("folders", [...state.openFolders]); buildNav(); markActive(); }
}

function showPeopleGrid() {
  setTitle(T.people, fmtNum(state.people.length));
  state.items = []; state.layout = null; state.rendered.clear();
  els.app.classList.remove("has-scrubber"); els.scrubber.replaceChildren();
  els.canvas.style.height = "";
  els.canvas.className = "canvas card-grid";
  els.canvas.style.gridTemplateColumns = `repeat(auto-fill, minmax(${Math.max(110, state.tile - 10)}px, 1fr))`;
  els.canvas.replaceChildren(...state.people.map(p => h("a", { class: "card person", href: hashFor("person:" + p.id) },
    h("div", { class: "cover" }, p.face ? h("img", { src: "face/" + p.face, alt: "", loading: "lazy" }) : null),
    h("h3", {}, p.name), h("p", {}, T.items(p.count)))));
}

// ------------------------------------------------------------------ fullscreen
// The lightbox goes fullscreen on its own; outside it the whole app does.
const canFullscreen = !!(document.fullscreenEnabled || document.webkitFullscreenEnabled);
const fsElement = () => document.fullscreenElement || document.webkitFullscreenElement || null;
function toggleFullscreen(target) {
  if (fsElement()) {
    Promise.resolve((document.exitFullscreen || document.webkitExitFullscreen).call(document)).catch(() => {});
    return;
  }
  const el = target || document.documentElement;
  const req = el.requestFullscreen || el.webkitRequestFullscreen;
  if (req) Promise.resolve(req.call(el)).catch(() => {});
}
const onFsChange = () => {
  lb.root.classList.toggle("fs", fsElement() === lb.root);
  document.documentElement.classList.toggle("is-fs", !!fsElement());
  poke();
};
document.addEventListener("fullscreenchange", onFsChange);
document.addEventListener("webkitfullscreenchange", onFsChange);

// ------------------------------------------------------------------ lightbox
const lb = {
  root: $("lightbox"), img: $("lbImg"), video: $("lbVideo"), live: $("lbLive"), msg: $("lbMsg"),
  spinner: $("lbSpinner"), date: $("lbDate"), sub: $("lbSub"), info: $("lbInfo"), liveBtn: $("lbLiveBtn"),
  download: $("lbDownload"), token: 0, pushed: false,
};

function openLightbox(i, push = true) {
  if (i < 0 || i >= state.items.length) return;
  const wasOpen = !lb.root.hidden;
  state.lbIndex = i;
  const [id, ts, flags] = state.items[i];
  if (push) {
    const target = hashFor(state.view, id);
    if (wasOpen) history.replaceState(null, "", target);
    else { history.pushState(null, "", target); lb.pushed = true; }
  }
  lb.root.hidden = false;
  document.body.style.overflow = "hidden";
  const token = ++lb.token;
  const d = new Date(ts * 1000);
  lb.date.textContent = fmtDay.format(d);
  lb.sub.textContent = fmtTime.format(d);
  lb.download.href = "o/" + id;
  lb.msg.hidden = true;
  lb.liveBtn.hidden = !(flags & FLAG_LIVE);
  lb.liveBtn.classList.remove("on");
  stopLive();
  lb.video.pause(); lb.video.removeAttribute("src"); lb.video.hidden = true;
  lb.img.hidden = false;
  lb.spinner.hidden = false;

  if (flags & FLAG_VIDEO) {
    lb.img.hidden = true;
    lb.video.hidden = false;
    lb.video.poster = "p/" + id;
    details(id).then(info => {
      if (token !== lb.token) return;
      lb.spinner.hidden = true;
      if (!info.available) { showMsg(T.missing); return; }
      if (!info.playable) { showMsg(T.notPlayable); return; }
      lb.video.src = "v/" + id;
      lb.video.play().catch(() => { /* autoplay blocked: controls remain */ });
    }).catch(() => { lb.spinner.hidden = true; });
    lb.video.onerror = () => { if (token === lb.token && lb.video.getAttribute("src")) showMsg(T.notPlayable); };
  } else {
    lb.img.onload = () => { if (token === lb.token) lb.spinner.hidden = true; };
    lb.img.onerror = () => { if (token === lb.token) { lb.spinner.hidden = true; showMsg(T.loadingError); } };
    lb.img.src = "p/" + id;
    const full = new Image();
    full.decoding = "async";
    full.onload = () => { if (token === lb.token) { lb.img.src = full.src; lb.spinner.hidden = true; } };
    full.src = "f/" + id;
  }
  // warm up neighbours
  for (const j of [i + 1, i - 1]) {
    const it = state.items[j];
    if (it && !(it[2] & FLAG_VIDEO)) new Image().src = "p/" + it[0];
  }
  $("lbPrev").hidden = i === 0;
  $("lbNext").hidden = i === state.items.length - 1;
  if (!lb.info.hidden) renderInfo(id, token);
  poke();
}

function closeLightbox(pop = true) {
  if (lb.root.hidden) return;
  if (fsElement() === lb.root) toggleFullscreen();
  lb.token++;
  lb.video.pause(); lb.video.removeAttribute("src"); lb.video.load();
  stopLive();
  lb.root.hidden = true;
  document.body.style.overflow = "";
  if (pop && parseHash().asset != null) {
    // Leave the lightbox entry the way we came in, without a stray history step.
    if (lb.pushed) history.back();
    else history.replaceState(null, "", hashFor(state.view));
  }
  lb.pushed = false;
  if (state.lbIndex >= 0) scrollToIndex(state.lbIndex);
  const el = els.canvas.querySelector(`[data-i="${state.lbIndex}"]`);
  if (el) el.focus({ preventScroll: true });
}

function step(delta) {
  const j = state.lbIndex + delta;
  if (j >= 0 && j < state.items.length) openLightbox(j);
}

function showMsg(text) {
  lb.msg.replaceChildren(text);
  if (text === T.notPlayable) {
    lb.msg.append(" ", h("a", { href: lb.download.href, download: "", style: "color:#8fb0ff" }, "↓"));
  }
  lb.msg.hidden = false;
}

async function details(id) {
  if (!state.details.has(id)) state.details.set(id, api("api/asset/" + id).catch(e => { state.details.delete(id); throw e; }));
  return state.details.get(id);
}

function playLive() {
  const id = state.items[state.lbIndex]?.[0];
  if (id == null) return;
  lb.live.src = "live/" + id;
  lb.live.hidden = false;
  lb.img.style.visibility = "hidden";
  lb.liveBtn.classList.add("on");
  lb.live.play().catch(stopLive);
}
function stopLive() {
  lb.live.pause(); lb.live.removeAttribute("src"); lb.live.hidden = true;
  lb.img.style.visibility = ""; lb.liveBtn.classList.remove("on");
}
lb.live.addEventListener("ended", stopLive);

async function renderInfo(id, token = lb.token) {
  lb.root.classList.add("info");
  lb.info.hidden = false;
  let d;
  try { d = await details(id); } catch { lb.info.replaceChildren(T.loadingError); return; }
  if (token !== lb.token) return;
  const local = new Date((d.date + d.tz) * 1000);
  const tz = d.tz ? `UTC${d.tz >= 0 ? "+" : "−"}${String(Math.floor(Math.abs(d.tz) / 3600)).padStart(2, "0")}:${String(Math.abs(d.tz) % 3600 / 60).padStart(2, "0")}` : "";
  const rows = [];
  const row = (k, v) => { if (v != null && v !== "") rows.push(h("dt", {}, k), h("dd", {}, v)); };
  row(T.file, d.filename);
  row(T.dimensions, d.width && d.height ? `${fmtNum(d.width)} × ${fmtNum(d.height)}` : null);
  row(T.filesize, d.size ? fmtBytes(d.size) : null);
  if (d.video) row(T.duration, fmtDur(d.duration));
  row(T.camera, d.camera);
  row(T.lens, d.lens);
  const exp = [
    d.aperture ? `ƒ/${(+d.aperture).toFixed(1)}` : null,
    d.shutter ? (d.shutter < 1 ? `1/${Math.round(1 / d.shutter)} s` : `${(+d.shutter).toFixed(1)} s`) : null,
    d.iso ? `ISO ${d.iso}` : null,
    d.focal ? `${Math.round(d.focal)} mm${d.focal35 && Math.round(d.focal35) !== Math.round(d.focal) ? ` (${Math.round(d.focal35)} mm KB)` : ""}` : null,
  ].filter(Boolean).join(" · ");
  row(T.exposure, exp);
  if (d.video) row(T.codec, [d.codec, d.fps ? `${Math.round(d.fps)} fps` : null].filter(Boolean).join(" · "));
  if (d.edited) row(T.edited, T.editedYes);
  if (d.lat != null) {
    const z = 15;
    row(T.location, h("a", {
      class: "map", target: "_blank", rel: "noopener noreferrer",
      href: `https://www.openstreetmap.org/?mlat=${d.lat}&mlon=${d.lon}#map=${z}/${d.lat}/${d.lon}`,
    }, `${d.lat.toFixed(4)}, ${d.lon.toFixed(4)} ↗`));
  }
  const chips = (title, list) => list.length ? [h("h3", {}, title), h("div", { class: "chips" }, list)] : [];
  lb.info.replaceChildren(...[
    h("h2", {}, d.title || fmtDay.format(local)),
    h("p", { class: "sub" }, [d.title ? fmtShortDay.format(local) : null, fmtTime.format(local), tz].filter(Boolean).join(" · ")),
    d.description ? h("p", { class: "desc" }, d.description) : null,
    h("dl", {}, rows),
    ...chips(T.people, d.people.map(p => h("a", { href: hashFor("person:" + p.id) }, p.name))),
    ...chips(T.albums, d.albums.map(a => h("a", { href: hashFor("album:" + a.id) }, a.title || "—"))),
    ...chips(T.keywords, d.keywords.map(k => h("a", { href: hashFor("search:" + k) }, k))),
  ].filter(Boolean));
}
function toggleInfo() {
  if (lb.info.hidden) renderInfo(state.items[state.lbIndex][0]);
  else { lb.info.hidden = true; lb.root.classList.remove("info"); }
  store.set("info", !lb.info.hidden);
}

let idleTimer;
function poke() {
  lb.root.classList.remove("idle");
  clearTimeout(idleTimer);
  idleTimer = setTimeout(() => { if (!lb.root.hidden && lb.info.hidden) lb.root.classList.add("idle"); }, 2600);
}

// ------------------------------------------------------------------ events
function bindUi() {
  let raf = 0;
  els.scroller.addEventListener("scroll", () => {
    if (raf) return;
    raf = requestAnimationFrame(() => { raf = 0; paint(); updatePill(); });
  }, { passive: true });

  let lastWidth = els.canvas.clientWidth;
  new ResizeObserver(() => {
    const w = els.canvas.clientWidth;
    if (!state.layout || w === lastWidth) return;
    lastWidth = w;
    renderGrid(firstVisibleIndex());
  }).observe(els.scroller);

  els.zoom.addEventListener("input", () => {
    state.tile = +els.zoom.value;
    store.set("tile", state.tile);
    if (state.layout) renderGrid(firstVisibleIndex());
    else if (state.view === "people") showPeopleGrid();
    else if (state.view === "albums" || state.view.startsWith("folder:")) showView(state.view);
  });

  els.canvas.addEventListener("click", e => {
    const t = e.target.closest(".tile");
    if (!t || e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
    e.preventDefault();
    openLightbox(+t.dataset.i);
  });

  $("searchForm").addEventListener("submit", e => {
    e.preventDefault();
    const q = els.search.value.trim();
    if (q) go("search:" + q); else go("library");
    els.search.blur();
  });

  $("menuBtn").addEventListener("click", () => els.app.classList.toggle("nav-open"));
  $("scrim").addEventListener("click", () => els.app.classList.remove("nav-open"));
  els.nav.addEventListener("click", e => { if (e.target.closest("a")) els.app.classList.remove("nav-open"); });

  $("lbClose").addEventListener("click", () => closeLightbox());
  $("lbPrev").addEventListener("click", () => step(-1));
  $("lbNext").addEventListener("click", () => step(1));
  $("lbInfoBtn").addEventListener("click", toggleInfo);
  if (!canFullscreen) document.documentElement.classList.add("no-fullscreen");
  $("lbFullBtn").addEventListener("click", () => toggleFullscreen(lb.root));
  $("fullBtn").addEventListener("click", () => toggleFullscreen());
  $("lbStage").addEventListener("dblclick", e => { if (e.target !== lb.video && canFullscreen) toggleFullscreen(lb.root); });
  lb.liveBtn.addEventListener("click", () => (lb.live.hidden ? playLive() : stopLive()));
  lb.root.addEventListener("mousemove", poke);
  lb.info.addEventListener("click", e => { if (e.target.closest("a[href^='#']")) closeLightbox(false); });
  if (store.get("info", false)) { lb.info.hidden = false; lb.root.classList.add("info"); }

  let tx = null, ty = null;
  $("lbStage").addEventListener("touchstart", e => { if (e.touches.length === 1) { tx = e.touches[0].clientX; ty = e.touches[0].clientY; } }, { passive: true });
  $("lbStage").addEventListener("touchend", e => {
    if (tx == null) return;
    const dx = e.changedTouches[0].clientX - tx, dy = e.changedTouches[0].clientY - ty;
    tx = null;
    if (Math.abs(dx) > 50 && Math.abs(dx) > Math.abs(dy) * 1.5) step(dx < 0 ? 1 : -1);
    else if (dy > 90 && Math.abs(dy) > Math.abs(dx) * 1.5) closeLightbox();
    poke();
  });
  $("lbStage").addEventListener("click", e => {
    if (e.target === lb.video) return;
    if (window.matchMedia("(hover: none)").matches) lb.root.classList.toggle("idle");
  });

  document.addEventListener("keydown", e => {
    if (lb.root.hidden) {
      if (e.key === "/" && document.activeElement !== els.search) { e.preventDefault(); els.search.focus(); }
      else if ((e.key === "f" || e.key === "F") && document.activeElement !== els.search && canFullscreen) toggleFullscreen();
      return;
    }
    if (e.target === els.search) return;
    switch (e.key) {
      case "ArrowRight": step(1); break;
      case "ArrowLeft": step(-1); break;
      case "Escape": closeLightbox(); break;
      case "i": toggleInfo(); break;
      case "f": case "F": if (canFullscreen) toggleFullscreen(lb.root); break;
      case " ":
        if (!lb.video.hidden) { e.preventDefault(); lb.video.paused ? lb.video.play() : lb.video.pause(); }
        else if (!lb.liveBtn.hidden) { e.preventDefault(); lb.live.hidden ? playLive() : stopLive(); }
        break;
      default: return;
    }
    poke();
  });
}

boot();
