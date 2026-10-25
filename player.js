/* player.js — страница фильма + плеер с переключаемыми провайдерами.
   Подключается ПОСЛЕ основного inline-скрипта index.html: использует его
   $, $$, tmdb, IMG, tint, genreColors, defColors, spin, toggle и переопределяет play(). */
(() => {
'use strict';

/* ================= КОНФИГУРАЦИЯ ================= */
const PLAYER_CONFIG = {
  // Шаблон универсального iframe-провайдера. Плейсхолдеры:
  //   {id}      — первый доступный ID из idPriority
  //   {imdb_id} {kp_id} {tmdb_id} — конкретный ID
  iframeTemplate: 'https://example.com/{id}', // ЗАГЛУШКА — подставьте свой URL
  idPriority: ['kp', 'imdb'],                 // что подставлять в {id}
  kpApiKey: '',                               // токен kinopoisk.dev; нужен только для kp_id
  iframeSandbox: '',                          // напр. 'allow-scripts allow-same-origin allow-forms'
  defaultProvider: 'archive',
};

/* ================= УТИЛИТЫ ================= */
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const jget = async (url, opt) => { const r = await fetch(url, opt); if (!r.ok) throw new Error(r.status); return r.json(); };
const norm = s => String(s || '').toLowerCase().replace(/[^\p{L}\p{N}]+/gu, ' ').trim();

/* IMDb → Кинопоиск ID (через kinopoisk.dev, нужен ключ) */
const kpCache = new Map();
async function resolveKpId(imdb) {
  if (!PLAYER_CONFIG.kpApiKey || !imdb) return null;
  if (kpCache.has(imdb)) return kpCache.get(imdb);
  let id = null;
  try {
    const d = await jget(`https://api.kinopoisk.dev/v1.4/movie?externalId.imdb=${encodeURIComponent(imdb)}&selectFields=id&limit=1`,
      { headers: { 'X-API-KEY': PLAYER_CONFIG.kpApiKey } });
    id = d.docs?.[0]?.id ?? null;
  } catch {}
  kpCache.set(imdb, id);
  return id;
}

/* ================= УНИВЕРСАЛЬНЫЙ IFRAME-ОБРАБОТЧИК ================= */
function buildIframeUrl(template, ids) {
  if (!/^https?:\/\//i.test(template)) return null;
  const byType = { kp: ids.kp, imdb: ids.imdb, tmdb: ids.tmdb };
  const vals = {
    id: PLAYER_CONFIG.idPriority.map(k => byType[k]).find(Boolean),
    imdb_id: ids.imdb, kp_id: ids.kp, tmdb_id: ids.tmdb,
  };
  let missing = false;
  const url = template.replace(/\{(id|imdb_id|kp_id|tmdb_id)\}/g, (_, k) => {
    if (!vals[k]) { missing = true; return ''; }
    return encodeURIComponent(vals[k]);
  });
  return missing ? null : url;
}

/* Фабрика: добавить ещё один iframe-источник = ещё одна строка в providers */
const iframeProvider = ({ key, label, template }) => ({
  key, label,
  async resolve(ctx) {
    await ctx.loadIds();
    const src = buildIframeUrl(template, ctx.ids);
    return src ? { kind: 'iframe', src }
               : { error: 'Для этого фильма не нашлось нужного ID (imdb_id / kp_id).' };
  },
});

/* ================= INTERNET ARCHIVE ================= */
async function resolveArchive({ details: d }) {
  const titles = [...new Set([d.original_title, d.title].filter(Boolean))];
  for (const t of titles) {
    const q = `title:("${t.replace(/"/g, '')}") AND mediatype:movies AND collection:feature_films`;
    const s = await jget(`https://archive.org/advancedsearch.php?q=${encodeURIComponent(q)}&fl[]=identifier&fl[]=title&rows=10&output=json`);
    const hit = (s.response?.docs || []).find(x => norm(x.title) === norm(t));
    if (!hit) continue;
    const id = encodeURIComponent(hit.identifier);
    const embed = `https://archive.org/embed/${id}`;
    const meta = await jget(`https://archive.org/metadata/${id}`);
    const mp4 = (meta.files || []).filter(f => /\.mp4$/i.test(f.name))
      .sort((a, b) => (a.format === 'h.264' ? 0 : 1) - (b.format === 'h.264' ? 0 : 1) || (+b.size || 0) - (+a.size || 0))[0];
    return mp4
      ? { kind: 'video', src: `https://archive.org/download/${id}/${mp4.name.split('/').map(encodeURIComponent).join('/')}`, fallback: embed }
      : { kind: 'iframe', src: embed };
  }
  return { error: 'Этого фильма нет в Internet Archive (там в основном общественное достояние). Переключитесь на другой источник.' };
}

/* ================= МАССИВ ПРОВАЙДЕРОВ ================= */
const providers = [
  { key: 'archive', label: 'Internet Archive', resolve: resolveArchive },
  iframeProvider({ key: 'iframe', label: 'Кастомный iframe', template: PLAYER_CONFIG.iframeTemplate }),
  { key: 'trailer', label: 'Трейлер', async resolve({ details: d }) {
      const v = (d.videos?.results || []).filter(x => x.site === 'YouTube' && x.type === 'Trailer');
      const t = v.find(x => x.iso_639_1 === 'ru') || v[0];
      return t ? { kind: 'iframe', src: `https://www.youtube-nocookie.com/embed/${encodeURIComponent(t.key)}` }
               : { error: 'Трейлер не найден.' };
  } },
];

/* ================= СТРАНИЦА ФИЛЬМА ================= */
const main = $('main'), vd = $('#vd'), vw = $('#pm .vw'), vc = $('#pm .vc'), ac = $('#ac'), bf = $('#bf'), pp = $('#pp');
const page = Object.assign(document.createElement('section'), { className: 'mp', id: 'mp', hidden: true });
main.after(page);

// Старые элементы плеера хранятся в «парковке» и переезжают на страницу при каждом показе.
// Так сохраняются все их обработчики (перемотка, громкость, время и т.д.).
const stash = Object.assign(document.createElement('div'), { hidden: true });
document.body.append(stash);
const frame = document.createElement('iframe');
frame.setAttribute('allow', 'fullscreen; autoplay; picture-in-picture; encrypted-media');
frame.allowFullscreen = true;
frame.referrerPolicy = 'origin';
frame.title = 'Видеоплеер';
vw.append(frame);
stash.append(vw, vc, ac);

let box = null, token = 0, selToken = 0, scrollY0 = 0, inApp = false, ctx = null;

function useFrame(src) {
  vd.pause(); vd.removeAttribute('src'); vd.load();
  vd.hidden = true; vc.hidden = true; frame.hidden = false;
  PLAYER_CONFIG.iframeSandbox ? frame.setAttribute('sandbox', PLAYER_CONFIG.iframeSandbox) : frame.removeAttribute('sandbox');
  frame.src = src;
  bf.classList.remove('on');
}
function useVideo(r) {
  frame.hidden = true; frame.src = 'about:blank';
  vd.hidden = false; vc.hidden = false;
  vd.removeAttribute('crossorigin'); vd.loop = false; vd.preload = 'metadata';
  vd.dataset.fb = r.fallback || '';
  vd.src = r.src; vd.load();
  pp.textContent = 'Играть';
  spin();
}
function stopAll() {
  vd.pause(); frame.src = 'about:blank';
}

async function select(key) {
  const p = providers.find(x => x.key === key);
  if (!p || !ctx) return;
  const t = ++selToken;
  try { localStorage.setItem('cs_provider', key); } catch {}
  $$('.pl-sw .chip', page).forEach(b => { const on = b.dataset.k === key; b.classList.toggle('on', on); b.setAttribute('aria-selected', on); });
  stopAll(); spin();
  let r;
  try { r = await p.resolve(ctx); } catch { r = { error: 'Источник не отвечает. Попробуйте другой.' }; }
  if (t !== selToken) return;
  if (r.error) { frame.hidden = true; vd.hidden = true; vc.hidden = true; bf.innerHTML = esc(r.error); bf.classList.add('on'); return; }
  r.kind === 'video' ? useVideo(r) : useFrame(r.src);
}

// Если прямой mp4 не загрузился — показать официальный embed Internet Archive
vd.addEventListener('error', () => { const fb = vd.dataset.fb; if (fb && !vd.hidden) { vd.dataset.fb = ''; useFrame(fb); } });
vd.addEventListener('loadedmetadata', () => bf.classList.remove('on'));

function render(d, wantTrailer) {
  const year = (d.release_date || '').slice(0, 4);
  const genres = (d.genres || []).map(g => g.name);
  const rt = d.runtime ? `${Math.floor(d.runtime / 60)}ч ${d.runtime % 60}м` : '';
  const bg = d.backdrop_path ? `${IMG}/w1280${d.backdrop_path}` : '';
  const ids = { tmdb: d.id, imdb: d.external_ids?.imdb_id || d.imdb_id || null, kp: undefined };
  ctx = { details: d, ids, async loadIds() { if (ids.kp === undefined) ids.kp = await resolveKpId(ids.imdb); return ids; } };

  const [a, b] = genreColors[d.genres?.[0]?.id] || defColors;
  tint({ a, b });
  document.title = `${d.title} — CineSearch`;

  page.innerHTML = `
    <div class="mp-bg">${bg ? `<img src="${bg}" alt="">` : ''}</div>
    <div class="wrap">
      <button class="btn o sm" id="mp-back">← Назад</button>
      <div class="mp-top">
        ${d.poster_path ? `<img class="mp-poster" src="${IMG}/w500${d.poster_path}" alt="">` : '<div class="mp-poster"></div>'}
        <div class="mp-info">
          <h1>${esc(d.title)}</h1>
          ${d.tagline ? `<p class="sub">${esc(d.tagline)}</p>` : ''}
          <div class="meta"><span class="rt">★ ${d.vote_average ? d.vote_average.toFixed(1) : '—'} TMDB</span>${year ? `<span>${year}</span>` : ''}${rt ? `<span>${rt}</span>` : ''}${ids.imdb ? `<span>${esc(ids.imdb)}</span>` : ''}</div>
          <div class="chips">${genres.map(g => `<span class="pill">${esc(g)}</span>`).join('')}</div>
          <p class="mp-ov">${esc(d.overview || 'Описание отсутствует.')}</p>
        </div>
      </div>
      <div class="pl">
        <div class="pl-sw" role="tablist" aria-label="Источник видео">${providers.map(p => `<button class="chip" role="tab" data-k="${p.key}">${esc(p.label)}</button>`).join('')}</div>
        <div class="pl-box"></div>
      </div>
    </div>`;

  box = $('.pl-box', page);
  box.append(vw, vc);
  $('.pl', page).prepend(ac);
  $('#mp-back').onclick = () => inApp ? history.back() : (location.hash = '#top');
  $('.pl-sw', page).onclick = e => { const k = e.target.closest('[data-k]')?.dataset.k; if (k) select(k); };

  let saved = null; try { saved = localStorage.getItem('cs_provider'); } catch {}
  const first = wantTrailer ? 'trailer' : (providers.some(p => p.key === saved && p.key !== 'trailer') ? saved : PLAYER_CONFIG.defaultProvider);
  select(first);
}

async function openMovie(id, wantTrailer) {
  const t = ++token;
  stopAll(); stash.append(vw, vc, ac);
  main.hidden = true; page.hidden = false; scrollTo(0, 0);
  page.innerHTML = '<div class="loading" style="min-height:60vh"><div class="sp"></div></div>';
  let d;
  try { d = await tmdb(`/movie/${id}`, { append_to_response: 'external_ids,videos', include_video_language: 'ru,en,null' }); }
  catch { if (t === token) page.innerHTML = '<div class="load-err"><b>Не удалось загрузить фильм</b>Проверьте подключение к интернету</div>'; return; }
  if (t === token) render(d, wantTrailer);
}

function closeMovie() {
  token++; selToken++;
  stopAll(); stash.append(vw, vc, ac);
  page.hidden = true; main.hidden = false;
  document.title = 'CineSearch — Кинотеатр нового поколения';
  const target = location.hash.length > 1 && document.getElementById(location.hash.slice(1));
  target ? target.scrollIntoView() : scrollTo(0, scrollY0);
  M?.length && tint(M[cur]);
}

function route() {
  const m = location.hash.match(/^#\/movie\/(\d+)(\/trailer)?$/);
  if (m) openMovie(+m[1], !!m[2]);
  else if (!page.hidden) closeMovie();
}

/* ================= ПОДКЛЮЧЕНИЕ К САЙТУ ================= */
// Все места сайта (карточки, hero, поиск, «Трейлер») вызывают play(movie, trailer)
window.play = (m, trailer) => {
  if (!m) return;
  inApp = true; scrollY0 = scrollY;
  location.hash = `#/movie/${m.id}${trailer ? '/trailer' : ''}`;
};
$('#fs').onclick = () => document.fullscreenElement ? document.exitFullscreen() : box?.requestFullscreen?.();
document.addEventListener('keydown', e => {
  if (page.hidden || e.code !== 'Space' || vd.hidden || $$('.md.open').length || /INPUT|BUTTON|IFRAME/.test(e.target.tagName)) return;
  e.preventDefault(); toggle();
});
addEventListener('hashchange', route);
route();
})();
