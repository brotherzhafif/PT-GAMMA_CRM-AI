// ======================================================
// SmartClinic CRM AI — wa-service/index.js
// Service Node.js untuk kirim attachment via WhatsApp
// Menggunakan whatsapp-web.js + Puppeteer
//
// Endpoint:
//   GET  /status           Cek status koneksi WA
//   GET  /qr               Ambil QR code untuk login (base64)
//   POST /send-attachment  Kirim file ke nomor WA
//
// Last Change   :   16 May 2026
// Developer     :   Raja Zhafif Raditya Harahap
// ======================================================

const express = require('express')
const { Client, LocalAuth, MessageMedia } = require('whatsapp-web.js')
const qrcode = require('qrcode-terminal')
const axios = require('axios')

const app = express()
app.use(express.json())

const PORT = process.env.PORT || 3000

// ── State ─────────────────────────────────────────────────────────────────────
let qrCodeData = null      // QR code string untuk ditampilkan
let isReady = false        // true jika WA sudah terkoneksi
let isInitializing = true  // true selama proses init/scan QR

// ── WhatsApp Client ───────────────────────────────────────────────────────────
const client = new Client({
    authStrategy: new LocalAuth({
        // Session disimpan di folder /app/.wwebjs_auth di dalam container
        // Di-mount ke volume Docker agar persistent setelah restart
        dataPath: '/app/.wwebjs_auth',
    }),
    puppeteer: {
        headless: true,
        args: [
            '--no-sandbox',
            '--disable-setuid-sandbox',
            '--disable-dev-shm-usage',
            '--disable-accelerated-2d-canvas',
            '--no-first-run',
            '--no-zygote',
            '--disable-gpu',
        ],
    },
})

// ── Events ────────────────────────────────────────────────────────────────────

client.on('qr', (qr) => {
    qrCodeData = qr
    isReady = false
    isInitializing = false
    // Tampilkan QR di terminal juga untuk debugging
    qrcode.generate(qr, { small: true })
    console.log('[WA] QR Code generated — scan via GET /qr atau lihat terminal')
})

client.on('ready', () => {
    isReady = true
    isInitializing = false
    qrCodeData = null
    console.log('[WA] WhatsApp siap digunakan!')
})

client.on('authenticated', () => {
    console.log('[WA] Authenticated — session tersimpan')
})

client.on('auth_failure', (msg) => {
    isReady = false
    console.error('[WA] Auth gagal:', msg)
})

client.on('disconnected', (reason) => {
    isReady = false
    isInitializing = true
    console.warn('[WA] Disconnected:', reason)
    // Auto reconnect
    client.initialize()
})

// Mulai inisialisasi client
client.initialize()
console.log('[WA] Initializing WhatsApp client...')


// ── Helper ────────────────────────────────────────────────────────────────────

/**
 * Format nomor WA — pastikan pakai format internasional tanpa +
 * Contoh: 08123 → 628123, 628123 → 628123
 */
function formatNumber(number) {
    let num = number.replace(/\D/g, '') // hapus non-digit
    if (num.startsWith('0')) {
        num = '62' + num.slice(1)
    }
    return `${num}@c.us`
}

/**
 * Download file dari URL dan konversi ke MessageMedia
 */
async function urlToMedia(url, filename) {
    const response = await axios.get(url, { responseType: 'arraybuffer' })
    const buffer = Buffer.from(response.data)
    const base64 = buffer.toString('base64')
    const mimeType = response.headers['content-type'] || 'application/octet-stream'
    return new MessageMedia(mimeType, base64, filename || 'file')
}

/**
 * Delay untuk simulasi human behavior (anti-ban)
 */
function delay(ms) {
    return new Promise(resolve => setTimeout(resolve, ms))
}


// ══════════════════════════════════════════════════════════════════════════════
// ENDPOINTS
// ══════════════════════════════════════════════════════════════════════════════

/**
 * GET /status
 * Cek status koneksi WhatsApp.
 */
app.get('/status', (req, res) => {
    res.json({
        status: isReady ? 'connected' : isInitializing ? 'initializing' : 'disconnected',
        ready: isReady,
        has_qr: !!qrCodeData,
    })
})


/**
 * GET /qr
 * Ambil QR code dalam format base64 PNG.
 * Tampilkan di dashboard admin untuk proses scan pertama kali.
 */
app.get('/qr', async (req, res) => {
    if (isReady) {
        return res.json({ status: 'already_connected', qr: null })
    }
    if (!qrCodeData) {
        return res.json({ status: isInitializing ? 'initializing' : 'no_qr', qr: null })
    }

    // Convert QR string ke base64 PNG
    const QRCode = require('qrcode')
    const qrBase64 = await QRCode.toDataURL(qrCodeData)
    res.json({ status: 'qr_ready', qr: qrBase64 })
})


/**
 * POST /send-attachment
 * Kirim file ke nomor WhatsApp.
 *
 * Body:
 *   target          : string — nomor WA tujuan (628xxx)
 *   message         : string — caption/pesan (opsional)
 *   attachment_url  : string — URL publik file (PDF, JPG, PNG, dll)
 *   filename        : string — nama file yang tampil di WA (opsional)
 */
app.post('/send-attachment', async (req, res) => {
    const { target, message = '', attachment_url, filename } = req.body

    if (!target || !attachment_url) {
        return res.status(400).json({
            status: 'error',
            message: 'target dan attachment_url wajib diisi',
        })
    }

    if (!isReady) {
        return res.status(503).json({
            status: 'error',
            message: 'WhatsApp belum terkoneksi. Scan QR dulu via GET /qr',
            has_qr: !!qrCodeData,
        })
    }

    try {
        const chatId = formatNumber(target)

        // Download file dari URL dan konversi ke format WA
        console.log(`[WA] Download attachment dari: ${attachment_url}`)
        const media = await urlToMedia(attachment_url, filename)

        // Delay acak 2-5 detik sebelum kirim (anti-ban)
        const delayMs = Math.floor(Math.random() * 3000) + 2000
        console.log(`[WA] Delay ${delayMs}ms sebelum kirim ke ${target}...`)
        await delay(delayMs)

        // Kirim file
        await client.sendMessage(chatId, media, {
            caption: message,
        })

        console.log(`[WA] Attachment terkirim ke ${target} (${filename || 'file'})`)
        res.json({ status: 'ok', message: `Attachment terkirim ke ${target}` })

    } catch (err) {
        console.error(`[WA] Error kirim ke ${target}:`, err.message)
        res.status(500).json({ status: 'error', message: err.message })
    }
})


// ── Start Server ──────────────────────────────────────────────────────────────
app.listen(PORT, () => {
    console.log(`[WA] Service berjalan di http://0.0.0.0:${PORT}`)
    console.log(`[WA] Endpoints: GET /status | GET /qr | POST /send-attachment`)
})
