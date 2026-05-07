# File ini berisikan logika untuk memastikan respons dari Groq LLM sesuai dengan topik layanan Klinik Smart Clinic.
# Guardrail adalah filter tambahan untuk mencegah LLM memberikan jawaban yang tidak relevan, berbahaya, atau melanggar aturan yang sudah ditetapkan.

import re

# Definisikan langsung disini agar tidak perlu import dari groq_service
TOLAK_TOPIK_GUARD = (
    "Mohon maaf Bapak/Ibu, saya hanya dapat membantu hal-hal yang berkaitan "
    "dengan layanan Klinik Smart Clinic. Untuk pertanyaan di luar topik tersebut, "
    "saya tidak dapat membantu."
)

class ResponseGuardrail:
    def __init__(self):
        # Daftar pola respon yang menunjukkan struktur coding
        self.forbidden_patterns = [
            r"```",             # Markdown code block
            r"def\s+\w+\(",     # Definisi fungsi python
            r"import\s+\w+",    # Import library
            r"class\s+\w+:",    # Definisi class
            r"console\.log",    # JS
            r"<\?php",          # PHP
            r"<html>"           # HTML
        ]

    def filter(self, response: str) -> str:
        text_lower = response.lower()
        
        # Cek apakah ada pola coding
        for pattern in self.forbidden_patterns:
            if re.search(pattern, response): 
                return TOLAK_TOPIK_GUARD
        
        # Proteksi tambahan jika AI mencoba memberikan rumus matematika kompleks
        if " = " in response and any(op in response for op in ["+", "-", "*", "/"]):
             if len(re.findall(r"\d+", response)) > 3: 
                 return TOLAK_TOPIK_GUARD

        return response