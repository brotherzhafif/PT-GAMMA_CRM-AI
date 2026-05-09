FROM python:3.9-slim
WORKDIR /app

# Ambil requirements dari folder LLM
COPY LLM/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy seluruh folder 
COPY . .

# Jalankan app.py dari folder App
CMD ["python", "App/app.py"]