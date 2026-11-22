# NÉO — Nouvel Équipier Opérationnel

Assistant pédagogique intelligent **local, autonome et open source**, conçu pour accompagner un formateur pendant ses sessions de formation (en présentiel ou à distance) sur un PC Windows standard (8 Go de RAM, CPU uniquement, sans GPU ni dépendance cloud).

---

## Fonctionnalités principales

- **100 % local et confidentiel** : écoute exclusivement sur `http://127.0.0.1:7860`, communique uniquement avec votre instance **Ollama** locale (`http://127.0.0.1:11434`). Aucun appel cloud, aucune clé API, aucune télémétrie.
- **Capture microphone légère & VAD CPU** : détection des microphones Windows (`sounddevice`), test de niveau sonore, détection d'activité vocale (VAD) et segmentation sérialisée (1 seul segment traité à la fois pour préserver RAM et CPU).
- **Transcription locale Faster-Whisper** : exécution CPU quantifiée (`int8`, langue française). **Aucun modèle n'est téléchargé automatiquement** : vous choisissez explicitement quand installer un modèle. Suppression automatique des WAV temporaires après traitement.
- **Moteur comportemental déterministe** : indépendant du LLM, applique les modes (`ACTIF`, `PASSIF`, `SUR_DEMANDE`, `OFF`), le cooldown configurable, les interruptions immédiates, le filtrage hors sujet, la gestion d'incertitude et l'anti-répétition.
- **Voix locale française (Piper TTS CPU)** : synthèse vocale 100 % hors ligne via **Piper TTS** avec chargement paresseux, déchargement automatique en RAM, lecture par blocs interruptible en moins de 50 ms et zéro fichier audio conservé.
- **3 modes vocaux** :
  - `SILENCIEUX` : NÉO analyse et propose uniquement à l'écrit.
  - `ASSISTANT` : NÉO prépare ses propositions et ne parle que lorsque vous cliquez sur **« Faire prononcer par NÉO »**.
  - `AUTONOME` : NÉO ne prend la parole que si le moteur comportemental autorise l'intervention et qu'aucun humain ne parle.
- **Priorité absolue d'interruption (`Formateur > Apprenants > NÉO`)** : toute détection de parole humaine au micro (VAD) ou tout clic sur le bouton global **« STOP VOIX »** coupe immédiatement la voix de NÉO sans jamais arrêter le micro, le VAD ou le STT.
- **Restitution claire pour le formateur** : séparation nette entre *suggestions privées destinées au formateur* et *réponses validées pour les apprenants*.
- **Mode démonstration (10 scénarios)** : permet de tester sans microphone le comportement déterministe et Ollama réel.

---

## Architecture du projet

```text
neo/
├── app/
│   ├── main.py                     # Point d'entrée FastAPI / Uvicorn (127.0.0.1:7860)
│   ├── runtime.py                  # Conteneur applicatif modulaire
│   ├── api/                        # Routes REST (dashboard, session, audio, tts, modèles, config)
│   ├── core/                       # Moteur comportemental déterministe, décisions, état, événements
│   ├── ai/                         # Client Ollama HTTP local, prompts compacts, parseur JSON strict
│   ├── audio/                      # Capture sounddevice, VAD énergie, file bornée, Faster-Whisper STT
│   ├── tts/                        # Moteur local Piper TTS, gestion voix FR, sanitizeur, worker audio
│   ├── config/                     # Schéma Pydantic et persistance dashboard_config.json
│   ├── services/                   # Services transcription, pédagogie, TTS, diagnostic
│   ├── static/                     # CSS & JavaScript natifs (zéro framework lourd)
│   └── templates/dashboard.html    # Interface web locale
├── models/voices/                  # Voix françaises Piper (.onnx + .onnx.json), ignorées par Git
├── tools/piper/                    # Optionnel : binaire piper.exe Windows autonome, ignoré par Git
├── scripts/check_env.py            # Vérification de l'environnement Python & TTS
├── tests/                          # Suite de tests pytest
├── pytest.ini
├── requirements.txt
├── requirements-dev.txt
├── run.bat
└── README.md
```

---

## Prérequis

- **Système** : Windows 10 ou Windows 11 (ou Linux/macOS compatible Python).
- **Matériel** : 8 Go de RAM, processeur Intel ou AMD (aucun GPU requis).
- **Python** : version **3.11** ou supérieure.
- **Ollama** : installé localement pour l'intelligence pédagogique (optionnel : le moteur déterministe continue de fonctionner même si Ollama est arrêté).

---

## Installation pas à pas sous Windows

### 1. Cloner le dépôt

```bash
git clone <URL_DU_DEPOT_GITHUB>
cd neo
```

### 2. Créer l'environnement virtuel Python et installer les dépendances

```cmd
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Pour exécuter également les tests :

```cmd
pip install -r requirements-dev.txt
```

### 3. Installer Ollama et un modèle léger (compatible 8 Go de RAM)

1. Téléchargez et installez Ollama depuis [https://ollama.com](https://ollama.com).
2. Vérifiez qu'Ollama tourne localement (`http://127.0.0.1:11434`).
3. Téléchargez explicitement un modèle léger quantifié (1B à 2B recommandé sur 8 Go RAM) :

```cmd
ollama pull llama3.2:1b
```
*(ou `qwen2.5:1.5b` / `gemma2:2b` — aucun modèle n'est imposé ni téléchargé par NÉO).*

### 4. Installer le moteur TTS local (Piper) et une voix française

NÉO est compatible avec **deux méthodes 100 % locales** (choisissez la plus simple sous Windows 11) :

#### Option A — Binaire autonome officiel Windows (`piper.exe`) *(recommandé sous Windows 11 / Python 3.11+)*
1. Téléchargez l'archive `piper_windows_amd64.zip` depuis les releases officielles de Piper (`rhasspy/piper` sur GitHub).
2. Décompressez le contenu dans le dossier `neo/tools/piper/` afin d'avoir `neo/tools/piper/piper.exe` (et ses DLL associées dans le même dossier).
3. Vous pouvez aussi placer `piper.exe` dans votre `PATH` Windows ou définir la variable `PIPER_EXE_PATH`.

#### Option B — Module Python (`piper-tts`)
Si votre architecture Python dispose d'un wheel compatible :
```cmd
.venv\Scripts\activate
pip install piper-tts
```

#### Installer une voix française (jamais automatique au démarrage)
- **Depuis le dashboard** : ouvrez l'onglet **Voix de NÉO**, sélectionnez par exemple `fr_FR-siwis-medium` *(recommandée 8 Go RAM, ~63 Mo)* ou `fr_FR-gilles-low` *(~18 Mo)*, puis cliquez sur **Installer la voix sélectionnée**.
- **Procédure 100 % hors ligne (sans connexion Internet sur le PC cible)** : copiez manuellement les deux fichiers `<nom_voix>.onnx` et `<nom_voix>.onnx.json` dans `neo/models/voices/`, puis cliquez sur **Actualiser** dans l'onglet **Voix de NÉO**.

---

## Lancement

Double-cliquez sur `run.bat` ou lancez depuis le terminal :

```cmd
.venv\Scripts\activate
python -m uvicorn app.main:app --host 127.0.0.1 --port 7860
```

Ouvrez ensuite dans votre navigateur :

**http://127.0.0.1:7860**

---

## Configuration recommandée pour 8 Go de RAM (budget simultané)

Lorsque **Faster-Whisper + Ollama + Piper TTS** tournent sur une machine de 8 Go de RAM sans GPU, respectez cette configuration recommandée :

| Composant | Choix recommandé 8 Go RAM | Empreinte RAM estimée |
|---|---|---|
| Windows 11 + navigateur | — | ~2,5 à 3,2 Go |
| Faster-Whisper (CPU `int8`) | `tiny` (~75 Mo) ou `base` (~145 Mo) — `small` (~460 Mo) si marge suffisante | ~250 à 700 Mo |
| Ollama local (quantifié Q4) | `llama3.2:1b` ou `qwen2.5:1.5b` | ~1,2 à 1,8 Go |
| Piper TTS (CPU ONNX) | `fr_FR-siwis-medium` (~63 Mo) ou `fr_FR-gilles-low` (~18 Mo) | ~90 à 180 Mo (déchargée auto après inactivité) |

Bonnes pratiques intégrées par NÉO :
- Un seul segment audio traité à la fois (pas de parallélisme incontrôlé).
- Déchargement automatique du modèle TTS après inactivité (`tts_auto_unload_seconds`, 120 s par défaut) et bouton **Libérer la RAM TTS**.
- Déchargement des modèles STT et TTS lors de l'arrêt de session ou du passage en mode `OFF`.

---

## Procédure de test audio (micro + voix)

1. Ouvrez l'onglet **Audio & STT**, sélectionnez votre microphone (casque/micro-cravate recommandé en salle pour limiter l'écho), puis cliquez sur **Tester le microphone (1,2 s)**.
2. Ouvrez l'onglet **Voix de NÉO**, cochez **Activer la voix locale de NÉO**, vérifiez que votre voix française apparaît comme **Installée**, puis cliquez sur **Tester la voix**.
3. Vérifiez que le bouton permanent **STOP VOIX** dans la barre supérieure interrompt immédiatement la lecture de test.
4. Démarrez une session en mode vocal `ASSISTANT` avant de passer éventuellement en mode `AUTONOME`.

---

## Désinstaller un modèle vocal ou STT

- **Voix Piper** : dans l'onglet **Voix de NÉO**, sélectionnez la voix et cliquez sur **Désinstaller cette voix** (ou supprimez les fichiers `.onnx` / `.onnx.json` dans `neo/models/voices/`).
- **Modèle Whisper** : supprimez le dossier correspondant dans `%USERPROFILE%\.cache\huggingface\hub\models--Systran--faster-whisper-*`.
- **Modèle Ollama** : exécutez `ollama rm <nom_du_modele>`.

---

## Tests automatisés

Exécuter toute la suite de tests unitaires (sans matériel ni téléchargement) :

```cmd
pytest -m "not real_hardware"
```

Exécuter les tests incluant le matériel/modèles réels présents sur votre PC :

```cmd
pytest -m real_hardware
```

---

## Dépannage

- **Ollama déconnecté** : vérifiez qu'Ollama est démarré (`ollama serve`) et accessible sur `http://127.0.0.1:11434`. NÉO reste fonctionnel en mode déterministe même sans Ollama.
- **Aucun microphone détecté** : vérifiez les autorisations microphone Windows (*Paramètres > Confidentialité et sécurité > Microphone*) puis cliquez sur **Actualiser** dans *Audio & STT*.
- **Moteur Piper introuvable** : vérifiez la présence de `neo/tools/piper/piper.exe` (avec ses DLL) ou l'installation de `piper-tts` dans `.venv`.
- **Voix française absente ou invalide** : assurez-vous que les deux fichiers `<voix>.onnx` et `<voix>.onnx.json` sont bien présents dans `neo/models/voices/`.
- **Aucune sortie sonore TTS** : vérifiez le périphérique de sortie audio Windows par défaut et le niveau du curseur **Volume** dans *Voix de NÉO*.
- **NÉO s'auto-interrompt sur haut-parleurs** : utilisez de préférence un casque ou baissez le volume des haut-parleurs / augmentez légèrement le *Seuil d'énergie VAD* dans *Audio & STT*.
- **Latence élevée sur 8 Go RAM** : choisissez un modèle Ollama `1B`–`1.5B`, le modèle STT `tiny` ou `base`, et une voix `low` ou `medium`.

---

## Licences & confidentialité

- **Application NÉO** : licence MIT (`LICENSE`).
- **Moteur Piper TTS** : licence MIT (`rhasspy/piper`).
- **Voix françaises Piper** : modèles open source distribués sous licences libres (MIT / Open Speech / CC-BY selon la voix choisie, affichées dans l'onglet *Voix de NÉO*).
- **Confidentialité** : bind réseau strict sur `127.0.0.1`, aucun appel cloud, suppression automatique des fichiers audio temporaires, micro coupé à l'arrêt de session ou en mode `OFF`.
