# Mali Conflict Monitor — sources publiques sans jeton

Mini-site Leaflet statique qui combine :

- une situation de référence, dessinée et vérifiée manuellement ;
- des signaux récents issus de médias et flux publics ;
- une file CSV permettant de revoir tout ce qui a été collecté ou filtré.

Le projet n'utilise plus ACLED, ne demande aucun compte et ne contient aucun secret. Un article est présenté comme un **signal médiatique à vérifier**, jamais comme une confirmation automatique.

## Sources actuelles

Le collecteur interroge GDELT DOC 2.0, Google Actualités RSS, RFI Afrique, France 24 Afrique, ONU Info Afrique, DW Afrique et Le Monde Afrique. Les médias maliens directement ciblés sont Studio Tamani, Journal du Mali, Maliweb, Malijet, MaliActu et Bamada.

La liste se trouve dans [`tools/public_sources.json`](tools/public_sources.json). Pour ajouter un flux RSS public :

```json
{
  "name": "Nom du média",
  "kind": "rss",
  "url": "https://exemple.org/feed.xml",
  "tier": "editorial",
  "language": "fr",
  "enabled": true
}
```

Il est impossible de garantir une couverture littérale de « tous les sites » : certains bloquent les robots, n'ont pas de flux, sont derrière un paywall ou interdisent la réutilisation. GDELT et Google Actualités apportent la couverture large ; les flux directs renforcent les sources locales et institutionnelles.

## Veille X/Twitter sans jeton

X permet d'afficher des profils publics, mais ne fournit pas de flux de découverte RSS officiel et stable sans API. Le monitor ne contourne donc pas les protections de X et ne scrape pas ses pages. Il propose deux niveaux :

- une watchlist publique de comptes locaux dans [`tools/social_targets.json`](tools/social_targets.json) ;
- une ingestion automatique facultative si un flux RSS public et autorisé est indiqué par cible avec `rss_url`, ou fourni par un bridge que vous contrôlez via `X_RSS_TEMPLATE`.

Le modèle d'URL doit contenir `{handle}`, par exemple :

```bash
X_RSS_TEMPLATE='https://rss.exemple.org/x/{handle}.xml' python tools/update_daily.py
```

Un post social doit mentionner le Mali et un élément de conflit, atteindre un seuil renforcé et respecter le même délai de sécurité que les articles. Il reste toujours marqué comme signal à recouper. Les comptes actuellement vérifiés sont `@StudioTamani`, `@Malijetactu` et `@maliactu`.

## Fonctionnement

```text
GDELT + RSS publics
        ↓
nettoyage, dédoublonnage, score de pertinence
        ↓
délai de sécurité de 2 jours
        ↓
data/events.geojson + data/events.csv
        ↓
carte et liste dans le navigateur
```

Les articles sans lieu identifiable restent visibles dans la liste avec `geometry: null`. Quand une localité est reconnue, le point indique seulement son centre approximatif, arrondi à deux décimales. Les signaux sont conservés 45 jours afin qu'une panne ponctuelle d'un flux ne vide pas la carte.

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
- `COORD_DECIMALS` : précision des centres de localité, maximum 3 et valeur par défaut 2 ;
- `MAX_PUBLISHED_EVENTS` : maximum de signaux automatiques conservés ;
- `RELEVANCE_THRESHOLD` : seuil de publication, 4 par défaut ;
- `FETCH_GDELT` et `FETCH_RSS` : permettent de désactiver une famille de sources.
- `FETCH_SOCIAL` : désactive les éventuels flux RSS de réseaux sociaux ;
- `X_RSS_TEMPLATE` : modèle facultatif d'un bridge RSS public avec le marqueur `{handle}`.

## Automatisation GitHub

Le workflow [`.github/workflows/update-map.yml`](.github/workflows/update-map.yml) s'exécute chaque jour. Il :

1. lance les tests unitaires ;
2. collecte les sources publiques ;
3. valide les JSON, URL, géométries et compteurs ;
4. commit uniquement les données effectivement modifiées.

Aucun secret GitHub n'est requis. Si toutes les sources échouent ou si aucune donnée publiable n'existe, le job échoue sans écraser le dernier jeu valide.

## Fichiers importants

- `data/situation.geojson` : zones et positions de référence revues manuellement ;
- `data/events.geojson` : signaux médiatiques lus par le frontend ;
- `data/review_candidates.csv` : articles publiés, filtrés ou encore sous délai ;
- `data/source_log.json` : santé et compteurs de chaque collecte ;
- `data/social_watch.json` : watchlist sociale affichée par le frontend ;
- `tools/mali_places.csv` : centres approximatifs utilisés pour la géolocalisation ;
- `tools/social_targets.json` : comptes sociaux publics ciblés et flux RSS éventuels ;
- `tools/update_daily.py` : collecte et normalisation ;
- `tools/validate_data.py` : garde-fous de publication.

## Prudence OSINT

Ne pas ajouter de positions tactiques, horaires de mouvements, convois, identités personnelles non nécessaires ou informations non publiées. Une zone colorée n'est pas une frontière de contrôle certaine. Toute information sensible ou contestée doit rester approximative, datée, sourcée et explicitement qualifiée.
