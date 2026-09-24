# MiniSEED to SDS Converter

`miniseed_to_sds.py` mengonversi satu file atau sekumpulan file MiniSEED ke
arsip **SeisComP Data Structure (SDS)**. Data dipisahkan pada batas hari UTC,
kemudian segmen yang saling tumpang tindih digabungkan.

## Fitur

- Membaca satu file MiniSEED atau seluruh file dalam sebuah folder.
- Mendukung pencarian dalam subfolder.
- Mengubah kode network, station, location, dan channel melalui konfigurasi.
- Membagi data menjadi file harian sesuai struktur SDS.
- Menggabungkan data baru dengan file SDS yang sudah ada.
- Menyediakan mode simulasi (`--dry-run`) tanpa menulis file.

## Persyaratan

- Python 3
- [ObsPy](https://docs.obspy.org/)

Instal ObsPy jika belum tersedia:

```powershell
python -m pip install obspy
```

## Konfigurasi

Secara default, program membaca `sds_config.json` dari folder tempat perintah
dijalankan.

```json
{
  "input": ".",
  "network": "VG",
  "station": "SAPL",
  "location": "00",
  "channel_map": {
    "DPE": "DPE",
    "DPN": "DPN",
    "DPZ": "DPZ"
  }
}
```

Keterangan:

| Properti | Fungsi |
|---|---|
| `input` | Alamat satu file MiniSEED atau folder berisi file MiniSEED. |
| `network` | Mengganti kode network dari data sumber. |
| `station` | Mengganti kode station dari data sumber. |
| `location` | Mengganti kode location; gunakan string kosong (`""`) untuk location kosong. |
| `channel_prefix` | Opsional: mengganti dua karakter awal kode channel, misalnya `"HH"`. |
| `channel_map` | Memetakan kode channel sumber ke kode channel tujuan. |

Path relatif pada `input` dihitung dari lokasi file konfigurasi. Contoh:

```json
"input": "data/miniseed"
```

Untuk path absolut Windows, gunakan garis miring `/`:

```json
"input": "D:/data/miniseed"
```

Alternatifnya, backslash harus ditulis dua kali karena file konfigurasi memakai
format JSON:

```json
"input": "D:\\data\\miniseed"
```

Penulisan seperti `"D:\data\miniseed"` tidak valid dalam JSON dan dapat
menyebabkan pesan `Invalid \escape`.

## Penggunaan

Jalankan menggunakan sumber yang ditentukan dalam `sds_config.json`:

```powershell
python miniseed_to_sds.py
```

Tentukan satu file sumber melalui command line:

```powershell
python miniseed_to_sds.py "D:/data/rekaman.mseed"
```

Tentukan folder sumber dan folder keluaran:

```powershell
python miniseed_to_sds.py "D:/data/miniseed" "D:/arsip/SDS"
```

Argumen sumber dari command line memiliki prioritas lebih tinggi daripada nilai
`input` dalam konfigurasi.

### Memilih file konfigurasi

```powershell
python miniseed_to_sds.py --config "D:/config/sds_config.json"
```

### Memindai subfolder

```powershell
python miniseed_to_sds.py --recursive
```

Ekstensi yang dicari adalah `.miniseed`, `.mseed`, `.msd`, dan `.seed`.

### Memeriksa hasil tanpa menulis file

```powershell
python miniseed_to_sds.py --dry-run
```

### Mengganti file SDS yang sudah ada

Secara default, data baru digabungkan dengan file SDS yang sudah ada. Gunakan
opsi berikut untuk menggantinya:

```powershell
python miniseed_to_sds.py --overwrite
```

### Override metadata melalui command line

```powershell
python miniseed_to_sds.py `
  --network VG `
  --station SAPL `
  --location 00 `
  --channel-prefix DP
```

Nilai dari command line memiliki prioritas atas nilai yang sama dalam file
konfigurasi.

## Struktur keluaran

File ditulis mengikuti pola SDS:

```text
YEAR/NET/STA/CHAN.D/NET.STA.LOC.CHAN.D.YEAR.JDAY
```

Contoh:

```text
SDS/2026/VG/SAPL/DPZ.D/VG.SAPL.00.DPZ.D.2026.218
```

## Opsi lengkap

Tampilkan seluruh argumen yang tersedia dengan:

```powershell
python miniseed_to_sds.py --help
```

## Catatan

- Pembagian hari menggunakan waktu UTC.
- Panjang record keluaran default adalah 4096 byte.
- File SDS yang berada di dalam folder output tidak dipindai kembali sebagai
  input.
- Pastikan kode SEED memenuhi batas panjang: network 2 karakter, station 5
  karakter, location 2 karakter, dan channel 3 karakter.
