from flask import Flask, render_template, request, jsonify, send_file, session
from flask_sqlalchemy import SQLAlchemy
from werkzeug.utils import secure_filename
import os
import re
import json
import nltk
import spacy
from difflib import SequenceMatcher
from textstat import flesch_reading_ease, flesch_kincaid_grade
import language_tool_python
from datetime import datetime
import uuid
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.colors import red, green, blue, black
import docx
import PyPDF2
from io import BytesIO
import mysql.connector
from mysql.connector import Error
import threading
from concurrent.futures import ThreadPoolExecutor
import multiprocessing
from functools import lru_cache
import chardet
import logging
from datetime import datetime, timedelta
from pytz import timezone
# - By:ArfanVn -


# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Download required NLTK data
try:
    nltk.download('punkt', quiet=True)
    nltk.download('stopwords', quiet=True)
    nltk.download('averaged_perceptron_tagger', quiet=True)
    # Indonesian language support
    nltk.download('punkt_tab', quiet=True)
except:
    pass

app = Flask(__name__)
app.config['SECRET_KEY'] = 'fd1ffLZwHeL1GVMDFkKMK37dP28d0y6h'
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # Increased to 50MB for larger files

# Database configuration
app.config['SQLALCHEMY_DATABASE_URI'] = 'mysql+pymysql://root:4rfanivan777@localhost/journal_checker'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_size': 10,
    'pool_recycle': 120,
    'pool_pre_ping': True
}

db = SQLAlchemy(app)

# Create upload folder if it doesn't exist
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Database Models
class Analysis(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.String(100), nullable=False)
    filename = db.Column(db.String(200), nullable=False)
    journal_format = db.Column(db.String(50), nullable=False)
    language = db.Column(db.String(10), default='id')  # Language detection
    plagiarism_score = db.Column(db.Float, default=0.0)
    grammar_errors = db.Column(db.Integer, default=0)
    format_errors = db.Column(db.Integer, default=0)
    academic_score = db.Column(db.Float, default=0.0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    analysis_data = db.Column(db.Text)

class PlagiarismDatabase(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(500), nullable=False)
    content = db.Column(db.Text, nullable=False)
    authors = db.Column(db.String(500))
    year = db.Column(db.Integer)
    source = db.Column(db.String(200))
    language = db.Column(db.String(10), default='id')
    
    # Perbaikan: Add indexing for better query performance
    __table_args__ = (
        db.Index('idx_language_content', 'language'),
        db.Index('idx_language_year', 'language', 'year'),
    )

# Enhanced journal format templates with Indonesian support
JOURNAL_FORMATS = {
    'ieee': {
        'title_pattern': r'^[A-Z\u00C0-\u017F][A-Za-z\s:,.-\u00C0-\u017F]+$',
        'abstract_required': True,
        'keywords_required': True,
        'sections': {
            'en': ['introduction', 'methodology', 'results', 'discussion', 'conclusion'],
            'id': ['pendahuluan', 'metodologi', 'hasil', 'pembahasan', 'kesimpulan', 'introduction', 'methodology', 'results', 'discussion', 'conclusion']
        },
        'reference_format': r'^\[\d+\]\s+[A-Z\u00C0-\u017F].*\.$',
        'citation_format': r'\[\d+\]'
    },
    'apa': {
        'title_pattern': r'^[A-Z\u00C0-\u017F][A-Za-z\s:,.-\u00C0-\u017F]+$',
        'abstract_required': True,
        'keywords_required': True,
        'sections': {
            'en': ['introduction', 'method', 'results', 'discussion'],
            'id': ['pendahuluan', 'metode', 'hasil', 'pembahasan', 'introduction', 'method', 'results', 'discussion']
        },
        'reference_format': r'^[A-Z\u00C0-\u017F][A-Za-z,.\s\u00C0-\u017F]+\(\d{4}\)\.',
        'citation_format': r'\([A-Za-z,\s\u00C0-\u017F]+\d{4}\)'
    },
    'mla': {
        'title_pattern': r'^[A-Z\u00C0-\u017F][A-Za-z\s:,.-\u00C0-\u017F]+$',
        'abstract_required': False,
        'keywords_required': False,
        'sections': {
            'en': ['introduction', 'body', 'conclusion'],
            'id': ['pendahuluan', 'isi', 'kesimpulan', 'introduction', 'body', 'conclusion']
        },
        'reference_format': r'^[A-Z\u00C0-\u017F][A-Za-z,.\s\u00C0-\u017F]+\d{4}\.',
        'citation_format': r'\([A-Za-z\s\u00C0-\u017F]+\d+\)'
    }
}

class OptimizedJournalAnalyzer:

    def __init__(self):
        # === 1. Grammar Tool Initialization ===
        self.grammar_tools = {}

        # English grammar tool
        try:
            self.grammar_tools['en'] = language_tool_python.LanguageTool('en-US')
            test_matches = self.grammar_tools['en'].check("This are a test.")
            logger.info(f"English grammar tool initialized. Test errors: {len(test_matches)}")
        except Exception as e:
            logger.error(f"English grammar tool initialization failed: {e}")
            self.grammar_tools['en'] = None

        # Indonesian grammar tool (LanguageTool tidak mendukung 'id-ID')
        try:
            # Jika kamu tetap ingin coba, tapi siap-siap gagal
            self.grammar_tools['id'] = language_tool_python.LanguageTool('id-ID')
            test_matches = self.grammar_tools['id'].check("Ini adalah test kalimat dengan kesalahan.")
            logger.info(f"Indonesian grammar tool initialized. Test errors: {len(test_matches)}")
        except Exception as e:
            logger.warning(f"Indonesian grammar tool initialization failed, fallback to None: {e}")
            self.grammar_tools['id'] = None

        # === 2. NLP Model Initialization ===
        self.nlp_models = {}

        # English spaCy model
        try:
            self.nlp_models['en'] = spacy.load("en_core_web_sm")
        except Exception as e:
            logger.warning(f"English spaCy model not found: {e}")
            self.nlp_models['en'] = None

        # Indonesian spaCy model (pakai model multilingual)
        try:
            self.nlp_models['id'] = spacy.load("xx_sent_ud_sm")
        except Exception as e:
            logger.warning(f"Indonesian spaCy model not found: {e}")
            self.nlp_models['id'] = None


        # === 3. Academic & Non-Academic Words ===
        self.academic_words = {
            'en': {
                'analyze', 'approach', 'assessment', 'concept', 'conclude', 'consistent',
                'context', 'data', 'definition', 'distribution', 'evidence', 'evaluate',
                'factors', 'function', 'indicate', 'interpretation', 'issues', 'method',
                'policy', 'procedure', 'research', 'significant', 'structure', 'theory',
                'variables', 'implementation', 'hypothesis', 'correlation', 'regression',
                'empirical', 'qualitative', 'quantitative', 'synthesis', 'variable',
                'parameter', 'bias', 'sample', 'population', 'validity', 'reliability',
                'analysis', 'model', 'framework', 'criteria', 'statistic', 'experiment',
                'observation', 'literature', 'review', 'trend', 'inference', 'conceptual',
                'methodology', 'phenomenon', 'domain', 'scope', 'limitations', 'findings',
                'implication', 'conclusion', 'discourse', 'contextual', 'substantive',
                'deduction', 'induction', 'generalize', 'replicate', 'construct',
                'operationalize', 'theoretical', 'explore', 'validate', 'sufficient',
                'significance', 'assumption', 'causal', 'association', 'classification',
                'description', 'explanation', 'objective', 'outcome', 'pattern', 'process',
                'relationship', 'scenario', 'simulation', 'strategy', 'threshold',
                'transformation', 'conceptualization', 'data collection', 'empiricism',
                'hypothetical', 'interpretive', 'longitudinal', 'meta-analysis',
                'operational definition', 'paradigm', 'qualifier', 'randomization',
                'reliability coefficient', 'sampling', 'statistical significance',
                'systematic review', 'variable control', 'validity test', 'measurement',
                'analytical', 'coding', 'dissemination', 'triangulation', 'protocol',
                'manuscript', 'publication', 'citation', 'referencing', 'annotation',
                'research question', 'null hypothesis', 'alternative hypothesis',
                'instrumentation', 'peer review', 'case study', 'fieldwork', 'ethnography',
                'dissertation', 'thesis', 'scholarship', 'constructivist', 'deductive',
                'inductive', 'mixed methods', 'controlled variables', 'dependent variable',
                'independent variable', 'nonresponse bias', 'literature gap'
            },
            'id': {
                'analisis', 'pendekatan', 'penilaian', 'konsep', 'menyimpulkan', 'konsisten',
                'konteks', 'data', 'definisi', 'distribusi', 'bukti', 'evaluasi', 'faktor',
                'fungsi', 'menunjukkan', 'interpretasi', 'masalah', 'metode', 'kebijakan',
                'prosedur', 'penelitian', 'signifikan', 'struktur', 'teori', 'variabel',
                'implementasi', 'hipotesis', 'korelasi', 'regresi', 'empiris', 'kualitatif',
                'kuantitatif', 'sintesis', 'parameter', 'bias', 'sampel', 'populasi',
                'validitas', 'reliabilitas', 'model', 'kerangka', 'kriteria', 'statistik',
                'eksperimen', 'observasi', 'literatur', 'tinjauan', 'tren', 'inferensi',
                'konseptual', 'metodologi', 'fenomena', 'domain', 'cakupan', 'batasan',
                'temuan', 'implikasi', 'kesimpulan', 'diskursus', 'kontekstual',
                'substansial', 'deduksi', 'induksi', 'generalisasi', 'replikasi',
                'konstruksi', 'operasionalisasi', 'teoretis', 'eksplorasi', 'validasi',
                'cukup', 'signifikansi', 'asumsi', 'kausal', 'asosiasi', 'klasifikasi',
                'deskripsi', 'penjelasan', 'objektif', 'hasil', 'pola', 'proses',
                'hubungan', 'skenario', 'simulasi', 'strategi', 'ambang', 'transformasi',
                'pengumpulan data', 'empirisme', 'hipotetis', 'interpretatif',
                'longitudinal', 'meta-analisis', 'definisi operasional', 'paradigma',
                'pengendalian variabel', 'randomisasi', 'koefisien reliabilitas',
                'pengambilan sampel', 'signifikansi statistik', 'tinjauan sistematis',
                'uji validitas', 'kualifikasi', 'pengukuran', 'analisis data', 'pengelola',
                'kodefikasi', 'diseminasi', 'triangulasi', 'protokol', 'naskah',
                'publikasi', 'sitasi', 'referensi', 'anotasi', 'pertanyaan penelitian',
                'hipotesis nol', 'hipotesis alternatif', 'instrumentasi',
                'kajian sejawat', 'studi kasus', 'kerja lapangan', 'etnografi',
                'disertasi', 'tesis', 'beasiswa', 'konstruktivis', 'deduktif',
                'induktif', 'metode campuran', 'variabel terkontrol',
                'variabel terikat', 'variabel bebas', 'bias nonrespon',
                'kesenjangan literatur', 'studi literatur', 'lapangan', 'etnografi', 'kajian pustaka',
                'sistematika', 'substansi', 'objektivitas', 'subjektivitas', 'pemodelan',
                'verifikasi', 'sinkronisasi', 'eksplisit', 'implisit', 'rancangan penelitian',
                'instrumen', 'indikator', 'kodefikasi', 'triangulasi', 'reduksi data',
                'pengkodean', 'penafsiran', 'penjabaran', 'komparatif', 'diskursif',
                'eksaminasi', 'responden', 'narasumber', 'relevansi', 'akuntabilitas',
                'kredibilitas', 'transferabilitas', 'dependabilitas', 'konfirmabilitas',
                'penguatan teori', 'perumusan masalah', 'rumusan tujuan', 'latar belakang',
                'metode analisis', 'sumber data', 'informan', 'prosedur penelitian',
                'etika penelitian', 'pengujian hipotesis', 'variabel bebas', 'variabel terikat',
                'kerangka konseptual', 'kerangka berpikir', 'hasil temuan', 'rekomendasi',
                'keselarasan', 'kebermaknaan', 'keajegan', 'keabsahan', 'keandalan',
                'pemahaman mendalam', 'penarikan kesimpulan', 'perbandingan', 'pengamatan',
                'persepsi', 'pengalaman subyektif', 'intervensi', 'teknik analisis',
                'pengolahan data', 'sumber primer', 'sumber sekunder', 'naskah akademik',
                'tesis', 'disertasi', 'publikasi ilmiah', 'artikel jurnal', 'makalah',
                'forum ilmiah', 'simposium', 'seminar', 'karya ilmiah', 'kajian teoritis',
                'perspektif', 'paradigma penelitian', 'logika ilmiah', 'argumentasi', 'penalaran'
            }
        }

        self.non_academic_words = {
            'en': {
                'awesome', 'cool', 'stuff', 'things', 'really', 'very', 'pretty',
                'a lot', 'super', 'totally', 'basically', 'literally', 'like',
                'fun', 'nice', 'great', 'okay', 'yeah', 'wow', 'dude', 'kid',
                'buddy', 'thingy', 'sorta', 'kinda', 'maybe', 'actually', 'anyway',
                'lol', 'omg', 'fine', 'yep', 'nah', 'hey', 'guess', 'sweet',
                'chill', 'dope', 'rad', 'wicked', 'coolio', 'groovy', 'neat',
                'fab', 'boss', 'slick', 'tight', 'legit', 'lit', 'sick', 'bomb',
                'crazy', 'nuts', 'wild', 'lame', 'meh', 'ugh', 'ew', 'yuck',
                'boo', 'oops', 'ugh', 'haha', 'huh', 'blah', 'yada', 'yada',
                'gotcha', 'whatevs', 'nah', 'yolo', 'fomo', 'bae', 'bff', 'brb',
                'idk', 'tbh', 'imo', 'fwiw', 'smh', 'ftw', 'tmi', 'irl', 'af',
                'wth', 'wtf', 'lolz'
            },
            'id': {
                'keren', 'bagus banget', 'sangat', 'agak', 'semacam',
                'banyak sekali', 'kayak', 'gitu', 'banget', 'dong', 'sih',
                'pokoknya', 'intinya', 'sebenernya', 'gimana', 'kenapa',
                'yah', 'lho', 'deh', 'kok', 'hebat', 'mantap',
                'asyik', 'oke', 'sip', 'biasa aja', 'begitulah', 'lumayan',
                'cuma', 'aja', 'gak', 'nggak', 'siapa', 'gue',
                'bro', 'ga', 'loh', 'hah', 'aduh', 'eh',
                'hahaha', 'wakakak', 'wkwkwk', 'santai', 'kocak', 'gokil',
                'lucu', 'bete', 'seger', 'lembut', 'keras', 'sedih', 'senang',
                'malas', 'capek', 'gemes', 'banget deh', 'mantul', 'goks',
                'gemesin', 'syantik', 'cantik', 'cakep', 'ganteng'
            }
        }


        # === 4. Thread Pool Executor ===
        self.executor = ThreadPoolExecutor(max_workers=2)


    @lru_cache(maxsize=1000)
    def detect_language(self, text_sample):
        """Enhanced language detection with better accuracy"""
        if not text_sample or len(text_sample.strip()) < 10:
            logger.warning("Text sample too short for language detection")
            return 'id'  # Default to Indonesian
        
        # Perbaikan: Use larger sample size for better accuracy
        sample_size = min(1000, len(text_sample))  # Increased from 1000 to 5000
        text_lower = text_sample[:sample_size].lower()
        
        # Enhanced Indonesian indicators with more specific terms
        indonesian_indicators = {
            # Common words
            'dan': 3, 'yang': 3, 'atau': 2, 'dengan': 2, 'untuk': 2, 
            'dalam': 2, 'pada': 2, 'dari': 2, 'ke': 1, 'ini': 2,
            'itu': 2, 'adalah': 3, 'akan': 2, 'telah': 2, 'dapat': 2, 
            'tidak': 3, 'juga': 2, 'oleh': 2, 'sebagai': 2,
            
            # Academic terms
            'penelitian': 5, 'metode': 4, 'hasil': 4, 'pembahasan': 5, 
            'kesimpulan': 5, 'analisis': 4, 'data': 3, 'sistem': 3,
            'teknologi': 4, 'informasi': 3, 'pengembangan': 4,
            
            # Indonesian specific patterns
            'terhadap': 3, 'melalui': 3, 'berdasarkan': 4, 'sehingga': 3,
            'sedangkan': 3, 'kemudian': 2, 'selain': 2, 'antara': 2,
            'beberapa': 3, 'berbagai': 3, 'setiap': 2, 'semua': 2,
            
            # Prefixes and suffixes (as separate words due to spacing issues)
            'menggunakan': 4, 'dilakukan': 4, 'digunakan': 4, 
            'menunjukkan': 4, 'memberikan': 3, 'merupakan': 4
        }
        
        # Enhanced English indicators
        english_indicators = {
            # Common words
            'the': 3, 'and': 3, 'or': 2, 'with': 2, 'for': 2,
            'in': 2, 'on': 2, 'from': 2, 'to': 1, 'this': 2,
            'that': 2, 'is': 3, 'will': 2, 'has': 2, 'can': 2,
            'not': 3, 'also': 2, 'by': 2, 'as': 2,
            
            # Academic terms
            'research': 5, 'method': 4, 'results': 4, 'discussion': 5,
            'conclusion': 5, 'analysis': 4, 'data': 3, 'system': 3,
            'technology': 4, 'information': 3, 'development': 4,
            
            # English specific patterns
            'through': 3, 'based': 3, 'therefore': 4, 'however': 3,
            'while': 3, 'then': 2, 'besides': 2, 'between': 2,
            'several': 3, 'various': 3, 'each': 2, 'all': 2,
            
            # Common academic verbs
            'using': 4, 'conducted': 4, 'used': 4, 'shows': 4,
            'provides': 3, 'represents': 4, 'indicates': 4
        }
        
        # Perbaikan: More sophisticated scoring system
        words = re.findall(r'\b\w+\b', text_lower)
        
        if len(words) < 5:
            logger.warning("Too few words for reliable language detection")
            return 'id'
        
        id_score = 0
        en_score = 0
        
        # Calculate weighted scores
        for word in words:
            if word in indonesian_indicators:
                id_score += indonesian_indicators[word]
            if word in english_indicators:
                en_score += english_indicators[word]
        
        # Perbaikan: Additional pattern-based detection
        # Check for Indonesian-specific patterns
        id_patterns = [
            r'\bdi\s+\w+',  # "di" as separate word
            r'\bke\s+\w+',  # "ke" as separate word  
            r'\w+nya\b',    # words ending with "nya"
            r'\bmeng\w+',   # words starting with "meng"
            r'\bber\w+',    # words starting with "ber"
            r'\bter\w+',    # words starting with "ter"
        ]
        
        # Check for English-specific patterns
        en_patterns = [
            r'\bthe\s+\w+',     # "the" article usage
            r'\ban?\s+\w+',     # "a/an" article usage
            r'\w+ing\b',        # words ending with "ing"
            r'\w+ed\b',         # words ending with "ed"
            r'\w+tion\b',       # words ending with "tion"
            r'\w+ly\b',         # words ending with "ly"
        ]
        
        # Count pattern matches
        for pattern in id_patterns:
            matches = len(re.findall(pattern, text_lower))
            id_score += matches * 2
        
        for pattern in en_patterns:
            matches = len(re.findall(pattern, text_lower))
            en_score += matches * 2
        
        # Perbaikan: Consider text length and add confidence threshold
        total_words = len(words)
        id_ratio = id_score / total_words if total_words > 0 else 0
        en_ratio = en_score / total_words if total_words > 0 else 0
        
        # Log detection details for debugging
        logger.debug(f"Language detection - ID score: {id_score} ({id_ratio:.3f}), EN score: {en_score} ({en_ratio:.3f})")
        
        # Decision with confidence threshold
        if abs(id_score - en_score) < 3 and total_words < 50:
            # If scores are very close and text is short, default to Indonesian
            logger.info("Language detection uncertain, defaulting to Indonesian")
            return 'id'
        
        detected_language = 'id' if id_score > en_score else 'en'
        confidence = abs(id_score - en_score) / max(id_score + en_score, 1)
        
        logger.info(f"Detected language: {detected_language} (confidence: {confidence:.3f})")
        
        return detected_language

    def extract_text_from_file(self, file_path):
        """Enhanced text extraction with encoding detection and chunked processing"""
        text = ""
        try:
            if file_path.endswith('.pdf'):
                text = self._extract_from_pdf(file_path)
            elif file_path.endswith('.docx'):
                text = self._extract_from_docx(file_path)
            elif file_path.endswith('.txt'):
                text = self._extract_from_txt(file_path)
        except Exception as e:
            logger.error(f"Error extracting text from {file_path}: {e}")
        
        return text

    def _extract_from_pdf(self, file_path):
        """Optimized PDF text extraction"""
        text = ""
        try:
            with open(file_path, 'rb') as file:
                reader = PyPDF2.PdfReader(file)
                # Process pages in chunks to handle large files
                for i, page in enumerate(reader.pages):
                    try:
                        page_text = page.extract_text()
                        if page_text:
                            text += page_text + "\n"
                        
                        # Yield control for very large files
                        if i % 10 == 0 and i > 0:
                            logger.info(f"Processed {i} pages...")
                    except Exception as e:
                        logger.warning(f"Error extracting page {i}: {e}")
                        continue
        except Exception as e:
            logger.error(f"PDF extraction error: {e}")
        
        return text

    def _extract_from_docx(self, file_path):
        """Optimized DOCX text extraction"""
        text = ""
        try:
            doc = docx.Document(file_path)
            paragraphs = []
            
            # Extract paragraphs in chunks
            for paragraph in doc.paragraphs:
                if paragraph.text.strip():
                    paragraphs.append(paragraph.text)
            
            text = "\n".join(paragraphs)
        except Exception as e:
            logger.error(f"DOCX extraction error: {e}")
        
        return text

    def _extract_from_txt(self, file_path):
        """Enhanced TXT extraction with encoding detection"""
        text = ""
        try:
            # Detect encoding
            with open(file_path, 'rb') as file:
                raw_data = file.read()
                detected = chardet.detect(raw_data)
                encoding = detected['encoding'] or 'utf-8'
            
            # Read with detected encoding
            with open(file_path, 'r', encoding=encoding, errors='ignore') as file:
                text = file.read()
        except Exception as e:
            logger.error(f"TXT extraction error: {e}")
            # Fallback to utf-8 with error ignore
            try:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as file:
                    text = file.read()
            except:
                pass
        
        return text

    def check_plagiarism_optimized(self, text, language='id'):
        """Optimized plagiarism detection with improved database handling"""
        logger.info(f"Starting plagiarism check for language: {language}")
        
        # Perbaikan: Check database availability first
        try:
            db_count = PlagiarismDatabase.query.filter_by(language=language).count()
            logger.info(f"Found {db_count} database entries for language: {language}")
            
            if db_count == 0:
                logger.warning(f"No plagiarism database entries for language: {language}")
                return 0.0, []
        except Exception as e:
            logger.error(f"Database query failed: {e}")
            return 0.0, []
        
        plagiarism_results = []
        
        # Split text into sentences efficiently
        try:
            if language == 'id':
                # Enhanced Indonesian sentence splitting
                sentences = re.split(r'[.!?]+\s+', text)
            else:
                sentences = nltk.sent_tokenize(text)
        except Exception as e:
            logger.warning(f"Sentence tokenization failed: {e}")
            sentences = re.split(r'[.!?]+\s+', text)
        
        # Filter substantial sentences with better criteria
        substantial_sentences = []
        for s in sentences:
            s_clean = s.strip()
            word_count = len(s_clean.split())
            # Perbaikan: Lower minimum word count and add character check
            if word_count >= 8 and len(s_clean) >= 50:  # Reduced from 10 words
                substantial_sentences.append(s_clean)
        
        if not substantial_sentences:
            logger.warning("No substantial sentences found for plagiarism check")
            return 0.0, []
        
        logger.info(f"Processing {len(substantial_sentences)} substantial sentences")
        
        # Perbaikan: Batch query with pagination for better performance
        page_size = 100
        all_db_texts = []
        
        try:
            offset = 0
            while len(all_db_texts) < 500:  # Limit total entries processed
                batch = PlagiarismDatabase.query.filter_by(language=language)\
                    .offset(offset).limit(page_size).all()
                
                if not batch:
                    break
                    
                all_db_texts.extend(batch)
                offset += page_size
                
            logger.info(f"Loaded {len(all_db_texts)} database texts for comparison")
            
        except Exception as e:
            logger.error(f"Failed to load database texts: {e}")
            return 0.0, []
        
        if not all_db_texts:
            logger.warning("No database texts loaded")
            return 0.0, []
        
        # Perbaikan: Lower similarity threshold and improved checking
        similarity_threshold = 0.6  # Reduced from 0.75
        
        def check_sentence_similarity(sentence):
            results = []
            sentence_lower = sentence.lower()
            sentence_words = set(sentence_lower.split())
            
            # Skip very short sentences
            if len(sentence_words) < 5:
                return results
            
            for db_text in all_db_texts:
                try:
                    db_content_lower = db_text.content.lower()
                    
                    # Quick word overlap check first
                    db_words = set(db_content_lower.split())
                    word_overlap = len(sentence_words.intersection(db_words)) / len(sentence_words.union(db_words))
                    
                    # Only do expensive similarity check if word overlap is promising
                    if word_overlap > 0.3:
                        similarity = SequenceMatcher(None, sentence_lower, db_content_lower).ratio()
                        
                        if similarity > similarity_threshold:
                            results.append({
                                'text': sentence[:200],  # Limit text length
                                'similarity': similarity,
                                'source': db_text.source or 'Unknown',
                                'title': db_text.title[:100] if db_text.title else 'Untitled'  # Limit title length
                            })
                            
                except Exception as e:
                    logger.debug(f"Similarity check failed for one entry: {e}")
                    continue
                    
            return results
        
        # Process sentences with improved error handling
        processed_count = 0
        max_sentences = min(50, len(substantial_sentences))  # Limit sentences processed
        
        for sentence in substantial_sentences[:max_sentences]:
            try:
                results = check_sentence_similarity(sentence)
                plagiarism_results.extend(results)
                processed_count += 1
                
                # Log progress for long operations
                if processed_count % 10 == 0:
                    logger.debug(f"Processed {processed_count}/{max_sentences} sentences")
                    
            except Exception as e:
                logger.warning(f"Failed to check sentence similarity: {e}")
                continue
        
        # Calculate plagiarism score with improved logic
        total_sentences = len(substantial_sentences)
        flagged_sentences = len(set(result['text'][:50] for result in plagiarism_results))  # Use first 50 chars as key
        plagiarism_score = (flagged_sentences / total_sentences) * 100 if total_sentences > 0 else 0
        
        # Sort results by similarity and limit
        plagiarism_results.sort(key=lambda x: x['similarity'], reverse=True)
        limited_results = plagiarism_results[:15]  # Reduced from 20 to 15
        
        logger.info(f"Plagiarism check completed: {plagiarism_score:.2f}% score, {len(limited_results)} flagged items")
        
        return round(plagiarism_score, 2), limited_results

    def _basic_grammar_check(self, text, language='id'):
        """Fallback grammar check using expanded patterns when LanguageTool fails"""
        import re

        errors = []
        error_count = 0

        if language == 'id':
            patterns = [
                # Awalan dan akhiran
                (r'\bdi\s+(?![a-z])', 'Penulisan "di" seharusnya disambung dengan kata berikutnya'),
                (r'\bke\s+(?![a-z])', 'Penulisan "ke" seharusnya disambung dengan kata berikutnya'),
                (r'\b(meng|meny|men|mem|me|ber|ter)\s+[a-z]', 'Awalan harus disambung tanpa spasi'),
                (r'[a-z]\s+(ku|mu|nya)\b', 'Akhiran "-ku", "-mu", atau "-nya" seharusnya disambung'),

                # Kapitalisasi
                (r'(?<=\.\s)[a-z]', 'Awal kalimat seharusnya huruf kapital'),
                (r'\b[a-z]+\s+[A-Z][a-z]+', 'Kemungkinan kesalahan kapitalisasi di tengah kalimat'),

                # Tanda baca
                (r'\s+[.,;!?]', 'Tanda baca tidak boleh didahului spasi'),
                (r'[.,;!?](?![\s\n])', 'Tanda baca harus diikuti spasi'),

                # Kata ulang tidak disambung
                (r'\b(\w+)\s+\1\b', 'Penulisan kata ulang seharusnya menggunakan tanda hubung, misalnya "buku-buku"'),

                # Kata baku umum (hanya indikasi, tidak validasi kosakata)
                (r'\bgak\b', 'Gunakan bentuk baku seperti "tidak"'),
                (r'\bnggak\b', 'Gunakan bentuk baku seperti "tidak"'),
            ]
        else:
            patterns = [
                (r'\ba\s+[aeiouAEIOU]', 'Use "an" before vowel sounds'),
                (r'\ban\s+[bcdfghjklmnpqrstvwxyzBCDFGHJKLMNPQRSTVWXYZ]', 'Use "a" before consonant sounds'),
                (r'\b[iI]\s', 'Capitalize "I"'),
                (r'\.[A-Z]', 'Missing space after period'),
                (r'\s+[.,;!?]', 'No space before punctuation'),
                (r'[.,;!?](?!\s)', 'Add space after punctuation'),
            ]

        for pattern, message in patterns:
            matches = re.finditer(pattern, text)
            for match in matches:
                error_count += 1
                if len(errors) < 20:
                    errors.append({
                        'message': message,
                        'context': text[max(0, match.start() - 20):match.end() + 20],
                        'offset': match.start(),
                        'length': match.end() - match.start(),
                        'suggestions': []
                    })

        return error_count, errors


    def check_grammar_optimized(self, text, language='id'):
        """Optimized grammar checking with improved error handling"""
        logger.info(f"Starting grammar check for language: {language}")
        
        # Perbaikan: Explicit check for tool availability
        if language not in self.grammar_tools or self.grammar_tools[language] is None:
            logger.warning(f"Grammar tool not available for language: {language}, using fallback")
            return self._basic_grammar_check(text, language)
        
        try:
            # Perbaikan: Smaller chunk size and better error handling
            chunk_size = 2000  # Reduced from 5000
            chunks = [text[i:i+chunk_size] for i in range(0, len(text), chunk_size)]
            
            all_errors = []
            total_errors = 0
            
            logger.info(f"Processing {len(chunks)} chunks for grammar check")
            
            for i, chunk in enumerate(chunks[:8]):  # Reduced from 10 to 8 chunks
                try:
                    logger.debug(f"Checking grammar for chunk {i+1}/{min(8, len(chunks))}")
                    matches = self.grammar_tools[language].check(chunk)
                    chunk_errors = []
                    
                    for match in matches[:15]:  # Reduced from 20 to 15
                        error_info = {
                            'message': match.message,
                            'context': match.context,
                            'offset': match.offset + (i * chunk_size),
                            'length': match.errorLength,
                            'suggestions': [str(suggestion) for suggestion in match.replacements[:3]]
                        }
                        chunk_errors.append(error_info)
                    
                    all_errors.extend(chunk_errors)
                    total_errors += len(matches)
                    
                    logger.debug(f"Chunk {i+1} completed: {len(matches)} errors found")
                    
                except Exception as e:
                    logger.error(f"Grammar check error for chunk {i}: {e}")
                    # Don't fail completely, continue with next chunk
                    continue
            
            logger.info(f"Grammar check completed: {total_errors} total errors, {len(all_errors)} detailed errors")
            return total_errors, all_errors[:30]  # Reduced from 50 to 30
            
        except Exception as e:
            logger.error(f"Grammar checking failed completely: {e}", exc_info=True)
            # Fallback to basic grammar check
            return self._basic_grammar_check(text, language)

    def check_academic_language_optimized(self, text, language='id'):
        """Optimized academic language analysis"""
        words = re.findall(r'\b\w+\b', text.lower())
        total_words = len(words)
        
        if total_words == 0:
            return 0, []
        
        # Get word sets for the detected language
        academic_words = self.academic_words.get(language, self.academic_words['en'])
        non_academic_words = self.non_academic_words.get(language, self.non_academic_words['en'])
        
        # Count academic and non-academic words
        academic_count = sum(1 for word in words if word in academic_words)
        non_academic_count = sum(1 for word in words if word in non_academic_words)
        
        # Calculate academic score
        academic_ratio = academic_count / total_words
        non_academic_ratio = non_academic_count / total_words
        
        academic_score = max(0, (academic_ratio * 100) - (non_academic_ratio * 50))
        
        # Find problematic phrases (limit results)
        problematic_phrases = []
        text_lower = text.lower()
        
        for phrase in list(non_academic_words)[:20]:  # Limit check
            if phrase in text_lower:
                problematic_phrases.append(phrase)
        
        return academic_score, problematic_phrases

    def check_format_compliance_optimized(self, text, format_type, language='id'):
        """Optimized format compliance checking"""
        if format_type not in JOURNAL_FORMATS:
            return 0, []
        
        format_rules = JOURNAL_FORMATS[format_type]
        errors = []
        
        # Check title format
        lines = text.split('\n')
        non_empty_lines = [line.strip() for line in lines if line.strip()]
        
        if non_empty_lines:
            title_line = non_empty_lines[0]
            if not re.match(format_rules['title_pattern'], title_line):
                errors.append("Format judul tidak sesuai pola yang diperlukan" if language == 'id' 
                            else "Title format doesn't match required pattern")
        
        # Check for required sections
        text_lower = text.lower()
        required_sections = format_rules['sections'].get(language, format_rules['sections']['en'])
        
        missing_sections = []
        for section in required_sections:
            if section not in text_lower:
                missing_sections.append(section)
        
        # Only report missing if more than half are missing (flexible check)
        if len(missing_sections) > len(required_sections) // 2:
            if language == 'id':
                errors.append(f"Bagian yang hilang: {', '.join(missing_sections)}")
            else:
                errors.append(f"Missing sections: {', '.join(missing_sections)}")
        
        # Check abstract and keywords
        if format_rules['abstract_required']:
            abstract_terms = ['abstract', 'abstrak'] if language == 'id' else ['abstract']
            if not any(term in text_lower for term in abstract_terms):
                errors.append("Abstrak diperlukan tetapi tidak ditemukan" if language == 'id' 
                            else "Abstract is required but missing")
        
        if format_rules['keywords_required']:
            keyword_terms = ['keywords', 'kata kunci'] if language == 'id' else ['keywords']
            if not any(term in text_lower for term in keyword_terms):
                errors.append("Kata kunci diperlukan tetapi tidak ditemukan" if language == 'id' 
                            else "Keywords are required but missing")
        
        # Calculate compliance score
        compliance_score = max(0, 100 - (len(errors) * 15))  # More lenient scoring
        
        return compliance_score, errors

    def analyze_document_optimized(self, file_path, format_type):
        """Optimized complete document analysis"""
        logger.info(f"Starting analysis of {file_path}")
        
        # Extract text
        text = self.extract_text_from_file(file_path)
        
        if not text.strip():
            return None
        
        # Detect language
        language = self.detect_language(text[:1000])  # Use first 1000 chars for detection
        logger.info(f"Detected language: {language}")
        
        # Perform analysis in parallel where possible
        futures = {}
        
        # Start plagiarism check
        futures['plagiarism'] = self.executor.submit(
            self.check_plagiarism_optimized, text, language
        )
        
        # Start grammar check
        futures['grammar'] = self.executor.submit(
            self.check_grammar_optimized, text, language
        )
        
        # Start academic language check
        futures['academic'] = self.executor.submit(
            self.check_academic_language_optimized, text, language
        )
        
        # Start format check
        futures['format'] = self.executor.submit(
            self.check_format_compliance_optimized, text, format_type, language
        )
        
        # Collect results with timeout
        results = {}
        for key, future in futures.items():
            try:
                results[key] = future.result(timeout=60)  # 30 second timeout
            except Exception as e:
                logger.error(f"Analysis failed for {key}: {e}")
                # Provide default values
                if key == 'plagiarism':
                    results[key] = (0.0, [])
                elif key == 'grammar':
                    results[key] = (0, [])
                elif key == 'academic':
                    results[key] = (50.0, [])  # Default neutral score
                elif key == 'format':
                    results[key] = (50.0, [])
        
        plagiarism_score, plagiarism_results = results.get('plagiarism', (0.0, []))
        grammar_error_count, grammar_errors = results.get('grammar', (0, []))
        academic_score, non_academic_phrases = results.get('academic', (50.0, []))
        format_score, format_errors = results.get('format', (50.0, []))
        
        # Calculate readability scores
        try:
            readability_score = flesch_reading_ease(text)
            grade_level = flesch_kincaid_grade(text)
        except:
            readability_score = 50.0  # Default neutral score
            grade_level = 12.0
        
        # Generate highlighted text (simplified for performance)
        issues = {
            'plagiarism': plagiarism_results[:10],  # Limit for performance
            'grammar': grammar_errors[:20],
            'non_academic': non_academic_phrases[:10]
        }
        
        highlighted_text = self.generate_highlights_optimized(text, issues)
        
        # Calculate overall score
        overall_score = (
            (100 - plagiarism_score) * 0.3 +
            (100 - min(grammar_error_count, 100)) * 0.25 +
            academic_score * 0.25 +
            format_score * 0.2
        )
        
        logger.info(f"Analysis completed. Overall score: {overall_score}")
        
        return {
            'original_text': text[:1000],  # Limit stored text size
            'highlighted_text': highlighted_text[:1000],  # Limit highlighted text
            'language': language,
            'plagiarism_score': round(plagiarism_score, 2),
            'plagiarism_results': plagiarism_results[:10],
            'grammar_error_count': grammar_error_count,
            'grammar_errors': grammar_errors[:20],
            'academic_score': round(academic_score, 2),
            'non_academic_phrases': non_academic_phrases[:10],
            'format_score': round(format_score, 2),
            'format_errors': format_errors,
            'readability_score': round(readability_score, 2),
            'grade_level': round(grade_level, 2),
            'overall_score': round(overall_score, 2),
            'word_count': len(text.split()),
            'character_count': len(text)
        }

    def generate_highlights_optimized(self, text, issues):
        """Optimized text highlighting with limited processing"""
        # For very long texts, only highlight the first portion
        max_highlight_length = 10000
        text_to_highlight = text[:max_highlight_length] if len(text) > max_highlight_length else text
        
        highlighted_text = text_to_highlight
        
        # Add highlighting with limits to prevent performance issues
        try:
            # Plagiarism highlighting (limited)
            for item in issues.get('plagiarism', [])[:5]:
                problem_text = item['text'][:200]  # Limit length
                if problem_text in highlighted_text:
                    highlighted_text = highlighted_text.replace(
                        problem_text,
                        f'<span class="highlight-plagiarism" title="Plagiarisme terdeteksi">{problem_text}</span>',
                        1  # Only replace first occurrence
                    )
            
            # Non-academic language highlighting (limited)
            for phrase in issues.get('non_academic', [])[:5]:
                if len(phrase) > 50:  # Skip very long phrases
                    continue
                highlighted_text = re.sub(
                    r'\b' + re.escape(phrase) + r'\b',
                    f'<span class="highlight-academic" title="Bahasa non-akademik">{phrase}</span>',
                    highlighted_text,
                    count=3,  # Limit replacements
                    flags=re.IGNORECASE
                )
        
        except Exception as e:
            logger.warning(f"Highlighting error: {e}")
            # Return original text if highlighting fails
            return text_to_highlight
        
        return highlighted_text

# Initialize optimized analyzer
analyzer = OptimizedJournalAnalyzer()

@app.route('/')
def index():
    return render_template('index.html', formats=list(JOURNAL_FORMATS.keys()))

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({'error': 'Tidak ada file yang dipilih'}), 400
    
    file = request.files['file']
    format_type = request.form.get('format', 'ieee')
    
    if file.filename == '':
        return jsonify({'error': 'Tidak ada file yang dipilih'}), 400
    
    if file and allowed_file(file.filename):
        # Generate session ID
        if 'session_id' not in session:
            session['session_id'] = str(uuid.uuid4())
        
        filename = secure_filename(file.filename)
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(file_path)
        
        # Analyze document
        try:
            logger.info(f"Starting analysis for file: {filename}")
            results = analyzer.analyze_document_optimized(file_path, format_type)
            
            if results is None:
                return jsonify({'error': 'Tidak dapat mengekstrak teks dari file'}), 400
            
            # Save analysis to database
            analysis = Analysis(
                session_id=session['session_id'],
                filename=filename,
                journal_format=format_type,
                language=results.get('language', 'id'),
                plagiarism_score=results['plagiarism_score'],
                grammar_errors=results['grammar_error_count'],
                format_errors=len(results['format_errors']),
                academic_score=results['academic_score'],
                analysis_data=json.dumps(results, default=str, ensure_ascii=False)
            )
            
            db.session.add(analysis)
            db.session.commit()
            
            # Clean up uploaded file
            try:
                os.remove(file_path)
            except:
                pass
            
            logger.info(f"Analysis completed for file: {filename}")
            
            return jsonify({
                'success': True,
                'analysis_id': analysis.id,
                'results': results
            })
            
        except Exception as e:
            logger.error(f"Analysis failed for {filename}: {e}")
            # Clean up uploaded file
            try:
                os.remove(file_path)
            except:
                pass
            return jsonify({'error': f'Analisis gagal: {str(e)}'}), 500
    
    return jsonify({'error': 'Tipe file tidak valid'}), 400

@app.route('/download_report/<int:analysis_id>')
def download_report(analysis_id):
    analysis = Analysis.query.get_or_404(analysis_id)
    
    if analysis.session_id != session.get('session_id'):
        return "Tidak diizinkan", 403
    
    try:
        results = json.loads(analysis.analysis_data)
    except:
        return "Data analisis tidak valid", 400
    
    # Generate PDF report
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    styles = getSampleStyleSheet()
    story = []
    
    # Title
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=16,
        spaceAfter=30,
    )
    
    # Determine language for report
    language = results.get('language', 'id')
    
    if language == 'id':
        story.append(Paragraph("Laporan Analisis Jurnal", title_style))
        story.append(Spacer(1, 12))
        
        # Basic Info
        story.append(Paragraph(f"<b>File:</b> {analysis.filename}", styles['Normal']))
        story.append(Paragraph(f"<b>Format:</b> {analysis.journal_format.upper()}", styles['Normal']))
        story.append(Paragraph(f"<b>Bahasa:</b> {'Indonesia' if analysis.language == 'id' else 'English'}", styles['Normal']))
        story.append(Paragraph(f"<b>Tanggal Analisis:</b> {analysis.created_at.astimezone(timezone('Asia/Jakarta')).strftime('%Y-%m-%d %H:%M')}", styles['Normal']))
        story.append(Spacer(1, 20))
        
        # Scores Summary
        story.append(Paragraph("Ringkasan Analisis", styles['Heading2']))
        story.append(Paragraph(f"Skor Keseluruhan: {results['overall_score']}/100", styles['Normal']))
        story.append(Paragraph(f"Skor Plagiarisme: {results['plagiarism_score']}%", styles['Normal']))
        story.append(Paragraph(f"Kesalahan Tata Bahasa: {results['grammar_error_count']}", styles['Normal']))
        story.append(Paragraph(f"Skor Bahasa Akademik: {results['academic_score']}/100", styles['Normal']))
        story.append(Paragraph(f"Kepatuhan Format: {results['format_score']}/100", styles['Normal']))
        story.append(Paragraph(f"Jumlah Kata: {results['word_count']}", styles['Normal']))
        story.append(Spacer(1, 20))
        
        # Detailed Issues
        if results.get('format_errors'):
            story.append(Paragraph("Masalah Format", styles['Heading3']))
            for error in results['format_errors'][:10]:  # Limit to 10 errors
                story.append(Paragraph(f"• {error}", styles['Normal']))
            story.append(Spacer(1, 12))
        
        if results.get('non_academic_phrases'):
            story.append(Paragraph("Bahasa Non-Akademik", styles['Heading3']))
            for phrase in results['non_academic_phrases'][:10]:  # Limit to 10 phrases
                story.append(Paragraph(f"• {phrase}", styles['Normal']))
            story.append(Spacer(1, 12))
        
        if results.get('plagiarism_results'):
            story.append(Paragraph("Indikasi Plagiarisme", styles['Heading3']))
            for item in results['plagiarism_results'][:5]:  # Limit to 5 items
                story.append(Paragraph(f"• Kesamaan {item['similarity']:.1%} dengan: {item['title']}", styles['Normal']))
            story.append(Spacer(1, 12))
    
    else:
        story.append(Paragraph("Journal Analysis Report", title_style))
        story.append(Spacer(1, 12))
        
        # Basic Info
        story.append(Paragraph(f"<b>File:</b> {analysis.filename}", styles['Normal']))
        story.append(Paragraph(f"<b>Format:</b> {analysis.journal_format.upper()}", styles['Normal']))
        story.append(Paragraph(f"<b>Language:</b> {'Indonesian' if analysis.language == 'id' else 'English'}", styles['Normal']))
        story.append(Paragraph(f"<b>Analysis Date:</b> {analysis.created_at.astimezone(timezone('Asia/Jakarta')).strftime('%Y-%m-%d %H:%M')}", styles['Normal']))
        story.append(Spacer(1, 20))
        
        # Scores Summary
        story.append(Paragraph("Analysis Summary", styles['Heading2']))
        story.append(Paragraph(f"Overall Score: {results['overall_score']}/100", styles['Normal']))
        story.append(Paragraph(f"Plagiarism Score: {results['plagiarism_score']}%", styles['Normal']))
        story.append(Paragraph(f"Grammar Errors: {results['grammar_error_count']}", styles['Normal']))
        story.append(Paragraph(f"Academic Language Score: {results['academic_score']}/100", styles['Normal']))
        story.append(Paragraph(f"Format Compliance: {results['format_score']}/100", styles['Normal']))
        story.append(Paragraph(f"Word Count: {results['word_count']}", styles['Normal']))
        story.append(Spacer(1, 20))
        
        # Detailed Issues
        if results.get('format_errors'):
            story.append(Paragraph("Format Issues", styles['Heading3']))
            for error in results['format_errors'][:10]:
                story.append(Paragraph(f"• {error}", styles['Normal']))
            story.append(Spacer(1, 12))
        
        if results.get('non_academic_phrases'):
            story.append(Paragraph("Non-Academic Language", styles['Heading3']))
            for phrase in results['non_academic_phrases'][:10]:
                story.append(Paragraph(f"• {phrase}", styles['Normal']))
            story.append(Spacer(1, 12))
        
        if results.get('plagiarism_results'):
            story.append(Paragraph("Plagiarism Indicators", styles['Heading3']))
            for item in results['plagiarism_results'][:5]:
                story.append(Paragraph(f"• {item['similarity']:.1%} similarity with: {item['title']}", styles['Normal']))
            story.append(Spacer(1, 12))
    
    # Build PDF
    try:
        doc.build(story)
        buffer.seek(0)
        
        return send_file(
            buffer,
            as_attachment=True,
            download_name=f"laporan_analisis_{analysis.id}.pdf",
            mimetype='application/pdf'
        )
    except Exception as e:
        logger.error(f"PDF generation failed: {e}")
        return "Gagal membuat laporan PDF", 500

@app.route('/history')
def history():
    if 'session_id' not in session:
        return render_template('history.html', analyses=[])
    
    analyses = Analysis.query.filter_by(
        session_id=session['session_id']
    ).order_by(Analysis.created_at.desc()).limit(50).all()  # Limit to 50 recent analyses
    
    return render_template('history.html', analyses=analyses)

@app.route('/api/status/<int:analysis_id>')
def get_analysis_status(analysis_id):
    """Get analysis status for real-time updates"""
    analysis = Analysis.query.get_or_404(analysis_id)
    
    if analysis.session_id != session.get('session_id'):
        return jsonify({'error': 'Unauthorized'}), 403
    
    return jsonify({
        'id': analysis.id,
        'status': 'completed',
        'created_at': analysis.created_at.isoformat(),
        'filename': analysis.filename,
        'overall_score': analysis.analysis_data
    })

def allowed_file(filename):
    ALLOWED_EXTENSIONS = {'txt', 'pdf', 'docx', 'doc'}
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# Error handlers
@app.errorhandler(413)
def too_large(e):
    return jsonify({'error': 'File terlalu besar. Maksimal 50MB.'}), 413

@app.errorhandler(500)
def internal_error(e):
    logger.error(f"Internal server error: {e}")
    return jsonify({'error': 'Terjadi kesalahan server internal'}), 500

@app.errorhandler(404)
def not_found(e):
    return jsonify({'error': 'Halaman tidak ditemukan'}), 404

def init_database():
    """Initialize database with comprehensive sample data"""
    try:
        with app.app_context():
            db.create_all()
            logger.info("Database tables created successfully")
            
            # Perbaikan: Check if data exists and validate
            existing_count = PlagiarismDatabase.query.count()
            logger.info(f"Existing database entries: {existing_count}")
            
            if existing_count == 0:
                logger.info("Initializing database with sample data...")
                
                # Perbaikan: More comprehensive sample data
                sample_texts = [
                    # --- Indonesian Academic Texts ---
                    {
                        'title': 'Pembelajaran Mesin dan Aplikasinya dalam Industri',
                        'content': 'Pembelajaran mesin adalah bagian dari kecerdasan buatan yang berfokus pada algoritma dan model statistik yang digunakan komputer untuk melakukan tugas spesifik tanpa instruksi eksplisit.',
                        'authors': 'Dr. Ahmad Santoso, Prof. Budi Prasetyo',
                        'year': 2020,
                        'source': 'Jurnal Teknik Informatika Indonesia',
                        'language': 'id'
                    },
                    {
                        'title': 'Analisis Data dalam Era Digital: Tantangan dan Peluang',
                        'content': 'Era digital telah menghadirkan volume data yang sangat besar. Analisis data menggabungkan metode statistik dengan teknik komputasi untuk mengekstrak informasi berguna.',
                        'authors': 'Prof. Siti Nurhaliza, Dr. Andi Wijaya',
                        'year': 2021,
                        'source': 'Jurnal Sains Data Indonesia',
                        'language': 'id'
                    },
                    {
                        'title': 'Sistem Informasi Manajemen: Konsep dan Implementasi',
                        'content': 'Sistem informasi manajemen modern mengintegrasikan TI dengan proses bisnis untuk mendukung pengambilan keputusan.',
                        'authors': 'Dr. Bambang Sutrisno, M.Kom',
                        'year': 2022,
                        'source': 'Jurnal Sistem Informasi dan Teknologi',
                        'language': 'id'
                    },
                    {
                        'title': 'Metodologi Penelitian dalam Ilmu Komputer',
                        'content': 'Penelitian dalam ilmu komputer memerlukan metodologi yang sesuai untuk menghasilkan kontribusi ilmiah yang valid.',
                        'authors': 'Prof. Dr. Indira Sari, M.T.',
                        'year': 2023,
                        'source': 'Jurnal Penelitian Ilmu Komputer',
                        'language': 'id'
                    },
                    {
                        'title': 'Keamanan Siber: Ancaman dan Strategi Pertahanan',
                        'content': 'Berbagai ancaman siber memerlukan strategi pertahanan berlapis yang komprehensif.',
                        'authors': 'Dr. Rizky Pratama, S.Kom., M.T.',
                        'year': 2023,
                        'source': 'Jurnal Keamanan Informasi',
                        'language': 'id'
                    },
                    {
                        'title': 'Peran Ekonomi Digital dalam Peningkatan UMKM di Indonesia',
                        'content': 'Ekonomi digital membuka peluang baru bagi UMKM untuk berkembang melalui platform e-commerce dan pembayaran digital.',
                        'authors': 'Dr. Lestari Rahayu',
                        'year': 2022,
                        'source': 'Jurnal Ekonomi dan Bisnis Indonesia',
                        'language': 'id'
                    },
                    {
                        'title': 'Pendidikan Karakter di Sekolah Dasar: Sebuah Pendekatan Holistik',
                        'content': 'Pendidikan karakter merupakan bagian penting dalam membentuk pribadi siswa melalui nilai-nilai moral dan etika.',
                        'authors': 'Prof. Nina Suryani, M.Pd.',
                        'year': 2021,
                        'source': 'Jurnal Pendidikan dan Kebudayaan',
                        'language': 'id'
                    },
                    {
                        'title': 'Dampak Perubahan Iklim terhadap Ketahanan Pangan Nasional',
                        'content': 'Perubahan iklim mempengaruhi produktivitas pertanian yang berdampak pada ketahanan pangan nasional.',
                        'authors': 'Dr. Yudha Permana',
                        'year': 2020,
                        'source': 'Jurnal Agrikultura Tropika',
                        'language': 'id'
                    },
                    {
                        'title': 'Pengaruh Media Sosial terhadap Perilaku Remaja di Perkotaan',
                        'content': 'Media sosial mempengaruhi persepsi diri dan interaksi sosial remaja secara signifikan.',
                        'authors': 'Dr. Dini Maharani',
                        'year': 2023,
                        'source': 'Jurnal Psikologi Sosial',
                        'language': 'id'
                    },

                    # --- Indonesian Academic Texts (Tambahan) ---
                    {
                        'title': 'Analisis Yuridis terhadap Tindak Pidana Siber di Indonesia',
                        'content': 'Tindak pidana siber menimbulkan tantangan baru bagi sistem hukum Indonesia, khususnya dalam hal pembuktian dan yurisdiksi. Perlu pendekatan hukum yang adaptif terhadap perkembangan teknologi.',
                        'authors': 'Dr. Farid Maulana, S.H., M.H.',
                        'year': 2022,
                        'source': 'Jurnal Hukum dan Teknologi',
                        'language': 'id'
                    },
                    {
                        'title': 'Potensi Energi Terbarukan di Kawasan Timur Indonesia',
                        'content': 'Kawasan Timur Indonesia memiliki potensi besar dalam pengembangan energi terbarukan seperti tenaga surya dan angin. Optimalisasi potensi ini memerlukan investasi dan infrastruktur yang memadai.',
                        'authors': 'Prof. Wulandari Pramesti',
                        'year': 2021,
                        'source': 'Jurnal Energi dan Lingkungan',
                        'language': 'id'
                    },
                    {
                        'title': 'Teknik Irigasi Terkini untuk Pertanian Berkelanjutan',
                        'content': 'Sistem irigasi modern seperti drip irrigation dapat meningkatkan efisiensi penggunaan air dan hasil pertanian, terutama di daerah kering.',
                        'authors': 'Ir. Hendra Wijaya, M.Agr.',
                        'year': 2023,
                        'source': 'Jurnal Teknologi Pertanian',
                        'language': 'id'
                    },
                    {
                        'title': 'Revitalisasi Budaya Lokal Melalui Media Digital',
                        'content': 'Media digital menjadi alat penting dalam melestarikan dan mempromosikan budaya lokal kepada generasi muda dan audiens global.',
                        'authors': 'Dr. Sari Dewi, M.Sn.',
                        'year': 2023,
                        'source': 'Jurnal Seni dan Budaya Nusantara',
                        'language': 'id'
                    },
                    {
                        'title': 'Penerapan BIM (Building Information Modeling) dalam Konstruksi Gedung Tinggi',
                        'content': 'Building Information Modeling (BIM) memberikan efisiensi dalam perencanaan dan pelaksanaan proyek konstruksi gedung tinggi.',
                        'authors': 'Ir. Agus Pratomo, M.T.',
                        'year': 2022,
                        'source': 'Jurnal Teknik Sipil Modern',
                        'language': 'id'
                    },
                    {
                        'title': 'Persepsi Masyarakat terhadap Vaksinasi COVID-19 di Pedesaan',
                        'content': 'Tingkat penerimaan vaksin di pedesaan dipengaruhi oleh tingkat pendidikan, kepercayaan masyarakat, dan informasi yang tersedia.',
                        'authors': 'Dr. Lutfiah Handayani, M.PH.',
                        'year': 2021,
                        'source': 'Jurnal Kesehatan Masyarakat Indonesia',
                        'language': 'id'
                    },
                    {
                        'title': 'Perkembangan Ekonomi Syariah di Asia Tenggara',
                        'content': 'Ekonomi syariah terus berkembang pesat di Asia Tenggara didorong oleh populasi muslim yang besar dan dukungan kebijakan pemerintah.',
                        'authors': 'Dr. Zaki Ramadhan, M.E.I.',
                        'year': 2023,
                        'source': 'Jurnal Ekonomi Islam Global',
                        'language': 'id'
                    },
                    {
                        'title': 'Kajian Linguistik terhadap Bahasa Gaul di Media Sosial',
                        'content': 'Penggunaan bahasa gaul di media sosial mencerminkan dinamika bahasa dalam masyarakat urban dan generasi muda.',
                        'authors': 'Prof. Andika Mahendra, M.Hum.',
                        'year': 2022,
                        'source': 'Jurnal Linguistik Kontemporer',
                        'language': 'id'
                    },
                    {
                        'title': 'Strategi Pendidikan Inklusif di Sekolah Dasar',
                        'content': 'Pendidikan inklusif memerlukan pendekatan pedagogis yang fleksibel dan dukungan lingkungan belajar yang adaptif bagi semua siswa.',
                        'authors': 'Dr. Fitriani Lestari, M.Pd.',
                        'year': 2023,
                        'source': 'Jurnal Pendidikan Khusus dan Inklusif',
                        'language': 'id'
                    },
                    {
                        'title': 'Analisis Pengaruh Kualitas Layanan terhadap Kepuasan Pelanggan E-Commerce',
                        'content': 'Kualitas layanan yang baik memiliki pengaruh signifikan terhadap tingkat kepuasan pelanggan dalam platform e-commerce.',
                        'authors': 'Dr. Siti Aisyah',
                        'year': 2023,
                        'source': 'Jurnal Ekonomi Digital',
                        'language': 'id'
                    },
                    {
                        'title': 'Penggunaan Drone dalam Pemetaan Wilayah Pertanian',
                        'content': 'Drone menjadi alat efektif dalam pemetaan lahan pertanian dan pemantauan kondisi tanaman secara real-time.',
                        'authors': 'Ir. Bambang Purnomo',
                        'year': 2022,
                        'source': 'Jurnal Pertanian Modern',
                        'language': 'id'
                    },
                    {
                        'title': 'Perbandingan Efektivitas Pembelajaran Tatap Muka dan Daring',
                        'content': 'Studi ini membandingkan hasil belajar antara pembelajaran tatap muka dan pembelajaran daring selama pandemi.',
                        'authors': 'Dr. Nurhayati',
                        'year': 2021,
                        'source': 'Jurnal Pendidikan Indonesia',
                        'language': 'id'
                    },
                    {
                        'title': 'Efek Paparan Polusi Udara terhadap Kesehatan Anak di Perkotaan',
                        'content': 'Anak-anak di wilayah perkotaan lebih rentan terhadap gangguan pernapasan akibat tingginya polusi udara.',
                        'authors': 'Dr. Eko Prasetyo',
                        'year': 2022,
                        'source': 'Jurnal Kesehatan Masyarakat',
                        'language': 'id'
                    },
                    {
                        'title': 'Perancangan Aplikasi Mobile untuk Deteksi Dini Diabetes Mellitus',
                        'content': 'Aplikasi ini dirancang untuk membantu pengguna melakukan deteksi dini terhadap risiko diabetes melalui input data kesehatan.',
                        'authors': 'Ir. Nia Ayuningtyas',
                        'year': 2024,
                        'source': 'Jurnal Informatika Medis',
                        'language': 'id'
                    },
                    {
                        'title': 'Evaluasi Program Vaksinasi COVID-19 di Indonesia',
                        'content': 'Evaluasi mencakup efektivitas distribusi, penerimaan masyarakat, dan dampak vaksinasi terhadap angka kasus.',
                        'authors': 'Dr. Hendra Wijaya',
                        'year': 2023,
                        'source': 'Jurnal Epidemiologi Nasional',
                        'language': 'id'
                    },
                    {
                        'title': 'Analisis Sentimen Pengguna Twitter terhadap Kebijakan Pemerintah',
                        'content': 'Data mining digunakan untuk menganalisis opini masyarakat melalui media sosial mengenai kebijakan nasional.',
                        'authors': 'Dr. Lestari Dewi',
                        'year': 2023,
                        'source': 'Jurnal Ilmu Komputer dan Sosial',
                        'language': 'id'
                    },
                    {
                        'title': 'Pemanfaatan Limbah Organik menjadi Energi Biogas',
                        'content': 'Konversi limbah organik menjadi biogas merupakan solusi energi terbarukan yang ramah lingkungan.',
                        'authors': 'Dr. Ahmad Fauzan',
                        'year': 2022,
                        'source': 'Jurnal Teknologi Energi',
                        'language': 'id'
                    },
                    {
                        'title': 'Kajian Terhadap Ketahanan Pangan di Masa Krisis Global',
                        'content': 'Ketahanan pangan menjadi isu krusial dalam menghadapi krisis ekonomi dan bencana alam yang berdampak luas.',
                        'authors': 'Dr. Indah Kartika',
                        'year': 2024,
                        'source': 'Jurnal Sosial Ekonomi Pertanian',
                        'language': 'id'
                    },
                    {
                        'title': 'Manajemen Risiko Proyek Konstruksi di Kawasan Perkotaan',
                        'content': 'Identifikasi risiko dan strategi mitigasi penting dalam menjamin keberhasilan proyek konstruksi skala besar.',
                        'authors': 'Ir. Suryo Hadi',
                        'year': 2021,
                        'source': 'Jurnal Teknik Sipil Indonesia',
                        'language': 'id'
                    },
                    {
                        'title': 'Strategi Pengelolaan Sampah Berbasis Komunitas di Perkotaan',
                        'content': 'Pengelolaan sampah berbasis komunitas terbukti efektif mengurangi beban TPA dan meningkatkan kesadaran lingkungan masyarakat.',
                        'authors': 'Dr. Yuliana Rahayu',
                        'year': 2023,
                        'source': 'Jurnal Lingkungan Perkotaan',
                        'language': 'id'
                    },
                    {
                        'title': 'Penerapan Algoritma Genetika dalam Optimasi Jadwal Produksi',
                        'content': 'Algoritma genetika dapat digunakan untuk menyusun jadwal produksi optimal di industri manufaktur dengan mengurangi waktu idle mesin.',
                        'authors': 'Ir. Dwi Wicaksono',
                        'year': 2022,
                        'source': 'Jurnal Rekayasa Industri',
                        'language': 'id'
                    },
                    {
                        'title': 'Kepemimpinan Transformasional dalam Organisasi Pemerintah',
                        'content': 'Gaya kepemimpinan transformasional mampu meningkatkan kinerja dan motivasi pegawai sektor publik.',
                        'authors': 'Dr. Rina Kurniasari',
                        'year': 2021,
                        'source': 'Jurnal Administrasi Negara',
                        'language': 'id'
                    },
                    {
                        'title': 'Tinjauan Hukum terhadap Perlindungan Data Pribadi di Indonesia',
                        'content': 'Regulasi terkait perlindungan data pribadi masih memerlukan harmonisasi agar sejalan dengan praktik global.',
                        'authors': 'Dr. Andika Mahendra',
                        'year': 2023,
                        'source': 'Jurnal Hukum Siber',
                        'language': 'id'
                    },
                    {
                        'title': 'Pengaruh Gaya Hidup terhadap Pola Konsumsi Masyarakat Perkotaan',
                        'content': 'Modernisasi dan urbanisasi membentuk pola konsumsi baru yang berdampak pada sektor ritel dan keuangan.',
                        'authors': 'Dr. Lailatul Husna',
                        'year': 2022,
                        'source': 'Jurnal Sosiologi Modern',
                        'language': 'id'
                    },
                    {
                        'title': 'Desain Kurikulum STEAM untuk Sekolah Dasar di Indonesia',
                        'content': 'Penerapan pendekatan STEAM dapat meningkatkan minat siswa pada bidang sains dan teknologi sejak dini.',
                        'authors': 'Dr. Farhan Ridwan',
                        'year': 2023,
                        'source': 'Jurnal Pendidikan Dasar',
                        'language': 'id'
                    },
                    {
                        'title': 'Analisis Dampak Sosial Pembangunan Jalan Tol',
                        'content': 'Pembangunan infrastruktur jalan tol berdampak sosial signifikan terhadap masyarakat sekitar terutama dalam hal relokasi dan ekonomi lokal.',
                        'authors': 'Dr. Mega Yuliarti',
                        'year': 2022,
                        'source': 'Jurnal Pembangunan Wilayah',
                        'language': 'id'
                    },
                    {
                        'title': 'Rekayasa Perangkat Lunak dalam Sistem Informasi Rumah Sakit',
                        'content': 'Perancangan sistem informasi rumah sakit memerlukan pendekatan modular, integratif, dan berorientasi pasien.',
                        'authors': 'M. Arif Setiawan, M.Kom',
                        'year': 2021,
                        'source': 'Jurnal Teknologi Informasi Kesehatan',
                        'language': 'id'
                    },
                    {
                        'title': 'Model Pembelajaran Adaptif Berbasis AI untuk Pendidikan Jarak Jauh',
                        'content': 'Pembelajaran berbasis kecerdasan buatan dapat menyesuaikan konten sesuai kebutuhan dan kemampuan masing-masing siswa.',
                        'authors': 'Dr. Dian Rosita',
                        'year': 2023,
                        'source': 'Jurnal Teknologi Pendidikan',
                        'language': 'id'
                    },
                    {
                        'title': 'Pemanfaatan IoT untuk Monitoring Kualitas Air Sungai',
                        'content': 'Sensor berbasis IoT memberikan data real-time yang dapat digunakan untuk pengambilan kebijakan lingkungan secara cepat.',
                        'authors': 'Ir. Bagus Nugroho',
                        'year': 2024,
                        'source': 'Jurnal Teknologi Lingkungan',
                        'language': 'id'
                    }
                ]

                # Perbaikan: Add data with proper error handling and validation
                added_count = 0
                failed_count = 0
                
                for text_data in sample_texts:
                    try:
                        # Validate required fields
                        if not text_data.get('title') or not text_data.get('content'):
                            logger.warning(f"Skipping invalid entry: {text_data.get('title', 'No title')}")
                            failed_count += 1
                            continue
                        
                        new_entry = PlagiarismDatabase(**text_data)
                        db.session.add(new_entry)
                        added_count += 1
                        
                    except Exception as e:
                        logger.error(f"Failed to add entry '{text_data.get('title', 'Unknown')}': {e}")
                        failed_count += 1
                        continue
                
                # Perbaikan: Commit with error handling
                try:
                    db.session.commit()
                    logger.info(f"Successfully added {added_count} entries to plagiarism database")
                    if failed_count > 0:
                        logger.warning(f"Failed to add {failed_count} entries")
                        
                    # Verify data was actually inserted
                    final_count = PlagiarismDatabase.query.count()
                    logger.info(f"Final database count: {final_count}")
                    
                    # Log distribution by language
                    id_count = PlagiarismDatabase.query.filter_by(language='id').count()
                    en_count = PlagiarismDatabase.query.filter_by(language='en').count()
                    logger.info(f"Language distribution - Indonesian: {id_count}, English: {en_count}")
                    
                except Exception as e:
                    logger.error(f"Database commit failed: {e}")
                    db.session.rollback()
                    raise
            else:
                logger.info("Database already contains data, skipping initialization")
                
    except Exception as e:
        logger.error(f"Database initialization failed: {e}", exc_info=True)
        raise

def cleanup_old_data():
    """Clean up old analyses and files"""
    try:
        cutoff_date = datetime.utcnow() - timedelta(days=30)
        old_analyses = Analysis.query.filter(Analysis.created_at < cutoff_date).all()
        
        for analysis in old_analyses:
            db.session.delete(analysis)
        
        db.session.commit()
        logger.info(f"Cleaned up {len(old_analyses)} old analyses")
        
    except Exception as e:
        logger.error(f"Cleanup failed: {e}")

init_database()

if __name__ == '__main__':
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    cleanup_old_data()
    app.run(debug=False, host='0.0.0.0', port=2314, threaded=True)

# kode sampel ini terlalu berat untuk di jalankan di laptop spesifikasi rendah dan terus menerus memkana ram karena language tool dan java 
# serta model bahasa indonesia sulit di cari karena itu tolong kembangkan lebih jauh
# ini juga bukan kode yang sempurna, banyak bagian cacat yang perlu di perbaiki

