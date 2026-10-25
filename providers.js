/* CineSearch — конфиг и источники видео для плеера.
   Провайдер: { key, label, resolve(movie) -> { src, sandbox?, note? } | { error } }
   movie: { id (TMDB), title, orig, year, imdb_id, videos } */
(() => {
const CONFIG = {
  TMDB_KEY: 'e1a265c9540a7704194b117e4ca0021b',
  KP_API_KEY: '', // токен kinopoisk.dev, нужен только если шаблону нужен kp_id (виден посетителям — лучше проксировать)
  iframe: {
    label: 'Iframe',
    template: 'https://example.com/{id}', // заглушка. Плейсхолдеры: {id} {imdb_id} {kp_id} {tmdb_id}
    idType: 'imdb', // что подставлять вместо {id}: 'imdb' | 'kp'
    sandbox: 'allow-scripts allow-same-origin allow-presentation allow-forms' // '' — без sandbox
  }
};

/* kp_id по imdb_id через kinopoisk.dev (TMDB Кинопоиск не отдаёт) */
const kpCache = {};
async function kpId(m) {
  if (!m.imdb_id || !CONFIG.KP_API_KEY) return null;
  if (!(m.imdb_id in kpCache)) {
    const r = await fetch(
      `https://api.kinopoisk.dev/v1.4/movie?limit=1&externalId.imdb=${encodeURIComponent(m.imdb_id)}`,
      { headers: { 'X-API-KEY': CONFIG.KP_API_KEY } }
    );
    kpCache[m.imdb_id] = r.ok ? (await r.json()).docs?.[0]?.id ?? null : null;
  }
  return kpCache[m.imdb_id];
}

/* Универсальный iframe: берёт шаблон из CONFIG.iframe и подставляет imdb_id / kp_id / tmdb_id */
const iframe = {
  key: 'iframe',
  label: CONFIG.iframe.label,
  async resolve(m) {
    const c = CONFIG.iframe;
    const idKey = n => (n === 'id' ? c.idType : n.replace(/_id$/, ''));
    const names = [...c.template.matchAll(/\{(\w+)\}/g)].map(x => idKey(x[1]));
    const ids = { imdb: m.imdb_id, tmdb: m.id };
    if (names.includes('kp')) ids.kp = await kpId(m);
    const bad = names.find(k => !ids[k]);
    if (bad) {
      return { error: bad === 'kp' && !CONFIG.KP_API_KEY
        ? 'Для {kp_id} укажите KP_API_KEY в providers.js.'
        : `Не нашёл ${bad}_id для этого фильма.` };
    }
    let url;
    try { url = new URL(c.template.replace(/\{(\w+)\}/g, (_, n) => encodeURIComponent(ids[idKey(n)]))); }
    catch { return { error: 'Некорректный шаблон URL в providers.js.' }; }
    if (url.protocol !== 'https:') return { error: 'Разрешены только https-адреса.' };
    return { src: url.href, sandbox: c.sandbox };
  }
};

/* Internet Archive: поиск по названию, встраивание через archive.org/embed */
const archive = {
  key: 'archive',
  label: 'Internet Archive',
  async resolve(m) {
    const t = (m.orig || m.title).replace(/["\\]/g, ' ').trim();
    const p = new URLSearchParams({ q: `title:("${t}") AND mediatype:movies`, rows: '5', output: 'json' });
    ['identifier', 'title', 'year'].forEach(f => p.append('fl[]', f));
    p.append('sort[]', 'downloads desc');
    const r = await fetch('https://archive.org/advancedsearch.php?' + p);
    if (!r.ok) throw new Error(r.status);
    const docs = (await r.json()).response?.docs || [];
    const hit = docs.find(d => { const y = parseInt(d.year); return !m.year || isNaN(y) || Math.abs(y - m.year) <= 1; });
    return hit
      ? { src: 'https://archive.org/embed/' + encodeURIComponent(hit.identifier), note: `Internet Archive: «${hit.title}»` }
      : { error: 'В Internet Archive этого фильма нет: там в основном общественное достояние.' };
  }
};

/* Трейлер из TMDB (YouTube) — для кнопки «Трейлер» на главной */
const trailer = {
  key: 'trailer',
  label: 'Трейлер',
  async resolve(m) {
    const yt = m.videos.filter(v => v.site === 'YouTube');
    const tr = yt.filter(v => v.type === 'Trailer');
    const t = tr.find(v => v.iso_639_1 === 'ru') || tr[0] || yt[0];
    return t
      ? { src: `https://www.youtube-nocookie.com/embed/${encodeURIComponent(t.key)}`, note: 'Трейлер с YouTube' }
      : { error: 'Трейлер не найден.' };
  }
};

window.CineProviders = { CONFIG, PROVIDERS: [archive, iframe, trailer] };
})();
