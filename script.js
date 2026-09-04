const SOURCE_FILES = [
  { id: 'situation', url: 'data/situation.geojson', label: 'situation de référence' },
  { id: 'events', url: 'data/events.geojson', label: 'signaux médiatiques' }
];
const SOCIAL_WATCH_FILE = 'data/social_watch.json';
const MAP_CONTEXT_FILE = 'data/map_context.geojson';
const MONITORED_COUNTRIES = ['Mali', 'Niger', 'Burkina Faso', 'Mauritanie', 'Tchad'];
const SAHEL_BOUNDS = [[7.2, -18.2], [25.2, 24.8]];
const COUNTRY_BOUNDS = {
  'Mali': [[10.0, -12.3], [25.1, 4.4]],
  'Niger': [[11.4, 0.1], [23.6, 16.1]],
  'Burkina Faso': [[9.3, -5.7], [15.2, 2.5]],
  'Mauritanie': [[14.5, -17.2], [27.4, -4.8]],
  'Tchad': [[7.3, 13.4], [23.6, 24.1]]
};
const countryColors = {
  'Mali': '#d7aa5d',
  'Niger': '#48c8b5',
  'Burkina Faso': '#d88456',
  'Mauritanie': '#7d95d6',
  'Tchad': '#a982cc'
};

const colors = {
  'FAMa / État malien': '#3b82f6',
  'FLA / Azawad': '#9a75d4',
  'JNIM / GSIM': '#d95c52',
  'État islamique au Sahel': '#c8463c',
  'Plusieurs acteurs': '#df8c44',
  'Contesté': '#df8c44',
  'À vérifier': '#d7aa5d',
  'Événement récent': '#d7aa5d',
  'humanitaire': '#48c8b5',
  'politique': '#7f91a2',
  'sécurité': '#d95c52'
};

const map = L.map('map', {
  zoomControl: false,
  preferCanvas: false
}).setView([16.8, -2.3], 6);

L.control.zoom({ position: 'bottomright' }).addTo(map);
L.control.scale({ position: 'bottomright', imperial: false, maxWidth: 110 }).addTo(map);
map.attributionControl.setPrefix(false);
map.attributionControl.addAttribution('Map context: Natural Earth');
map.attributionControl.addAttribution('Localités: <a href="https://www.geonames.org/" target="_blank" rel="noopener">GeoNames</a>');

let allFeatures = [];
let renderedLayers = [];
let datasetMetadata = {};
let socialWatch = { metadata: {}, targets: [] };
let contextLayer = null;
let mapContextData = null;

const itemList = document.getElementById('itemList');
const itemCount = document.getElementById('itemCount');
const layerFilter = document.getElementById('layerFilter');
const actorFilter = document.getElementById('actorFilter');
const countryFilter = document.getElementById('countryFilter');
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

function featureCountry(feature) {
  const props = feature?.properties || {};
  if (MONITORED_COUNTRIES.includes(props.country)) return props.country;
  const text = normalizeText([props.region, props.location, props.title, props.summary].join(' '));
  return MONITORED_COUNTRIES.find(country => text.includes(normalizeText(country))) || (props.layer !== 'event' ? 'Mali' : '');
}

function focusSelectedCountry(animate = true) {
  const bounds = COUNTRY_BOUNDS[countryFilter.value] || SAHEL_BOUNDS;
  map.fitBounds(bounds, { animate, padding: [20, 20] });
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
  if (props.layer === 'event') {
    return colors[props.actor] || colors[props.category] || colors['Événement récent'];
  }
  return colors[props.actor] || colors[props.status] || '#94a3b8';
}

function markerFor(feature, latlng) {
  const props = feature.properties || {};
  const color = featureColor(props);
  const isSocial = props.layer === 'event' && (
    String(props.source_system || '').startsWith('X ') || String(props.layer_label || '').includes('réseau social')
  );
  return L.circleMarker(latlng, {
    radius: isSocial ? 7.5 : props.layer === 'event' ? 6.5 : 8.5,
    color,
    weight: isSocial ? 2.2 : props.layer === 'event' ? 1.5 : 2,
    fillColor: color,
    fillOpacity: props.layer === 'event' ? 0.78 : 0.92,
    dashArray: isSocial ? '2 3' : null,
    className: isSocial ? 'map-signal-marker map-social-marker' : props.layer === 'event' ? 'map-signal-marker' : 'map-reference-marker'
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
    fillOpacity: props.layer === 'zone' ? 0.13 : 0.16,
    dashArray: props.status === 'Contesté' || String(props.confidence || '').startsWith('faible') ? '5,7' : null,
    className: props.layer === 'zone' ? 'map-zone-shape' : 'map-reference-shape'
  };
}

function smoothClosedRing(coordinates, iterations = 2) {
  if (!Array.isArray(coordinates) || coordinates.length < 4) return coordinates;
  const first = coordinates[0];
  const last = coordinates[coordinates.length - 1];
  const isClosed = first[0] === last[0] && first[1] === last[1];
  let points = (isClosed ? coordinates.slice(0, -1) : coordinates).map(point => [...point]);
  if (points.length < 3) return coordinates;

  for (let iteration = 0; iteration < iterations; iteration += 1) {
    const rounded = [];
    points.forEach((point, index) => {
      const next = points[(index + 1) % points.length];
      rounded.push([
        point[0] * 0.75 + next[0] * 0.25,
        point[1] * 0.75 + next[1] * 0.25
      ]);
      rounded.push([
        point[0] * 0.25 + next[0] * 0.75,
        point[1] * 0.25 + next[1] * 0.75
      ]);
    });
    points = rounded;
  }
  return [...points, [...points[0]]];
}

function smoothZoneFeature(feature) {
  if (feature?.properties?.layer !== 'zone' || !feature.geometry) return feature;
  const geometry = feature.geometry;
  let coordinates = geometry.coordinates;
  if (geometry.type === 'Polygon') {
    coordinates = coordinates.map(ring => smoothClosedRing(ring));
  } else if (geometry.type === 'MultiPolygon') {
    coordinates = coordinates.map(polygon => polygon.map(ring => smoothClosedRing(ring)));
  }
  return { ...feature, geometry: { ...geometry, coordinates } };
}

function cross(origin, pointA, pointB) {
  return (pointA[0] - origin[0]) * (pointB[1] - origin[1])
    - (pointA[1] - origin[1]) * (pointB[0] - origin[0]);
}

function convexHull(points) {
  const unique = [...new Map(points.map(point => [`${point[0]},${point[1]}`, point])).values()]
    .sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  if (unique.length < 3) return [];
  const lower = [];
  unique.forEach(point => {
    while (lower.length >= 2 && cross(lower[lower.length - 2], lower[lower.length - 1], point) <= 0) lower.pop();
    lower.push(point);
  });
  const upper = [];
  unique.slice().reverse().forEach(point => {
    while (upper.length >= 2 && cross(upper[upper.length - 2], upper[upper.length - 1], point) <= 0) upper.pop();
    upper.push(point);
  });
  return [...lower.slice(0, -1), ...upper.slice(0, -1)];
}

function distanceKm(pointA, pointB) {
  const meanLatitude = ((pointA[1] + pointB[1]) / 2) * Math.PI / 180;
  const longitudeDistance = (pointA[0] - pointB[0]) * Math.cos(meanLatitude);
  const latitudeDistance = pointA[1] - pointB[1];
  return Math.hypot(longitudeDistance, latitudeDistance) * 111;
}

function geographicClusters(points, thresholdKm = 420) {
  const remaining = points.map(point => [...point]);
  const clusters = [];
  while (remaining.length) {
    const cluster = [remaining.pop()];
    for (let index = 0; index < cluster.length; index += 1) {
      for (let candidateIndex = remaining.length - 1; candidateIndex >= 0; candidateIndex -= 1) {
        if (distanceKm(cluster[index], remaining[candidateIndex]) <= thresholdKm) {
          cluster.push(remaining.splice(candidateIndex, 1)[0]);
        }
      }
    }
    clusters.push(cluster);
  }
  return clusters;
}

function roundedEnvelope(points) {
  const hull = convexHull(points);
  if (hull.length < 3) return [];
  const center = hull.reduce((result, point) => [result[0] + point[0], result[1] + point[1]], [0, 0])
    .map(value => value / hull.length);
  const expanded = hull.map(point => {
    const dx = point[0] - center[0];
    const dy = point[1] - center[1];
    const distance = Math.hypot(dx, dy) || 1;
    const padding = 0.22;
    return [point[0] + dx / distance * padding, point[1] + dy / distance * padding];
  });
  return smoothClosedRing([...expanded, expanded[0]], 2);
}

function renderSignalEnvelopes(features) {
  const byCountry = new Map();
  features.forEach(feature => {
    if (
      feature?.properties?.layer !== 'event'
      || !feature?.properties?.source_system
      || feature?.geometry?.type !== 'Point'
    ) return;
    const country = featureCountry(feature);
    if (!country) return;
    const coordinates = feature.geometry.coordinates;
    if (!byCountry.has(country)) byCountry.set(country, []);
    byCountry.get(country).push(coordinates);
  });

  byCountry.forEach((points, country) => {
    geographicClusters(points).forEach(cluster => {
      const ring = roundedEnvelope(cluster);
      if (!ring.length) return;
      const layer = L.polygon(ring.map(([longitude, latitude]) => [latitude, longitude]), {
        className: 'signal-envelope',
        color: countryColors[country] || '#48c8b5',
        fillColor: countryColors[country] || '#48c8b5',
        weight: 1.4,
        opacity: 0.65,
        fillOpacity: 0.055,
        dashArray: '3 11',
        interactive: false,
        smoothFactor: 0.7
      }).addTo(map);
      renderedLayers.push(layer);
    });
  });
}

function popupHtml(props = {}) {
  const tags = [props.country, props.layer_label, props.actor, props.status, props.confidence, props.precision]
    .filter(Boolean)
    .map(tag => `<span class="badge">${escapeHtml(tag)}</span>`)
    .join('');

  const sourceUrl = safeExternalUrl(props.source_url || props.url);
  const source = sourceUrl
    ? `<div class="popup-source"><a href="${escapeHtml(sourceUrl)}" target="_blank" rel="noopener noreferrer">Lire la source</a></div>`
    : '';

  return `
    <div class="popup-kicker">${escapeHtml(props.layer_label || 'Open source signal')}</div>
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
  const country = countryFilter.value;
  const layer = layerFilter.value;
  const actor = actorFilter.value;
  const query = normalizeText(searchInput.value.trim());

  if (country !== 'all' && featureCountry(feature) !== country) return false;
  if (layer !== 'all' && props.layer !== layer) return false;
  if (actor !== 'all' && props.actor !== actor && props.status !== actor) return false;

  if (query) {
    const haystack = normalizeText([
      props.title,
      props.summary,
      props.actor,
      props.status,
      props.country,
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

  renderSignalEnvelopes(mapped);

  mapped.forEach(feature => {
    const displayFeature = smoothZoneFeature(feature);
    const layer = L.geoJSON(displayFeature, {
      pointToLayer: markerFor,
      style: styleFeature,
      onEachFeature: (currentFeature, currentLayer) => {
        const props = currentFeature.properties || {};
        currentLayer.bindPopup(popupHtml(props), { maxWidth: 340, closeButton: true });
        currentLayer.bindTooltip(escapeHtml(props.title || 'Signal public'), {
          direction: 'top',
          className: 'map-tooltip',
          offset: [0, -6],
          opacity: 1
        });
        currentLayer.on('mouseover', () => {
          if (currentLayer.setStyle) {
            currentLayer.setStyle({ weight: 3, fillOpacity: props.layer === 'zone' ? 0.2 : 1 });
            currentLayer.bringToFront?.();
          }
        });
        currentLayer.on('mouseout', () => {
          if (currentLayer.setStyle) currentLayer.setStyle(styleFeature(currentFeature));
        });
      }
    }).addTo(map);
    renderedLayers.push(layer);
  });

  if (contextLayer) {
    contextLayer.setStyle(contextCountryStyle);
    contextLayer.bringToBack();
  }

  renderList(visible);
  itemCount.textContent = `${visible.length} affichés · ${mapped.length} cartographiés`;
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
      item.style.setProperty('--item-accent', featureColor(props));
      const location = props.location || props.region || '';
      item.innerHTML = `
        <div class="item-overline">
          <span class="item-source">${escapeHtml(props.source || props.layer_label || 'Source publique')}</span>
          <time datetime="${escapeHtml(featureDate(feature))}">${escapeHtml(formatDate(featureDate(feature)))}</time>
        </div>
        <div class="item-title">${escapeHtml(props.title || 'Sans titre')}</div>
        <div class="item-tags">
          ${featureCountry(feature) ? `<span class="item-tag item-country">${escapeHtml(featureCountry(feature))}</span>` : ''}
          ${props.actor || props.status ? `<span class="item-tag">${escapeHtml(props.actor || props.status)}</span>` : ''}
          ${location ? `<span class="item-tag">${escapeHtml(location)}</span>` : ''}
          ${props.category ? `<span class="item-tag">${escapeHtml(props.category)}</span>` : ''}
        </div>
      `;

      const actions = document.createElement('div');
      actions.className = 'item-actions';
      if (feature.geometry) {
        const zoomButton = document.createElement('button');
        zoomButton.type = 'button';
        zoomButton.className = 'item-action';
        zoomButton.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 21s7-5.2 7-12a7 7 0 1 0-14 0c0 6.8 7 12 7 12Z"/><circle cx="12" cy="9" r="2.2"/></svg>Localiser';
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
        sourceLink.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M14 5h5v5M10 14 19 5M19 13v6H5V5h6"/></svg>Ouvrir la source';
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
  const mediaSignals = features.filter(feature => feature.properties?.source_system);
  const signals = mediaSignals.length;
  const mappedSignals = mediaSignals.filter(feature => feature.geometry).length;
  const sourceSummary = metadata?.source_summary || {};
  const successfulSources = sourceSummary.successful_sources ?? '—';
  const localSources = sourceSummary.local_media_sources ?? '—';
  const socialTargetCount = watch?.metadata?.target_count ?? 0;
  const activeSocialFeeds = watch?.metadata?.active_feed_count ?? 0;
  const mappedRatio = signals ? Math.round((mappedSignals / signals) * 100) : 0;

  const cards = [
    {
      label: 'Signaux actifs',
      value: signals,
      meta: `Dernier · ${formatDate(metadata?.latest_signal_date)}`,
      tone: 'sand'
    },
    {
      label: 'Cartographiés',
      value: mappedSignals,
      meta: `${mappedRatio}% des signaux · ${zones} zones`,
      tone: 'red'
    },
    {
      label: 'Pays suivis',
      value: MONITORED_COUNTRIES.length,
      meta: `${successfulSources} sources · ${localSources} locales`,
      tone: 'teal'
    },
    {
      label: 'X indexé',
      value: socialTargetCount,
      meta: `${activeSocialFeeds} veille(s) automatique(s)`,
      tone: 'purple'
    }
  ];

  statusCards.innerHTML = cards.map(card => `
    <article class="status-card tone-${escapeHtml(card.tone)}">
      <span class="status-card-label">${escapeHtml(card.label)}</span>
      <strong class="status-card-value">${escapeHtml(card.value)}</strong>
      <span class="status-card-meta">${escapeHtml(card.meta)}</span>
    </article>
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
    handle.textContent = `${target.country || 'Sahel'} · @${target.handle || 'inconnu'}`;
    identity.append(name, handle);

    const status = document.createElement('span');
    status.className = `social-feed-status ${target.feed_active ? 'is-active' : ''}`;
    status.textContent = target.feed_active ? (target.discovery_method || 'Flux public actif') : 'veille directe';

    item.append(identity, status);
    if (profileUrl) {
      const link = document.createElement('a');
      link.href = profileUrl;
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
      link.textContent = 'Consulter ↗';
      item.appendChild(link);
    }
    socialTargets.appendChild(item);
  });
}

function contextCountryStyle(feature) {
  const name = feature.properties?.name;
  const monitored = Boolean(feature.properties?.monitored);
  const selected = countryFilter.value === name;
  const faded = countryFilter.value !== 'all' && monitored && !selected;
  const color = countryColors[name] || '#52656b';
  return {
    color: selected ? '#f0d398' : monitored ? color : '#43545a',
    weight: selected ? 2.3 : monitored ? 1.45 : 0.85,
    opacity: faded ? 0.38 : monitored ? 0.86 : 0.58,
    fillColor: monitored ? color : '#111c21',
    fillOpacity: selected ? 0.23 : faded ? 0.045 : monitored ? 0.105 : 0.68,
    className: monitored ? 'monitored-country' : 'context-country'
  };
}

function renderMapContext(data) {
  if (contextLayer) map.removeLayer(contextLayer);

  const countries = L.geoJSON(data, {
    interactive: true,
    style: contextCountryStyle,
    onEachFeature: (feature, layer) => {
      const name = feature.properties?.name || '';
      if (!feature.properties?.monitored) return;
      layer.bindTooltip(name, { sticky: true, className: 'country-tooltip', opacity: 1 });
      layer.on('click', () => {
        countryFilter.value = name;
        render();
        focusSelectedCountry();
      });
    }
  });

  contextLayer = countries.addTo(map);
  countries.bringToBack();
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

async function loadMapContext() {
  const response = await fetch(MAP_CONTEXT_FILE, { cache: 'force-cache' });
  if (!response.ok) throw new Error(`contexte cartographique indisponible (${response.status})`);
  const data = await response.json();
  if (data?.type !== 'FeatureCollection' || !Array.isArray(data.features)) {
    throw new Error('contexte cartographique invalide');
  }
  return data;
}

async function loadSocialWatch() {
  const response = await fetch(SOCIAL_WATCH_FILE, { cache: 'no-store' });
  if (!response.ok) throw new Error(`watchlist sociale indisponible (${response.status})`);
  const data = await response.json();
  if (!Array.isArray(data?.targets)) throw new Error('watchlist sociale invalide');
  return data;
}

async function init() {
  const [results, loadedSocialWatch, loadedMapContext] = await Promise.all([
    Promise.allSettled(SOURCE_FILES.map(loadDataset)),
    loadSocialWatch().catch(error => {
      console.error(error);
      return { metadata: {}, targets: [] };
    }),
    loadMapContext().catch(error => {
      console.error(error);
      return null;
    })
  ]);
  socialWatch = loadedSocialWatch;
  mapContextData = loadedMapContext;
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
  if (mapContextData) renderMapContext(mapContextData);
  render();
  focusSelectedCountry(false);
}

countryFilter.addEventListener('change', () => {
  render();
  focusSelectedCountry();
});
layerFilter.addEventListener('change', render);
actorFilter.addEventListener('change', render);
searchInput.addEventListener('input', render);

resetBtn.addEventListener('click', () => {
  countryFilter.value = 'all';
  layerFilter.value = 'all';
  actorFilter.value = 'all';
  searchInput.value = '';
  render();
  focusSelectedCountry();
});

document.addEventListener('keydown', event => {
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
    event.preventDefault();
    searchInput.focus();
    searchInput.select();
  }
  if (event.key === 'Escape' && document.activeElement === searchInput) {
    searchInput.value = '';
    searchInput.blur();
    render();
  }
});

init().catch(error => {
  console.error(error);
  itemCount.textContent = 'Erreur inattendue pendant le chargement.';
});
