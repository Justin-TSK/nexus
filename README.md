# Nexus — Agent IA personnel (Bot Telegram)

**Nexus** est ton assistant personnel pour étudiant en informatique : il reçoit des
**messages texte**, des **vocaux** (transcription + réponse) et des **fichiers** (PDF,
images, code) via Telegram. Grâce au *function calling* Gemini, il décide lui-même
d'appeler ses intégrations : **Gmail**, **iCloud Mail**, **Google Agenda**, **Notion**,
**Spotify**, **Perplexity** et ton **carnet de contacts**.

Personnalité : professionnel, encourageant, geek et complice ; réponses concises,
adaptées à l'affichage smartphone, avec des emojis pertinents.

## Fonctionnalités

| Type | Action |
|------|--------|
| 📝 Texte | Conversation avec mémoire, contexte par utilisateur |
| 🎤 Vocal | Transcription automatique (Gemini) puis réponse |
| 📄 Fichiers | PDF / images / code (`.py`, `.txt`, `.md`, `.js`, …) : résumé + aide |
| 📧 Gmail | Trier / résumer / **rédiger et envoyer** des mails (stages, profs) |
| 🍎 iCloud Mail | Lister, compter les non-lus, lire (IMAP) |
| 🗓️ Google Agenda | Lister les événements à venir, **planifier** cours / examens / révisions |
| 📘 Notion | Résumés de cours, fiches de révision, To-Do list |
| 🎧 Spotify | Concentration (Lo-fi, Deep Focus), morceau en cours, play/pause/next, file |
| 🔎 Perplexity | Recherche web sourcée : bugs, algorithmique, veille techno |
| 🌤️ Météo | Prévisions actuelles et à venir (ville par défaut : Moscou) |
| 👤 Contacts | Chercher / ajouter un contact (liste locale JSON) |
| /traduire | Traduction via DeepL (docs techniques, articles, PDF) |
| /tools | Liste les intégrations actives |
| /reset | Efface la mémoire de conversation |

> Exemples : *« quels mails non lus j'ai ? »*, *« ajoute ce sujet de TD dans mes notes
> Notion »*, *« planifie 2h de révision vendredi à 14h »*, *« cherche comment corriger ce
> bug en Python »*, *« mets du Lo-fi pour travailler »*

## Démarrage rapide (local)

```bash
# 1. Créer le venv et installer les dépendances
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 2. Renseigner vos clés
cp .env.example .env   # puis éditez le fichier

# 3. (Optionnel mais recommandé) ffmpeg pour convertir les vocaux
# macOS : brew install ffmpeg   |   Debian/Ubuntu : sudo apt install ffmpeg

# 4. Lancer
python main.py
```

> **Important** : créez le bot avec [@BotFather](https://t.me/BotFather) et récupérez le token.
> Les clés Gemini s'obtiennent sur [Google AI Studio](https://aistudio.google.com/apikey).
> DeepL sur [DeepL API](https://www.deepl.com/pro-api). DeepL est optionnel.

## Configuration (.env)

Toutes les options sont documentées dans `.env.example` : token, clés API, modèle Gemini,
langue de transcription, liste blanche d'utilisateurs (`ALLOWED_USER_IDS`), mode
`polling` ou `webhook`.

**Sécurité** : renseignez `ALLOWED_USER_IDS` avec votre ID Telegram (via
[@userinfobot](https://t.me/userinfobot)) pour réserver le bot à vous seul.

## Connecter les intégrations

### Notion
1. Créez une intégration sur [notion.so/my-integrations](https://www.notion.so/my-integrations) → copiez le token.
2. **Partagez vos pages avec l'intégration** : sur chaque page (et les pages parentes),
   menu `•••` → *Connexions* → ajouter l'intégration. Sans ça, Nexus ne voit pas les pages privées.
3. Deux façons de stocker les notes :
   - **Base de données** : créez une base (vue Table) pour les notes, partagez-la, puis
     mettez `NOTION_DATABASE_ID` (l'ID dans l'URL) dans `.env`.
   - **Page existante** (pratique avec vos pages privées) : mettez `NOTION_PARENT_PAGE_ID`
     (l'ID de la page dans l'URL) — Nexus créera chaque note comme **sous-page**.
4. Renseignez `NOTION_TOKEN` + l'une des deux zones ci-dessus dans `.env`.

> Pour récupérer un ID : l'URL d'une page Notion est `notion.so/<nom>-<32 caractères>` —
> l'ID est la série de 32 caractères.

### Gmail
1. Sur [Google Cloud Console](https://console.cloud.google.com) : créez un projet,
   activez l'API **Gmail**, puis `Identifiants` → créer un **ID client OAuth** de type
   *Application de bureau* → téléchargez le `client_secret.json` dans `credentials/`.
2. Mettez `GOOGLE_CLIENT_SECRET_FILE` dans `.env`.
3. Lancez `python scripts/auth_setup.py google` : un navigateur s'ouvre, autorisez le compte.

### Google Agenda
1. Dans le **même** projet Cloud, activez l'API **Google Calendar** (même fichier
   `client_secret.json`, rien d'autre à télécharger).
2. Lancez `python scripts/auth_setup.py calendar` pour autoriser l'agenda.

### Perplexity
1. Créez une clé API sur [console.perplexity.ai/settings/api](https://console.perplexity.ai/settings/api).
2. Renseignez `PERPLEXITY_API_KEY` dans `.env` (modèle réglable via `PERPLEXITY_MODEL`).

### iCloud Mail
1. Créez un **mot de passe d'application** sur [appleid.apple.com](https://appleid.apple.com)
   (Connexion & Sécurité → Mot de passe d'application).
2. Renseignez `ICLOUD_EMAIL` (adresse @icloud.com/@me.com) et `ICLOUD_APP_PASSWORD` dans `.env`.

### Spotify
1. Créez une app sur [developer.spotify.com/dashboard](https://developer.spotify.com/dashboard).
2. Ajoutez `http://127.0.0.1:8888/callback` dans *Redirect URIs*.
3. Renseignez `SPOTIFY_CLIENT_ID` / `SPOTIFY_CLIENT_SECRET` dans `.env`.
4. Lancez `python scripts/auth_setup.py spotify`.

> Le contrôle de lecture Spotify nécessite un compte **Premium** et un appareil actif.

## Architecture

```
.
├── main.py              # point d'entrée (polling / webhook) + logs
├── config.py            # chargement .env + validation
├── core/
│   └── agent.py         # orchestration, boucle de function-calling, mémoire par utilisateur
├── services/
│   ├── gemini.py        # conversation, transcription audio, analyse de fichiers
│   ├── deepl.py         # traduction (optionnel)
│   ├── media.py         # téléchargement + conversion ffmpeg + types de fichiers
│   ├── google_auth.py   # OAuth Google (Gmail + Agenda)
│   ├── icloud.py        # iCloud Mail via IMAP
│   └── contacts_store.py# contacts locaux (JSON)
├── tools/
│   ├── registry.py      # BaseTool + registry (conversion en déclarations Gemini)
│   ├── gmail.py         # 📧 Gmail
│   ├── calendar.py      # 🗓️ Google Agenda
│   ├── icloud.py        # 🍎 iCloud Mail
│   ├── notion.py        # 📘 Notion
│   ├── spotify.py       # 🎧 Spotify
│   ├── perplexity.py    # 🔎 Perplexity (recherche web)
│   ├── weather.py       # 🌤️ Météo (wttr.in, sans clé)
│   └── contacts.py      # 👤 Contacts
├── scripts/
│   └── auth_setup.py    # OAuth interactif (Google + Spotify)
└── bot/
    ├── app.py           # montage de l'Application + registry d'outils
    └── handlers.py      # commandes + messages (texte, vocal, fichiers)
```

## Ajouter une intégration (pattern)

1. Créez `tools/mon_service.py` avec une classe héritant de `BaseTool`
   (`name`, `description`, `parameters`, `async run()`).
2. Option : un service sous `services/` pour la logique d'accès.
3. Enregistrez l'outil dans `build_registry()` (`bot/app.py`).

Gemini appelle automatiquement l'outil dès que la demande de l'utilisateur correspond à
sa description. Ajoutez le libellé dans la commande `/tools` si souhaité.

## Déploiement VPS

Prérequis sur le serveur : Python 3.11+, `ffmpeg` (pour les vocaux),
`sudo apt install -y ffmpeg`.

```bash
# Sur le serveur
sudo useradd -r -s /usr/sbin/nologin nexus
sudo mkdir -p /opt/nexus && sudo chown nexus:nexus /opt/nexus
git clone <votre-depot> /opt/nexus        # ou scp du dossier (sans .env/.venv)
cd /opt/nexus && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
sudo -u nexus cp /tmp/.env /opt/nexus/.env   # vos secrets + ALLOWED_USER_IDS
# IMPORTANT : copiez aussi credentials/ (tokens Gmail/Agenda/Spotify) et data/ vers /opt/nexus
sudo cp deploy/nexus.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now nexus
sudo systemctl status nexus
```

- **Mode polling** (simple, aucun domaine requis) : `BOT_MODE=polling` (défaut).
  Redémarrage automatique géré par systemd (`Restart=always`).
- **Mode webhook** (si vous avez un domaine HTTPS, ex. nginx + certbot) :
  `BOT_MODE=webhook` avec `WEBHOOK_URL` et `WEBHOOK_PORT`, et un reverse proxy vers le port.

## Roadmap

- [x] Gmail (lecture, recherche, rédaction, envoi)
- [x] iCloud Mail (IMAP)
- [x] Google Agenda (planning cours/examens/révisions)
- [x] Notion (résumés, fiches, To-Do)
- [x] Spotify (concentration + contrôle playback)
- [x] Perplexity (recherche web sourcée)
- [x] Météo (ville par défaut : Moscou)
- [x] Contacts (liste locale)
- [ ] Planning automatique selon l'emploi du temps
