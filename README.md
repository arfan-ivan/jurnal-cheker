# Journal Checker - Panduan Instalasi dan Penggunaan

Sistem pengecekan jurnal komprehensif dengan Flask yang mengintegrasikan berbagai fitur analisis plagiarisme, grammar checking, dan validasi format.

## Fitur Utama

- **Deteksi Plagiarisme** - Menggunakan algoritma similarity matching
- **Grammar & Spelling Check** - Menggunakan LanguageTool
- **Analisis Bahasa Akademik** - Mendeteksi penggunaan kata non-akademik
- **Validasi Format Jurnal** - Mendukung IEEE, APA, MLA
- **Laporan PDF** - Download hasil analisis lengkap
- **Text Highlighting** - Marking masalah dengan warna berbeda
- **Database MySQL** - Penyimpanan riwayat analisis
- **Interface Modern** - Bootstrap 5 dengan animasi

## Persyaratan Sistem

- Python 3.8+
- MySQL 8.0+
- RAM minimal 4GB (untuk model NLP)

## Instalasi

### 1. Clone atau Download Project

```bash
git clone https://github.com/arfan-ivan/jurnal-cheker.git
cd journal-checker
```

### 2. Setup Virtual Environment

```bash
python -m venv venv
source venv/bin/activate  # Linux/Mac
# atau
venv\Scripts\activate     # Windows
```

### 3. Install Dependencies

```bash
pip install Flask Flask-SQLAlchemy Werkzeug nltk spacy language-tool-python textstat reportlab python-docx PyPDF2 mysql-connector-python PyMySQL cryptography

```

### 4. Download Model NLP

```bash
python -m spacy download en_core_web_sm
python -c "import nltk; nltk.download('punkt'); nltk.download('stopwords'); nltk.download('averaged_perceptron_tagger')"
```

### 5. Setup Database MySQL

Buat database baru di MySQL:

```sql
CREATE DATABASE journal_checker CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'journal_user'@'localhost' IDENTIFIED BY 'your_secure_password';
GRANT ALL PRIVILEGES ON journal_checker.* TO 'journal_user'@'localhost';
FLUSH PRIVILEGES;
```

### 6. Konfigurasi Database

Edit konfigurasi database di `app.py`:

```python
app.config['SQLALCHEMY_DATABASE_URI'] = 'mysql+pymysql://journal_user:your_secure_password@localhost/journal_checker'
```

### 7. Struktur Folder

Buat struktur folder yang diperlukan:

```
journal-checker/
├── app.py
├── templates/
│   ├── index.html
│   └── history.html
├── uploads/          # Akan dibuat otomatis
└── static/          # Opsional untuk CSS/JS tambahan
```

### 8. Setup Template HTML

Buat folder `templates` dan file-file berikut:

**templates/index.html** - Halaman utama upload dan analisis
**templates/history.html** - Halaman riwayat analisis

Copy HTML template yang disediakan ke masing-masing file tersebut.

## Menjalankan Aplikasi

```bash
python app.py
```

Akses aplikasi di: `http://localhost:5000`

## Penggunaan

### 1. Upload Document
- Pilih file (PDF, DOCX, TXT)
- Pilih format jurnal (IEEE, APA, MLA)
- Klik "Analyze Document"

### 2. Lihat Hasil Analisis
- Overall Score (0-100)
- Plagiarism Percentage
- Grammar Errors Count
- Academic Language Score
- Format Compliance Score

### 3. Download Report
- Klik "Download PDF Report"
- Mendapat laporan lengkap dengan highlighting

### 4. Riwayat Analisis
- Kunjungi halaman "History"
- Lihat semua analisis sebelumnya
- Download ulang laporan lama

## Kustomisasi

### Menambah Format Jurnal Baru

Edit dictionary `JOURNAL_FORMATS` di `app.py`:

```python
JOURNAL_FORMATS['harvard'] = {
    'title_pattern': r'^[A-Z][A-Za-z\s:,.-]+$',
    'abstract_required': True,
    'keywords_required': False,
    'sections': ['introduction', 'literature review', 'methodology', 'findings', 'conclusion'],
    'reference_format': r'^[A-Z][A-Za-z,.\s]+\(\d{4}\)',
    'citation_format': r'\([A-Za-z,\s]+\d{4}\)'
}
```

### Menambah Database Plagiarisme

Tambahkan teks referensi ke database:

```python
new_text = PlagiarismDatabase(
    title="Judul Paper",
    content="Isi konten untuk pengecekan plagiarisme",
    authors="Nama Penulis",
    year=2024,
    source="Nama Jurnal"
)
db.session.add(new_text)
db.session.commit()
```

### Kustomisasi Scoring

Edit bobot scoring di method `analyze_document`:

```python
overall_score = (
    (100 - plagiarism_score) * 0.4 +      # 40% weight
    (100 - min(grammar_error_count * 2, 100)) * 0.3 +  # 30% weight
    academic_score * 0.2 +                 # 20% weight
    format_score * 0.1                     # 10% weight
)
```

## Troubleshooting

### Error: MySQL connection failed
- Pastikan MySQL service berjalan
- Cek username/password database
- Pastikan database sudah dibuat

### Error: spaCy model not found
```bash
python -m spacy download en_core_web_sm
```

### Error: NLTK data not found
```bash
python -c "import nltk; nltk.download('all')"
```

### Error: LanguageTool timeout
- Pastikan koneksi internet stabil
- Atau gunakan LanguageTool server lokal

### File upload gagal
- Cek ukuran file (max 16MB)
- Pastikan format file didukung (PDF, DOCX, TXT)
- Pastikan folder `uploads` memiliki permission write

## Optimasi Performa

### 1. Caching
Implementasi Redis untuk caching hasil analisis:

```python
import redis
r = redis.Redis(host='localhost', port=6379, db=0)
```

### 2. Background Processing
Gunakan Celery untuk analisis background:

```python
from celery import Celery
celery = Celery('journal_checker')
```

### 3. Database Indexing
Tambahkan index pada kolom yang sering diquery:

```sql
CREATE INDEX idx_session_id ON analysis(session_id);
CREATE INDEX idx_created_at ON analysis(created_at);
```

## Security Considerations

1. **File Upload Security**
   - Validasi MIME type
   - Scan untuk malware
   - Limit ukuran file

2. **Database Security**
   - Gunakan prepared statements
   - Validasi input
   - Encrypt sensitive data

3. **Session Security**
   - Set secure secret key
   - Implement CSRF protection
   - Use HTTPS in production

## Production Deployment

### Menggunakan Gunicorn + Nginx

1. Install Gunicorn:
```bash
pip install gunicorn
```

2. Jalankan dengan Gunicorn:
```bash
gunicorn -w 4 -b 0.0.0.0:8000 app:app
```

3. Setup Nginx sebagai reverse proxy:
```nginx
server {
    listen 80;
    server_name your-domain.com;
    
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

### Upload Endpoint
```
POST /upload
Content-Type: multipart/form-data

Parameters:
- file: Document file (PDF/DOCX/TXT)
- format: Journal format (ieee/apa/mla)

Response:
{
    "success": true,
    "analysis_id": 123,
    "results": { ... }
}
```

## License

MIT License - Silakan gunakan untuk keperluan akademik dan komersial.

**Catatan**: Sistem ini menggunakan library open source dan free. Untuk penggunaan production, pertimbangkan untuk menggunakan API komersial untuk akurasi yang lebih tinggi.
