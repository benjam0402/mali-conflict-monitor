# Sahel Conflict Monitor — sources publiques sans jeton

Mini-site Leaflet statique couvrant le Mali, le Niger, le Burkina Faso, la Mauritanie et le Tchad. Il combine :

- des contours nationaux précis issus de Natural Earth ;
- des zones de référence revues manuellement et affichées avec des contours adoucis ;
- des signaux récents issus de médias, agrégateurs et profils X publics indexés ;
- des enveloppes dynamiques calculées à partir des concentrations de signaux géolocalisés ;
- une file CSV permettant de revoir tout ce qui a été collecté ou filtré.

Le projet n'utilise plus ACLED, ne demande aucun compte et ne contient aucun secret. Un élément collecté est présenté comme un **signal public à vérifier**, jamais comme une confirmation automatique. Une enveloppe de signaux ne représente ni un front ni un contrôle territorial.

## Couverture et sources

Le collecteur interroge GDELT DOC 2.0, Google Actualités RSS, RFI Afrique, France 24 Afrique, ONU Info Afrique, DW Afrique et Le Monde Afrique. Il cible aussi directement des médias locaux : Studio Tamani, Journal du Mali, Maliweb, Malijet, MaliActu et Bamada pour le Mali ; Studio Kalangou pour le Niger ; Burkina 24 et LeFaso.net pour le Burkina Faso ; Sahara Médias pour la Mauritanie ; Tchadinfos pour le Tchad.

La liste se trouve dans [`tools/public_sources.json`](tools/public_sources.json). Pour ajouter un flux RSS public :

```json
{
  "name": "Nom du média",
  "kind": "rss",
  "url": "https://exemple.org/feed.xml",
  "tier": "editorial",
  "language": "fr",
  "country": "Niger",
  "local": true,
  "enabled": true
}
```

Il est impossible de garantir une couverture littérale de « tous les sites » : certains bloquent les robots, n'ont pas de flux, sont derrière un paywall ou interdisent la réutilisation. GDELT et Google Actualités apportent une couverture large ; les flux directs renforcent les sources locales et institutionnelles.

## Veille X/Twitter sans jeton

Le monitor ne contourne pas les protections de X et ne scrape pas ses pages. Il utilise l'indexation publique de profils X dans Google Actualités RSS, sans compte ni jeton. Cette voie est automatique mais non exhaustive.

Les cibles sont configurées dans [`tools/social_targets.json`](tools/social_targets.json) avec un `search_rss_url`. Les sept profils initiaux couvrent les cinq pays : `@StudioTamani`, `@Malijetactu`, `@maliactu`, `@actuniger`, `@burkina24`, `@ONUMauritanie` et `@tchadinfos`.

Un bridge RSS public que vous contrôlez peut aussi être utilisé avec un `rss_url` par cible ou le modèle `X_RSS_TEMPLATE` :

```bash
X_RSS_TEMPLATE='https://rss.exemple.org/x/{handle}.xml' python tools/update_daily.py
```

Un signal social doit appartenir à l'un des pays suivis, mentionner un élément de conflit, atteindre un seuil renforcé et respecter le même délai de sécurité que les articles. Si une localité de la base est reconnue, il est reporté automatiquement au centre approximatif de cette localité.

## Géolocalisation et carte dynamique

La base [`tools/sahel_places.csv`](tools/sahel_places.csv) contient 346 localités et sièges administratifs issus de [GeoNames](https://download.geonames.org/export/dump/) (CC BY 4.0), avec pays, région, coordonnées et alias. Les coordonnées sont limitées à trois décimales et désignent des centres de localités, jamais des positions tactiques.

```text
GDELT + RSS médias + index public X
                 ↓
nettoyage, dédoublonnage, pays et localité, score de pertinence
                 ↓
délai de sécurité de 2 jours
                 ↓
data/events.geojson + data/events.csv
                 ↓
points + enveloppes de concentration + liste dans le navigateur
```

Les articles sans lieu identifiable restent visibles avec `geometry: null`. Les signaux sont conservés 45 jours afin qu'une panne ponctuelle d'un flux ne vide pas la carte.

## Exécution locale

Python 3.12 ou plus récent suffit ; aucun paquet externe n'est nécessaire.

```bash
python -m unittest discover -s tests -v
python tools/update_daily.py
python tools/validate_data.py
python -m http.server 8000
```

Puis ouvrir `http://localhost:8000`.

Variables optionnelles :

- `LOOKBACK_DAYS` : fenêtre demandée à GDELT, 14 jours par défaut ;
- `RETENTION_DAYS` : conservation des signaux, 45 jours par défaut ;
- `MIN_DAYS_DELAY` : embargo de sécurité, minimum 1 et valeur par défaut 2 jours ;
- `COORD_DECIMALS` : précision des centres de localité, maximum et valeur par défaut 3 ;
- `MAX_PUBLISHED_EVENTS` : maximum de signaux automatiques conservés ;
- `RELEVANCE_THRESHOLD` : seuil de publication, 4 par défaut ;
- `FETCH_GDELT`, `FETCH_RSS` et `FETCH_SOCIAL` : désactivent une famille de sources ;
- `X_RSS_TEMPLATE` : modèle facultatif d'un bridge RSS public avec le marqueur `{handle}`.

## Automatisation GitHub

Le workflow [`.github/workflows/update-map.yml`](.github/workflows/update-map.yml) s'exécute chaque jour. Il lance les tests, collecte les sources publiques, valide les données et commit uniquement les fichiers effectivement modifiés. Aucun secret GitHub n'est requis.

## Fichiers importants

- `data/situation.geojson` : zones et repères de référence revus manuellement ;
- `data/map_context.geojson` : frontières régionales issues de Natural Earth (domaine public) ;
- `data/events.geojson` : signaux publics lus par le frontend ;
- `data/review_candidates.csv` : articles publiés, filtrés ou encore sous délai ;
- `data/source_log.json` : santé et compteurs de chaque collecte ;
- `data/social_watch.json` : watchlist sociale affichée par le frontend ;
- `tools/sahel_places.csv` : centres de localités utilisés pour la géolocalisation ;
- `tools/update_daily.py` : collecte, filtrage et normalisation ;
- `tools/validate_data.py` : garde-fous de publication.

## Prudence OSINT

Ne pas ajouter de positions tactiques, horaires de mouvements, convois, identités personnelles non nécessaires ou informations non publiées. Toute information sensible ou contestée doit rester approximative, datée, sourcée et explicitement qualifiée.
