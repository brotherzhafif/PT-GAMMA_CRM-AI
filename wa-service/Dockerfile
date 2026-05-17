# ======================================================
# wa-service/Dockerfile
# Node.js + Chromium untuk whatsapp-web.js di ARM64
# ======================================================

# Pakai node:20-bullseye karena Chromium tersedia native di ARM64
FROM node:20-bullseye-slim

# Install Chromium dan dependencies Puppeteer
RUN apt-get update && apt-get install -y \
    chromium \
    fonts-freefont-ttf \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libcups2 \
    libdrm2 \
    libgbm1 \
    libgtk-3-0 \
    libnss3 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxkbcommon0 \
    libxrandr2 \
    xdg-utils \
    --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

# Install qrcode library (untuk convert QR string ke PNG)
RUN npm install -g qrcode

WORKDIR /app

# Copy package.json dan install dependencies
COPY package.json .
RUN npm install

# Copy source code
COPY index.js .

# Beritahu Puppeteer pakai Chromium yang sudah terinstall (bukan download sendiri)
ENV PUPPETEER_SKIP_CHROMIUM_DOWNLOAD=true
ENV PUPPETEER_EXECUTABLE_PATH=/usr/bin/chromium

EXPOSE 3000

CMD ["node", "index.js"]
