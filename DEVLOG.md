# Dev Log — transcripto

Format per entry: data · cosa è stato fatto · problemi incontrati · soluzione · lesson learned.

---

## 2026-06-04 — Download video YouTube con scelta qualità interattiva

**Done:**

- `--video` su singolo video YouTube: `list_video_formats()` sonda i formati disponibili (senza download), stampa un menu CLI (risoluzione/codec/fps/dimensione stimata), utente sceglie o annulla con `[0]`.
- `download_video()` scarica `bestvideo[height<=N]+bestaudio` mergiati da ffmpeg, container nativo (no re-encode); `--quality N` salta il menu.
- Video salvato in `data/<name>/video/`; audio estratto dal video solo per trascrivere, poi cancellato. Solo singolo video, niente batch di canale.
- **CLI ridisegnata esplicita**: `--youtube` = solo il link, le azioni le decidono i flag. Singolo video: `--transcribe` e/o `--video` (nessuna azione → errore). Canale: trascrizione automatica (unica azione possibile), `--video` su canale → errore. `--transcribe` ora azione esplicita (non più trascrizione implicita per i singoli).
- File video salvato col **titolo pulito** (`_safe_stem`, stesso nome del `.md`) invece dell'id: scaricato sotto l'id poi rinominato, così l'`outtmpl` di yt-dlp resta privo di caratteri del titolo.
- **Feedback di progresso** durante il download: `_make_progress_hook()` (progress_hook yt-dlp) disegna una barra `█░` con % e MB/s, spinner braille come fallback se la size totale è ignota. Usato sia da `download_video` che `download_audio` (prima erano muti tra "Downloading..." e fine). `noprogress:True` sopprime la barra interna di yt-dlp, l'hook fa il rendering nostro.

**Problemi:**

- Gli stream video ad alta risoluzione su YouTube sono video-only (DASH): la `filesize` del formato non include l'audio → stima sottodimensionata.
- 4K/1440p spesso solo VP9/AV1 → file `.webm`/`.mkv`, non `.mp4`.

**Lesson learned:**

- Stima dimensione = filesize video + best audio-only filesize, altrimenti il menu mostra valori fuorvianti.
- Container nativo (no merge_output_format forzato) = nessun re-encode e VLC legge tutto (VP9 da VLC 2.x, AV1 da 3.x); forzare mp4 costerebbe transcodifica lenta e perdita qualità.
- Il tetto di qualità lo decide il video caricato, non yt-dlp: `height<=N` filtra ma non può creare risoluzioni inesistenti.

---

## 2026-05-28 — Single YouTube video support

**Done:**

- Added `fetch_video_info(url)` to `yt_downloader.py` — fetches title, channel, duration, upload date via yt-dlp without downloading
- Added `process_youtube_video()` to `pipeline.py` — mirrors channel flow for a single video
- `--youtube` flag now auto-detects video vs channel by checking for `watch?v=` / `youtu.be/` in the URL

**Lesson learned:**

- No new flag needed — URL pattern is an unambiguous discriminator, keeps the CLI surface minimal

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
