const SOURCE_FILE = 'data/situation.geojson';

const colors = {
  'FAMa / État malien': '#3b82f6',
  'FLA / Azawad': '#8b5cf6',
  'JNIM / GSIM': '#ef4444',
  'Contesté': '#f97316',
  'À vérifier': '#94a3b8',
  'Événement récent': '#94a3b8'
};

const map = L.map('map', {
  zoomControl: true,
  preferCanvas: true
}).setView([16.8, -2.3], 6);

L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
  maxZoom: 18,
  attribution: '&copy; OpenStreetMap contributors'
}).addTo(map);

let allFeatures = [];
let renderedLayers = [];
const itemList = document.getElementById('itemList');
const itemCount = document.getElementById('itemCount');
const layerFilter = document.getElementById('layerFilter');
const actorFilter = document.getElementById('actorFilter');
const searchInput = document.getElementById('searchInput');
const resetBtn = document.getElementById('resetBtn');
const lastUpdated = document.getElementById('lastUpdated');
const statusCards = document.getElementById('statusCards');

function featureColor(props) {
  if (props.layer === 'event') return colors['Événement récent'];
  return colors[props.actor] || colors[props.status] || '#94a3b8';
}

function markerFor(feature, latlng) {
  const props = feature.properties;
  const color = featureColor(props);
  return L.circleMarker(latlng, {
    radius: props.layer === 'event' ? 7 : 9,
    color,
    weight: 2,
    fillColor: color,
    fillOpacity: props.layer === 'event' ? 0.7 : 0.9
  });
}

function styleFeature(feature) {
  const props = feature.properties || {};
  const color = featureColor(props);
  return {
    color,
    weight: 2,
    opacity: 0.9,
    fillColor: color,
    fillOpacity: props.layer === 'zone' ? 0.20 : 0.12,
    dashArray: props.status === 'Contesté' || props.confidence === 'faible' ? '7,7' : null
  };
}

function popupHtml(props) {
  const tags = [props.layer_label, props.actor, props.status, props.confidence]
    .filter(Boolean)
    .map(t => `<span class="badge">${escapeHtml(t)}</span>`)
    .join('');

  const source = props.source_url
    ? `<div class="popup-source"><a href="${props.source_url}" target="_blank" rel="noopener">Source</a></div>`
    : '';

  return `
    <div class="popup-title">${escapeHtml(props.title || 'Sans titre')}</div>
    <div>${tags}</div>
    <div class="popup-meta">Mise à jour : ${escapeHtml(props.as_of || 'non précisée')}</div>
    <div class="popup-summary">${escapeHtml(props.summary || '')}</div>
    ${source}
  `;
}

function escapeHtml(value) {
  return String(value || '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

function passesFilters(feature) {
  const props = feature.properties || {};
  const layer = layerFilter.value;
  const actor = actorFilter.value;
  const q = searchInput.value.trim().toLowerCase();

  if (layer !== 'all' && props.layer !== layer) return false;
  if (actor !== 'all' && props.actor !== actor && props.status !== actor) return false;

  if (q) {
    const haystack = [props.title, props.summary, props.actor, props.status, props.region, props.category]
      .join(' ')
      .toLowerCase();
    if (!haystack.includes(q)) return false;
  }

  return true;
}

function clearRendered() {
  renderedLayers.forEach(layer => map.removeLayer(layer));
  renderedLayers = [];
  itemList.innerHTML = '';
}

function render() {
  clearRendered();
  const visible = allFeatures.filter(passesFilters);

  visible.forEach(feature => {
    const layer = L.geoJSON(feature, {
      pointToLayer: markerFor,
      style: styleFeature,
      onEachFeature: (feat, lyr) => {
        lyr.bindPopup(popupHtml(feat.properties || {}));
      }
    }).addTo(map);
    renderedLayers.push(layer);
  });

  renderList(visible);
  itemCount.textContent = `${visible.length} élément(s) affiché(s)`;
}

function renderList(features) {
  features
    .slice()
    .sort((a, b) => {
      const order = { zone: 0, point: 1, event: 2 };
      return (order[a.properties.layer] ?? 9) - (order[b.properties.layer] ?? 9);
    })
    .forEach(feature => {
      const props = feature.properties || {};
      const item = document.createElement('div');
      item.className = 'item';
      item.innerHTML = `
        <div class="item-title">${escapeHtml(props.title)}</div>
        <div class="item-meta">${escapeHtml(props.actor || props.status || '')} · ${escapeHtml(props.layer_label || '')}</div>
      `;
      item.addEventListener('click', () => zoomToFeature(feature));
      itemList.appendChild(item);
    });
}

function zoomToFeature(feature) {
  const tmp = L.geoJSON(feature);
  const bounds = tmp.getBounds();
  if (bounds.isValid()) {
    map.fitBounds(bounds.pad(0.5), { maxZoom: feature.properties.layer === 'zone' ? 8 : 10 });
  }
}

function renderStatusCards(features) {
  const cards = [
    {
      title: 'Nord',
      body: 'Kidal est affichée comme zone FLA / Azawad selon la synthèse Wikipédia 2026, avec forte incertitude hors centre urbain.'
    },
    {
      title: 'Centre',
      body: 'Mopti, Sévaré et les axes voisins sont marqués contestés ou revendiqués, pas comme contrôle certain.'
    },
    {
      title: 'Sud / capitale',
      body: 'Bamako et Kati restent indiquées comme contrôle étatique, avec historique d’attaques signalées.'
    }
  ];

  statusCards.innerHTML = cards.map(card => `
    <div class="status-card">
      <strong>${escapeHtml(card.title)}</strong>
      <span>${escapeHtml(card.body)}</span>
    </div>
  `).join('');
}

async function init() {
  try {
    const response = await fetch(SOURCE_FILE, { cache: 'no-store' });
    if (!response.ok) throw new Error(`Impossible de charger ${SOURCE_FILE}`);
    const data = await response.json();
    allFeatures = data.features || [];
    lastUpdated.textContent = data.metadata?.last_updated || new Date().toISOString().slice(0, 10);
    renderStatusCards(allFeatures);
    render();

    const bounds = L.geoJSON(data).getBounds();
    if (bounds.isValid()) map.fitBounds(bounds.pad(0.15));
  } catch (err) {
    console.error(err);
    itemCount.textContent = 'Erreur de chargement des données.';
  }
}

[layerFilter, actorFilter, searchInput].forEach(el => {
  el.addEventListener('input', render);
  el.addEventListener('change', render);
});

resetBtn.addEventListener('click', () => {
  layerFilter.value = 'all';
  actorFilter.value = 'all';
  searchInput.value = '';
  render();
});

init();
