/* photoslibrary-viewer – browser UI (no build step; Leaflet is loaded only for the map). */
"use strict";

// ------------------------------------------------------------------ i18n
const LANG = (navigator.language || "en").toLowerCase().startsWith("de") ? "de" : "en";
const T = {
  de: {
    library: "Mediathek", all: "Alle Fotos", days: "Tage", months: "Monate", years: "Jahre",
    collections: "Sammlungen", memories: "Rückblicke", people: "Personen", places: "Orte", favorites: "Favoriten",
    imports: "Importe", albums: "Alben", mediaTypes: "Medientypen", videos: "Videos", selfies: "Selfies",
    live: "Live Photos", portrait: "Porträt", panoramas: "Panoramen", timelapse: "Zeitraffer", slomo: "Slo-Mo",
    bursts: "Serienbilder", screenshots: "Bildschirmfotos", screenrec: "Bildschirmaufnahmen", edited: "Bearbeitet",
    more: "Weitere", hidden: "Ausgeblendet", deleted: "Zuletzt gelöscht", myAlbums: "Meine Alben",
    search: "Suchen", searchFor: "Suche", items: n => `${fmtNum(n)} ${n === 1 ? "Objekt" : "Objekte"}`,
    photosVideos: (p, v) => `${fmtNum(p)} Fotos, ${fmtNum(v)} Videos`, nothing: "Hier ist nichts.",
    noResults: "Keine Treffer.", file: "Datei", dimensions: "Abmessungen", filesize: "Dateigröße", camera: "Kamera",
    lens: "Objektiv", exposure: "Aufnahme", duration: "Dauer", codec: "Codec", location: "Ort", coordinates: "Koordinaten",
    keywords: "Schlagwörter", editedYes: "Ja, bearbeitete Fassung wird gezeigt", notPlayable: "Dieses Videoformat kann der Browser nicht abspielen. Original herunterladen?",
    missing: "Originaldatei fehlt in der Mediathek.", loadingError: "Konnte nicht geladen werden.", folder: "Ordner",
    albumsCount: n => `${fmtNum(n)} ${n === 1 ? "Album" : "Alben"}`, zoom: "Größe", readOnly: "nur lesend",
    trip: "Reise", weekend: "Wochenende", importedFrom: "Importiert aus", deletedOn: "Gelöscht am",
    mapLoading: "Karte wird geladen …", mapError: "Die Karte konnte nicht geladen werden.", source: "Quelle",
    selfie: "Selfie", type: "Art", found: { place: "Ort", person: "Person", album: "Album", scene: "Motiv", text: "Text im Bild", camera: "Kamera", date: "Zeit", type: "Medientyp", keyword: "Schlagwort" },
    slideshow: "Diashow",
  },
  en: {
    library: "Library", all: "All Photos", days: "Days", months: "Months", years: "Years",
    collections: "Collections", memories: "Memories", people: "People", places: "Places", favorites: "Favorites",
    imports: "Imports", albums: "Albums", mediaTypes: "Media Types", videos: "Videos", selfies: "Selfies",
    live: "Live Photos", portrait: "Portrait", panoramas: "Panoramas", timelapse: "Time-lapse", slomo: "Slo-mo",
    bursts: "Bursts", screenshots: "Screenshots", screenrec: "Screen Recordings", edited: "Edited",
    more: "Other", hidden: "Hidden", deleted: "Recently Deleted", myAlbums: "My Albums",
    search: "Search", searchFor: "Search", items: n => `${fmtNum(n)} ${n === 1 ? "item" : "items"}`,
    photosVideos: (p, v) => `${fmtNum(p)} photos, ${fmtNum(v)} videos`, nothing: "Nothing here.",
    noResults: "No results.", file: "File", dimensions: "Dimensions", filesize: "File size", camera: "Camera",
    lens: "Lens", exposure: "Exposure", duration: "Duration", codec: "Codec", location: "Location", coordinates: "Coordinates",
    keywords: "Keywords", editedYes: "Yes, showing the edited version", notPlayable: "Your browser cannot play this video format. Download the original?",
    missing: "Original file is missing from the library.", loadingError: "Could not be loaded.", folder: "Folder",
    albumsCount: n => `${fmtNum(n)} ${n === 1 ? "album" : "albums"}`, zoom: "Size", readOnly: "read-only",
    trip: "Trip", weekend: "Weekend", importedFrom: "Imported from", deletedOn: "Deleted on",
    mapLoading: "Loading map …", mapError: "The map could not be loaded.", source: "Source",
    selfie: "Selfie", type: "Type", found: { place: "Place", person: "Person", album: "Album", scene: "Scene", text: "Text in photo", camera: "Camera", date: "Time", type: "Media type", keyword: "Keyword" },
    slideshow: "Slideshow",
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
const fmtLocalDateTime = new Intl.DateTimeFormat(LOCALE, { dateStyle: "medium", timeStyle: "short" });
const fmtDur = s => { s = Math.round(s); const m = Math.floor(s / 60); return `${m}:${String(s % 60).padStart(2, "0")}`; };
const fmtBytes = b => b == null ? "" : b < 1e6 ? `${(b / 1e3).toFixed(0)} KB` : b < 1e9 ? `${(b / 1e6).toFixed(1)} MB` : `${(b / 1e9).toFixed(2)} GB`;
const dayKey = ts => new Date(ts * 1000).toISOString().slice(0, 10);

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
  for (const kid of kids.flat()) if (kid != null && kid !== false) el.append(kid.nodeType ? kid : String(kid));
  return el;
};
const icon = d => { const s = document.createElementNS("http://www.w3.org/2000/svg", "svg"); s.setAttribute("viewBox", "0 0 24 24"); s.innerHTML = d; return s; };
const ICONS = {
  all: '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
  days: '<rect x="3" y="4" width="18" height="17" rx="2"/><path d="M3 9h18M8 2v4M16 2v4"/>',
  months: '<rect x="3" y="4" width="18" height="17" rx="2"/><path d="M3 9h18M8 13h2M12 13h2M16 13h1M8 17h2M12 17h2"/>',
  years: '<rect x="4" y="3" width="16" height="7" rx="1.5"/><rect x="4" y="14" width="16" height="7" rx="1.5"/>',
  memories: '<path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M5.6 18.4l2.1-2.1M16.3 7.7l2.1-2.1"/><circle cx="12" cy="12" r="3"/>',
  places: '<path d="M12 21s-7-6.2-7-11a7 7 0 0 1 14 0c0 4.8-7 11-7 11z"/><circle cx="12" cy="10" r="2.5"/>',
  imports: '<path d="M12 3v12M7 10l5 5 5-5M4 17v3h16v-3"/>',
  fav: '<path d="M12 20s-7-4.4-7-10a4 4 0 0 1 7-2.6A4 4 0 0 1 19 10c0 5.6-7 10-7 10z"/>',
  video: '<rect x="3" y="6" width="13" height="12" rx="2"/><path d="M16 10l5-3v10l-5-3"/>',
  selfie: '<circle cx="12" cy="9" r="4"/><path d="M4.5 21a7.5 7.5 0 0 1 15 0"/>',
  live: '<circle cx="12" cy="12" r="3"/><circle cx="12" cy="12" r="6.5" stroke-dasharray="2 2"/><circle cx="12" cy="12" r="9.5"/>',
  portrait: '<path d="M12 3a9 9 0 1 0 0 18"/><path d="M12 3a9 9 0 0 1 0 18" stroke-dasharray="1.5 2.5"/>',
  panorama: '<path d="M3 6c6 2 12 2 18 0v12c-6-2-12-2-18 0z"/>',
  timelapse: '<circle cx="12" cy="12" r="9" stroke-dasharray="1 2.6"/><path d="M12 7v5l3 2"/>',
  slomo: '<circle cx="12" cy="12" r="9" stroke-dasharray="4 2"/><path d="M12 7v5"/>',
  bursts: '<rect x="7" y="7" width="13" height="13" rx="2"/><path d="M4 16V5a1 1 0 0 1 1-1h11"/>',
  screenshot: '<rect x="6" y="2" width="12" height="20" rx="2.5"/><path d="M3 8V5M3 5h3M21 16v3M21 19h-3"/>',
  screenrec: '<rect x="6" y="2" width="12" height="20" rx="2.5"/><circle cx="12" cy="12" r="3"/>',
  edited: '<circle cx="6" cy="6" r="2"/><circle cx="18" cy="12" r="2"/><circle cx="9" cy="18" r="2"/><path d="M8 6h13M3 6h1M3 12h13M20 12h1M3 18h4M11 18h10"/>',
  hidden: '<path d="M3 3l18 18M10.6 6.1A9.8 9.8 0 0 1 12 6c5 0 9 6 9 6a15 15 0 0 1-3 3.4M6.5 7.6A15 15 0 0 0 3 12s4 6 9 6a9 9 0 0 0 3.5-.7"/>',
  deleted: '<path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13"/>',
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
const apiCache = new Map();
const api = async (path, cache = false) => {
  if (cache && apiCache.has(path)) return apiCache.get(path);
  const p = fetch(path).then(r => { if (!r.ok) throw new Error(`${r.status} ${path}`); return r.json(); });
  if (cache) { apiCache.set(path, p); p.catch(() => apiCache.delete(path)); }
  return p;
};

// ------------------------------------------------------------------ state
const state = {
  info: null, albums: [], albumIndex: new Map(), people: [],
  view: null, items: [], group: "month", days: {}, layout: null, rendered: new Map(),
  tile: store.get("tile", 160), lbIndex: -1, details: new Map(), openFolders: new Set(store.get("folders", [])),
};

const els = {
  app: $("app"), nav: $("nav"), scroller: $("scroller"), canvas: $("canvas"), empty: $("empty"), head: $("viewHead"),
  title: $("viewTitle"), count: $("viewCount"), datePill: $("datePill"), scrubber: $("scrubber"),
  zoom: $("zoom"), search: $("searchInput"), showBtn: $("showBtn"),
};

// Grid views (asset lists) and their sidebar entries.
const MEDIA_TYPES = [
  ["videos", "video"], ["selfies", "selfie"], ["live", "live"], ["portrait", "portrait"],
  ["panoramas", "panorama"], ["timelapse", "timelapse"], ["slomo", "slomo"], ["bursts", "bursts"],
  ["screenshots", "screenshot"], ["screenrec", "screenrec"], ["edited", "edited"],
];
const CARD_VIEWS = new Set(["albums", "folder", "people", "memories", "years", "months", "imports", "places"]);

// ------------------------------------------------------------------ boot
async function boot() {
  els.search.placeholder = T.search;
  els.zoom.value = state.tile;
  els.zoom.parentElement.title = T.zoom;
  els.showBtn.title = `${T.slideshow} (S)`;
  try {
    const [info, albums, people] = await Promise.all([api("api/info"), api("api/albums"), api("api/people")]);
    state.info = info; state.albums = albums; state.people = people;
  } catch (e) {
    els.empty.hidden = false; els.empty.textContent = T.loadingError + " " + e.message; return;
  }
  indexAlbums(state.albums, null);
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
const hashFor = (view, asset) => "#" + encodeURIComponent(view).replace(/%3A/g, ":").replace(/%7C/g, "|") + (asset != null ? "@" + asset : "");

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
  const i = state.info, c = i.counts || {};
  const item = (view, ico, label, num) =>
    h("a", { class: "nav-item", href: hashFor(view), "data-view": view },
      icon(ICONS[ico]), h("span", { class: "label" }, label), num != null ? h("span", { class: "num" }, fmtNum(num)) : null);
  const group = (title, ...items) => {
    const kids = items.filter(Boolean);
    return kids.length ? h("div", { class: "nav-group" }, h("h2", {}, title), kids) : null;
  };
  const groups = [
    group(T.library,
      item("library", "all", T.all, i.assets),
      c.days ? item("days", "days", T.days) : null,
      i.years ? item("months", "months", T.months) : null,
      i.years ? item("years", "years", T.years) : null),
    group(T.collections,
      i.memories ? item("memories", "memories", T.memories, i.memories) : null,
      state.people.length ? item("people", "people", T.people, state.people.length) : null,
      c.places ? item("places", "places", T.places, i.cities || null) : null,
      c.favorites ? item("favorites", "fav", T.favorites, c.favorites) : null,
      i.imports ? item("imports", "imports", T.imports, i.imports) : null,
      item("albums", "album", T.albums, i.albums)),
    group(T.mediaTypes, ...MEDIA_TYPES.map(([v, ico]) => c[v] ? item(v, ico, T[v], c[v]) : null)),
    group(T.more,
      i.hidden ? item("hidden", "hidden", T.hidden, c.hidden) : null,
      i.deleted ? item("deleted", "deleted", T.deleted, c.deleted) : null),
  ];
  if (state.albums.length) groups.push(group(T.myAlbums, ...albumTree(state.albums)));
  els.nav.replaceChildren(...groups.filter(Boolean));
  markActive();
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

function toggleFolder(n, row, kids) {
  const open = !state.openFolders.has(n.id);
  if (open) state.openFolders.add(n.id); else state.openFolders.delete(n.id);
  store.set("folders", [...state.openFolders]);
  row.classList.toggle("open", open);
  kids.replaceChildren(...(open ? albumTree(n.children) : []));
  markActive();
}

function markActive() {
  const base = state.view && state.view.startsWith("months:") ? "months" : state.view;
  for (const a of els.nav.querySelectorAll(".nav-item")) a.classList.toggle("active", a.dataset.view === base);
}

// ------------------------------------------------------------------ views
const VIEW_TITLES = () => ({
  library: T.all, days: T.days, favorites: T.favorites, hidden: T.hidden, deleted: T.deleted, places: T.places,
  ...Object.fromEntries(MEDIA_TYPES.map(([v]) => [v, T[v]])),
});

function resetCanvas() {
  state.items = []; state.layout = null; state.rendered.clear();
  els.app.classList.remove("has-scrubber"); els.scrubber.replaceChildren();
  els.canvas.style.height = ""; els.canvas.style.gridTemplateColumns = "";
  els.canvas.className = "canvas";
  els.canvas.replaceChildren();
  els.head.replaceChildren(); els.head.hidden = true;
  els.empty.hidden = true;
  els.showBtn.hidden = true;
  destroyMap();
}

async function showView(view) {
  state.view = view;
  const [kind, arg] = view.split(/:(.*)/s);
  markActive();
  els.scroller.scrollTop = 0;
  resetCanvas();
  if (kind === "search") els.search.value = arg || ""; else if (document.activeElement !== els.search) els.search.value = "";
  try {
    switch (kind) {
      case "albums": case "folder": return showAlbumGrid(kind === "folder" ? state.albumIndex.get(+arg) : null);
      case "people": return showPeopleGrid();
      case "memories": return await showMemories();
      case "years": return await showYears();
      case "months": return await showMonths(arg || "");
      case "imports": return await showImports();
      case "places": return await showPlaces();
    }
  } catch (e) {
    if (state.view === view) { els.empty.hidden = false; els.empty.textContent = T.loadingError; }
    return;
  }
  const titles = VIEW_TITLES();
  setTitle(titles[kind] || "", "");
  let data;
  try { data = await api("api/assets?view=" + encodeURIComponent(view)); }
  catch (e) { if (state.view === view) { els.empty.hidden = false; els.empty.textContent = T.loadingError; } return; }
  if (state.view !== view) return; // user moved on meanwhile
  state.items = data.items;
  state.group = data.group || "month";
  state.days = data.days || {};
  let title = data.title || titles[kind] || "";
  if (kind === "search") title = `${T.searchFor}: „${data.title}“`;
  if (kind === "import" && data.title) title = fmtLocalDateTime.format(new Date(data.title.replace(" ", "T")));
  setTitle(title, [data.subtitle, T.items(state.items.length)].filter(Boolean).join(" · "));
  if (data.chips && data.chips.length) {
    els.head.hidden = false;
    els.head.replaceChildren(h("div", { class: "chips-row" }, data.chips.map(c =>
      h("a", { class: "chip", href: hashFor("search:" + c.text) },
        h("span", {}, c.text), c.kind ? h("small", {}, T.found[c.kind] || "") : null, h("em", {}, fmtNum(c.count))))));
  }
  els.showBtn.hidden = !state.items.length;
  renderGrid();
  if (!state.items.length) { els.empty.hidden = false; els.empty.textContent = kind === "search" ? T.noResults : T.nothing; }
}

function setTitle(title, count) {
  els.title.textContent = title; els.count.textContent = count;
  document.title = title ? `${title} – ${state.info.title}` : state.info.title;
}

// ---------- photo grid (virtualised) ----------
const GAP = 4, HEAD = 54, OVERSCAN = 900;
const canvasTop = () => els.canvas.offsetTop;

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
  if (state.group === "month" || state.group === "day") {
    const byDay = state.group === "day";
    const keyOf = ts => { const d = new Date(ts * 1000); return byDay ? dayKey(ts) : d.getUTCFullYear() * 12 + d.getUTCMonth(); };
    let i = 0;
    while (i < items.length) {
      const key = keyOf(items[i][1]);
      let j = i;
      while (j < items.length && keyOf(items[j][1]) === key) j++;
      const d = new Date(items[i][1] * 1000);
      heads.push({
        y, year: d.getUTCFullYear(), count: j - i, start: i,
        label: byDay ? fmtDay.format(d) : fmtMonth.format(d),
        sub: byDay ? state.days[key] || "" : "",
        pill: byDay ? fmtShortDay.format(d) : fmtMonth.format(d),
      });
      y += HEAD;
      pushRows(i, j);
      y += 6;
      i = j;
    }
  } else {
    y = 12;
    pushRows(0, items.length);
  }
  return { cols, size, rows, heads, height: y + 40 };
}

function renderGrid(keepIndex) {
  els.canvas.replaceChildren();
  els.canvas.className = "canvas";
  state.rendered.clear();
  state.layout = computeLayout();
  const width = els.canvas.clientWidth;
  buildScrubber(); // may add padding for the year column, changing the width
  if (els.canvas.clientWidth !== width) state.layout = computeLayout();
  els.canvas.style.height = state.layout.height + "px";
  if (keepIndex != null) scrollToIndex(keepIndex, "start");
  paint();
}

function paint() {
  const L = state.layout;
  if (!L) return;
  const st = els.scroller.scrollTop - canvasTop();
  const top = st - OVERSCAN, bottom = st + els.scroller.clientHeight + OVERSCAN;
  const wanted = new Set();
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
      const el = h("div", { class: "section-head", style: `top:${hd.y}px;height:${HEAD}px` },
        h("span", {}, hd.label), hd.sub ? h("span", { class: "place" }, hd.sub) : null, h("small", {}, fmtNum(hd.count)));
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
  const off = canvasTop();
  const st = els.scroller.scrollTop, vh = els.scroller.clientHeight;
  if (mode === "start") els.scroller.scrollTop = Math.max(off + row.y - HEAD, 0);
  else if (off + row.y < st) els.scroller.scrollTop = off + row.y - HEAD;
  else if (off + row.y + L.size > st + vh) els.scroller.scrollTop = off + row.y + L.size - vh + 12;
}

function firstVisibleIndex() {
  const L = state.layout;
  if (!L || !L.rows.length) return null;
  const st = els.scroller.scrollTop - canvasTop();
  const row = L.rows.find(r => r.y + L.size > st);
  return row ? row.start : null;
}

function buildScrubber() {
  const L = state.layout;
  els.scrubber.replaceChildren();
  const years = [];
  for (const hd of L.heads) if (!years.length || years[years.length - 1].year !== hd.year) years.push(hd);
  const show = years.length > 1;
  els.app.classList.toggle("has-scrubber", show);
  if (!show) return;
  const room = Math.max(4, Math.floor((els.scroller.clientHeight - 20) / 18));
  const step = Math.ceil(years.length / room);
  years.forEach((hd, k) => {
    if (k % step && k !== years.length - 1) return;
    els.scrubber.append(h("button", { type: "button", onclick: () => { els.scroller.scrollTop = canvasTop() + hd.y; } }, String(hd.year)));
  });
}

let pillTimer;
function updatePill() {
  const L = state.layout;
  if (!L || !L.heads.length) return;
  const st = els.scroller.scrollTop - canvasTop() + 10;
  let hd = L.heads[0];
  for (const x of L.heads) { if (x.y <= st) hd = x; else break; }
  els.datePill.textContent = hd.pill;
  els.datePill.hidden = st < 40;
  clearTimeout(pillTimer);
  pillTimer = setTimeout(() => { els.datePill.hidden = true; }, 1100);
}

// ---------- card overviews ----------
function cardGrid(min, cards) {
  els.canvas.className = "canvas card-grid";
  els.canvas.style.gridTemplateColumns = `repeat(auto-fill, minmax(min(${min}px, 100%), 1fr))`;
  els.canvas.replaceChildren(...cards);
  if (!cards.length) { els.empty.hidden = false; els.empty.textContent = T.nothing; }
}

// A card: cover image, title and a line of text. `variant`: "", "wide", "round", "folder", "hero"
function card({ href, key, title, sub, variant = "", overlay, extra, face }) {
  const cover = h("div", { class: "cover" });
  if (face) cover.append(h("img", { src: "face/" + face, alt: "", loading: "lazy" }));
  else if (key) cover.append(h("img", { src: "t/" + key, alt: "", loading: "lazy" }));
  else if (variant === "folder") cover.append(h("div", { class: "folder-icon" }, icon(ICONS.folder)));
  if (overlay) cover.append(h("div", { class: "overlay" }, overlay));
  return h("div", { class: "card " + variant },
    h("a", { href }, cover, title != null ? h("h3", {}, title) : null, sub ? h("p", {}, sub) : null),
    extra || null);
}

function showAlbumGrid(folder) {
  const nodes = folder ? folder.children : state.albums;
  setTitle(folder ? folder.title : T.albums, T.albumsCount(countAlbums(nodes)));
  cardGrid(Math.max(130, state.tile + 20), nodes.map(n => card({
    href: hashFor((n.folder ? "folder:" : "album:") + n.id), key: n.key, variant: n.folder ? "folder" : "",
    title: n.title || "—", sub: n.folder ? `${T.folder} · ${T.albumsCount(countAlbums(n.children))}` : T.items(n.count),
  })));
  if (folder) expandTo(folder);
}
const countAlbums = nodes => nodes.reduce((s, n) => s + (n.folder ? countAlbums(n.children) : 1), 0);

function expandTo(node) {
  const chain = [];
  for (let n = node; n; n = n.parent) if (n.folder) chain.unshift(n);
  let changed = false;
  for (const n of chain) if (!state.openFolders.has(n.id)) { state.openFolders.add(n.id); changed = true; }
  if (changed) { store.set("folders", [...state.openFolders]); buildNav(); }
}

function showPeopleGrid() {
  setTitle(T.people, fmtNum(state.people.length));
  cardGrid(Math.max(110, state.tile - 10), state.people.map(p => card({
    href: hashFor("person:" + p.id), face: p.face, variant: "round", title: p.name, sub: T.items(p.count),
  })));
}

async function showMemories() {
  const list = await api("api/memories", true);
  if (state.view !== "memories") return;
  setTitle(T.memories, fmtNum(list.length));
  cardGrid(Math.max(240, state.tile * 1.7), list.map(m => card({
    href: hashFor("memory:" + m.id), key: m.key, variant: "wide",
    overlay: [h("strong", {}, m.title), h("span", {}, m.subtitle)], sub: T.items(m.count),
  })));
}

async function showYears() {
  const list = await api("api/years", true);
  if (state.view !== "years") return;
  setTitle(T.years, fmtNum(list.length));
  cardGrid(Math.max(220, state.tile * 1.5), list.map(y => card({
    href: hashFor("months:" + y.year), key: y.key, variant: "wide",
    overlay: [h("strong", { class: "big" }, y.year), y.places ? h("span", {}, y.places) : null], sub: T.items(y.count),
  })));
}

async function showMonths(year) {
  const view = state.view;
  const list = await api("api/months?year=" + encodeURIComponent(year), true);
  if (state.view !== view) return;
  setTitle(year ? `${T.months} ${year}` : T.months, fmtNum(list.length));
  cardGrid(Math.max(240, state.tile * 1.7), list.map(m => card({
    href: hashFor("month:" + m.id), key: m.key, variant: "wide",
    overlay: [h("strong", {}, m.title), m.places ? h("span", {}, m.places) : null], sub: T.items(m.count),
    extra: m.trips.length ? h("div", { class: "trips" }, m.trips.map(t =>
      h("a", { href: hashFor("trip:" + t.id), class: "chip" },
        h("span", {}, t.title), h("small", {}, [t.trip ? T.trip : T.weekend, t.places].filter(Boolean).join(" · "))))) : null,
  })));
}

async function showImports() {
  const list = await api("api/imports", true);
  if (state.view !== "imports") return;
  setTitle(T.imports, fmtNum(list.length));
  cardGrid(Math.max(150, state.tile + 20), list.map(x => card({
    href: hashFor("import:" + x.id), key: x.key,
    title: fmtLocalDateTime.format(new Date(x.date * 1000)),
    sub: [T.items(x.count), x.source].filter(Boolean).join(" · "),
  })));
}

// ---------- places: map + list ----------
let map = null;
function loadAsset(tag, attrs) {
  return new Promise((resolve, reject) => {
    const el = document.createElement(tag);
    Object.assign(el, attrs);
    el.onload = resolve; el.onerror = reject;
    document.head.append(el);
  });
}
let leafletReady = null;
function loadLeaflet() {
  if (!leafletReady) {
    leafletReady = Promise.all([
      loadAsset("link", { rel: "stylesheet", href: "static/vendor/leaflet/leaflet.css" }),
      loadAsset("link", { rel: "stylesheet", href: "static/vendor/markercluster/MarkerCluster.css" }),
      loadAsset("script", { src: "static/vendor/leaflet/leaflet.js" }),
    ]).then(() => loadAsset("script", { src: "static/vendor/markercluster/leaflet.markercluster.js" }));
    leafletReady.catch(() => { leafletReady = null; });
  }
  return leafletReady;
}
function destroyMap() { if (map) { map.remove(); map = null; } }

async function showPlaces() {
  setTitle(T.places, "");
  const [data, cities] = await Promise.all([api("api/assets?view=places", true), api("api/places", true)]);
  if (state.view !== "places") return;
  setTitle(T.places, [cities.length ? `${fmtNum(cities.length)} ${T.places}` : null, T.items(data.items.length)].filter(Boolean).join(" · "));
  // The map's markers open the lightbox, so the map's photos are this view's items.
  state.items = data.items;
  els.showBtn.hidden = !state.items.length;
  const mapEl = h("div", { class: "map", id: "map" }, h("div", { class: "map-msg" }, T.mapLoading));
  els.head.hidden = false;
  els.head.replaceChildren(mapEl);
  cardGrid(Math.max(150, state.tile + 10), cities.map(c => card({
    href: hashFor("place:" + c.id), key: c.key, title: c.city, sub: [c.country, T.items(c.count)].filter(Boolean).join(" · "),
  })));
  try { await loadLeaflet(); } catch { mapEl.replaceChildren(h("div", { class: "map-msg" }, T.mapError)); return; }
  if (state.view !== "places") return;
  mapEl.replaceChildren();
  const L = window.L;
  map = L.map(mapEl, { worldCopyJump: true, zoomControl: true, attributionControl: true });
  L.tileLayer(state.info.map.tiles, { maxZoom: 19, attribution: state.info.map.attribution }).addTo(map);
  const index = new Map(state.items.map((it, i) => [it[0], i]));
  const thumbIcon = (id, n) => L.divIcon({
    className: "map-pin", iconSize: [52, 52], iconAnchor: [26, 26],
    html: `<img src="t/${id}" alt="">${n ? `<b>${n > 999 ? Math.round(n / 1000) + "k" : n}</b>` : ""}`,
  });
  const cluster = L.markerClusterGroup({
    showCoverageOnHover: false, maxClusterRadius: 60,
    iconCreateFunction: c => thumbIcon(c.getAllChildMarkers()[0].options.pk, c.getChildCount()),
  });
  const markers = data.geo.map(([pk, lat, lon]) => {
    const m = L.marker([lat, lon], { pk, icon: thumbIcon(pk, 0) });
    m.on("click", () => openLightbox(index.get(pk)));
    return m;
  });
  cluster.addLayers(markers);
  map.addLayer(cluster);
  if (markers.length) map.fitBounds(cluster.getBounds(), { padding: [30, 30], maxZoom: 12 });
  else map.setView([30, 10], 2);
}

// ------------------------------------------------------------------ fullscreen
// The lightbox goes fullscreen on its own; outside it the whole app does.
const canFullscreen = !!(document.fullscreenEnabled || document.webkitFullscreenEnabled);
const fsElement = () => document.fullscreenElement || document.webkitFullscreenElement || null;
function toggleFullscreen(target, want) {
  const on = !!fsElement();
  if (want === on) return;
  if (on) {
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
  if (show.on && fsElement() === lb.root) show.wasFs = true;
  else if (show.on && show.wasFs) stopSlideshow(); // Esc left the slideshow's fullscreen
  poke();
};
document.addEventListener("fullscreenchange", onFsChange);
document.addEventListener("webkitfullscreenchange", onFsChange);

// ------------------------------------------------------------------ lightbox
const lb = {
  root: $("lightbox"), stage: $("lbStage"), img: $("lbImg"), video: $("lbVideo"), live: $("lbLive"), msg: $("lbMsg"),
  spinner: $("lbSpinner"), date: $("lbDate"), sub: $("lbSub"), info: $("lbInfo"), liveBtn: $("lbLiveBtn"),
  download: $("lbDownload"), zoomBadge: $("lbZoom"), token: 0, pushed: false,
};

function openLightbox(i, push = true) {
  if (i == null || i < 0 || i >= state.items.length) return;
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
  details(id).then(info => {
    if (token === lb.token && info.city) lb.sub.textContent = `${fmtTime.format(d)} · ${[info.city, info.country].filter(Boolean).join(", ")}`;
  }).catch(() => {});
  lb.download.href = "o/" + id;
  lb.msg.hidden = true;
  lb.liveBtn.hidden = !(flags & FLAG_LIVE);
  stopLive();
  resetZoom();
  lb.video.pause(); lb.video.removeAttribute("src"); lb.video.hidden = true;
  lb.video.onended = null;
  lb.img.hidden = false;
  lb.spinner.hidden = false;
  lb.img.classList.remove("shown");

  if (flags & FLAG_VIDEO) {
    lb.img.hidden = true;
    lb.video.hidden = false;
    lb.video.poster = "p/" + id;
    details(id).then(info => {
      if (token !== lb.token) return;
      lb.spinner.hidden = true;
      if (!info.available) { showMsg(T.missing); slideshowNext(token, 3000); return; }
      if (!info.playable) { showMsg(T.notPlayable); slideshowNext(token, 3000); return; }
      lb.video.src = "v/" + id;
      lb.video.play().catch(() => {
        // Autoplay with sound refused: try muted, else just move on in a slideshow.
        lb.video.muted = true;
        lb.video.play().catch(() => slideshowNext(token));
      });
      lb.video.onended = () => slideshowNext(token, 300);
    }).catch(() => { lb.spinner.hidden = true; slideshowNext(token); });
    lb.video.onerror = () => { if (token === lb.token && lb.video.getAttribute("src")) { showMsg(T.notPlayable); slideshowNext(token, 3000); } };
  } else {
    lb.img.onload = () => { if (token === lb.token) { lb.spinner.hidden = true; lb.img.classList.add("shown"); } };
    lb.img.onerror = () => { if (token === lb.token) { lb.spinner.hidden = true; showMsg(T.loadingError); } };
    lb.img.src = "p/" + id;
    const full = new Image();
    full.decoding = "async";
    full.onload = () => { if (token === lb.token) { lb.img.src = full.src; lb.spinner.hidden = true; lb.full = full; } };
    lb.full = null;
    full.src = "f/" + id;
    slideshowNext(token);
  }
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
  stopSlideshow();
  if (fsElement() === lb.root) toggleFullscreen();
  lb.token++;
  lb.video.pause(); lb.video.removeAttribute("src"); lb.video.load();
  stopLive();
  resetZoom();
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
  resetZoom();
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

// ---------- zoom & pan ----------
const zoom = { s: 1, x: 0, y: 0, pointers: new Map(), pinch: null, drag: null };
const MAX_ZOOM = 8;

function applyZoom() {
  lb.img.style.transform = zoom.s === 1 ? "" : `translate(${zoom.x}px, ${zoom.y}px) scale(${zoom.s})`;
  lb.root.classList.toggle("zoomed", zoom.s > 1);
  lb.zoomBadge.hidden = zoom.s <= 1;
  lb.zoomBadge.textContent = `${Math.round(zoom.s * 100)} %`;
}
function resetZoom() { zoom.s = 1; zoom.x = 0; zoom.y = 0; zoom.drag = null; zoom.pinch = null; applyZoom(); }
function clampPan() {
  const r = lb.stage.getBoundingClientRect();
  const w = lb.img.naturalWidth || r.width, hgt = lb.img.naturalHeight || r.height;
  const fit = Math.min(r.width / w, r.height / hgt);
  const maxX = Math.max(0, (w * fit * zoom.s - r.width) / 2), maxY = Math.max(0, (hgt * fit * zoom.s - r.height) / 2);
  zoom.x = Math.min(maxX, Math.max(-maxX, zoom.x));
  zoom.y = Math.min(maxY, Math.max(-maxY, zoom.y));
}
// Zoom to `s`, keeping the point under (cx, cy) (client coordinates) in place.
function zoomTo(s, cx, cy) {
  if (lb.img.hidden) return;
  s = Math.min(MAX_ZOOM, Math.max(1, s));
  const r = lb.stage.getBoundingClientRect();
  const px = cx - (r.left + r.width / 2), py = cy - (r.top + r.height / 2);
  zoom.x = px - (px - zoom.x) * (s / zoom.s);
  zoom.y = py - (py - zoom.y) * (s / zoom.s);
  zoom.s = s;
  if (s === 1) { zoom.x = 0; zoom.y = 0; }
  clampPan();
  applyZoom();
  if (s > 1) { stopLive(); pauseSlideshow(); }
}
function actualSizeZoom() {
  const r = lb.stage.getBoundingClientRect();
  const w = lb.img.naturalWidth, hgt = lb.img.naturalHeight;
  if (!w || !hgt) return 2.5;
  const fit = Math.min(r.width / w, r.height / hgt);
  const actual = 1 / fit;
  return actual > 1.4 ? Math.min(actual, MAX_ZOOM) : 2.5;
}

function bindZoom() {
  const st = lb.stage;
  st.addEventListener("wheel", e => {
    if (lb.img.hidden) return;
    e.preventDefault();
    const factor = Math.exp(-e.deltaY * (e.ctrlKey ? 0.01 : 0.0025));
    zoomTo(zoom.s * factor, e.clientX, e.clientY);
  }, { passive: false });
  st.addEventListener("dblclick", e => {
    if (lb.img.hidden || e.target === lb.video) return;
    zoomTo(zoom.s > 1 ? 1 : actualSizeZoom(), e.clientX, e.clientY);
  });
  st.addEventListener("pointerdown", e => {
    if (lb.img.hidden) return;
    zoom.pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (zoom.pointers.size === 2) {
      const [a, b] = [...zoom.pointers.values()];
      zoom.pinch = { d: Math.hypot(a.x - b.x, a.y - b.y), s: zoom.s };
      zoom.drag = null;
    } else if (zoom.s > 1) {
      zoom.drag = { x: e.clientX, y: e.clientY, ox: zoom.x, oy: zoom.y };
      st.setPointerCapture(e.pointerId);
    }
  });
  st.addEventListener("pointermove", e => {
    if (!zoom.pointers.has(e.pointerId)) return;
    zoom.pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (zoom.pinch && zoom.pointers.size === 2) {
      const [a, b] = [...zoom.pointers.values()];
      const d = Math.hypot(a.x - b.x, a.y - b.y);
      zoomTo(zoom.pinch.s * d / zoom.pinch.d, (a.x + b.x) / 2, (a.y + b.y) / 2);
    } else if (zoom.drag) {
      zoom.x = zoom.drag.ox + e.clientX - zoom.drag.x;
      zoom.y = zoom.drag.oy + e.clientY - zoom.drag.y;
      clampPan();
      applyZoom();
    }
  });
  const end = e => {
    zoom.pointers.delete(e.pointerId);
    if (zoom.pointers.size < 2) zoom.pinch = null;
    if (!zoom.pointers.size) zoom.drag = null;
  };
  st.addEventListener("pointerup", end);
  st.addEventListener("pointercancel", end);
}

// ---------- slideshow ----------
const show = { on: false, paused: false, timer: 0, interval: 4000, wasFs: false };

function startSlideshow(from) {
  if (!state.items.length) return;
  show.on = true; show.paused = false;
  lb.root.classList.add("slideshow");
  document.documentElement.classList.add("slideshow-on");
  if (canFullscreen && fsElement() !== lb.root) {
    if (fsElement()) toggleFullscreen();
    setTimeout(() => toggleFullscreen(lb.root, true), fsElement() ? 150 : 0);
  }
  show.wasFs = false;
  if (lb.root.hidden || from != null) openLightbox(from ?? Math.max(0, state.lbIndex));
  else slideshowNext(lb.token);
  lb.root.classList.add("idle");
}
function stopSlideshow() {
  if (!show.on) return;
  show.on = false; show.paused = false; show.wasFs = false;
  clearTimeout(show.timer);
  lb.root.classList.remove("slideshow");
  document.documentElement.classList.remove("slideshow-on");
}
function pauseSlideshow() { if (show.on) { show.paused = true; clearTimeout(show.timer); lb.root.classList.add("paused"); } }
function resumeSlideshow() {
  if (!show.on) return;
  show.paused = false; lb.root.classList.remove("paused");
  if (lb.video.hidden) slideshowNext(lb.token); else lb.video.play().catch(() => {});
}
// Schedule the next slide for the item shown under `token`.
function slideshowNext(token, delay = show.interval) {
  if (!show.on || show.paused) return;
  clearTimeout(show.timer);
  show.timer = setTimeout(() => {
    if (!show.on || show.paused || token !== lb.token) return;
    if (state.lbIndex >= state.items.length - 1) { stopSlideshow(); return; }
    openLightbox(state.lbIndex + 1);
  }, delay);
}

// ---------- info panel ----------
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
  if (d.city || d.country) {
    row(T.location, [
      d.place ? h("a", { href: hashFor("place:" + d.place) }, [d.city, d.country].filter(Boolean).join(", ")) : [d.city, d.country].filter(Boolean).join(", "),
      d.address ? h("div", { class: "muted" }, d.address) : null,
    ]);
  }
  if (d.lat != null) {
    row(T.coordinates, h("a", {
      class: "map", target: "_blank", rel: "noopener noreferrer",
      href: `https://www.openstreetmap.org/?mlat=${d.lat}&mlon=${d.lon}#map=15/${d.lat}/${d.lon}`,
    }, `${d.lat.toFixed(4)}, ${d.lon.toFixed(4)} ↗`));
  }
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
  row(T.type, [d.selfie ? T.selfie : null, d.portrait ? T.portrait : null].filter(Boolean).join(", "));
  if (d.edited) row(T.edited, T.editedYes);
  row(T.importedFrom, d.importedBy);
  if (d.deleted && d.deletedAt) row(T.deletedOn, fmtLocalDateTime.format(new Date(d.deletedAt * 1000)));
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
  idleTimer = setTimeout(() => { if (!lb.root.hidden && lb.info.hidden) lb.root.classList.add("idle"); }, show.on ? 1200 : 2600);
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
    else if (CARD_VIEWS.has(state.view.split(":")[0])) { const v = state.view; state.view = null; showView(v); }
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
  $("lbShowBtn").addEventListener("click", () => {
    if (!show.on) startSlideshow();
    else if (show.paused) resumeSlideshow();
    else pauseSlideshow();
  });
  els.showBtn.addEventListener("click", () => startSlideshow(Math.max(0, firstVisibleIndex() ?? 0)));
  lb.liveBtn.addEventListener("click", () => (lb.live.hidden ? playLive() : stopLive()));
  lb.root.addEventListener("mousemove", poke);
  lb.info.addEventListener("click", e => { if (e.target.closest("a[href^='#']")) closeLightbox(false); });
  if (store.get("info", false)) { lb.info.hidden = false; lb.root.classList.add("info"); }
  bindZoom();

  let tx = null, ty = null;
  lb.stage.addEventListener("touchstart", e => { if (e.touches.length === 1 && zoom.s === 1) { tx = e.touches[0].clientX; ty = e.touches[0].clientY; } else tx = null; }, { passive: true });
  lb.stage.addEventListener("touchend", e => {
    if (tx == null || zoom.s > 1) { tx = null; return; }
    const dx = e.changedTouches[0].clientX - tx, dy = e.changedTouches[0].clientY - ty;
    tx = null;
    if (Math.abs(dx) > 50 && Math.abs(dx) > Math.abs(dy) * 1.5) step(dx < 0 ? 1 : -1);
    else if (dy > 90 && Math.abs(dy) > Math.abs(dx) * 1.5) closeLightbox();
    poke();
  });
  lb.stage.addEventListener("click", e => {
    if (e.target === lb.video) return;
    if (show.on) { stopSlideshow(); return; }
    if (window.matchMedia("(hover: none)").matches) lb.root.classList.toggle("idle");
  });

  document.addEventListener("keydown", e => {
    if (e.target === els.search || e.altKey || e.metaKey || e.ctrlKey) return;
    if (lb.root.hidden) {
      if (e.key === "/") { e.preventDefault(); els.search.focus(); }
      else if ((e.key === "f" || e.key === "F") && canFullscreen) toggleFullscreen();
      else if ((e.key === "s" || e.key === "S") && state.items.length && !els.showBtn.hidden) startSlideshow(Math.max(0, firstVisibleIndex() ?? 0));
      return;
    }
    switch (e.key) {
      case "ArrowRight": step(1); break;
      case "ArrowLeft": step(-1); break;
      case "Escape":
        if (show.on) stopSlideshow();
        else if (zoom.s > 1) resetZoom();
        else closeLightbox();
        break;
      case "i": toggleInfo(); break;
      case "f": case "F": if (canFullscreen) toggleFullscreen(lb.root); break;
      case "s": case "S": show.on ? stopSlideshow() : startSlideshow(); break;
      case "+": case "=": zoomTo(zoom.s * 1.5, innerWidth / 2, innerHeight / 2); break;
      case "-": zoomTo(zoom.s / 1.5, innerWidth / 2, innerHeight / 2); break;
      case "0": resetZoom(); break;
      case " ":
        e.preventDefault();
        if (show.on) { show.paused ? resumeSlideshow() : (pauseSlideshow(), lb.video.hidden || lb.video.pause()); }
        else if (!lb.video.hidden) lb.video.paused ? lb.video.play() : lb.video.pause();
        else if (!lb.liveBtn.hidden) lb.live.hidden ? playLive() : stopLive();
        break;
      default: return;
    }
    poke();
  });
}

boot();
