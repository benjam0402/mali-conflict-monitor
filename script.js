const EVENT_DATA_URL = './data/events.geojson';
const ZONES_DATA_URL = './data/zones.geojson';

const map = L.map('map', {
  minZoom: 4,
  maxZoom: 12,
  zoomControl: true,
}).setView([17.5707, -3.9962], 6);

L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
  maxZoom: 19,
  attribution: '&copy; OpenStreetMap contributors'
}).addTo(map);

const eventsLayer = L.layerGroup().addTo(map);
const zonesLayer = L.layerGroup().addTo(map);
const overlayControl = L.control.layers(null, {
  'Événements': eventsLayer,
  'Zones approximatives': zonesLayer,
}, { collapsed: false }).addTo(map);

let allEvents = [];
let allZones = [];
let markerIndex = new Map();

const filters = {
  type: document.getElementById('typeFilter'),
  reliability: document.getElementById('reliabilityFilter'),
  startDate: document.getElementById('startDate'),
  endDate: document.getElementById('endDate'),
  search: document.getElementById('searchInput'),
  reset: document.getElementById('resetFilters'),
};

const typeColors = {
  attaque: '#ef4444',
  combat: '#f97316',
  revendication: '#8b5cf6',
  humanitaire: '#38bdf8',
  route: '#f59e0b',
  politique: '#22c55e',
  autre: '#94a3b8',
};

const zoneColors = {
  etat: '#2563eb',
  jnim: '#dc2626',
  fla: '#7c3aed',
  conteste: '#f97316',
  inconnu: '#64748b',
};

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

function normalize(value) {
  return String(value ?? '')
    .toLowerCase()
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .trim();
}

function eventColor(feature) {
  const type = normalize(feature.properties?.type || 'autre');
  const reliability = normalize(feature.properties?.reliability || 'a-verifier');
  if (reliability === 'a-verifier' || reliability === 'conteste') return '#94a3b8';
  return typeColors[type] || typeColors.autre;
}

function eventPopup(feature) {
  const p = feature.properties || {};
  const sourceLink = p.url
    ? `<a href="${escapeHtml(p.url)}" target="_blank" rel="noopener">Ouvrir la source</a>`
    : 'Aucun lien source';

  return `
    <div class="popup">
      <h3>${escapeHtml(p.title || 'Événement')}</h3>
      <p class="popup-meta">${escapeHtml(p.date || 'Date inconnue')} · ${escapeHtml(p.location || 'Lieu inconnu')} · ${escapeHtml(p.region || '')}</p>
      <p><strong>Type :</strong> ${escapeHtml(p.type || 'autre')}</p>
      <p><strong>Acteurs :</strong> ${escapeHtml(p.actors || '—')}</p>
      <p><strong>Fiabilité :</strong> ${escapeHtml(p.reliability || 'à vérifier')}</p>
      <p><strong>Précision :</strong> ${escapeHtml(p.precision || 'approximation')}</p>
      <p>${escapeHtml(p.summary || '')}</p>
      <p>${sourceLink}</p>
    </div>
  `;
}

function passesFilters(feature) {
  const p = feature.properties || {};
  const type = normalize(p.type || 'autre');
  const reliability = normalize(p.reliability || 'a-verifier');
  const date = p.date ? new Date(p.date) : null;
  const q = normalize(filters.search.value);

  if (filters.type.value !== 'all' && type !== filters.type.value) return false;
  if (filters.reliability.value !== 'all' && reliability !== filters.reliability.value) return false;

  if (filters.startDate.value && date && date < new Date(filters.startDate.value)) return false;
  if (filters.endDate.value && date && date > new Date(filters.endDate.value)) return false;

  if (q) {
    const haystack = normalize([
      p.title, p.location, p.region, p.actors, p.type, p.reliability, p.summary, p.source
    ].join(' '));
    if (!haystack.includes(q)) return false;
  }

  return true;
}

function renderEvents() {
  eventsLayer.clearLayers();
  markerIndex.clear();

  const filtered = allEvents.filter(passesFilters);

  filtered.forEach((feature, idx) => {
    const coords = feature.geometry?.coordinates;
    if (!coords || coords.length < 2) return;

    const marker = L.circleMarker([coords[1], coords[0]], {
      radius: 8,
      color: '#111827',
      weight: 1.5,
      fillColor: eventColor(feature),
      fillOpacity: 0.88,
    }).bindPopup(eventPopup(feature));

    marker.addTo(eventsLayer);
    markerIndex.set(feature.properties?.id || idx, marker);
  });

  renderEventList(filtered);
}

function renderEventList(events) {
  const list = document.getElementById('eventList');
  const count = document.getElementById('eventCount');
  count.textContent = String(events.length);

  if (!events.length) {
    list.innerHTML = '<p class="empty-state">Aucun événement à afficher. Ajoute tes données dans <code>data/events.geojson</code> ou enlève les filtres.</p>';
    return;
  }

  const sorted = [...events].sort((a, b) => String(b.properties?.date || '').localeCompare(String(a.properties?.date || '')));
  list.innerHTML = '';

  sorted.forEach((feature, idx) => {
    const p = feature.properties || {};
    const card = document.createElement('article');
    card.className = 'event-card';
    card.innerHTML = `
      <h3>${escapeHtml(p.title || 'Événement')}</h3>
      <div class="event-meta">${escapeHtml(p.date || 'Date inconnue')} · ${escapeHtml(p.location || 'Lieu inconnu')}</div>
      <p>${escapeHtml(p.summary || '').slice(0, 150)}${String(p.summary || '').length > 150 ? '…' : ''}</p>
      <span class="badge">${escapeHtml(p.type || 'autre')} · ${escapeHtml(p.reliability || 'à vérifier')}</span>
    `;

    card.addEventListener('click', () => {
      const marker = markerIndex.get(p.id || idx);
      const coords = feature.geometry?.coordinates;
      if (marker && coords) {
        map.setView([coords[1], coords[0]], 8);
        marker.openPopup();
      }
    });

    list.appendChild(card);
  });
}

function renderZones() {
  zonesLayer.clearLayers();
  if (!allZones.length) return;

  L.geoJSON({ type: 'FeatureCollection', features: allZones }, {
    style: feature => {
      const status = normalize(feature.properties?.status || 'inconnu');
      return {
        color: zoneColors[status] || zoneColors.inconnu,
        weight: 1.5,
        fillOpacity: 0.12,
      };
    },
    onEachFeature: (feature, layer) => {
      const p = feature.properties || {};
      layer.bindPopup(`
        <div class="popup">
          <h3>${escapeHtml(p.name || 'Zone')}</h3>
          <p><strong>Statut :</strong> ${escapeHtml(p.status || 'inconnu')}</p>
          <p><strong>Fiabilité :</strong> ${escapeHtml(p.reliability || 'à vérifier')}</p>
          <p>${escapeHtml(p.note || '')}</p>
        </div>
      `);
    }
  }).addTo(zonesLayer);
}

async function fetchJson(url, fallback) {
  try {
    const res = await fetch(url, { cache: 'no-store' });
    if (!res.ok) throw new Error(`${url} : ${res.status}`);
    return await res.json();
  } catch (error) {
    console.warn(error);
    return fallback;
  }
}

async function init() {
  const [eventsData, zonesData] = await Promise.all([
    fetchJson(EVENT_DATA_URL, { type: 'FeatureCollection', features: [] }),
    fetchJson(ZONES_DATA_URL, { type: 'FeatureCollection', features: [] }),
  ]);

  allEvents = eventsData.features || [];
  allZones = zonesData.features || [];

  document.getElementById('lastUpdated').textContent = eventsData.metadata?.last_updated || new Date().toLocaleDateString('fr-FR');

  renderZones();
  renderEvents();

  if (allEvents.length) {
    const eventGroup = L.geoJSON({ type: 'FeatureCollection', features: allEvents });
    const bounds = eventGroup.getBounds();
    if (bounds.isValid()) map.fitBounds(bounds.pad(0.2));
  }
}

Object.values(filters).forEach(el => {
  if (el && el.id !== 'resetFilters') el.addEventListener('input', renderEvents);
});

filters.reset.addEventListener('click', () => {
  filters.type.value = 'all';
  filters.reliability.value = 'all';
  filters.startDate.value = '';
  filters.endDate.value = '';
  filters.search.value = '';
  renderEvents();
});

init();
