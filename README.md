# Mali Conflict Monitor

Mini-site Leaflet pour créer une carte OSINT évolutive sur la situation sécuritaire au Mali.

Cette version contient maintenant une **automatisation quotidienne avancée** : GitHub Actions lance un script Python tous les jours, récupère les événements ACLED, produit `data/events.geojson`, puis republie la carte via GitHub Pages.

## Structure

```text
index.html
style.css
script.js
requirements.txt

data/
  events.geojson              # fichier lu par la carte
  events.csv                  # export tableur des événements publiés
  manual_events.geojson       # événements manuels conservés à chaque mise à jour
  review_candidates.csv       # signaux GDELT/ReliefWeb à relire
  source_log.json             # résumé de la dernière exécution
  zones.geojson               # zones dessinées manuellement

tools/
  update_daily.py             # automatisation ACLED + GDELT + ReliefWeb
  convert_csv_to_geojson.py   # convertisseur simple CSV -> GeoJSON
  mali_places.csv             # petit dictionnaire de lieux pour géocoder les articles

.github/workflows/
  update-map.yml              # mise à jour quotidienne automatique
```

## Lancer en local

Ne double-clique pas simplement sur `index.html`, car le navigateur peut bloquer le chargement des fichiers GeoJSON locaux.

```bash
cd mali_conflict_monitor
python3 -m http.server 8000
```

Puis ouvre :

```text
http://localhost:8000
```

## Fonctionnement de l'automatisation

Le pipeline est :

```text
ACLED API + GDELT + ReliefWeb
        ↓
tools/update_daily.py
        ↓
data/events.geojson + data/events.csv + data/review_candidates.csv
        ↓
GitHub Actions commit les nouveaux fichiers
        ↓
GitHub Pages affiche la carte mise à jour
```

### Source principale : ACLED

ACLED est la source publiée automatiquement sur la carte, parce que ses événements sont déjà structurés avec date, lieu, acteurs, type d'événement et coordonnées.

Le script interroge le pays `Mali` sur une fenêtre glissante de 10 jours. Par défaut il applique `MIN_DAYS_DELAY=1`, donc il ne publie pas les événements du jour même. C'est volontaire : la carte reste analytique et non opérationnelle.

### Sources secondaires : GDELT et ReliefWeb

GDELT et ReliefWeb sont utilisés pour créer `data/review_candidates.csv`.

Ils servent à repérer des articles/signaux récents à relire, mais ils ne sont pas publiés directement sur la carte car leur géolocalisation est moins fiable qu'ACLED.

## Configuration GitHub

### 1. Crée un dépôt GitHub

Mets tous les fichiers à la racine du dépôt.

### 2. Active GitHub Pages

Dans GitHub :

```text
Settings → Pages → Deploy from a branch → main → /root
```

### 3. Crée un compte myACLED

ACLED demande un compte pour l'accès API. Crée un compte, puis ajoute les identifiants dans les secrets GitHub.

### 4. Ajoute les secrets GitHub

Dans ton dépôt :

```text
Settings → Secrets and variables → Actions → New repository secret
```

Ajoute :

```text
ACLED_USERNAME       ton email myACLED
ACLED_PASSWORD       ton mot de passe myACLED
```

Optionnel :

```text
ACLED_ACCESS_TOKEN   si tu utilises un jeton Bearer au lieu du login/mot de passe
RELIEFWEB_APPNAME    nom d'application ReliefWeb, ex: mali-conflict-monitor
```

### 5. Lance un premier test manuel

Dans GitHub :

```text
Actions → Update Mali Conflict Monitor → Run workflow
```

Si tout marche, GitHub va modifier automatiquement :

```text
data/events.geojson
data/events.csv
data/review_candidates.csv
data/source_log.json
```

## Horaire de mise à jour

Le fichier `.github/workflows/update-map.yml` contient :

```yaml
schedule:
  - cron: '37 6 * * *'
```

Cela lance la mise à jour tous les jours à 06:37 UTC, soit environ 08:37 à Paris en heure d'été.

## Modifier les paramètres

Dans `.github/workflows/update-map.yml` :

```yaml
LOOKBACK_DAYS: '10'
MIN_DAYS_DELAY: '1'
COORD_DECIMALS: '3'
FETCH_GDELT: 'true'
FETCH_RELIEFWEB: 'true'
```

- `LOOKBACK_DAYS` : nombre de jours repris à chaque exécution. 10 évite de rater une correction tardive.
- `MIN_DAYS_DELAY` : 1 évite de publier des événements le jour même.
- `COORD_DECIMALS` : 3 arrondit les points pour éviter une précision inutilement tactique.
- `FETCH_GDELT` / `FETCH_RELIEFWEB` : true/false selon ce que tu veux récupérer en candidats.

## Ajouter des événements manuels

Ajoute-les dans `data/manual_events.geojson`. Ils seront fusionnés à chaque mise à jour automatique et ne seront pas écrasés.

## Ajouter des zones

Les zones doivent rester dans `data/zones.geojson` et être dessinées/validées manuellement.

Important : une zone de contrôle ou d'influence au Mali peut être contestée ou changer rapidement. Il faut toujours indiquer une date, une fiabilité et une note.

## Règles éditoriales recommandées

Cette carte doit rester analytique :

- pas de positions tactiques précises en temps réel ;
- pas de mouvement de convois non publics ;
- pas de checkpoints actifs ou d'informations exploitables immédiatement ;
- pas de données personnelles ;
- toujours citer la source ;
- marquer les revendications non vérifiées comme telles ;
- dater chaque événement et chaque zone ;
- garder une trace des événements GDELT/ReliefWeb dans `review_candidates.csv` avant publication manuelle.

## Dépannage rapide

### La carte reste vide

Vérifie l'onglet GitHub `Actions`. Si le script indique `ACLED_USERNAME/ACLED_PASSWORD absents`, il faut ajouter les secrets.

### GitHub Actions ne se lance pas

Le workflow doit être dans :

```text
.github/workflows/update-map.yml
```

Et le dépôt doit avoir de l'activité au moins périodiquement pour éviter la désactivation des workflows planifiés sur certains dépôts publics inactifs.

### ReliefWeb renvoie une erreur d'appname

ReliefWeb recommande/nécessite un `appname`. Mets un secret `RELIEFWEB_APPNAME` avec une valeur simple comme `mali-conflict-monitor` ou le nom de ton domaine.
