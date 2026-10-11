# Catatan integrasi

## Sumber

- `main` lokal berawal dari `7d9ba0c`, lalu fast-forward ke `origin/main` (`6239d6e`).
- `dev_wilton` (`c61549d`) digabungkan dengan merge tanpa konflik source.
- Kontribusi `origin/dev_irman` (`41d549c`) dan `origin/dev_ken` (`b2e0f40`) sudah tercakup dalam riwayat main.
- `AnoaChip-main.zip` dan `PandaChip-main.zip` diimpor ke `modules/` tanpa menimpa source Gelochip.

## Perlindungan

`before.json` merekam checksum file output yang sudah ada di checkout awal, konfigurasi main, laporan dan artefak tapeout, serta daftar folder root awal. File lokal awal diperiksa byte-for-byte; pembandingan dengan blob main mengizinkan konversi LF ke CRLF oleh checkout Git Windows. `git diff` terhadap main tetap kosong untuk path terlindungi.

File yang ada di Wilton tetapi tidak ada di main dipulihkan agar tidak hilang, termasuk `app/web_app.py`, notebook IGBT, dan script fine-tuning. Source lama ini tersedia sebagai referensi; entrypoint Studio adalah `app.kaizen_app:app`.

PandaChip membawa pasangan `templates/ieeeaccess/Logo.png` / `logo.png` dan `NoTaglineLogo.png` / `notaglinelogo.png`. Windows memperlakukan masing-masing pasangan sebagai path sama. Kedua pasangan memiliki isi identik; satu file fisik mempertahankan isinya. Hash ZIP dan hasil pembandingan tercatat di `zip-manifest.json`.

Folder dependensi bawaan ZIP tetap ada di disk. `node_modules` baru tidak dimasukkan ke commit; source dan lockfile asli dipertahankan. Dependensi dan artefak yang sudah terlacak dalam branch lama tidak dihapus.

## Batas integrasi

Portal menyediakan navigasi dan status backend tiga aplikasi. Integrasi belum menyediakan pertukaran netlist otomatis atau satu runtime dependensi bersama. AnoaChip masih memerlukan checkout Glayout di `modules/gLayout`; PandaChip memerlukan runtime container dan Go; Gelochip memerlukan dependensi EDA/agent.

## Validasi

- Empat tes HTTP portal lulus.
- 154 pemeriksaan baseline konfigurasi/artefak dan keberadaan folder awal lulus.
- ZIP diperiksa terhadap hasil ekstraksi dengan SHA-256: 3.688 entry AnoaChip dan 1.292 entry PandaChip, nol perbedaan isi; lihat `zip-manifest.json`.
- Syntax Python diperiksa pada 233 file aplikasi/engine, tanpa kesalahan parsing.
- Tes EDA/agent penuh belum dijalankan karena dependensi Python terkait, Go, PDK dan model belum disiapkan pada lingkungan ini.
- Build frontend Gelochip lulus menggunakan Vite 5.4.21 dalam direktori terpisah; folder build dan dependensi lama tidak ditimpa.
- Instalasi lockfile frontend Gelochip melaporkan 7 temuan audit npm (2 moderate, 5 high). Versi dependensi bawaan tidak diubah dalam penggabungan ini.

Penggabungan dilakukan lokal. Branch sumber tetap disimpan dan tidak dilakukan push atau deployment cloud.
