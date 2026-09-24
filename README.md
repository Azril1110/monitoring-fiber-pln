# Sistem Web Monitoring Jaringan Jaringan Fiber PLN Icon+

Aplikasi web monitoring infrastruktur fiber optik dan transmisi jaringan telekomunikasi per Ring untuk **PLN Icon+**. Dibangun dengan **Python (Flask)** dan mendukung database **Supabase (PostgreSQL Cloud)** serta fallback **SQLite lokal**.

---

## Fitur Utama

### 1. Halaman Dashboard (`/`)
- **KPI Metrik Utama**:
  - Total Ring Jaringan aktif.
  - Total Panjang Kabel Fiber (dalam KM dan Meter).
  - Persentase Tingkat Kesehatan Jaringan (% panjang kabel dengan status AMAN).
  - Indikator Peringatan Segmen Putus (dengan alert merah jika ada kabel terputus).
- **Detail Progres per Ring**:
  - Progres persentase (%) operasional tiap ring.
  - Total jarak bentangan fiber tiap ring.
  - Jumlah titik antara (DCU / Data Concentrator Unit).
  - Status kendala aktif per ring.
  - Tombol navigasi langsung ke visualizer ring.
- **Detail Kendala & Gangguan Aktif (Lintas Seluruh Ring)**:
  - Tabel rekapitulasi kendala terkini (Kabel Putus, Redaman Tinggi, Proyek Galian, dll), prioritas (*Critical, High, Medium*), status, dan PIC teknisi lapangan.

### 2. Halaman Monitoring Per Ring (`/monitoring/<ring_id>`)
- **Navigasi Tab Ring**: Beralih cepat antar Ring (Ring 1, Ring 2, Ring 3, dst) atau buat Ring baru.
- **Topologi Visual Interaktif**:
  - Dimulai dari **POP 1 (MULAI)** di sisi awal jaringan.
  - Titik antara yang fleksibel: **DCU** (*Data Concentrator Unit*), ODC, ODP, FAT, Gardu Hubung.
  - Diakhiri dengan **POP 2 (AKHIR)** di ujung jaringan.
  - **Segmen Kabel Penghubung Antar Titik**:
    - Menampilkan **Jarak** (meter dan KM) yang dapat diisi/diedit manual.
    - **2 Opsi Status Kabel**:
      - **AMAN**: Kabel menyala berwarna **HIJAU** (`#10b981`) dengan partikel aliran sinyal normal.
      - **PUTUS**: Kabel berkedip berwarna **MERAH** (`#ef4444`) dengan indikator peringatan broken gap.
    - Klik langsung pada kabel untuk membuka quick editor: ubah jarak atau ubah status Aman/Putus seketika.
  - **Tambah DCU / Titik Antara**: Tombol sisip langsung di antara dua node mana pun.
  - **Detail Node**: Klik edit untuk memperbarui nama, alamat, koordinat GPS, dan parameter teknis.
- **Detail Kendala (Bagian Paling Bawah Halaman)**:
  - Form pelaporan kendala baru khusus untuk ring tersebut (pilih segmen terdampak, kategori, severity, status, PIC teknisi, dan kronologi).
  - Tabel manajemen kendala dengan aksi ubah status (Open / Investigasi / Selesai) atau hapus.

### 3. Integrasi Database Supabase (`/settings`)
- Aplikasi mendukung database **Supabase Cloud (PostgreSQL)** secara *native* menggunakan `supabase-py`.
- Disediakan skrip `supabase_schema.sql` siap jalan di SQL Editor Supabase.
- Jika belum dikonfigurasi, sistem otomatis berjalan dalam mode **SQLite lokal** sebagai preview yang berfungsi penuh, dan dapat langsung beralih ke Supabase kapan saja melalui menu Pengaturan.

---

## Panduan Instalasi & Menjalankan Aplikasi

### 1. Menjalankan Server Flask
Di terminal proyek `d:\monitoring pln`:
```bash
python app.py
```
Aplikasi akan berjalan di: **`http://127.0.0.1:5000`**

### 2. Menghubungkan ke Supabase (Opsional / Rekomendasi)
1. Buka project dashboard di [supabase.com](https://supabase.com).
2. Buka menu **SQL Editor**, buka file `supabase_schema.sql` (atau salin dari halaman `/settings` di aplikasi), lalu klik **Run**.
3. Buka menu **Project Settings &rarr; API**, salin:
   - **Project URL**
   - **API Key** (`anon` public atau `service_role`)
4. Masukkan ke file `.env` di folder proyek:
   ```env
   SUPABASE_URL=https://your-project-ref.supabase.co
   SUPABASE_KEY=your-supabase-key
   PORT=5000
   ```
   *(Atau masukkan langsung via halaman antarmuka web di menu `/settings`)*.
5. Klik tombol **"Isi Data Sampel ke Supabase"** untuk langsung memuat data contoh awal.

---

## Struktur File Proyek

```
d:/monitoring pln/
├── app.py                  # Server web Flask & REST API endpoints
├── database.py             # Layer database hybrid (Supabase & SQLite fallback)
├── requirements.txt        # Daftar dependensi Python (Flask, supabase, dll)
├── supabase_schema.sql     # Skrip DDL PostgreSQL untuk Supabase
├── .env.example            # Contoh template konfigurasi environment
├── .env                    # File environment konfigurasi lokal
├── README.md               # Dokumentasi lengkap proyek
└── templates/
    ├── base.html           # Layout utama bernuansa PLN Icon+
    ├── dashboard.html      # Tampilan Dashboard progres & kendala
    ├── monitoring.html     # Halaman monitoring visual per ring (POP 1 -> DCU -> POP 2)
    ├── monitoring_empty.html # State kosong jika belum ada ring
    └── settings.html       # Halaman pengaturan koneksi Supabase & SQL schema
```
