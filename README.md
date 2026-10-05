# 🎩 VICTOR Local

**Ton assistant vocal personnel, façon majordome numérique, qui tourne sur ton PC.**

Tu parles à une orbe futuriste. VICTOR te répond à la voix (avec un flegme
impeccable), et il sait vraiment faire des choses :

- 🗣️ **Conversation vocale en temps réel**, en français, avec une détection
  intelligente de fin de phrase (il ne te coupe pas quand tu marques une pause)
  et la possibilité de **l'interrompre** en parlant
- 🛠️ **Vraies tâches sur ta machine** : il lance des sessions **Claude Code**
  (chercher sur internet, analyser des fichiers, écrire du code, créer des
  documents...) et te résume le résultat à voix haute
- 🚀 **Lancer tes applications** : « Ouvre Discord », « Mets Spotify sur
  l'écran de gauche » (multi-écrans géré sous Windows)
- 🌐 **Ouvrir des sites** : « Ouvre mes emails » → Gmail s'ouvre dans ton navigateur
- 📊 **Afficher des rapports** : cartes, indicateurs, graphiques interactifs et
  tableaux directement sur l'interface
- ⌨️ **Écrire au lieu de parler** dans le champ sous l'orbe
- ❌ **Annuler une tâche** à la voix ou d'un clic

### Comment c'est construit

| Rôle | Service | Pourquoi |
|---|---|---|
| 👂 Oreille (transcription) | **Gradium** (Paris, équipe Kyutai) | VAD sémantique : comprend quand tu as fini ta phrase |
| 🧠 Cerveau (conversation + outils) | **Claude Haiku** (API Anthropic) | rapide, très bon pour appeler les outils |
| 🗣️ Voix (synthèse) | **Gradium** | ~50 ms avant le premier son, voix françaises naturelles |
| 🛠️ Bras (vraies tâches) | **Claude Code** (ton abonnement) | fichiers, code, recherches web |

Tout passe par le petit serveur local : **tes clés ne quittent jamais ton PC**.
Par défaut, l'audio est traité sur les serveurs européens de Gradium.

> Le lancement d'applications marche sous Windows (et basiquement sur macOS /
> Linux) ; le placement multi-écrans est **Windows uniquement**. Tout le reste
> (voix, tâches Claude, rapports) marche partout.

---

## 💰 Combien ça coûte ?

| Service | Sert à | Coût approximatif |
|---|---|---|
| **Gradium** | Oreille + voix | Offre gratuite : 1 h d'utilisation par mois. Ensuite dès ~13 $/mois |
| **API Anthropic** | Le cerveau | Paiement à l'usage, quelques centimes pour une conversation (Haiku est le modèle le moins cher). 5 $ de crédit suffisent largement pour découvrir |
| **Claude Pro** | Les tâches Claude Code | ~20 $/mois — si tu utilises déjà Claude Code, tu l'as déjà |

💡 Pour économiser l'heure gratuite de Gradium, VICTOR ne transcrit que
quand ton micro capte un son, et met son « oreille » en veille après 8 secondes
de silence (indiqué en bas de l'écran : *OREILLE ACTIVE / EN VEILLE*).

---

## 📋 Étape 0 — Les prérequis

### uv (gère Python et les dépendances pour toi)

[uv](https://docs.astral.sh/uv/) installe tout seul la bonne version de Python
et les dépendances de VICTOR, dans un environnement isolé : **pas besoin
d'installer Python toi-même**.

1. Installe uv :
   - **Windows** : ouvre PowerShell (touche Windows → tape `powershell` → Entrée) et colle :
     ```
     powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
     ```
   - **macOS / Linux** : dans un terminal :
     ```
     curl -LsSf https://astral.sh/uv/install.sh | sh
     ```
2. **Ferme et rouvre** ton terminal, puis vérifie :
   ```
   uv --version
   ```

### Node.js (nécessaire pour installer Claude Code)

1. Va sur https://nodejs.org et télécharge la version **LTS**
2. Installe en cliquant Suivant partout
3. Vérifie dans un **nouveau** terminal :
   ```
   node --version
   ```

---

## 🧠 Étape 1 — Installer Claude Code (pour les tâches)

1. **Crée un compte Claude** sur https://claude.ai et prends un abonnement
   **Claude Pro** (paramètres → *Upgrade*)
2. **Installe Claude Code** — dans un terminal :
   ```
   npm install -g @anthropic-ai/claude-code
   ```
3. **Connecte-le à ton compte** :
   ```
   claude
   ```
   La première fois, il ouvre ton navigateur pour te connecter. Suis les
   instructions, puis tape `/exit` pour quitter.
4. **Vérifie** :
   ```
   claude -p "Dis bonjour"
   ```
   Si Claude te répond dans le terminal, c'est gagné. ✅

---

## 🔑 Étape 2 — Clé API Anthropic (le cerveau)

⚠️ C'est **différent** de ton abonnement Claude Pro : l'API est un compte
développeur, facturé à l'usage.

1. Va sur https://console.anthropic.com et connecte-toi (même e-mail que
   claude.ai si tu veux)
2. **Ajoute du crédit** : *Settings → Billing* → achète du crédit (5 $ suffisent
   pour commencer). Sans crédit, VICTOR affichera une erreur « credit balance ».
3. **Crée ta clé** : *Settings → API Keys → Create Key* → nomme-la « victor »
4. **Copie la clé immédiatement** (elle commence par `sk-ant-...`) : elle ne
   sera plus jamais affichée. Garde-la secrète, c'est comme un mot de passe.

---

## 🎙️ Étape 3 — Clé API Gradium (l'oreille et la voix)

1. Crée un compte sur https://gradium.ai (offre gratuite, sans carte)
2. Dans ton espace, va dans la section des **clés API** et crée une clé
3. Copie-la et garde-la secrète

---

## ⚙️ Étape 4 — Installer VICTOR

1. **Décompresse ce dossier** où tu veux

2. **Ouvre un terminal dans le dossier** : dans l'Explorateur Windows, ouvre le
   dossier, clique dans la barre d'adresse, tape `cmd` et appuie sur Entrée

3. **Configure tes clés** :
   - Fais une copie du fichier `.env.example` et renomme-la `.env`
     (dans le terminal : `copy .env.example .env`)
   - Ouvre `.env` avec le Bloc-notes et colle tes deux clés (sans espaces, sans
     guillemets) :
     ```
     GRADIUM_API_KEY=ta-cle-gradium
     ANTHROPIC_API_KEY=sk-ant-ta-cle-anthropic
     ```
   - (Fortement conseillé) Décommente `VICTOR_WORKDIR` et mets un dossier dédié
     où VICTOR aura le droit de travailler sur tes fichiers

---

## 🚀 Étape 5 — Lancer VICTOR

Dans le terminal, toujours dans le dossier :

```
uv run server.py
```

La première fois, uv télécharge Python si besoin et installe les dépendances
dans un dossier `.venv` (quelques secondes) ; les fois suivantes, ça démarre
directement.

Puis ouvre ton navigateur (Chrome ou Edge conseillés) sur **http://127.0.0.1:8788**

1. Clique sur l'orbe
2. **Autorise le micro** quand le navigateur le demande
3. Parle !

### Exemples de commandes vocales

- « Bonjour Victor, présente-toi. »
- « Ouvre Discord. » / « Mets Chrome sur l'écran de droite. »
- « Ouvre mes emails. »
- « Liste les fichiers de mon dossier de travail et dis-moi ce qu'il y a dedans. »
- « Cherche les dernières actus IA et fais-moi un résumé. »
- « Affiche-moi un comparatif des 3 meilleurs GPU du moment dans un rapport. »
- « Annule la tâche. »

Pour couper VICTOR au milieu d'une phrase : parle-lui, ou appuie sur **Échap**.
Pour l'arrêter : reclique sur l'orbe, et ferme le terminal (ou Ctrl+C dedans).

🎧 **Conseil** : avec un casque, tout est parfait. Avec des haut-parleurs, le
navigateur supprime l'écho de VICTOR, mais si VICTOR s'interrompt tout seul,
mets `VICTOR_BARGE_IN=0` dans `.env` (tu ne pourras plus le couper à la voix,
seulement avec Échap).

---

## 🌅 Lancer VICTOR au démarrage du PC (Linux)

Une fois que VICTOR marche avec `uv run server.py`, arrête-le (Ctrl+C) puis,
dans le dossier :

```
./installer-demarrage.sh
```

Le script trouve tout seul `uv`, `claude` et `node`, vérifie ton `.env`, puis :
- crée un **service** (`~/.config/systemd/user/victor.service`) qui démarre le
  serveur à l'ouverture de ta session et le relance s'il plante ;
- ajoute une **ouverture automatique** de la page dans ton navigateur
  (`~/.config/autostart/victor.desktop`).

Il te restera à **cliquer sur l'orbe** : les navigateurs exigent un geste de ta
part pour activer le micro et le son. L'autorisation du micro, elle, est
retenue.

| Pour… | Commande |
|---|---|
| voir s'il tourne | `systemctl --user status victor` |
| lire ses messages | `journalctl --user -u victor -f` |
| le relancer (après une modif de `.env`) | `systemctl --user restart victor` |
| retirer le démarrage automatique | `./installer-demarrage.sh --desinstaller` |

> Si tu déplaces le dossier `victor-local`, relance `./installer-demarrage.sh`.
>
> **Windows** : crée un fichier `victor.bat` contenant
> `cd /d "C:\chemin\vers\victor-local" && uv run server.py`, puis place un
> raccourci vers ce fichier dans le dossier de démarrage (touche Windows + R →
> `shell:startup` → Entrée).

---

## 🗂️ Plusieurs assistants AIGORA

Un seul VICTOR peut lancer ses tâches Claude Code dans plusieurs dossiers
(par exemple un espace « business » et un espace « dev »), chacun avec son
propre `CLAUDE.md`, ses skills et ses connecteurs. Déclare-les dans `.env` :

```
VICTOR_ESPACES=business:~/dev/aigora/aigora-business;dev:~/dev/aigora/aigora-dev
VICTOR_ESPACES_DESC=business:mails kSuite, agenda, Odoo, prospection;dev:code R et Python, QGIS, revue de code
```

Dis « côté dev, … » ou « dans l'aigora business, … » ; sinon VICTOR choisit
l'espace d'après le sujet, et te le demande en cas de doute. Le nom de
l'espace s'affiche sur chaque session, à droite de l'interface.
`VICTOR_WORKDIR` reste l'espace par défaut (nommé « defaut » s'il ne fait pas
partie de la liste). Un espace dont le dossier n'existe pas est ignoré, avec
un avertissement dans la console au démarrage.

### Néméton

Si un espace s'appelle `nemeton` (celui qui porte le serveur MCP Néméton),
VICTOR sait piloter les diagnostics forestiers :

- « Où en est le projet Couchey ? » → réponse courte + rapport à l'écran ;
- « Lance le calcul de Couchey » → le calcul part en tâche de fond (il peut
  durer plus d'une heure et survit à la tâche Claude Code) ;
- « Où en est le calcul ? » → progression ;
- « Ouvre la synthèse de Couchey » → l'application s'ouvre sur l'onglet voulu.

L'outil `open_nemeton` n'ouvre **que** `http://127.0.0.1:3838/…` (toute autre
adresse est refusée : elle viendrait d'une tâche qui a pu lire une page web).
Si l'application ne répond pas, il démarre le service `nemetonshiny` :

```ini
# ~/.config/systemd/user/nemetonshiny.service
[Service]
EnvironmentFile=-%h/dev/nemetonshiny/.Renviron
ExecStart=/usr/bin/Rscript -e 'nemetonshiny::run_app(tour = FALSE, options = list(port = 3838, launch.browser = FALSE))'
Restart=on-failure

[Install]
WantedBy=default.target
```

puis `systemctl --user enable --now nemetonshiny`.

---

## 🔧 Personnalisation (fichier `.env`)

| Variable | Défaut | Rôle |
|---|---|---|
| `GRADIUM_API_KEY` | *(requis)* | Clé Gradium (oreille + voix) |
| `ANTHROPIC_API_KEY` | *(requis)* | Clé API Anthropic (cerveau) |
| `VICTOR_TITRE` | `monsieur` | Comment VICTOR t'appelle |
| `VICTOR_GENRE` | selon le titre | Accords au masculin (`m`) ou au féminin (`f`) |
| `VICTOR_VOICE_ID` | Gaspard | Voix Gradium (liste dans `.env.example`). Avec une voix féminine (Apolline, Noémie, Solène), l'assistante s'appelle **VICTORINE** |
| `VICTOR_LANGUAGE` | `fr` | Langue (fr, en, es, de, pt) |
| `VICTOR_MODEL` | `claude-haiku-4-5-20251001` | Modèle Claude du cerveau |
| `GRADIUM_HOST` | `eu.api.gradium.ai` | Serveurs Gradium (Europe par défaut) |
| `VICTOR_STT_DELAY` | `10` | Délai de transcription (7 = rapide, 55 = précis) |
| `VICTOR_TURN_HORIZON` | `1.0` | Fin de phrase : 0.5 (vif) … 3 (patient) |
| `VICTOR_TURN_THRESHOLD` | `0.5` | Certitude de silence requise (0 à 1) |
| `VICTOR_BARGE_IN` | `1` | Interrompre VICTOR en parlant |
| `VICTOR_MIC_THRESHOLD` | `0.02` | Niveau sonore qui réveille l'oreille (0 = toujours active) |
| `VICTOR_STT_IDLE_CLOSE` | `8` | Secondes de silence avant mise en veille de l'oreille |
| `VICTOR_WORKDIR` | dossier utilisateur | Où travaillent les sessions Claude Code |
| `VICTOR_ESPACES` | *(vide)* | Plusieurs espaces de travail : `nom:chemin;nom:chemin` |
| `VICTOR_ESPACES_DESC` | *(vide)* | Une phrase par espace pour aider VICTOR à choisir : `nom:description;…` |
| `VICTOR_TASK_TIMEOUT` | `600` | Durée max d'une tâche (secondes) |
| `VICTOR_PERMISSION_MODE` | `bypassPermissions` | Autorisations des sessions Claude Code (voir Sécurité) |
| `VICTOR_PORT` | `8788` | Port du serveur local |

---

## ❓ Problèmes fréquents

**« GRADIUM_API_KEY / ANTHROPIC_API_KEY manquant »**
→ Le fichier `.env` n'existe pas ou une clé n'est pas dedans. Vérifie qu'il
s'appelle bien `.env` (pas `.env.txt` — active l'affichage des extensions de
fichiers dans l'Explorateur) et relance `uv run server.py`.

**« Claude : … credit balance is too low »**
→ Pas de crédit sur ton compte API Anthropic. Retourne à l'étape 2, point 2.

**« Gradium (transcription) : … » ou « Gradium (voix) : … »**
→ Clé Gradium invalide, quota gratuit épuisé, ou pas d'internet. Le message
affiché donne la vraie raison.

**VICTOR ne réagit pas quand je parle**
→ Regarde en bas de l'écran : si l'oreille reste *EN VEILLE* pendant que tu
parles, ton micro est trop faible : baisse `VICTOR_MIC_THRESHOLD` (ex. `0.01`)
ou mets `0`.

**VICTOR me coupe quand je fais une pause / répond trop lentement**
→ Monte `VICTOR_TURN_HORIZON` à `2` (plus patient) ou descends-le à `0.5`
(plus vif).

**« La commande 'claude' est introuvable » sur les tâches**
→ Claude Code n'est pas installé ou pas connecté. Refais l'étape 1 et vérifie
avec `claude -p "test"` dans un terminal.

**Le micro ne marche pas**
→ Vérifie que tu as bien cliqué "Autoriser" sur la demande du navigateur.
Sinon : icône 🔒/⚙ à gauche de l'adresse → Micro → Autoriser, puis recharge.
En attendant, tu peux écrire à VICTOR dans le champ sous l'orbe.

**Les rapports/graphiques ne s'affichent pas**
→ Il faut une connexion internet (les composants graphiques se chargent en ligne).

**« uv n'est pas reconnu »**
→ Ferme et rouvre ton terminal après l'installation de uv. Si ça persiste,
refais l'étape 0.

**Je préfère pip**
→ C'est possible : avec Python 3.10+ installé, `pip install -r requirements.txt`
puis `python server.py`.

---

## 🔒 Sécurité — à lire

- Tes clés **ne quittent jamais ton PC** : le navigateur parle uniquement au
  serveur local, qui relaie vers Gradium et Anthropic. Ne partage jamais ton
  fichier `.env`.
- Le serveur n'écoute que sur ta machine (127.0.0.1) **et refuse les connexions
  venant d'autres sites web** : une page ouverte dans ton navigateur ne peut pas
  piloter VICTOR à ta place. Ne le mets **jamais** sur internet.
- ⚠️ Les sessions Claude Code tournent **sans demande d'autorisation**
  (`VICTOR_PERMISSION_MODE=bypassPermissions`), car elles n'ont aucune interface
  pour te demander quoi que ce soit. En contrepartie, VICTOR peut écrire,
  supprimer et exécuter des commandes sans te consulter — y compris quand il lit
  des pages web, qui pourraient contenir des instructions piégées.
  **Configure donc `VICTOR_WORKDIR` sur un dossier dédié** (pas ton dossier
  utilisateur). Pour un garde-fou plus strict, mets
  `VICTOR_PERMISSION_MODE=acceptEdits` : les commandes shell seront alors
  refusées au lieu d'être exécutées.

## 📄 Licence

MIT — fais-en ce que tu veux.
