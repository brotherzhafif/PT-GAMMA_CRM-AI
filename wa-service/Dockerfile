# ==========================================
# STAGE 1: Builder (Install Node Dependencies)
# ==========================================
FROM node:20-bullseye-slim AS builder

WORKDIR /app

# Copy package files duluan untuk memanfaatkan Docker cache layer
COPY package*.json ./

# Install seluruh dependencies (termasuk devDependencies jika dibutuhkan saat build)
# Gunakan npm ci agar instalasi lebih clean dan cepat sesuai package-lock.json
RUN npm ci && npm cache clean --force


# ==========================================
# STAGE 2: Production (Final Slim Image)
# ==========================================
FROM node:20-bullseye-slim

# Set environment variabel Puppeteer di awal agar terbaca oleh system
ENV PUPPETEER_SKIP_CHROMIUM_DOWNLOAD=true
ENV PUPPETEER_EXECUTABLE_PATH=/usr/bin/chromium
ENV NODE_ENV=production

# Install Chromium & runtime dependencies saja (tanpa build tools tambahan)
RUN apt-get update && apt-get install -y --no-install-recommends \
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
    && rm -rf /var/lib/apt/lists/*

# Install global CLI tools jika memang dibutuhkan di runtime
RUN npm install -g qrcode && npm cache clean --force

WORKDIR /app

# Copy node_modules hasil instalasi bersih dari Stage 1
COPY --from=builder /app/node_modules ./node_modules
COPY package.json .

# Copy source code utama
COPY index.js .

EXPOSE 3000

CMD ["node", "index.js"]