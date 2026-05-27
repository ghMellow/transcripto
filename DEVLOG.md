# Dev Log — transcripto

Format per entry: data · cosa è stato fatto · problemi incontrati · soluzione · lesson learned.

---

## 2026-05-27 — Aggiunto --batch-transcribe per cartella audio locale

**Done:**

- Aggiunta funzione `batch_transcribe_local(audio_dir, out_dir, lang)` in `pipeline.py`
- Nuovo flag CLI `--batch-transcribe AUDIO_DIR` con `--out-dir` opzionale
- Legge `video_list.json` dalla parent dir per frontmatter YouTube (title, url, channel, duration)
- Fallback a ffprobe se nessun metadata YT disponibile
- Skip automatico se `<stem>.md` già esiste (resume-safe)

**Problemi:**

- Il pipeline YT esistente mandava l'output in `output/IBMTechnology/`, ma l'utente vuole `data/IBMTechnology/transcription/`
- 435 audio già scaricati, serve non ricaricare il modello ad ogni file

**Lesson learned:**

- mlx_whisper carica il modello una volta per processo — basta tenere tutto in un singolo `for` loop nello stesso processo; nessun warm-up esplicito necessario
- `video_list.json` è un dict `{channel_url, videos: [...]}`, non una lista diretta

---

## 2026-05-27 — Refactor SFSpeechRecognizer → mlx-whisper

**Done:**

- Sostituito `transcriber.py`: da PyObjC/SFSpeechRecognizer a mlx-whisper + ffmpeg preprocessing
- Creato `metadata.py`: estrazione metadata locale via ffprobe (title, author, duration, date)
- Aggiornato `pipeline.py`: output con YAML frontmatter Obsidian-compatible
- Aggiornato `pyproject.toml`: rimosso pyobjc, aggiunti mlx-whisper + watchdog
- Rimossi file obsoleti: `transcribe.swift`, `build.sh`, `src/Info.plist`, `src/transcribe.app/`

**Problemi:**

- SFSpeechRecognizer bloccato da macOS 26 TCC — nessun workaround disponibile
- `pyproject.toml` puntava a Python `>=3.13` mentre mlx-whisper richiede `>=3.11` → abbassato il vincolo

**Lesson learned:**

- Su macOS 26 beta le permission TCC per Speech Recognition non sono concedibili via CLI; serve un'app firmata → evitare SFSpeechRecognizer per tool da terminale
- mlx-whisper large-v3-turbo: ~5-8x realtime su M4 Pro, nessuna configurazione Metal richiesta

---

## 2026-05-27 — Watch mode con watchdog

**Done:**

- Sostituito il polling loop (`time.sleep(2)`) con `watchdog.Observer` + `FileSystemEventHandler`

**Problemi:**

- Il polling loop funzionava ma con latenza fissa di 2s e consumo CPU inutile

**Lesson learned:**

- `watchdog.Observer` usa FSEvents su macOS (kernel-level) — latenza ~0, zero CPU a riposo
- `observer.join()` blocca il main thread; Ctrl-C va catturato con `KeyboardInterrupt` per fare `observer.stop()` prima del join finale

---

## 2026-05-27 — YouTube integration

**Done:**

- Creato `yt_scraper.py`: lista video canale via yt-dlp flat-playlist, cache per-canale in `data/<slug>/video_list.json`
- Creato `yt_downloader.py`: batch download .m4a, skip-if-exists, delay 2s tra download
- Aggiornato `pipeline.py`: flag `--youtube` + `--refresh`, frontmatter YouTube distinto (source URL, channel, date_uploaded)
- Struttura dati per-canale: `data/<slug>/audio/` + `output/<slug>/`

**Problemi:**

- `channel_slug()` prendeva l'ultimo segmento del path → su URL tipo `/@IBMTechnology/videos` restituiva `videos` invece di `IBMTechnology` → fix: filtro sui segmenti "noise" (`videos`, `shorts`, `streams`, ecc.)
- yt-dlp crash su timeout CDN Google: `Read timed out` su `googlevideo.com` — **non era rate limit**, era connessione CDN droppata → fix: `socket_timeout=60`, `retries=3`, try/except per-video in `batch_download`
- Dati esistenti in `data/video_list.json` + `data/audio/` (flat) → migrati manualmente a `data/IBMTechnology/`

**Lesson learned:**

- YouTube CDN timeout ≠ rate limit (429). Il rate limit si manifesta come HTTP 429; il timeout CDN è una connessione che si blocca → gestirli diversamente
- yt-dlp `extract_flat=True` per il listing del canale è ordini di grandezza più veloce del full extract
- Importare yt-dlp dentro la funzione (lazy import) mantiene lo startup veloce quando non si usa la modalità YouTube
- La cache per-canale permette stop/resume senza re-fetch della lista (1445 video = chiamata lenta)
