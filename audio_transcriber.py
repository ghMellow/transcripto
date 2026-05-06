#!/usr/bin/env python3
"""
audio_transcriber.py
Flusso:
  1. Converti MP4 → MP3 con VLC
  2. Aspetta che l'utente trascini l'MP3 in Apple Note e ottenga la trascrizione
  3. Recupera il testo dalla nota (cercata per nome file) tramite AppleScript
  4. Salva la trascrizione in un file .md
"""

import subprocess
import sys
import re
from pathlib import Path

# ── CONFIGURAZIONE ─────────────────────────────────────────────────────────────
VLC_PATH = "/Applications/VLC.app/Contents/MacOS/VLC"

# Nome della cartella in Apple Note dove tieni le trascrizioni audio
# Cambia con il nome esatto della tua cartella/notebook in Note
NOTES_FOLDER = "Note"           # oppure es. "Trascrizioni Audio"
NOTES_ACCOUNT = "iCloud"        # oppure "On My Mac" se usi note locali

# Cartella di output per i file .md (di default stessa cartella dell'MP4)
OUTPUT_DIR = None  # es: OUTPUT_DIR = Path.home() / "Documenti" / "Trascrizioni"
# ──────────────────────────────────────────────────────────────────────────────


def converti_mp4_in_mp3(mp4_path: Path) -> Path:
    """Usa VLC da riga di comando per estrarre l'audio come MP3."""
    mp3_path = mp4_path.with_suffix(".mp3")
    print(f"\n🎬 Conversione: {mp4_path.name} → {mp3_path.name}")

    cmd = [
        VLC_PATH,
        str(mp4_path),
        "--intf", "dummy",                     # nessuna GUI
        "--sout",
        (
            f"#transcode{{acodec=mp3,ab=192,channels=2,samplerate=44100}}"
            f":std{{access=file,mux=raw,dst={mp3_path}}}"
        ),
        "vlc://quit",
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)

    if not mp3_path.exists():
        print("❌ VLC non ha generato il file MP3. Controlla il percorso di VLC.")
        print("   Stderr:", result.stderr[:500])
        sys.exit(1)

    print(f"✅ MP3 creato: {mp3_path}")
    return mp3_path


def leggi_nota_per_nome(nome_nota: str) -> str:
    """
    Cerca in Apple Note una nota il cui titolo corrisponde al nome_nota
    e ne restituisce il corpo (testo pulito dall'HTML).
    """
    # Il titolo della nota in Apple Note di solito coincide con il nome del file
    # audio che hai trascinato dentro (senza estensione).
    applescript = f"""
    tell application "Notes"
        set targetFolder to folder "{NOTES_FOLDER}" of account "{NOTES_ACCOUNT}"
        set allNotes to notes of targetFolder
        repeat with n in allNotes
            if name of n contains "{nome_nota}" then
                return body of n
            end if
        end repeat
        return "NOTA_NON_TROVATA"
    end tell
    """
    result = subprocess.run(
        ["osascript", "-e", applescript],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def pulisci_html(testo_html: str) -> str:
    """Rimuove tag HTML e decodifica entità comuni."""
    testo = re.sub(r"<[^>]+>", " ", testo_html)
    testo = testo.replace("&nbsp;", " ").replace("&amp;", "&")
    testo = testo.replace("&lt;", "<").replace("&gt;", ">")
    testo = re.sub(r" +", " ", testo)
    testo = re.sub(r"\n{3,}", "\n\n", testo)
    return testo.strip()


def salva_markdown(testo: str, mp3_path: Path) -> Path:
    """Salva la trascrizione in un file .md."""
    base = mp3_path.stem  # nome senza estensione
    if OUTPUT_DIR:
        out_dir = Path(OUTPUT_DIR)
    else:
        out_dir = mp3_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    md_path = out_dir / f"{base}.md"
    md_path.write_text(f"# {base}\n\n{testo}\n", encoding="utf-8")
    return md_path


def main():
    # ── 1. Input del file MP4 ───────────────────────────────────────────────
    if len(sys.argv) > 1:
        mp4_path = Path(sys.argv[1])
    else:
        raw = input("📂 Inserisci il percorso del file MP4: ").strip().strip("'\"")
        mp4_path = Path(raw)

    if not mp4_path.exists():
        print(f"❌ File non trovato: {mp4_path}")
        sys.exit(1)

    # ── 2. Conversione MP4 → MP3 con VLC ────────────────────────────────────
    mp3_path = converti_mp4_in_mp3(mp4_path)

    # ── 3. Pausa: l'utente trascina l'MP3 in Apple Note ─────────────────────
    print(f"\n⏸  Ora trascina manualmente il file MP3 in Apple Note:")
    print(f"   → {mp3_path}")
    print("   Aspetta che la trascrizione venga completata da Note.")
    print("\n   Premi Y per continuare (la trascrizione è pronta)")
    print("   Premi N per interrompere lo script\n")

    while True:
        scelta = input("Scelta [Y/N]: ").strip().upper()
        if scelta == "Y":
            break
        elif scelta == "N":
            print("🛑 Script interrotto.")
            sys.exit(0)
        else:
            print("   Digita Y oppure N.")

    # ── 4. Recupero trascrizione da Apple Note ───────────────────────────────
    nome_nota = mp3_path.stem  # es: "riunione_2026-05-06"
    print(f"\n🔍 Cerco la nota '{nome_nota}' in Apple Note (cartella: {NOTES_FOLDER})...")

    corpo_html = leggi_nota_per_nome(nome_nota)

    if not corpo_html or corpo_html == "NOTA_NON_TROVATA":
        print("⚠️  Nota non trovata automaticamente.")
        print("   Possibili motivi:")
        print("   • Il titolo della nota non corrisponde al nome del file MP3")
        print("   • La cartella in NOTES_FOLDER non è quella giusta")
        print("   • La trascrizione non è ancora terminata")
        print("\n   Puoi copiare il testo manualmente e incollarlo qui sotto.")
        print("   (Incolla il testo, poi premi Invio due volte per terminare)\n")
        righe = []
        while True:
            riga = input()
            if riga == "" and righe and righe[-1] == "":
                break
            righe.append(riga)
        testo_finale = "\n".join(righe).strip()
    else:
        testo_finale = pulisci_html(corpo_html)
        print("✅ Trascrizione recuperata da Apple Note.")

    if not testo_finale:
        print("❌ Nessun testo da salvare. Uscita.")
        sys.exit(1)

    # ── 5. Salvataggio in Markdown ───────────────────────────────────────────
    md_path = salva_markdown(testo_finale, mp3_path)
    print(f"\n💾 Trascrizione salvata in:\n   {md_path}")
    print("\n✨ Fatto!")


if __name__ == "__main__":
    main()
