# Logos Benchmark

Misst **TTFT** (Time to First Token), **TTLT** (Time to Last Token) und **GPU-Energieverbrauch** pro Request über drei Szenarien:

| Szenario | Beschreibung |
|---|---|
| `logos-sleep` | Logos mit aktiviertem Sleep Mode (Kapazitätsplaner darf Modelle entladen) |
| `logos-nosleep` | Logos ohne Sleep Mode (Modelle bleiben dauerhaft geladen) |
| `ollama` | Direkt gegen Ollama ohne Logos-Layer |

Jedes Szenario wird in zwei Konfigurationen getestet:
- **2-LLM-Config**: Requests verteilen sich auf 2 Modelle
- **5-LLM-Config**: Requests verteilen sich auf 5 Modelle

---

## Architektur

```
┌──────────────────────────────────────────┐
│  Logos-Host  (benchmark läuft hier)      │
│  ┌──────────────┐   ┌──────────────────┐ │
│  │ benchmark_   │   │   Logos-Server   │ │
│  │ logos.py     │   └────────┬─────────┘ │
│  └──────────────┘            │ HTTP      │
└─────────────────────────────┼────────────┘
                               │ vLLM-API
          ┌────────────────────┼────────────────────┐
          │  GPU-Node A        │       GPU-Node B   │
          │  ┌──────────┐  ┌──┴──────┐ ┌─────────┐ │
          │  │NVML-Poll │  │  vLLM   │ │  vLLM   │ │
          │  │(via SSH) │  │RTX Ada  │ │RTX Ada  │ │
          │  └──────────┘  └─────────┘ └─────────┘ │
          └─────────────────────────────────────────┘
```

**Wichtig:** Die GPU-Energie wird auf den **GPU-Nodes** gemessen, nicht auf dem Logos-Host. Das Benchmark-Script verbindet sich per SSH zu den GPU-Nodes und startet dort einen NVML-Poller, der kontinuierlich Leistungsaufnahme und Energiezähler streamt.

---

## Voraussetzungen

### Logos-Host (wo das Benchmark-Script läuft)

```bash
# Alte pynvml entfernen falls vorhanden
pip uninstall pynvml -y

pip install httpx paramiko numpy matplotlib
```

### GPU-Nodes (einmalig mit Root-Zugriff einrichten)

```bash
pip install nvidia-ml-py
```

Der Remote-Poller (`_REMOTE_POLLER` im Script eingebettet) nutzt dann `nvidia-ml-py` auf den Nodes. Falls `nvidia-ml-py` nicht installiert ist, fällt der Poller automatisch auf `nvidia-smi` zurück — allerdings ohne Hardware-Energiezähler (nur Power-Polling).

### Vorbereitung der Workloads

```bash
pip install datasets  # nur für prepare_benchmark.py benötigt
```

---

## Konfiguration

### `benchmark_config.py`

Zentrales Config-File für beide LLM-Konfigurationen und die Ollama-Namens-Übersetzung:

```python
# Zwei-LLM-Konfiguration
MODELS_2 = [
    "Qwen3-30B-A3B",
    "Llama-3.3-70B",
]

# Fünf-LLM-Konfiguration
MODELS_5 = [
    "Qwen3-30B-A3B",
    "Llama-3.3-70B",
    "Gemma3-4B",
    "microsoft/Phi-4-reasoning",
    "Gemma4-26b",
]

# Übersetzung Logos-Modellname → Ollama-Tag
OLLAMA_MODEL_MAP = {
    "Qwen3-30B-A3B":             "qwen3:30b-a3b",
    ...
}
```

**Vor dem ersten Lauf die Ollama-Tags überprüfen:**
```bash
# Auf dem Ollama-Server:
ollama list
```

---

## Schritt 1 — Workloads vorbereiten

`prepare_benchmark.py` lädt den **openai/gsm8k**-Datensatz von HuggingFace herunter und erzeugt pro LLM-Konfiguration eine Workload-CSV-Datei. Die Modelle werden **gleichmäßig per Round-Robin** über alle Requests verteilt.

```bash
python prepare_benchmark.py [OPTIONEN]
```

### Optionen

| Option | Standard | Beschreibung |
|---|---|---|
| `--split` | `test` | GSM8K-Split: `test` (1 319 Fragen) oder `train` (7 473 Fragen) |
| `--num-samples N` | alle | Nur die ersten N Beispiele verwenden |
| `--rps RATE` | `1.0` | Ankunftsrate in Requests/Sekunde (bestimmt `arrival_offset`) |
| `--max-tokens N` | `512` | `max_tokens` je Request |
| `--output-dir DIR` | `workloads/` | Zielverzeichnis |

### Beispiele

```bash
# 100 Test-Fragen, 0.5 req/s Ankunftsrate
python prepare_benchmark.py --num-samples 100 --rps 0.5

# Alle Test-Fragen, kein Timing (immer mit --sequential verwenden)
python prepare_benchmark.py --rps 0
```

### Ausgabe

```
workloads/
├── workload_gsm8k_2llm.csv    ← 2-Modell-Konfiguration
└── workload_gsm8k_5llm.csv    ← 5-Modell-Konfiguration
```

Jede Zeile enthält:

| Spalte | Bedeutung |
|---|---|
| `request_id` | Eindeutige ID (z. B. `gsm8k-0001`) |
| `arrival_offset` | Geplante Ankunftszeit in ms ab Benchmark-Start |
| `mode` | `interactive` (Logos-Scheduling-Parameter) |
| `priority` | `mid` (Logos-Scheduling-Parameter) |
| `body_json` | Vollständiger OpenAI-Chat-Payload als JSON-String |
| `question` | Original-GSM8K-Frage (Referenz/Auswertung) |
| `answer` | Original-GSM8K-Antwort inkl. Lösungsweg (Referenz/Auswertung) |
| `model_assigned` | Welches Modell diesem Request zugewiesen wurde |

---

## Schritt 2 — Benchmark ausführen

```bash
python benchmark_logos.py --scenario SZENARIO [OPTIONEN] \
    --workload PFAD/ZUR/workload.csv
```

### Optionen

| Option | Standard | Beschreibung |
|---|---|---|
| `--scenario` | `logos-sleep` | Szenario: `logos-sleep`, `logos-nosleep`, `ollama` |
| `--workload CSV` | — | Workload-CSV von `prepare_benchmark.py` |
| `--logos-url URL` | `http://localhost:8080` | Ziel-URL (Logos oder Ollama) |
| `--logos-key KEY` | — | Logos API-Key (erforderlich für `logos-*`-Szenarien) |
| `--sequential` | aus | **Sequentieller Modus** (siehe unten) |
| `--max-concurrent N` | `64` | Max. parallele Requests (ohne `--sequential`) |
| `--request-timeout-s S` | `600` | HTTP-Timeout pro Request |
| `--output-dir DIR` | `benchmark_results/` | Ausgabeverzeichnis |

### GPU-Energie-Optionen

| Option | Standard | Beschreibung |
|---|---|---|
| `--gpu-host HOST [HOST...]` | — | Hostnames der GPU-Nodes (SSH). Typischer Fall: Logos-Szenarien |
| `--gpu-ssh-user USER` | aktueller User | SSH-Benutzername auf den GPU-Nodes |
| `--gpu-ssh-key PATH` | — | Pfad zum SSH-Private-Key |
| `--gpu-ssh-port PORT` | `22` | SSH-Port |
| `--gpu-device-index IDX` | `0` | NVML-GPU-Index auf jedem Remote-Node |
| `--gpu-indices IDX [IDX...]` | — | Lokale GPU-Indices (nur wenn GPU auf diesem Server liegt) |
| `--poll-interval-ms MS` | `100` | GPU-Polling-Intervall (ms) |

`--gpu-host` und `--gpu-indices` schließen sich gegenseitig aus.

---

## `--sequential` — was es bewirkt

### Ohne `--sequential` (Concurrent-Modus, Standard)

Der Benchmark liest die `arrival_offset`-Spalte aus der CSV und sendet Requests zu den darin hinterlegten Zeitpunkten. Wenn mehrere Requests gleichzeitig aktiv sind, kann die GPU parallel für sie arbeiten — genau wie in realistischer Produktionslast.

```
t=0s    Request 1 → [===== vLLM berechnet =====]
t=1s    Request 2 →      [===== vLLM berechnet ======]
t=2s    Request 3 →           [===== vLLM berechnet =====]
                  ↑ Requests überlappen sich auf der GPU
```

**Konsequenz für die Energiemessung:** Der NVML-Energiezähler misst die **gesamte GPU-Energie im Zeitfenster eines Requests** — unabhängig davon, ob andere Requests gleichzeitig laufen. Bei überlappenden Requests wird die GPU-Energie im gemeinsamen Zeitraum von allen beteiligten Requests beansprucht (Doppelzählung in der Summe). Die Einzelwerte sind trotzdem aussagekräftig als "Energie, die während dieses Requests von der GPU verbraucht wurde".

### Mit `--sequential`

Der Benchmark ignoriert die `arrival_offset`-Spalte vollständig. Er sendet **exakt einen Request**, wartet bis der gesamte Stream abgeschlossen ist, und sendet erst dann den nächsten.

```
t=0s    Request 1 → [===== vLLM berechnet =====]
t=5s                                             Request 2 → [===== vLLM berechnet =====]
t=10s                                                                                     Request 3 → ...
                  ↑ Keine Überlappung, GPU idle zwischen Requests
```

**Vorteile:**

- **Exakte Energiezuordnung:** Zwischen zwei Requests ist die GPU (weitgehend) idle. Die Energie zwischen `t_start` und `t_end` stammt vollständig von diesem Request.
- **Reproduzierbarkeit:** Jeder Request startet unter identischen Bedingungen — kein Einfluss durch parallele GPU-Last.
- **Sauberste Vergleichsbasis** zwischen Szenarien: Logos-Sleep vs. -NoSleep vs. Ollama sind unter gleichen Isolationsbedingungen messbar.

**Nachteil:** Bildet keine realistische Produktionslast ab. Für Latenz-unter-Last-Tests sollte `--sequential` weggelassen werden.

### Empfehlung

| Messziel | Modus |
|---|---|
| Energievergleich zwischen Szenarien | `--sequential` ✓ |
| TTFT/TTLT im Einzelbetrieb | `--sequential` ✓ |
| Scheduling-Verhalten unter Last | ohne `--sequential` |
| Latenz bei realistischem Throughput | ohne `--sequential` |

---

## Vollständige Beispiel-Kommandos (alle 6 Runs)

```bash
# ── Schritt 1: Workloads vorbereiten (einmalig) ──────────────────────────
python prepare_benchmark.py --num-samples 200 --rps 0

# ── Szenario 1: Logos mit Sleep Mode ────────────────────────────────────
# Logos-Server vorher mit aktiviertem Sleep Mode konfigurieren/starten

python benchmark_logos.py \
    --scenario logos-sleep \
    --logos-url http://logos.ase.cit.tum.de \
    --logos-key YOUR_KEY \
    --workload workloads/workload_gsm8k_2llm.csv \
    --gpu-host gpu-node-a gpu-node-b \
    --gpu-ssh-user ubuntu --gpu-ssh-key ~/.ssh/id_rsa \
    --sequential --output-dir results

python benchmark_logos.py \
    --scenario logos-sleep \
    --logos-url http://logos.ase.cit.tum.de \
    --logos-key YOUR_KEY \
    --workload workloads/workload_gsm8k_5llm.csv \
    --gpu-host gpu-node-a gpu-node-b \
    --gpu-ssh-user ubuntu --gpu-ssh-key ~/.ssh/id_rsa \
    --sequential --output-dir results

# ── Szenario 2: Logos ohne Sleep Mode ───────────────────────────────────
# Logos-Server vorher mit deaktiviertem Sleep Mode neu starten

python benchmark_logos.py \
    --scenario logos-nosleep \
    --logos-url http://logos.ase.cit.tum.de \
    --logos-key YOUR_KEY \
    --workload workloads/workload_gsm8k_2llm.csv \
    --gpu-host gpu-node-a gpu-node-b \
    --gpu-ssh-user ubuntu --gpu-ssh-key ~/.ssh/id_rsa \
    --sequential --output-dir results

python benchmark_logos.py \
    --scenario logos-nosleep \
    --logos-url http://logos.ase.cit.tum.de \
    --logos-key YOUR_KEY \
    --workload workloads/workload_gsm8k_5llm.csv \
    --gpu-host gpu-node-a gpu-node-b \
    --gpu-ssh-user ubuntu --gpu-ssh-key ~/.ssh/id_rsa \
    --sequential --output-dir results

# ── Szenario 3: Ollama direkt ────────────────────────────────────────────
# Modellnamen werden automatisch via benchmark_config.py übersetzt.
# --gpu-host zeigt hier auf den Ollama-Server selbst.

python benchmark_logos.py \
    --scenario ollama \
    --logos-url http://ollama-host:11434 \
    --workload workloads/workload_gsm8k_2llm.csv \
    --gpu-host ollama-host \
    --gpu-ssh-user ubuntu --gpu-ssh-key ~/.ssh/id_rsa \
    --sequential --output-dir results

python benchmark_logos.py \
    --scenario ollama \
    --logos-url http://ollama-host:11434 \
    --workload workloads/workload_gsm8k_5llm.csv \
    --gpu-host ollama-host \
    --gpu-ssh-user ubuntu --gpu-ssh-key ~/.ssh/id_rsa \
    --sequential --output-dir results
```

---

## Ausgabe

Jeder Lauf erzeugt einen Unterordner in `--output-dir`:

```
results/
└── 20250603_143022_logos-sleep_workload_gsm8k_2llm/
    ├── results_detailed.csv          ← Ein Eintrag pro Request
    ├── results_summary.csv           ← Aggregierte Statistiken (mean/p50/p95/p99)
    ├── run_meta.json                 ← Metadaten (Szenario, GPU-Hosts, Zeitstempel)
    ├── chart_ttft.png                ← TTFT-Verteilung
    ├── chart_ttlt.png                ← TTLT-Verteilung
    ├── chart_energy_per_request.png
    ├── chart_energy_per_token.png
    ├── chart_power_timeline.png      ← GPU-Leistungskurve mit Request-Fenstern
    ├── chart_energy_vs_ttlt.png      ← Scatter: Energie vs. TTLT
    ├── chart_ttft_by_model.png       ← TTFT aufgeteilt nach Modell (Boxplot)
    └── chart_energy_by_model.png     ← Energie aufgeteilt nach Modell (Boxplot)
```

### `results_detailed.csv` — Spalten

| Spalte | Einheit | Beschreibung |
|---|---|---|
| `request_id` | — | Request-ID aus der Workload-CSV |
| `model` | — | Modellname wie vom Server zurückgegeben |
| `scenario` | — | Benchmark-Szenario |
| `ttft_ms` | ms | Time to First Token |
| `ttlt_ms` | ms | Time to Last Token (= Ende des Streams) |
| `tpot_ms` | ms/Token | Time Per Output Token (Decode-Phase) |
| `energy_j` | Joule | GPU-Energie während des Request-Fensters (Summe aller Nodes) |
| `energy_per_token_mj` | mJ/Token | Energie pro Output-Token |
| `throughput_tok_s` | Token/s | Output-Tokens pro Sekunde |
| `prompt_tokens` | — | Anzahl Input-Tokens |
| `completion_tokens` | — | Anzahl Output-Tokens |

---

## Energiemessung — technische Details

### Remote-Poller (SSH)

Bei Verwendung von `--gpu-host` verbindet sich das Script per SSH zu jedem GPU-Node und startet dort einen eingebetteten Python-Poller. Der Poller streamt alle `--poll-interval-ms` Millisekunden eine Zeile:

```
<unix_timestamp> <power_mW> <energy_mJ>
```

Der Poller nutzt in dieser Reihenfolge:
1. `nvmlDeviceGetTotalEnergyConsumption()` — Hardware-Energiezähler (präziseste Methode)
2. `nvmlDeviceGetPowerUsage()` — Leistungsaufnahme für Trapez-Integration
3. `nvidia-smi` — Fallback wenn `nvidia-ml-py` nicht installiert ist

### Primäre Methode: Hardware-Energiezähler

Die RTX Ada 6000 unterstützt `nvmlDeviceGetTotalEnergyConsumption()` — einen monoton steigenden Hardware-Counter in Millijoule. Das Script liest ihn unmittelbar vor und nach jedem Request:

```
E_request = counter_nach_request − counter_vor_request  [mJ → J]
```

Dieser Wert ist **hardware-genau** — kein Zeitfenster zwischen zwei Polls geht verloren.

Mit `--sequential` liest der Benchmark die aktuellsten gepollten Werte vor/nach dem Request. Der maximale Messfehler entspricht dem halben Poll-Intervall (Standard: ±50 ms). Bei Requests die typischerweise 5–60 Sekunden dauern ist das ein Fehler unter 2 %.

### Uhren-Synchronisation

Der Remote-Poller verwendet `time.time()` auf dem GPU-Node. Das Script korrigiert den Unterschied zur lokalen Uhr über eine NTP-artige SSH-Round-Trip-Messung beim Start (einmalig pro Host). Auf gut konfigurierten LAN-Servern (NTP aktiviert) liegt der verbleibende Fehler typischerweise unter 5 ms.

### Mehrere GPU-Nodes

Mit `--gpu-host gpu-node-a gpu-node-b` wird auf **jedem** Node ein Poller gestartet. Die gemessene Energie ist die **Summe** aller Nodes. Das ist korrekt, solange Logos Requests an alle angegebenen Nodes verteilt und auf keinem anderen Node Inference stattfindet.

---

## VRAM-Telemetrie mit ≥1 Hz abfragen

Für Benchmark-Auswertungen liefert der Webservice die VRAM-Daten (identisch zu
den `vram_delta`-Messages des `/api/ws/stats/v2`-WebSockets) auch per REST in
Roh-Auflösung — Cursor-basiertes Polling über `after_snapshot_id`:

```bash
curl -X POST https://<host>:9443/api/logosdb/get_ollama_vram_stats \
  -H "Content-Type: application/json" -H "logos_key: $LOGOS_KEY" \
  -d '{"day": "2026-06-10", "resolution": "second", "after_snapshot_id": 0}'
# → {"providers": [...], "last_snapshot_id": N}; N als after_snapshot_id des
#   nächsten Polls verwenden, um nur neue Samples zu erhalten.
```

Ohne `resolution` wird wie bisher auf Minuten- (Einzeltag) bzw. Stunden-Buckets
("all") heruntergesampelt. Damit tatsächlich sekündliche Samples *entstehen*,
muss der Workernode sie auch sekündlich pushen — in der workernode
`config.yml` für die Benchmark-Phase setzen:

```yaml
worker:
  gpu_poll_interval: 1          # default 5
logos:
  status_refresh_interval_seconds: 1   # default 15
```

---

## Troubleshooting

**`pynvml`-Warning erscheint trotzdem:**
```bash
pip show pynvml          # sollte leer sein
pip uninstall pynvml -y
pip install nvidia-ml-py
```

**SSH-Verbindung zu GPU-Node schlägt fehl:**
```bash
ssh -i ~/.ssh/id_rsa ubuntu@gpu-node-a "nvidia-smi"
# Sollte die GPU-Info ausgeben
```

**Remote-Poller startet nicht (base64/python3 nicht gefunden):**
```bash
# Auf dem GPU-Node prüfen:
which python3
which base64
pip show nvidia-ml-py
```

**Logos antwortet nicht:**
```bash
curl -H "logos_key: YOUR_KEY" http://logos.ase.cit.tum.de/v1/models
```

**Ollama-Modell nicht gefunden (404):**
```bash
# Auf dem Ollama-Server:
ollama list              # exakte Tags prüfen
ollama pull llama3.3:70b # fehlende Modelle pullen
```

**Energiemessung zeigt `not measured`:**
Entweder konnte keine SSH-Verbindung aufgebaut werden, oder `nvidia-ml-py` und `nvidia-smi` sind beide nicht verfügbar. Die detaillierte Fehlermeldung erscheint beim Start des Scripts (Zeilen mit `[gpu]`).
