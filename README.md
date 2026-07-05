# Mali Conflict Monitor — base Wikipédia actuelle

Mini-site Leaflet statique pour afficher une carte interactive de la situation générale au Mali.

## Utilisation

1. Mets tous les fichiers à la racine de ton dépôt GitHub.
2. Active GitHub Pages sur `main / root`.
3. Ouvre le lien GitHub Pages.

## Fichiers importants

- `index.html` : structure du site.
- `style.css` : design.
- `script.js` : logique de la carte, filtres, popups.
- `data/situation.geojson` : base de la situation actuelle.

## Modifier la situation

Tout se passe dans :

```text
data/situation.geojson
```

Chaque objet peut être :

- `layer: "zone"` pour une zone d'influence approximative ;
- `layer: "point"` pour une ville / position générale ;
- `layer: "event"` pour un événement récent.

## Sécurité / prudence

Cette carte est volontairement non opérationnelle : elle ne doit pas afficher de positions tactiques, horaires de mouvements, convois, ou informations non publiées par des sources ouvertes.
