# Gelochip - Unified Chip Design Workspace

Workspace untuk desain IC analog/RF yang menggabungkan **Gelochip Studio**, **AnoaChip Auto Layouter**, dan **PandaChip Auto Schematic Maker** dalam satu repository.

> Fokus integrasi ini: menyatukan source dan riwayat branch di `main`, menjaga konfigurasi serta artefak desain, dan menyediakan pintu masuk localhost. Ketiga engine memakai runtime masing-masing; transfer netlist antar engine masih manual.

## Tiga aplikasi, satu repository

| Aplikasi | Peran | Lokasi source | URL lokal |
|---|---|---|---|
| Workspace Portal | Navigasi dan pemeriksaan ketersediaan backend | `integration/` | http://localhost:8080 |
| Gelochip Studio | Agent desain analog/RF, building blocks, layout dan verifikasi | `app/`, `src/gelochip/` | http://localhost:8090 |
| AnoaChip | Auto Layouter: SPICE, simulasi spesifikasi, Glayout GDSII, DRC/LVS | `modules/AnoaChip/` | http://localhost:5175 (API :8012) |
| PandaChip | Auto Schematic Maker: schematic xschem, netlist, simulasi OpenADA | `modules/PandaChip/` | http://localhost:8317 |

```text
Gelochip/
|-- integration/          Portal localhost dan pemeriksaan integrasi
|-- modules/
|   |-- AnoaChip/          Source ZIP AnoaChip beserta data dan dokumentasinya
|   `-- PandaChip/         Source ZIP PandaChip beserta desain dan OpenADA
|-- app/                  Gelochip Studio (FastAPI + React)
|-- src/gelochip/          Agent, GLayout, primitive, blok analog/RF
|-- scripts/              Script Gelochip dan kontribusi RF Wilton
|-- tests/                Tes Gelochip
|-- outputs/              Artefak lama, tetap di lokasi asal
|-- Tapeout/              Artefak tapeout dari main
|-- tapeout_iris/          Desain dan bukti pemeriksaan IRIS
|-- report/               Laporan desain
`-- integration-audit/    Baseline checksum dan catatan penggabungan
```

## Mulai dari portal localhost

Portal hanya membutuhkan Python 3.10+ dan dapat dijalankan di Windows, Linux, atau WSL:

```powershell
python integration/portal.py
```

Buka **http://localhost:8080**. Jalankan aplikasi yang dibutuhkan di terminal terpisah dengan petunjuk di bawah. Status portal menunjukkan apakah backend dapat diakses; status tersebut bukan hasil DRC/LVS atau bukti keberhasilan desain.

## Menjalankan Gelochip Studio

Gunakan Linux/WSL2 untuk alur EDA. Dari root repository:

```bash
python3 -m venv .venv-studio
source .venv-studio/bin/activate
python -m pip install -r requirements-app.txt
# Buat .env hanya bila belum ada, kemudian sesuaikan provider dan PDK.
[ -f .env ] || cp .env.example .env
export PYTHONPATH="$PWD/src:$PWD/src/gelochip${PYTHONPATH:+:$PYTHONPATH}"
cd app/frontend
npm ci
npm run dev
```

Di terminal lain, aktifkan `.venv-studio`, tetapkan `PYTHONPATH` yang sama dari root, lalu jalankan:

```bash
python -m uvicorn app.kaizen_app:app --host 127.0.0.1 --port 8090
```

Frontend development berada di **http://localhost:5173**. Untuk menyajikan frontend dari backend :8090, build frontend memakai `npm run build`; perintah bawaan Vite memperbarui `app/static/web/`. **Jangan menjalankan build tersebut jika ingin mempertahankan hasil build lama tanpa perubahan.** Alternatif container tersedia di [panduan Docker](docs/DOCKER.md) bila file tersebut tersedia; lihat juga `Dockerfile` dan `docker-compose.yml`.

## Menjalankan AnoaChip Auto Layouter

AnoaChip mempertahankan `pyproject.toml`, `uv.lock`, dan struktur aslinya. Dependensi Glayout di ZIP menunjuk ke **`../gLayout`**, sehingga dari lokasi baru checkout tersebut harus berada di **`modules/gLayout/`**. Source `src/gelochip/glayout/` bukan otomatis pengganti package Glayout eksternal yang diminta AnoaChip.

Pada Linux/WSL2, siapkan checkout Glayout yang kompatibel di lokasi tersebut, kemudian:

```bash
cd modules/AnoaChip
[ -f .env ] || cp .env.example .env
bash scripts/install.sh
cd frontend
npm ci
cd ..
bash scripts/run.sh
```

Script installer melakukan download dependensi, model dan PDK, serta dapat memasang build tools melalui `sudo`. Periksa kebutuhan mesin sebelum menjalankannya. Backend menggunakan :8012, frontend :5175. README ZIP memiliki sebagian contoh port lama; konfigurasi Vite dan script run memakai port yang dicantumkan di sini.

Lihat [README AnoaChip](modules/AnoaChip/README.md) untuk knowledge store Postgres/MinIO, model, konfigurasi, dan pipeline layout.

## Menjalankan PandaChip Auto Schematic Maker

Gunakan Linux/WSL2 dengan Docker, Node.js/npm, Go 1.18+, Python, uv, dan Ollama. Runtime EDA menggunakan container `pandachip-eda`; schematic interaktif memerlukan X display sesuai script asal.

```bash
cd modules/PandaChip
uv venv .venv --python python3
uv pip install --python .venv/bin/python -e ./src jsonschema numpy matplotlib
cd frontend
npm ci
cd ..
bash scripts/start_eda_container.sh
bash scripts/run.sh
```

Buka **http://localhost:8317**. Pemilihan model dan kredensial Gemini/Vertex AI mengikuti [README PandaChip](modules/PandaChip/README.md). Model dengan suffix `:cloud` memerlukan akses cloud; menjalankan website pada localhost tidak berarti modelnya offline.

## Alur kerja lintas aplikasi

1. Buat schematic dan netlist melalui PandaChip.
2. Periksa port, model transistor, tegangan perangkat, dan PDK netlist.
3. Gunakan netlist beserta spesifikasi sebagai masukan alur AnoaChip atau Gelochip. Sesuaikan format input melalui fasilitas masing-masing aplikasi.
4. Tinjau hasil simulasi, DRC, LVS, serta GDSII dari run yang sama sebelum menyatakan desain lolos.

Saat ini belum ada API bersama, konversi otomatis schematic-ke-layout, akun bersama, atau antrean pekerjaan lintas aplikasi. Portal menghubungkan aplikasi yang sudah disatukan dalam repo. Aplikasi menyimpan hasil pada lokasi bawaan masing-masing, sehingga artefak lama tidak harus dipindah.

## Branch dan aturan pemeliharaan

- `main` lokal diselaraskan dengan `origin/main`, lalu perubahan `dev_wilton` digabungkan menggunakan merge agar riwayat kontribusi tetap ada.
- `origin/dev_irman` dan `origin/dev_ken` sudah menjadi ancestor dari `origin/main`; tidak perlu menyalin ulang kontribusinya.
- Branch asal tetap disimpan. Penggabungan lokal tidak otomatis melakukan push ke GitHub.
- `info.yaml`, `config.json`, `lvs_config.json`, folder output, laporan, dan artefak tapeout yang dilindungi diperiksa dengan SHA-256. Kapitalisasi nama file asli dipertahankan.
- Folder lama tetap berada di lokasi semula. File yang ada di checkout Wilton tetapi tidak ada di main dipertahankan juga.
- ZIP dipisahkan di `modules/` agar nama file, konfigurasi dan versi dependensi tidak saling menimpa.
- `node_modules` bawaan ZIP tersedia di disk, tetapi tidak perlu ditambahkan sebagai dependensi source baru. Gunakan lockfile dan `npm ci` untuk instalasi sesuai platform.

## Validasi integrasi

```bash
python integration/verify_preservation.py
python -m unittest discover -s integration -p "test_*.py" -v
```

Tes portal memeriksa halaman, endpoint status, penanganan layanan offline, dan penolakan akses file di luar endpoint. Audit penggabungan ada di [catatan integrasi](integration-audit/MERGE.md).

Tes Gelochip membutuhkan dependensi EDA/agent yang sudah terpasang:

```bash
PYTHONPATH=src:src/gelochip python -m pytest tests
```

Keberhasilan merge dan tes portal belum membuktikan pipeline LLM, simulasi, DRC/LVS, atau tapeout berhasil. Kebutuhan runtime harus tersedia sebelum pengujian desain menyeluruh.

## Arah hosting cloud

Struktur ini dapat menjadi dasar pemisahan layanan web, worker EDA, penyimpanan artefak dan model. Sebelum deployment publik, perlu konfigurasi reverse proxy, autentikasi, isolasi worker, storage persisten dan pengujian layanan. Portal saat ini bind ke loopback dan ditujukan untuk penggunaan lokal.

## Lisensi dan asal source

Lisensi Gelochip tersedia di [LICENSE](LICENSE). AnoaChip membawa [lisensinya sendiri](modules/AnoaChip/LICENSE). OpenADA yang disertakan PandaChip memiliki [LICENSE](modules/PandaChip/src/LICENSE). Pertahankan atribusi dan lisensi komponen masing-masing. Dokumentasi asli Gelochip main tersimpan di [arsip README](integration-audit/README-origin-main.md).
