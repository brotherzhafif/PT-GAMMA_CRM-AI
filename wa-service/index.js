// ======================================================
// SmartClinic CRM AI — wa-service/index.js
// Service Node.js untuk kirim attachment via WhatsApp
// Menggunakan whatsapp-web.js + Puppeteer
//
// Endpoint:
//  GET  /status           Cek status koneksi WA
//  GET  /qr               Ambil QR code untuk login (base64)
//  POST /send-message     Kirim pesan teks ke nomor WA
//  POST /send-attachment  Kirim file ke nomor WA
//
// Last Change   :   18 May 2026
// Developer     :   Raja Zhafif Raditya Harahap
// ======================================================

const express = require('express')
const { Client, LocalAuth, MessageMedia, Buttons, List, Poll } = require('whatsapp-web.js')
const qrcode = require('qrcode-terminal')
const axios = require('axios')
const multer = require('multer')
const fs = require('fs')
const path = require('path')

const app = express()
app.use(express.json())

const PORT = process.env.PORT || 3000
const CHAT_FILES_DIR = '/app/chat_files'

if (!fs.existsSync(CHAT_FILES_DIR)) {
    fs.mkdirSync(CHAT_FILES_DIR, { recursive: true })
}

const storage = multer.diskStorage({
    destination: (req, file, cb) => cb(null, CHAT_FILES_DIR),
    filename: (req, file, cb) => {
        const safeOriginalName = (file.originalname || 'upload')
            .replace(/[^a-zA-Z0-9._-]+/g, '_')
            .replace(/_+/g, '_')
        cb(null, `${Date.now()}-${safeOriginalName}`)
    },
})

const upload = multer({ storage })

// State 
let qrCodeData = null      // QR code string untuk ditampilkan
let isReady = false        // true jika WA sudah terkoneksi
let isInitializing = true  // true selama proses init/scan QR

// WhatsApp Client 
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

// Events 

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


// Helper 

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

function getMediaMethod(mimeType) {
    if (!mimeType) return 'document'
    if (mimeType.startsWith('image/')) return 'image'
    if (mimeType.startsWith('video/')) return 'video'
    if (mimeType.startsWith('audio/')) return 'audio'
    return 'document'
}

async function sendMediaByType(chatId, media, mimeType, caption) {
    const mediaType = getMediaMethod(mimeType)

    if (mediaType === 'image') {
        await client.sendMessage(chatId, media, { caption: caption || '' })
        return 'image'
    }

    if (mediaType === 'video') {
        await client.sendMessage(chatId, media, { caption: caption || '' })
        return 'video'
    }

    if (mediaType === 'audio') {
        await client.sendMessage(chatId, media, { sendAudioAsVoice: false })
        return 'audio'
    }

    await client.sendMessage(chatId, media, {
        caption: caption || '',
        sendMediaAsDocument: true,
    })
    return 'document'
}

function normalizeButtons(buttons) {
    return (buttons || []).map((button, index) => ({
        id: button.id || button.buttonId || `btn_${index + 1}`,
        body: button.body || button.text || button.title || `Pilihan ${index + 1}`,
    }))
}

function normalizeSections(sections) {
    return (sections || []).map((section, sectionIndex) => ({
        title: section.title || `Bagian ${sectionIndex + 1}`,
        rows: (section.rows || []).map((row, rowIndex) => ({
            id: row.id || row.rowId || `row_${sectionIndex + 1}_${rowIndex + 1}`,
            title: row.title || row.body || `Opsi ${rowIndex + 1}`,
            description: row.description || '',
        })),
    }))
}

function normalizePollOptions(pollOptions) {
    return (pollOptions || []).map((option, index) => {
        if (typeof option === 'string') {
            return { name: option, localId: index + 1 }
        }

        return {
            name: option.name || option.body || `Opsi ${index + 1}`,
            localId: option.localId || index + 1,
        }
    })
}

async function sendInteractiveMessage(chatId, payload) {
    const type = (payload.type || '').toLowerCase()

    if (type === 'buttons') {
        const interactive = new Buttons(
            payload.body || '',
            normalizeButtons(payload.buttons),
            payload.title || null,
            payload.footer || null,
        )
        return client.sendMessage(chatId, interactive)
    }

    if (type === 'list') {
        const interactive = new List(
            payload.body || '',
            payload.buttonText || 'Pilih',
            normalizeSections(payload.sections),
            payload.title || null,
            payload.footer || null,
        )
        return client.sendMessage(chatId, interactive)
    }

    if (type === 'poll') {
        const interactive = new Poll(
            payload.pollName || 'Polling',
            normalizePollOptions(payload.pollOptions),
            payload.options || {},
        )
        return client.sendMessage(chatId, interactive)
    }

    throw new Error(`Tipe interactive tidak didukung: ${payload.type}`)
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
 * POST /send-media
 * Upload media file langsung, simpan lokal di chat_files, lalu kirim sesuai tipe file.
 */
app.post('/send-media', upload.single('file'), async (req, res) => {
    const { target, message = '' } = req.body

    if (!target || !req.file) {
        return res.status(400).json({
            status: 'error',
            message: 'target dan file wajib diisi',
        })
    }

    if (!isReady) {
        return res.status(503).json({
            status: 'error',
            message: 'WhatsApp belum terkoneksi. Scan QR dulu via GET /qr',
            has_qr: !!qrCodeData,
        })
    }

    const savedPath = req.file.path
    const mimeType = req.file.mimetype || 'application/octet-stream'
    const chatId = formatNumber(target)

    try {
        const media = MessageMedia.fromFilePath(savedPath)

        const delayMs = Math.floor(Math.random() * 3000) + 2000
        console.log(`[WA] Delay ${delayMs}ms sebelum kirim media ke ${target}...`)
        await delay(delayMs)

        const sentAs = await sendMediaByType(chatId, media, mimeType, message)

        console.log(`[WA] Media terkirim ke ${target} sebagai ${sentAs} (${path.basename(savedPath)})`)
        res.json({
            status: 'ok',
            message: `Media terkirim ke ${target}`,
            stored_file: path.basename(savedPath),
            mime_type: mimeType,
            send_method: sentAs,
        })
    } catch (err) {
        console.error(`[WA] Error kirim media ke ${target}:`, err.message)
        res.status(500).json({ status: 'error', message: err.message })
    }
})


/**
 * POST /send-message
 * Kirim pesan teks ke nomor WhatsApp.
 *
 * Body:
 *   target   : string — nomor WA tujuan (628xxx)
 *   message  : string — isi pesan
 */
app.post('/send-message', async (req, res) => {
    const { target, message } = req.body

    if (!target || !message) {
        return res.status(400).json({
            status: 'error',
            message: 'target dan message wajib diisi',
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

        // Delay acak 2-5 detik sebelum kirim (anti-ban)
        const delayMs = Math.floor(Math.random() * 3000) + 2000
        console.log(`[WA] Delay ${delayMs}ms sebelum kirim teks ke ${target}...`)
        await delay(delayMs)

        await client.sendMessage(chatId, message)
        console.log(`[WA] Pesan teks terkirim ke ${target}`)

        res.json({ status: 'ok', message: `Pesan terkirim ke ${target}` })
    } catch (err) {
        console.error(`[WA] Error kirim teks ke ${target}:`, err.message)
        res.status(500).json({ status: 'error', message: err.message })
    }
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
        const sentAs = await sendMediaByType(chatId, media, media.mimetype, message)

        console.log(`[WA] Attachment terkirim ke ${target} sebagai ${sentAs} (${filename || 'file'})`)
        res.json({ status: 'ok', message: `Attachment terkirim ke ${target}`, send_method: sentAs })

    } catch (err) {
        console.error(`[WA] Error kirim ke ${target}:`, err.message)
        res.status(500).json({ status: 'error', message: err.message })
    }
})


/**
 * POST /send-interactive
 * Kirim pesan interaktif: buttons, list, atau poll.
 */
app.post('/send-interactive', async (req, res) => {
    const { target, type } = req.body

    if (!target || !type) {
        return res.status(400).json({
            status: 'error',
            message: 'target dan type wajib diisi',
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

        const delayMs = Math.floor(Math.random() * 3000) + 2000
        console.log(`[WA] Delay ${delayMs}ms sebelum kirim interactive ke ${target}...`)
        await delay(delayMs)

        const sentMessage = await sendInteractiveMessage(chatId, req.body)

        res.json({
            status: 'ok',
            message: `Interactive message terkirim ke ${target}`,
            type,
            message_id: sentMessage?.id?._serialized || sentMessage?.id || null,
        })
    } catch (err) {
        console.error(`[WA] Error kirim interactive ke ${target}:`, err.message)
        res.status(500).json({ status: 'error', message: err.message })
    }
})


// Start Server 
app.listen(PORT, () => {
    console.log(`[WA] Service berjalan di http://0.0.0.0:${PORT}`)
    console.log(`[WA] Endpoints: GET /status | GET /qr | POST /send-message | POST /send-media | POST /send-interactive | POST /send-attachment`)
})
