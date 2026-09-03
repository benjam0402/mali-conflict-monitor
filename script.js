const SOURCE_FILES = [
  { id: 'situation', url: 'data/situation.geojson', label: 'situation de référence' },
  { id: 'events', url: 'data/events.geojson', label: 'signaux médiatiques' }
];
const SOCIAL_WATCH_FILE = 'data/social_watch.json';

const colors = {
  'FAMa / État malien': '#3b82f6',
  'FLA / Azawad': '#8b5cf6',
  'JNIM / GSIM': '#ef4444',
  'État islamique au Sahel': '#dc2626',
  'Plusieurs acteurs': '#f97316',
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
let datasetMetadata = {};
let socialWatch = { metadata: {}, targets: [] };

const itemList = document.getElementById('itemList');
const itemCount = document.getElementById('itemCount');
const layerFilter = document.getElementById('layerFilter');
const actorFilter = document.getElementById('actorFilter');
const searchInput = document.getElementById('searchInput');
const resetBtn = document.getElementById('resetBtn');
const lastUpdated = document.getElementById('lastUpdated');
const statusCards = document.getElementById('statusCards');
const socialTargets = document.getElementById('socialTargets');

function normalizeText(value) {
  return String(value || '')
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase();
}

function escapeHtml(value) {
  return String(value || '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

function safeExternalUrl(value) {
  try {
    const url = new URL(String(value || ''), window.location.origin);
    return ['http:', 'https:'].includes(url.protocol) ? url.href : '';
  } catch {
    return '';
  }
}

function featureDate(feature) {
  const props = feature.properties || {};
  return props.as_of || props.date || '';
}

function formatDate(value, includeTime = false) {
  if (!value) return 'non précisée';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  const options = includeTime
    ? { dateStyle: 'medium', timeStyle: 'short', timeZone: 'Europe/Paris' }
    : { dateStyle: 'medium', timeZone: 'UTC' };
  return new Intl.DateTimeFormat('fr-FR', options).format(date);
}

function featureColor(props = {}) {
  if (props.layer === 'event') return colors['Événement récent'];
  return colors[props.actor] || colors[props.status] || '#94a3b8';
}

function markerFor(feature, latlng) {
  const props = feature.properties || {};
  const color = featureColor(props);
  return L.circleMarker(latlng, {
    radius: props.layer === 'event' ? 7 : 9,
    color,
    weight: 2,
    fillColor: color,
    fillOpacity: props.layer === 'event' ? 0.72 : 0.9
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
    fillOpacity: props.layer === 'zone' ? 0.2 : 0.12,
    dashArray: props.status === 'Contesté' || String(props.confidence || '').startsWith('faible') ? '7,7' : null
  };
}

function popupHtml(props = {}) {
  const tags = [props.layer_label, props.actor, props.status, props.confidence, props.precision]
    .filter(Boolean)
    .map(tag => `<span class="badge">${escapeHtml(tag)}</span>`)
    .join('');

  const sourceUrl = safeExternalUrl(props.source_url || props.url);
  const source = sourceUrl
    ? `<div class="popup-source"><a href="${escapeHtml(sourceUrl)}" target="_blank" rel="noopener noreferrer">Lire la source</a></div>`
    : '';

  return `
    <div class="popup-title">${escapeHtml(props.title || 'Sans titre')}</div>
    <div class="popup-badges">${tags}</div>
    <div class="popup-meta">Date : ${escapeHtml(formatDate(props.as_of || props.date))}</div>
    <div class="popup-meta">Source : ${escapeHtml(props.source || 'non précisée')}</div>
    <div class="popup-summary">${escapeHtml(props.summary || '')}</div>
    ${source}
  `;
}

function passesFilters(feature) {
  const props = feature.properties || {};
  const layer = layerFilter.value;
  const actor = actorFilter.value;
  const query = normalizeText(searchInput.value.trim());

  if (layer !== 'all' && props.layer !== layer) return false;
  if (actor !== 'all' && props.actor !== actor && props.status !== actor) return false;

  if (query) {
    const haystack = normalizeText([
      props.title,
      props.summary,
      props.actor,
      props.status,
      props.region,
      props.location,
      props.category,
      props.source
    ].join(' '));
    if (!haystack.includes(query)) return false;
  }
  return true;
}

function clearRendered() {
  renderedLayers.forEach(layer => map.removeLayer(layer));
  renderedLayers = [];
  itemList.replaceChildren();
}

function render() {
  clearRendered();
  const visible = allFeatures.filter(passesFilters);
  const mapped = visible.filter(feature => feature.geometry);

  mapped.forEach(feature => {
    const layer = L.geoJSON(feature, {
      pointToLayer: markerFor,
      style: styleFeature,
      onEachFeature: (currentFeature, currentLayer) => {
        currentLayer.bindPopup(popupHtml(currentFeature.properties || {}));
      }
    }).addTo(map);
    renderedLayers.push(layer);
  });

  renderList(visible);
  itemCount.textContent = `${visible.length} élément(s), dont ${mapped.length} sur la carte`;
}

function renderList(features) {
  features
    .slice()
    .sort((a, b) => {
      const layerOrder = { event: 0, point: 1, zone: 2 };
      const layerDifference = (layerOrder[a.properties?.layer] ?? 9) - (layerOrder[b.properties?.layer] ?? 9);
      if (layerDifference !== 0) return layerDifference;
      return featureDate(b).localeCompare(featureDate(a));
    })
    .forEach(feature => {
      const props = feature.properties || {};
      const item = document.createElement('article');
      item.className = 'item';
      item.innerHTML = `
        <div class="item-title">${escapeHtml(props.title || 'Sans titre')}</div>
        <div class="item-meta">${escapeHtml(props.actor || props.status || '')} · ${escapeHtml(props.layer_label || '')}</div>
        <div class="item-meta">${escapeHtml(formatDate(featureDate(feature)))} · ${escapeHtml(props.source || '')}</div>
      `;

      const actions = document.createElement('div');
      actions.className = 'item-actions';
      if (feature.geometry) {
        const zoomButton = document.createElement('button');
        zoomButton.type = 'button';
        zoomButton.className = 'item-action';
        zoomButton.textContent = 'Voir sur la carte';
        zoomButton.addEventListener('click', () => zoomToFeature(feature));
        actions.appendChild(zoomButton);
      }

      const sourceUrl = safeExternalUrl(props.source_url || props.url);
      if (sourceUrl) {
        const sourceLink = document.createElement('a');
        sourceLink.className = 'item-action item-link';
        sourceLink.href = sourceUrl;
        sourceLink.target = '_blank';
        sourceLink.rel = 'noopener noreferrer';
        sourceLink.textContent = 'Source';
        actions.appendChild(sourceLink);
      }

      if (actions.childElementCount) item.appendChild(actions);
      itemList.appendChild(item);
    });
}

function zoomToFeature(feature) {
  if (!feature.geometry) return;
  const temporaryLayer = L.geoJSON(feature);
  const bounds = temporaryLayer.getBounds();
  if (bounds.isValid()) {
    map.fitBounds(bounds.pad(0.5), { maxZoom: feature.properties?.layer === 'zone' ? 8 : 10 });
  }
}

function populateActorFilter(features) {
  const knownValues = new Set(Array.from(actorFilter.options).map(option => option.value));
  const actors = [...new Set(features.map(feature => feature.properties?.actor).filter(Boolean))].sort();
  actors.forEach(actor => {
    if (!knownValues.has(actor)) actorFilter.add(new Option(actor, actor));
  });
}

function renderStatusCards(features, metadata, watch) {
  const zones = features.filter(feature => feature.properties?.layer === 'zone').length;
  const signals = features.filter(feature => feature.properties?.layer === 'event').length;
  const mappedSignals = features.filter(feature => feature.properties?.layer === 'event' && feature.geometry).length;
  const sourceSummary = metadata?.source_summary || {};
  const successfulSources = sourceSummary.successful_sources ?? '—';
  const localSources = sourceSummary.local_media_sources ?? '—';
  const socialTargetCount = watch?.metadata?.target_count ?? 0;
  const activeSocialFeeds = watch?.metadata?.active_feed_count ?? 0;

  const cards = [
    {
      title: 'Couverture',
      body: `${zones} zone(s) de référence et ${signals} signal(aux) médiatique(s), dont ${mappedSignals} cartographié(s).`
    },
    {
      title: 'Collecte ouverte',
      body: `${successfulSources} source(s) publique(s) accessible(s), dont ${localSources} média(s) local(aux) ciblé(s). Dernier signal : ${formatDate(metadata?.latest_signal_date)}.`
    },
    {
      title: 'Veille sociale',
      body: `${socialTargetCount} compte(s) X public(s) dans la watchlist ; ${activeSocialFeeds} flux social(aux) automatisé(s).`
    },
    {
      title: 'Prudence',
      body: 'Un article est un signal à recouper, pas une confirmation. Les positions indiquent seulement une localité citée.'
    }
  ];

  statusCards.innerHTML = cards.map(card => `
    <div class="status-card">
      <strong>${escapeHtml(card.title)}</strong>
      <span>${escapeHtml(card.body)}</span>
    </div>
  `).join('');
}

function renderSocialTargets(watch) {
  socialTargets.replaceChildren();
  const targets = Array.isArray(watch?.targets) ? watch.targets : [];
  if (!targets.length) {
    socialTargets.textContent = 'Aucun compte public configuré.';
    return;
  }

  targets.forEach(target => {
    const profileUrl = safeExternalUrl(target.profile_url);
    const item = document.createElement('div');
    item.className = 'social-target';

    const identity = document.createElement('div');
    const name = document.createElement('strong');
    name.textContent = target.name || `@${target.handle}`;
    const handle = document.createElement('span');
    handle.textContent = `@${target.handle || 'inconnu'}`;
    identity.append(name, handle);

    const status = document.createElement('span');
    status.className = `social-feed-status ${target.feed_active ? 'is-active' : ''}`;
    status.textContent = target.feed_active ? 'RSS actif' : 'veille directe';

    item.append(identity, status);
    if (profileUrl) {
      const link = document.createElement('a');
      link.href = profileUrl;
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
      link.textContent = 'Ouvrir le profil public';
      item.appendChild(link);
    }
    socialTargets.appendChild(item);
  });
}

async function loadDataset(source) {
  const response = await fetch(source.url, { cache: 'no-store' });
  if (!response.ok) throw new Error(`${source.label} indisponible (${response.status})`);
  const data = await response.json();
  if (data?.type !== 'FeatureCollection' || !Array.isArray(data.features)) {
    throw new Error(`${source.label} invalide`);
  }
  return { ...source, data };
}

async function loadSocialWatch() {
  const response = await fetch(SOCIAL_WATCH_FILE, { cache: 'no-store' });
  if (!response.ok) throw new Error(`watchlist sociale indisponible (${response.status})`);
  const data = await response.json();
  if (!Array.isArray(data?.targets)) throw new Error('watchlist sociale invalide');
  return data;
}

async function init() {
  const [results, loadedSocialWatch] = await Promise.all([
    Promise.allSettled(SOURCE_FILES.map(loadDataset)),
    loadSocialWatch().catch(error => {
      console.error(error);
      return { metadata: {}, targets: [] };
    })
  ]);
  socialWatch = loadedSocialWatch;
  renderSocialTargets(socialWatch);
  const loaded = results.filter(result => result.status === 'fulfilled').map(result => result.value);
  const errors = results.filter(result => result.status === 'rejected').map(result => result.reason?.message || 'source inconnue');

  if (!loaded.length) {
    itemCount.textContent = 'Erreur : aucune donnée ne peut être chargée.';
    lastUpdated.textContent = 'indisponible';
    console.error(errors.join(' · '));
    return;
  }

  datasetMetadata = Object.fromEntries(loaded.map(source => [source.id, source.data.metadata || {}]));
  const byId = new Map();
  loaded.flatMap(source => source.data.features).forEach((feature, index) => {
    const id = feature.properties?.id || `feature-${index}`;
    byId.set(id, feature);
  });
  allFeatures = [...byId.values()];

  const eventMetadata = datasetMetadata.events || {};
  const referenceMetadata = datasetMetadata.situation || {};
  const updateValue = eventMetadata.generated_at || eventMetadata.last_updated || referenceMetadata.last_updated;
  lastUpdated.textContent = formatDate(updateValue, Boolean(String(updateValue || '').includes('T')));
  if (updateValue) lastUpdated.title = String(updateValue);
  if (errors.length) lastUpdated.textContent += ' · collecte partielle';

  populateActorFilter(allFeatures);
  renderStatusCards(allFeatures, eventMetadata, socialWatch);
  render();

  const geolocatedFeatures = allFeatures.filter(feature => feature.geometry);
  const bounds = L.geoJSON({ type: 'FeatureCollection', features: geolocatedFeatures }).getBounds();
  if (bounds.isValid()) map.fitBounds(bounds.pad(0.15));
}

layerFilter.addEventListener('change', render);
actorFilter.addEventListener('change', render);
searchInput.addEventListener('input', render);

resetBtn.addEventListener('click', () => {
  layerFilter.value = 'all';
  actorFilter.value = 'all';
  searchInput.value = '';
  render();
});

init().catch(error => {
  console.error(error);
  itemCount.textContent = 'Erreur inattendue pendant le chargement.';
});
