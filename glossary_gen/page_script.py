"""
page_script.py -- the glossary page's client-side JavaScript (search/
filter, and the in-game-screenshot full-page modal viewer), as a plain
string.

Unlike PAGE_CSS, this never goes through .format() (it has no
per-generation placeholders of its own), so it's kept as ordinary JS
with single braces -- no {{ }} escaping needed.
"""

PAGE_SCRIPT = """
const search = document.getElementById('search');
const fileGroups = Array.from(document.querySelectorAll('.file-group'));
const filterInputs = Array.from(document.querySelectorAll('.chip input[data-filter-group]'));
const clearButton = document.getElementById('clear-filters');

function checkedValues(group) {
  return filterInputs
    .filter(el => el.dataset.filterGroup === group && el.checked)
    .map(el => el.value);
}

function applyFilter() {
  const q = search.value.trim().toLowerCase();
  const affSel = checkedValues('affiliation');
  const classSel = checkedValues('class');
  const buildSel = checkedValues('build');
  const kindSel = checkedValues('unitkind');
  const eraSel = checkedValues('era');

  allRows.forEach(r => {
    const nameMatch = !q || r.dataset.name.includes(q);
    const rowAffs = (r.dataset.affiliations || '').split(' ');
    const affMatch = affSel.length === 0 || affSel.some(v => rowAffs.includes(v));
    const rowClasses = (r.dataset.classes || '').split(' ');
    const classMatch = classSel.length === 0 || classSel.some(v => rowClasses.includes(v));
    const rowBuild = (r.dataset.build || '').split(' ');
    const buildMatch = buildSel.length === 0 || buildSel.some(v => rowBuild.includes(v));
    const kindMatch = kindSel.length === 0 || kindSel.includes(r.dataset.unitKind);
    const rowEras = (r.dataset.era || '').split(' ');
    const eraMatch = eraSel.length === 0 || eraSel.some(v => rowEras.includes(v));
    // Easter eggs stay hidden (even from search) until their own
    // Unit Type filter is ticked, so they remain a surprise.
    const eggOk = r.dataset.unitKind !== 'easteregg' || kindSel.includes('easteregg');
    const match = nameMatch && affMatch && classMatch && buildMatch && kindMatch && eraMatch && eggOk;
    r.style.display = match ? '' : 'none';
  });
  fileGroups.forEach(g => {
    const anyVisible = Array.from(g.querySelectorAll('.row')).some(r => r.style.display !== 'none');
    g.style.display = anyVisible ? '' : 'none';
  });
}

// ---------------------------------------------------------------
// Sort By. "Default" is the generated order, grouped by source file.
// Alphabetical / Unit Class move every card into one flat list
// (#sorted-rows), ordered by data-sort-name or data-class-rank
// (Fighter, Bomber, Gunship, Corvette, Frigate, Capital, then
// anything else; alphabetical within a class). Switching back to
// Default returns each card to its original place.
// ---------------------------------------------------------------
const allRows = Array.from(document.querySelectorAll('.file-group .row'));
const homes = new Map(allRows.map(r => [r, { parent: r.parentNode, next: r.nextSibling }]));
const groupsEl = document.getElementById('groups');
const sortSelect = document.getElementById('sort-select');
let sortedWrap = null;

function applySort() {
  const mode = sortSelect ? sortSelect.value : 'default';
  if (mode === 'default') {
    if (sortedWrap) {
      // Put cards back in their original order, last first so each
      // "next sibling" reference is already in place.
      allRows.slice().reverse().forEach(r => {
        const h = homes.get(r);
        h.parent.insertBefore(r, h.next && h.next.parentNode === h.parent ? h.next : null);
      });
      sortedWrap.remove();
      sortedWrap = null;
    }
    fileGroups.forEach(g => g.classList.remove('sorted-away'));
  } else {
    if (!sortedWrap) {
      sortedWrap = document.createElement('div');
      sortedWrap.className = 'file-group sorted-rows';
      sortedWrap.innerHTML = '<div class="rows"></div>';
      groupsEl.prepend(sortedWrap);
    }
    const byName = (a, b) => a.dataset.sortName.localeCompare(b.dataset.sortName);
    const byClass = (a, b) => (Number(a.dataset.classRank) - Number(b.dataset.classRank)) || byName(a, b);
    // Tech level: lowest first; unbuildable cards (999) last; ties by
    // class order, then name.
    const byTech = (a, b) => (Number(a.dataset.tech) - Number(b.dataset.tech)) || byClass(a, b);
    const cmp = mode === 'class' ? byClass : mode === 'tech' ? byTech : byName;
    const list = sortedWrap.querySelector('.rows');
    allRows.slice().sort(cmp).forEach(r => list.appendChild(r));
    fileGroups.forEach(g => g.classList.add('sorted-away'));
  }
  // Group visibility depends on which cards each group holds now.
  applyFilter();
}
if (sortSelect) sortSelect.addEventListener('change', applySort);

search.addEventListener('input', applyFilter);
filterInputs.forEach(el => {
  el.addEventListener('change', () => {
    el.closest('.chip').classList.toggle('active', el.checked);
    applyFilter();
  });
});
applyFilter();

if (clearButton) {
  clearButton.addEventListener('click', () => {
    filterInputs.forEach(el => {
      el.checked = false;
      el.closest('.chip').classList.remove('active');
    });
    applyFilter();
  });
}

// Full-page modal viewer for in-game screenshot thumbnails (see
// render_group_row's in_game_images_html) -- ONE shared overlay for
// the whole page (#image-modal in page_template.PAGE_TEMPLATE), not
// one per row, since only a single screenshot is ever being viewed at
// a time regardless of which card's thumbnail opened it. A thumbnail's
// onclick calls openImageModal(src) directly with its own image path.
const imageModal = document.getElementById('image-modal');
const imageModalImg = document.getElementById('image-modal-img');

function openImageModal(src) {
  if (!imageModal || !imageModalImg) return;
  imageModalImg.setAttribute('src', src);
  imageModal.classList.add('open');
}

function closeImageModal() {
  if (!imageModal) return;
  imageModal.classList.remove('open');
  if (imageModalImg) imageModalImg.setAttribute('src', '');
}

if (imageModal) {
  // Clicking anywhere on the dark backdrop closes it; clicking the
  // image itself (or the close button, which stops its own event)
  // must NOT close it, so this listener only fires for a click whose
  // target IS the overlay element, not something inside it.
  imageModal.addEventListener('click', (e) => {
    if (e.target === imageModal) closeImageModal();
  });
}
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') closeImageModal();
});

// ---------------------------------------------------------------
// Galactic Map (see galaxy.py / html_output.render_map_box). The page
// embeds one JSON blob (#galaxy-data): every planet once, and per
// campaign set-up (= campaign file) its planets, trade routes, this
// faction's starting planets, whether the faction is in it at all,
// its max tech level, and where this page's units start in play.
// Each card's .map-box carries its rules in data-map:
//   [[requiredPlanetNames|null, minSpaceStation, needsSlot, tech|null, buildable], ...]
// and its variant Names in data-names. Every map has its own campaign
// menu; the page-level menu (#campaign-select) sets all of them.
// Maps are drawn lazily as they scroll into view.
// ---------------------------------------------------------------
(function () {
  const dataEl = document.getElementById('galaxy-data');
  const select = document.getElementById('campaign-select');
  if (!dataEl || !select) return;
  const GD = JSON.parse(dataEl.textContent);
  const P = GD.planets; // [name, label, x, y, maxSpaceBase, spaceSlots]
  const SVGNS = 'http://www.w3.org/2000/svg';
  const STORE_KEY = 'cwhGlossaryCampaign';

  function shortFile(f) {
    return f.replace(/^Campaigns_Imperial_Web_Way_?/i, '').replace(/\\.xml$/i, '');
  }
  const ERA_SHORT = { 'Clone Wars': 'CW', 'Galactic Civil War': 'GCW', 'Rise of the Empire': 'RotE' };
  function setupLabel(s) { return s.label + ' — ' + shortFile(s.file) + ' (' + (ERA_SHORT[s.era] || s.era) + ')'; }

  GD.setups.forEach((s, i) => {
    const o = document.createElement('option');
    o.value = String(i);
    o.textContent = setupLabel(s) + ' (' + s.p.length + ' planets)';
    select.appendChild(o);
  });
  let pageSetup = GD.default;
  try {
    const saved = localStorage.getItem(STORE_KEY);
    const idx = GD.setups.findIndex(s => s.id === saved);
    if (idx >= 0) pageSetup = idx;
  } catch (e) { /* storage unavailable -- keep default */ }
  select.value = String(pageSetup);

  // Per set-up geometry, computed once: view box and route paths.
  const geom = {};
  function geometry(i) {
    if (geom[i]) return geom[i];
    const s = GD.setups[i];
    let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
    s.p.forEach(pi => {
      const x = P[pi][2], y = -P[pi][3];
      minX = Math.min(minX, x); maxX = Math.max(maxX, x);
      minY = Math.min(minY, y); maxY = Math.max(maxY, y);
    });
    const pad = 25;
    const w = (maxX - minX) + pad * 2, h = (maxY - minY) + pad * 2;
    const size = Math.max(w, h);
    const vb = [minX - pad - (size - w) / 2, minY - pad - (size - h) / 2, size, size];
    let main = '', minor = '';
    s.e.forEach(([a, b, isMain]) => {
      const seg = 'M' + P[a][2] + ' ' + (-P[a][3]) + 'L' + P[b][2] + ' ' + (-P[b][3]);
      if (isMain) main += seg; else minor += seg;
    });
    geom[i] = { vb, main, minor, r: size / 90, own: new Set(s.own), inSetup: new Set(s.p) };
    return geom[i];
  }

  function circles(list, r) {
    let d = '';
    list.forEach(pi => {
      const x = P[pi][2], y = -P[pi][3];
      d += 'M' + (x - r) + ' ' + y + 'a' + r + ' ' + r + ' 0 1 0 ' + (2 * r) + ' 0a' + r + ' ' + r + ' 0 1 0 ' + (-2 * r) + ' 0';
    });
    return d;
  }
  function path(d, cls) {
    const el = document.createElementNS(SVGNS, 'path');
    el.setAttribute('d', d || 'M0 0');
    el.setAttribute('class', cls);
    return el;
  }

  // Can this card be recruited / does it start in play, in set-up i?
  // Returns {ok: [planet idx], starts: [planet idx], reason: string|null}.
  function evaluate(box, i) {
    const s = GD.setups[i];
    const rules = box._rules || (box._rules = JSON.parse(box.dataset.map));
    const names = box._names || (box._names = JSON.parse(box.dataset.names || '[]'));
    const g = geometry(i);
    const starts = [];
    names.forEach(n => (s.start[n] || []).forEach(pi => { if (!starts.includes(pi)) starts.push(pi); }));
    const buildable = rules.filter(r => r[4]);
    let reason = null, ok = [];
    // A card's Era tag (data-eras) must match the campaign's era,
    // unless the card is "All".
    const eras = box._eras || (box._eras = JSON.parse(box.dataset.eras || '["All"]'));
    if (s.present === false) {
      reason = "this faction isn't in this campaign.";
    } else if (!eras.includes('All') && !eras.some(e => s.eras.includes(e))) {
      reason = 'it\u2019s a ' + eras.join(' / ') + ' unit; this campaign is set in the ' + s.era + ' era.';
    } else if (!buildable.length) {
      reason = "it can't be built (it may still start in play).";
    } else {
      const techOk = buildable.filter(r => r[3] === null || s.maxTech == null || r[3] <= s.maxTech);
      if (!techOk.length) {
        reason = 'needs tech ' + Math.min(...buildable.map(r => r[3])) + '; this campaign stops at tech ' + s.maxTech + '.';
      } else {
        s.p.forEach(pi => {
          const [name, , , , space, slots] = P[pi];
          if (techOk.some(([planets, minSpace, needsSlot]) =>
              (!planets || planets.includes(name)) && space >= minSpace && (!needsSlot || slots > 0))) ok.push(pi);
        });
        if (!ok.length) {
          const wanted = techOk.some(r => r[0] && r[0].some(n => P.some((p, pi) => p[0] === n && g.inSetup.has(pi))));
          reason = techOk.every(r => r[0]) && !wanted
            ? "its required planets aren't in this campaign."
            : 'no planet in this campaign meets its requirements.';
        }
      }
    }
    return { ok, starts, reason };
  }

  function fillCardMenu(box) {
    const menu = box.querySelector('.map-campaign');
    if (!menu || menu.options.length) return;
    GD.setups.forEach((s, i) => {
      const r = evaluate(box, i);
      const o = document.createElement('option');
      o.value = String(i);
      const mark = r.ok.length ? '✓' : (r.starts.length ? '★' : '✗');
      // File name first, so a narrow menu still shows which file it is.
      o.textContent = mark + ' ' + shortFile(s.file) + ' \u00b7 ' + s.label + ' (' + (ERA_SHORT[s.era] || s.era) + ')';
      menu.appendChild(o);
    });
    menu.addEventListener('change', () => { box.dataset.setup = menu.value; draw(box); });
  }

  function draw(box) {
    fillCardMenu(box);
    const i = box.dataset.setup !== undefined ? Number(box.dataset.setup) : pageSetup;
    const menu = box.querySelector('.map-campaign');
    if (menu) menu.value = String(i);
    if (box.dataset.drawn === String(i)) return;
    box.dataset.drawn = String(i);
    const s = GD.setups[i];
    const g = geometry(i);
    const { ok, starts, reason } = evaluate(box, i);
    const okSet = new Set(ok);
    // Upgrade requirements (data-upg): [{p: [planet Names], label}],
    // drawn red. A marker whose planets aren't in this campaign is
    // reported in the caption instead.
    const upg = box._upg || (box._upg = JSON.parse(box.dataset.upg || '[]'));
    const inSetup = new Set(s.p);
    const upgHits = [], upgMissing = [];
    upg.forEach(m => {
      const idx = s.p.filter(pi => m.p.includes(P[pi][0]));
      if (idx.length) upgHits.push({ label: m.label, idx });
      else upgMissing.push(m.label);
    });
    const upgPlanets = [...new Set(upgHits.flatMap(h => h.idx))];
    const svg = box.querySelector('svg');
    svg.setAttribute('viewBox', g.vb.join(' '));
    svg.replaceChildren(
      path(g.minor, 'gm-route'),
      path(g.main, 'gm-route gm-route-main'),
      path(circles(s.p.filter(pi => !okSet.has(pi)), g.r * 0.75), 'gm-no'),
      // A soft halo when only a handful of planets qualify, so a single
      // recruitable world doesn't get lost among 140 faint dots.
      path(ok.length <= 12 ? circles(ok, g.r * 3.2) : '', 'gm-halo'),
      path(circles(ok, g.r * 1.15), 'gm-ok'),
      path(circles(starts, g.r * 1.3), 'gm-start'),
      path(circles(s.p.filter(pi => g.own.has(pi)), g.r * 1.9), 'gm-own'),
      path(circles(upgPlanets, g.r * 2.6), 'gm-upg')
    );
    box._upgSet = new Set(upgPlanets);
    box.classList.toggle('map-box--unavailable', !ok.length && !starts.length);
    box._planets = s.p;
    box._ok = okSet;
    box._starts = new Set(starts);
    const cap = box.querySelector('.map-caption');
    let text;
    if (ok.length) {
      const names = ok.length <= 6 ? ': ' + ok.map(pi => P[pi][1]).join(', ') : '';
      text = 'Recruitable at ' + ok.length + ' of ' + s.p.length + ' planets' + names + '.';
    } else {
      text = 'Not recruitable: ' + (reason || '');
    }
    if (starts.length) {
      text += ' Starts in play at ' + starts.map(pi => P[pi][1]).join(', ') + '.';
    }
    upgHits.forEach(h => {
      text += ' Upgrade requirement (' + h.label + '): only at ' + h.idx.map(pi => P[pi][1]).join(', ') + '.';
    });
    upgMissing.forEach(l => {
      text += ' Upgrade requirement (' + l + '): its planet isn\\u2019t in this campaign.';
    });
    cap.textContent = text;
    cap.classList.toggle('map-caption--none', !ok.length && !starts.length);
  }

  // Hover: name the nearest planet under the pointer.
  document.addEventListener('mousemove', e => {
    const svg = e.target.closest && e.target.closest('.galaxy-svg');
    if (!svg) return;
    const box = svg.closest('.map-box');
    if (!box._planets) return;
    const pt = svg.createSVGPoint();
    pt.x = e.clientX; pt.y = e.clientY;
    const ctm = svg.getScreenCTM();
    if (!ctm) return;
    const p = pt.matrixTransform(ctm.inverse());
    const g = geometry(Number(box.dataset.drawn));
    let best = null, bestD = (g.r * 4) ** 2;
    box._planets.forEach(pi => {
      const dx = P[pi][2] - p.x, dy = -P[pi][3] - p.y, d = dx * dx + dy * dy;
      if (d < bestD) { bestD = d; best = pi; }
    });
    const hover = box.querySelector('.map-hover');
    if (best === null) { hover.textContent = ' '; return; }
    const notes = [];
    notes.push(box._ok.has(best) ? 'recruitable' : 'not recruitable');
    if (box._starts.has(best)) notes.push('starts here');
    if (box._upgSet && box._upgSet.has(best)) notes.push('upgrade requirement');
    hover.textContent = P[best][1] + ' — ' + notes.join(', ');
  });

  const boxes = Array.from(document.querySelectorAll('.map-box'));
  let observer = null;
  if ('IntersectionObserver' in window) {
    observer = new IntersectionObserver(entries => {
      entries.forEach(en => { if (en.isIntersecting) draw(en.target); });
    }, { rootMargin: '400px' });
    boxes.forEach(b => observer.observe(b));
  } else {
    boxes.forEach(draw);
  }

  // The page-level menu resets every card to the chosen campaign.
  select.addEventListener('change', () => {
    pageSetup = Number(select.value);
    try { localStorage.setItem(STORE_KEY, GD.setups[pageSetup].id); } catch (e) { /* ignore */ }
    boxes.forEach(b => {
      delete b.dataset.setup;
      const r = b.getBoundingClientRect();
      if (r.bottom > -400 && r.top < window.innerHeight + 400) draw(b);
      else delete b.dataset.drawn;
    });
    if (observer) boxes.forEach(b => { observer.unobserve(b); observer.observe(b); });
  });
})();
"""
