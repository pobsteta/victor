# BRIEF — Pilotage de la vidéo tutoriel Nemeton par VICTOR / AIGORA

Brief de pilotage : VICTOR (ou AIGORA depuis RStudio) déroule le plan de production
de la vidéo « Nemeton : analyser un territoire forestier en 8 minutes », séquence
par séquence, en s'appuyant sur le serveur MCP de nemetonshiny (≥ 0.155.0) et les
scripts du kit de production (`capture_nemetonshiny.R`, `enregistrement_playwright.js`).

## Prérequis

- nemetonshiny ≥ 0.155.0 (serveur MCP : `lancer_calcul`, `etat_calcul`,
  `generer_rapport`, `exporter_gpkg`, `url_app`, `lister_projets`, `resume_projet`,
  `annuler_calcul`)
- Kit de production présent dans `~/dev/nemeton-video/` (scripts du kit Vibe)
- Node + Playwright installés (`npm install playwright && npx playwright install chromium`)
- Un projet de démo importé dans l'app (ex. la forêt communale de Marsannay-la-Côte)

## Rôle de VICTOR

VICTOR **orchestre**, il ne capture pas : la vidéo est enregistrée par Playwright
(headless) et les captures sortent du package R. VICTOR :

1. vérifie l'état (app lancée ? projet présent ? calcul fini ?) via MCP ;
2. déclenche chaque action au bon moment du storyboard ;
3. annonce l'avancement à la voix (utile si vous enregistrez en parallèle) ;
4. journalise chaque étape dans `captures/journal.txt` pour le montage.

## Déroulé pas à pas

### Étape 0 — Vérifications (avant tout)
- `lister_projets()` → le projet de démo doit apparaître. Sinon : demander à
  l'utilisateur d'importer ses parcelles avant de continuer.
- `url_app()` → noter l'URL ; la passer au script Playwright (variable `appUrl`).

### Étape 1 — Séquences 1, 2 (visuels animés)
- Ouvrir `visuels-animes.html` (scènes 1 et 2). VICTOR lance OBS ou demande à
  Playwright d'enregistrer la fenêtre (touches 1, 2, R).
- Journaliser : `S1 OK`, `S2 OK`.

### Étape 2 — Séquence 3 (installation)
- Aucune action MCP : réutiliser les captures RStudio existantes ou en refaire
  une avec OBS. VICTOR peut dicter les 3 commandes d'installation à la voix.

### Étape 3 — Séquence 4 (démo 30 secondes)
- Exécuter dans R : `data(massif_demo_units)` puis
  `nemeton_radar(massif_demo_units, unit_id = 1, mode = "family")`.
- Le PNG sort via le kit (`04-radar-parcelle1.png`). Journaliser : `S4 OK`.

### Étape 4 — Séquence 5 (workflow 6 étapes)
- Dérouler les 6 fonctions dans R via AIGORA (claude code) ; Playwright enregistre
  la session RStudio si demandé. Journaliser : `S5 OK`.

### Étape 5 — Séquence 7 (l'app, cœur du pilotage MCP)
VICTOR pilote l'app **sans interface**, pendant que Playwright enregistre la
fenêtre navigateur ouverte sur `url_app()` :

1. `lancer_calcul(projet = "<démo>")` → attendre `etat_calcul()` == terminé
   (VICTOR interroge toutes les 5 s, timeout 10 min) ;
2. `generer_rapport(projet = "<démo>")` → capture du rapport PDF ;
3. `exporter_gpkg(projet = "<démo>")` → capture de l'export ;
4. Playwright prend les captures d'écran intermédiaires (`07-*.png`) pendant
   que l'interface reflète les états.

### Étape 6 — Séquences 6, 8 (visuels animés)
- Scènes 6 et 8 de `visuels-animes.html` (barres NDP, écran de fin). `S6 OK`.

### Étape 7 — Assemblage
- VICTOR lance le montage semi-automatique : importer voix off (ElevenLabs,
  prompts du kit), `sous-titres.srt`, captures et animations dans DaVinci
  Resolve (ou assemblage FFmpeg scripté si vous préférez zéro logiciel GUI).

## Garde-fous

- Ne jamais lancer deux calculs simultanés (`annuler_calcul` disponible).
- Toute erreur MCP → VICTOR l'annonce à la voix et s'arrête ; jamais de repli
  silencieux (règle des briefs existants).
- Vérifier le compte d'indicateurs (31 vs 41) avant l'étape 7.

## Journal de production (`captures/journal.txt`)

Format : une ligne par événement, champs séparés par ` | `, horodatage ISO 8601 local :

```
<timestamp> | <séquence> | <action> | <statut> | <détail>
```

- `<séquence>` : `S0` à `S7` (numéro d'étape du déroulé ci-dessus)
- `<action>` : verbe court (`lancer_calcul`, `etat_calcul`, `capture`, `animation`…)
- `<statut>` : `OK`, `ERREUR`, `ATTENTE` (pour les sondes `etat_calcul`)
- `<détail>` : paramètre utile + fichier produit le cas échéant (`fichier=07-04-calcul.png`)

Exemple :

```
2026-10-28T14:32:05 | S5 | lancer_calcul | OK | projet=marsannay
2026-10-28T14:32:10 | S5 | etat_calcul | ATTENTE | en_cours
2026-10-28T14:33:42 | S5 | etat_calcul | OK | termine
2026-10-28T14:33:45 | S5 | capture | OK | fichier=07-04-calcul.png
```

Règles :

- Une ligne aussi pour les erreurs, jamais de repli silencieux : l'action est
  consignée, puis VICTOR s'arrête et l'annonce à la voix.
- En fin de production, VICTOR écrit `captures/resume-rushes.txt` : pour chaque
  rush, le timecode approximatif du storyboard (celui du `.srt`), le fichier
  produit et la séquence — c'est la liste de courses du montage DaVinci Resolve.
- Le journal est en ajout (`>>`), jamais tronqué en cours de route.

## Bonus — Victor comme voix off

VICTOR possédant une voix (Gradium) : il peut dicter les textes de voix off du
storyboard, séquence par séquence, pendant que vous enregistrez sa sortie audio.
Qualité à tester contre ElevenLabs avant de choisir.
