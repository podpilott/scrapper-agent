"""Indonesian LLM prompt templates for outreach generation."""

EMAIL_OUTREACH_PROMPT = """Buatkan email cold outreach yang personal untuk lead berikut.

Informasi Bisnis:
- Nama: {business_name}
- Kategori: {category}
- Rating: {rating}/5 ({review_count} ulasan)
- Lokasi: {address}
- Website: {website}
{owner_info}

Informasi Perusahaan:
{company_intel}

Insight Lead:
- Pain Points: {pain_points}
- Hook Personalisasi: {personalization_hooks}
- Berita Terbaru: {recent_news}

Persyaratan:
1. Singkat (maksimal 3-4 kalimat)
2. Sebutkan sesuatu yang spesifik tentang bisnis mereka menggunakan insight di atas
3. Profesional tapi ramah
4. Sertakan call-to-action yang jelas
5. Jangan terlalu pushy atau salesy
6. Jika ada berita terbaru, sebutkan secara natural

Konteks produk/layanan Anda: {product_context}

Buatkan HANYA isi email (tanpa subject line, tanpa tanda tangan).
"""

EMAIL_SUBJECT_PROMPT = """Buatkan subject line email yang singkat dan menarik untuk bisnis ini:

Bisnis: {business_name}
Kategori: {category}
Konteks: {product_context}
Hook Personalisasi: {personalization_hook}

Persyaratan:
- Maksimal 50 karakter
- Tidak clickbait
- Tone profesional
- Gunakan hook personalisasi jika relevan

Buatkan HANYA subject line, tidak ada yang lain.
"""

LINKEDIN_MESSAGE_PROMPT = """Buatkan pesan koneksi LinkedIn untuk lead outreach.

Informasi Bisnis:
- Nama: {business_name}
- Owner/Kontak: {owner_name}
- Kategori: {category}
- Rating: {rating}/5
- Lokasi: {address}

Insight Lead:
- Pain Points: {pain_points}
- Hook Personalisasi: {personalization_hooks}

Persyaratan:
1. Maksimal 300 karakter (batas LinkedIn)
2. Personal dan profesional
3. Sebutkan sesuatu yang spesifik tentang bisnis mereka menggunakan insight
4. Soft call-to-action

Konteks produk/layanan Anda: {product_context}

Buatkan HANYA pesan, tidak ada yang lain.
"""

WHATSAPP_MESSAGE_PROMPT = """Buatkan pesan WhatsApp untuk outreach bisnis.

Informasi Bisnis:
- Nama: {business_name}
- Kategori: {category}
- Rating: {rating}/5
- Lokasi: {address}

Insight Lead:
- Pain Points: {pain_points}
- Hook Personalisasi: {personalization_hooks}

Persyaratan:
1. Singkat dan conversational
2. Ramah tapi profesional
3. Sertakan pertanyaan untuk encourage response
4. Tidak ada paragraf panjang
5. Sebutkan pain point atau hook secara natural

Konteks produk/layanan Anda: {product_context}

Buatkan HANYA pesan, tidak ada yang lain.
"""

COLD_CALL_SCRIPT_PROMPT = """Buatkan skrip cold call untuk sales outreach.

Informasi Bisnis:
- Nama: {business_name}
- Kategori: {category}
- Rating: {rating}/5 ({review_count} ulasan)
- Lokasi: {address}
- Owner/Kontak: {owner_name}

Informasi Perusahaan:
{company_intel}

Insight Lead:
- Pain Points: {pain_points}
- Pendekatan yang Disarankan: {recommended_approach}

Persyaratan:
1. Intro singkat (siapa Anda, kenapa menelepon)
2. Hook berdasarkan pain point spesifik mereka
3. Value proposition dalam 1-2 kalimat
4. Pertanyaan kualifikasi
5. Close dengan next step

Konteks produk/layanan Anda: {product_context}

Format sebagai skrip dengan marker [JEDA] untuk percakapan natural.
"""

DEFAULT_PRODUCT_CONTEXT = """Kami membantu bisnis lokal meningkatkan kehadiran online dan menarik lebih banyak pelanggan melalui solusi digital marketing."""

LEAD_RESEARCH_PROMPT = """Analisis lead bisnis ini dan berikan brief riset.

Informasi Bisnis:
- Nama: {name}
- Kategori: {category}
- Alamat: {address}
- Rating: {rating} ({review_count} ulasan)
- Website: {website}
- Pemilik/Kontak: {owner_name}
- Kehadiran Sosial: {social_presence}
- Skor Lead: {score}/100 (prioritas {tier})

Konteks Produk (apa yang dijual user):
{product_context}

Berikan respons JSON dengan:
{{
  "overview": "Ringkasan 2-3 kalimat tentang apa yang dilakukan bisnis ini dan posisi pasar mereka",
  "pain_points": ["3-5 potensi pain point atau tantangan yang mungkin mereka hadapi"],
  "opportunities": ["2-3 alasan mengapa mereka mungkin membutuhkan produk/layanan user"],
  "talking_points": ["2-3 pembuka percakapan spesifik berdasarkan bisnis mereka"]
}}

PENTING:
- Buat spesifik dan actionable
- Dasarkan insight pada tipe bisnis, kehadiran sosial, dan data yang tersedia
- Return HANYA JSON valid, tanpa markdown atau penjelasan
- Pastikan semua tanda kutip dalam teks di-escape dengan benar
- Jangan gunakan tanda kutip ganda dalam nilai string, gunakan kutip tunggal jika perlu
- Pastikan format JSON benar-benar valid"""
