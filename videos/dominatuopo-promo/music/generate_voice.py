"""Genera la locución del promo con Kokoro (TTS local, voz masculina en español).

Uso: python generate_voice.py <modelo.onnx> <voices.bin> <carpeta_salida> [--measure]

Cada plano tiene un conjunto de líneas con su instante de entrada (segundos desde el
inicio del plano). Se genera un WAV por plano (con silencios), listo para colocarse en
el instante de inicio del plano. Con --measure solo se imprime la duración de cada línea.
"""
import json
import subprocess
import sys

import numpy as np
import soundfile as sf
from kokoro_onnx import Kokoro

VOICE = "em_alex"
SPEED = 0.97  # ligeramente pausado = más peso

MODEL, VOICES, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
measure = "--measure" in sys.argv

LINES = json.load(open(OUT + "/../voice_script.json", encoding="utf8"))
k = Kokoro(MODEL, VOICES)
SR = 24000
report = {}
for frame in LINES["frames"]:
    n = frame["n"]
    total = frame["duration"]
    buf = np.zeros(int(SR * (total + 2)))
    rep = []
    for line in frame["lines"]:
        s, sr = k.create(line["text"], voice=VOICE, speed=line.get("speed", SPEED), lang="es")
        assert sr == SR
        dur = len(s) / SR
        i = int(line["t"] * SR)
        if i + len(s) > len(buf):
            buf = np.pad(buf, (0, i + len(s) - len(buf)))
        buf[i : i + len(s)] += s
        rep.append({"t": line["t"], "dur": round(dur, 2), "end": round(line["t"] + dur, 2), "text": line["text"]})
    report[n] = rep
    if not measure:
        raw = f"{OUT}/raw_{n:02d}.wav"
        sf.write(raw, buf[: int(SR * total)], SR)
        # carácter "imponente": calidez en graves, compresión y un poco de aire; normalizado
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", raw, "-af",
             "highpass=f=70,equalizer=f=140:t=q:w=1.0:g=4,equalizer=f=3200:t=q:w=1.2:g=2,"
             "acompressor=threshold=-20dB:ratio=3.5:attack=8:release=140:makeup=4,"
             "aecho=0.8:0.5:55:0.12,volume=5.5dB,alimiter=limit=0.95:level=disabled:attack=3:release=40,aresample=44100",
             f"{OUT}/voice_{n:02d}.wav"],
            check=True,
        )
print(json.dumps(report, ensure_ascii=False, indent=1))
