FROM python:3.9-slim
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 5000

# 0.0.0.0 wajib agar bisa diakses dari luar container.
CMD ["uvicorn", "App.app:app", "--host", "0.0.0.0", "--port", "5000"]
