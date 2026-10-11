# Gelochip - Unified Chip Design Workspace

Workspace untuk desain IC analog/RF yang menggabungkan **Gelochip Studio**, **AnoaChip Auto Layouter**, dan **PandaChip Auto Schematic Maker** dalam satu repository.

> Fokus integrasi ini: menyatukan source dan riwayat branch di `main`, menjaga konfigurasi serta artefak desain, dan menyediakan pintu masuk localhost. Ketiga engine memakai runtime masing-masing; transfer netlist antar engine masih manual.

## Gambaran proyek

Gelochip dikembangkan sebagai platform berbasis web untuk membantu proses desain integrated circuit (IC) analog dan radio frequency (RF), mulai dari spesifikasi rangkaian hingga peninjauan layout dan bukti verifikasinya. Proyek ini menyatukan kemampuan pembuatan schematic dari PandaChip, pembuatan layout dari AnoaChip, serta agent dan pustaka blok analog/RF dari Gelochip Studio.

Bagian awal README ini disusun sebagai pengantar konsep proyek dengan gaya dokumen B100: menjelaskan latar belakang, masalah, tujuan, konsep solusi, dan batas pengembangan. Bagian ini bukan dokumen B100 formal yang mengikuti template institusi tertentu. Petunjuk instalasi dan penggunaan tersedia setelah penjelasan konsep.

## Latar belakang

Desain IC analog/RF melibatkan beberapa pekerjaan yang saling bergantung. Spesifikasi perlu diterjemahkan menjadi topologi rangkaian dan ukuran perangkat; schematic kemudian menghasilkan netlist untuk simulasi. Setelah perilaku rangkaian diperiksa, perangkat ditempatkan dan dihubungkan dalam layout sesuai aturan process design kit (PDK). Layout perlu diperiksa melalui design rule checking (DRC) dan layout versus schematic (LVS), serta dievaluasi kembali bila parasitik memengaruhi hasil desain.

Dalam alur yang memakai beberapa alat terpisah, perancang harus menjaga konsistensi spesifikasi, koneksi, model perangkat, pilihan PDK, dan versi berkas pada setiap tahap. Ketika schematic berubah, netlist, simulasi, dan layout terkait perlu ditinjau ulang. Pemindahan berkas dan konfigurasi secara manual dapat membuat hasil dari versi desain yang berbeda tercampur atau membuat pekerjaan harus diulang.

Repository ini telah memiliki beberapa bagian dari alur tersebut, tetapi kemampuan yang dibutuhkan tersebar di branch pengembangan dan proyek yang berbeda. PandaChip berfokus pada schematic xschem dan simulasi, AnoaChip menyediakan alur layout berbasis Glayout, sedangkan Gelochip menyediakan agent dan blok desain analog/RF. Penggabungan source menjadi langkah awal untuk membangun alur kerja bersama tanpa menghilangkan konfigurasi, hasil eksperimen, dan artefak desain yang sudah ada.

Penggunaan AI diarahkan untuk membantu menerjemahkan spesifikasi, menghasilkan rancangan awal, dan mendukung iterasi. Keputusan bahwa suatu desain memenuhi persyaratan tetap harus didasarkan pada hasil simulasi, pemeriksaan aturan, dan bukti kesesuaian rangkaian. Karena itu, platform perlu menampilkan hasil alat EDA dan asal artefaknya bersama hasil yang dihasilkan agent.

## Rumusan masalah

1. Bagaimana menyatukan kemampuan schematic, simulasi, layout, dan verifikasi dari tiga engine dalam satu website?
2. Bagaimana mempertahankan konsistensi netlist, port, model perangkat, tegangan, dan PDK saat desain berpindah tahap?
3. Bagaimana mengelola revisi desain, pekerjaan yang berjalan, log, dan artefak agar hasil pemeriksaan merujuk ke versi desain yang tepat?
4. Bagaimana menyediakan penggunaan awal di localhost dan mempersiapkan hosting cloud tanpa mengubah konfigurasi serta artefak lama?

## Tujuan dan manfaat yang diharapkan

Tujuan utama proyek adalah menghasilkan **satu website Gelochip dengan satu workspace proyek** untuk menjalankan alur desain analog/RF dari spesifikasi, schematic, dan simulasi hingga layout serta verifikasi.

Pengembangan diarahkan untuk mengurangi pemindahan berkas antar aplikasi, membantu pengguna menelusuri hubungan antara schematic dan layout, serta memudahkan peninjauan hasil simulasi dan laporan DRC/LVS. Bagi tim pengembang, struktur bersama diharapkan memudahkan pemeliharaan kontribusi dan penambahan engine tanpa mencampurkan lingkungan dependensinya. Manfaat tersebut merupakan sasaran pengembangan; peningkatan waktu pengerjaan atau kualitas desain belum diukur dalam integrasi saat ini.

## Pengguna dan kebutuhan utama

Pengguna yang dituju adalah peserta Chipathon, mahasiswa, peneliti, dan pengembang yang mengerjakan desain IC analog/RF dengan alat EDA terbuka.

| Kebutuhan pengguna | Respons sistem yang ditargetkan |
|---|---|
| Memulai desain dari spesifikasi | Form atau percakapan untuk memasukkan fungsi rangkaian, target kinerja, dan batasan desain |
| Membuat dan meninjau rangkaian | Workspace schematic dengan netlist, parameter perangkat, dan hasil simulasi |
| Melanjutkan rangkaian ke layout | Penghubung antar engine yang memeriksa kecocokan input sebelum menjalankan layout |
| Memahami hasil pemeriksaan | Viewer artefak, status pekerjaan, log, dan laporan simulasi/DRC/LVS dalam proyek yang sama |
| Mengulang desain setelah revisi | Riwayat versi dan hubungan antara input, run, serta hasil yang dihasilkan |
| Menjalankan pada mesin sendiri | Pengoperasian localhost dengan konfigurasi model dan runtime EDA yang sesuai |

## Konsep solusi

Solusi yang diusulkan menggunakan satu antarmuka web dan API penghubung untuk mengoordinasikan engine yang tetap memiliki runtime masing-masing. PandaChip menangani pembuatan schematic, AnoaChip menangani otomatisasi layout, dan Gelochip menyediakan kemampuan desain serta blok analog/RF sesuai kebutuhan alur.

Satu proyek menyimpan spesifikasi, pilihan PDK, revisi desain, dan hubungan antar artefak. Sebelum melanjutkan pekerjaan ke engine berikutnya, penghubung memeriksa format input dan kompatibilitas desain. Setiap pekerjaan menghasilkan status eksekusi dan bukti pemeriksaan yang dapat ditinjau pengguna; pekerjaan yang selesai dijalankan belum tentu memenuhi seluruh spesifikasi desain.

```text
Pengguna
   -> Satu website dan workspace proyek Gelochip
      -> Spesifikasi dan pilihan PDK
      -> PandaChip: schematic, netlist, dan simulasi
      -> AnoaChip / Gelochip: layout GDSII
      -> Simulasi terkait layout, DRC, dan LVS
      -> Peninjauan laporan dan artefak
      -> Revisi desain bila diperlukan
```

Arsitektur ini adalah arah pengembangan. Implementasi saat ini baru menyatukan source dan menyediakan portal akses; API penghubung dan alur otomatis lintas engine belum tersedia.

## Ruang lingkup dan batasan

Ruang lingkup proyek mencakup integrasi aplikasi, pengelolaan proyek dan artefak, penghubung schematic-ke-layout, serta penyajian hasil simulasi dan verifikasi untuk desain analog/RF pada PDK yang didukung engine terkait. Dukungan suatu PDK atau topologi harus diperiksa pada alur yang benar-benar digunakan; tidak semua kombinasi otomatis didukung oleh seluruh engine.

Tahap pertama berfokus pada localhost. Hosting cloud menjadi tahap berikutnya setelah alur terpadu diuji. Pemilihan model lokal atau cloud tidak mengubah kebutuhan terhadap runtime EDA, model perangkat, dan rule deck yang sesuai. Platform juga tidak menjamin desain siap fabrikasi hanya karena agent selesai atau berkas GDSII berhasil dibuat; keputusan tapeout memerlukan peninjauan dan persyaratan signoff yang berlaku untuk desain tersebut.

Pengembangan wajib mempertahankan `info.yaml`, `config.json`, serta folder dan artefak yang sudah ada seperti `OUTS`/`outputs`. Source engine dapat dihubungkan melalui komponen tambahan tanpa menimpa konfigurasi atau memindahkan hasil desain lama.

## Indikator keberhasilan dan kondisi saat ini

| Indikator | Kondisi saat ini | Target akhir |
|---|---|---|
| Source dan kontribusi branch berada di main | Sudah digabungkan secara lokal | Struktur bersama dapat dipelihara dan dikembangkan |
| Konfigurasi dan artefak lama terjaga | Audit baseline integrasi lulus | Tetap terlindungi selama pengembangan berikutnya |
| Akses aplikasi melalui web | Portal localhost tersedia | Satu antarmuka untuk seluruh tahap desain |
| Perpindahan schematic/netlist ke layout | Masih manual | Transfer otomatis dengan pemeriksaan kompatibilitas |
| Hubungan revisi, run, dan hasil pemeriksaan | Belum terpadu lintas engine | Setiap hasil dapat ditelusuri ke input dan versi desainnya |
| Pengujian desain menyeluruh | Belum dijalankan pada lingkungan integrasi ini | Proyek contoh melewati alur schematic, simulasi, layout, dan verifikasi sesuai kriteria yang ditetapkan |
| Hosting cloud | Belum dideploy | Deployment setelah validasi localhost dan kesiapan layanan |

Untuk pengujian akhir, tim perlu menetapkan proyek contoh, PDK, spesifikasi rangkaian, serta kriteria lulus simulasi dan DRC/LVS sebelum menjalankan evaluasi. End goal dinilai tercapai ketika proyek contoh tersebut dapat dikerjakan dan ditinjau dari website yang sama tanpa transfer berkas manual antar aplikasi, dengan bukti hasil yang dapat ditelusuri.

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

## End goal: satu website desain chip terpadu

Target akhir proyek adalah **satu website Gelochip** yang menggabungkan Gelochip Studio, AnoaChip Auto Layouter, dan PandaChip Auto Schematic Maker dalam satu antarmuka dan satu workspace proyek. Pengguna dapat menjalankan seluruh alur tanpa berpindah aplikasi atau memindahkan netlist secara manual:

```text
Prompt / spesifikasi
  -> Schematic (PandaChip)
  -> Netlist dan simulasi
  -> Layout GDSII (AnoaChip / Gelochip)
  -> DRC / LVS dan laporan
  -> Tinjau serta unduh artefak proyek
```

Website terpadu ditargetkan memiliki:

- Satu dashboard proyek dengan editor/viewer schematic, layout, hasil simulasi, dan laporan verifikasi.
- Satu API penghubung dengan format pertukaran netlist, spesifikasi, PDK, dan artefak yang disepakati antar engine.
- Alur schematic-ke-layout otomatis, dengan pemeriksaan kompatibilitas port, model perangkat, tegangan, dan PDK sebelum pekerjaan dilanjutkan.
- Status pekerjaan, log, dan riwayat hasil dalam proyek yang sama; hasil simulasi dan DRC/LVS tetap merujuk ke versi desain yang diperiksa.
- Pilihan model lokal atau cloud dari antarmuka yang sama, dengan lingkungan dependensi setiap engine tetap terpisah di backend.
- Pengoperasian di **localhost terlebih dahulu**, kemudian deployment cloud setelah alur terpadu berhasil diuji.

Tahapan pengembangan: penggabungan source dan portal lokal (saat ini), API serta format pertukaran bersama, antarmuka web terpadu, pengujian alur desain menyeluruh, lalu kesiapan hosting cloud. End goal tercapai ketika satu proyek dapat melewati alur schematic, simulasi, layout, dan verifikasi dari website yang sama, tanpa transfer file manual antar aplikasi.

Pengembangan berikutnya tetap menjaga `info.yaml`, `config.json`, dan folder serta artefak yang sudah ada seperti `OUTS`/`outputs`; integrasi harus menambahkan penghubung tanpa menimpa konfigurasi atau memindahkan hasil lama.

## Arah hosting cloud

Struktur ini dapat menjadi dasar pemisahan layanan web, worker EDA, penyimpanan artefak dan model. Sebelum deployment publik, perlu konfigurasi reverse proxy, autentikasi, isolasi worker, storage persisten dan pengujian layanan. Portal saat ini bind ke loopback dan ditujukan untuk penggunaan lokal.

## Lisensi dan asal source

Lisensi Gelochip tersedia di [LICENSE](LICENSE). AnoaChip membawa [lisensinya sendiri](modules/AnoaChip/LICENSE). OpenADA yang disertakan PandaChip memiliki [LICENSE](modules/PandaChip/src/LICENSE). Pertahankan atribusi dan lisensi komponen masing-masing. Dokumentasi asli Gelochip main tersimpan di [arsip README](integration-audit/README-origin-main.md).
