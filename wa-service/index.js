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
const AUTH_DATA_PATH = '/app/.wwebjs_auth'
const WA_EXECUTABLE_PATH = process.env.PUPPETEER_EXECUTABLE_PATH || '/usr/bin/chromium'

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

// Map: numericId → full chatId (@c.us atau @lid)
// Diisi saat pesan masuk dari kontak @lid agar balasan pakai format yang benar
const lidChatMap = new Map()

// WhatsApp Client 
let client = null

let bootstrapPromise = null

function createClient() {
    return new Client({
        authStrategy: new LocalAuth({
            // Session disimpan di folder /app/.wwebjs_auth di dalam container
            // Di-mount ke volume Docker agar persistent setelah restart
            dataPath: AUTH_DATA_PATH,
        }),
        puppeteer: {
            headless: true,
            executablePath: WA_EXECUTABLE_PATH,
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
}

async function disposeClient(instance) {
    if (!instance) return

    try {
        await instance.destroy()
    } catch (error) {
        if (instance.pupBrowser?.close) {
            try {
                await instance.pupBrowser.close()
            } catch (closeError) {
                // Abaikan error cleanup agar retry tetap berjalan.
            }
        }
    }
}

function clearStaleBrowserLocks() {
    const lockFileNames = ['SingletonLock', 'SingletonCookie', 'SingletonSocket']

    // Cari lock files secara rekursif di semua subdirektori auth path
    function clearInDir(directory) {
        if (!fs.existsSync(directory)) return
        for (const fileName of lockFileNames) {
            const filePath = path.join(directory, fileName)
            if (fs.existsSync(filePath)) {
                try {
                    fs.unlinkSync(filePath)
                    console.log(`[WA] Dihapus lock file: ${filePath}`)
                } catch (error) {
                    // Abaikan — retry akan menangani sendiri.
                }
            }
        }
        // Rekursi ke subdirektori
        try {
            for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
                if (entry.isDirectory()) {
                    clearInDir(path.join(directory, entry.name))
                }
            }
        } catch (error) {
            // Abaikan error baca direktori.
        }
    }

    clearInDir(AUTH_DATA_PATH)
}

async function getCurrentWhatsAppStatus() {
    let connectionState = null

    try {
        if (client) {
            connectionState = await client.getState()
        }
    } catch (error) {
        connectionState = null
    }

    const normalizedState = typeof connectionState === 'string' ? connectionState.toUpperCase() : null
    const browserConnected = !!client?.pupBrowser?.isConnected?.()
    const connected = !!isReady && browserConnected && normalizedState === 'CONNECTED'
    const initializing = !!isInitializing && !connected

    return {
        status: connected ? 'connected' : initializing ? 'initializing' : 'disconnected',
        ready: connected,
        has_qr: !!qrCodeData,
        connection_state: connectionState,
    }
}

client = createClient()

async function bootstrapClient() {
    if (bootstrapPromise) {
        return bootstrapPromise
    }

    bootstrapPromise = (async () => {
        let attempt = 0

        while (true) {
            attempt += 1

            try {
                isInitializing = true
                // Bersihkan lock file SEBELUM setiap percobaan inisialisasi
                // agar sisa lock dari container sebelumnya tidak menghalangi
                clearStaleBrowserLocks()

                if (!client) {
                    client = createClient()
                    attachClientEvents(client)
                }
                await client.initialize()
                return
            } catch (error) {
                isReady = false
                qrCodeData = null
                isInitializing = true
                console.error(`[WA] Gagal inisialisasi client (percobaan ${attempt}):`, error)

                await disposeClient(client)
                client = null
                clearStaleBrowserLocks()

                const retryDelayMs = Math.min(30000, 5000 * attempt)
                await delay(retryDelayMs)
            }
        }
    })().finally(() => {
        bootstrapPromise = null
    })

    return bootstrapPromise
}

// Events 

function attachClientEvents(instance) {
    instance.on('qr', (qr) => {
        qrCodeData = qr
        isReady = false
        isInitializing = false
        // Tampilkan QR di terminal juga untuk debugging
        qrcode.generate(qr, { small: true })
        console.log('[WA] QR Code generated — scan via GET /qr atau lihat terminal')
    })

    instance.on('ready', () => {
        isReady = true
        isInitializing = false
        qrCodeData = null
        console.log('[WA] WhatsApp siap digunakan!')
    })

    instance.on('authenticated', () => {
        console.log('[WA] Authenticated — session tersimpan')
    })

    instance.on('auth_failure', (msg) => {
        isReady = false
        console.error('[WA] Auth gagal:', msg)
    })

    instance.on('disconnected', (reason) => {
        isReady = false
        isInitializing = true
        qrCodeData = null
        console.warn('[WA] Disconnected:', reason)
        // Auto reconnect
        void bootstrapClient()
    })

    // ── INCOMING MESSAGE HANDLER ──
    // Forward semua pesan masuk ke FastAPI webhook
    instance.on('message', async (msg) => {
        try {
            // Skip pesan dari bot sendiri
            if (msg.fromMe) {
                return
            }

            const isGroup = msg.from.endsWith('@g.us')
            if (isGroup) {
                console.log(`[WA] Skip pesan grup: ${msg.from}`)
                return
            }

            const isLid = msg.from.endsWith('@lid')
            const message = msg.body || ''

            // Numeric sender ID (tanpa suffix) — bisa di-overwrite jika LID berhasil di-resolve
            let numericSender = msg.from
                .replace('@c.us', '')
                .replace('@g.us', '')
                .replace('@lid', '')

            if (isLid) {
                try {
                    let resolvedPhone = null

                    // Approach 1: contact.id._serialized dalam format @c.us (paling akurat)
                    const contact = await msg.getContact()
                    if (contact?.id?._serialized?.endsWith('@c.us')) {
                        resolvedPhone = contact.id.user
                        console.log(`[WA] LID resolved via contact.id: ${msg.from} → ${resolvedPhone}@c.us`)
                    }

                    // Approach 2: contact.number — cek panjangnya, LID biasanya >15 digit
                    if (!resolvedPhone && contact?.number) {
                        const num = String(contact.number).replace(/\D/g, '')
                        if (num.length >= 8 && num.length <= 15) {
                            resolvedPhone = num
                            console.log(`[WA] LID resolved via contact.number: ${msg.from} → ${resolvedPhone}`)
                        }
                    }

                    // Approach 3: chat.id dalam format @c.us
                    if (!resolvedPhone) {
                        const chat = await msg.getChat()
                        if (chat?.id?._serialized?.endsWith('@c.us')) {
                            resolvedPhone = chat.id.user
                            console.log(`[WA] LID resolved via chat.id: ${msg.from} → ${resolvedPhone}@c.us`)
                        }
                    }

                    if (resolvedPhone) {
                        // Normalisasi ke format Indonesia: 628xxx
                        let phone = String(resolvedPhone).replace(/\D/g, '')
                        if (phone.startsWith('0')) phone = '62' + phone.slice(1)
                        else if (!phone.startsWith('62')) phone = '62' + phone

                        // Simpan mapping: nomor telepon → @lid chatId (untuk kirim balik)
                        lidChatMap.set(phone, msg.from)
                        lidChatMap.set(numericSender, msg.from) // backup: LID numeric → @lid
                        numericSender = phone
                        console.log(`[WA] LID sender → nomor Indonesia: ${phone}`)
                    } else {
                        // Tidak bisa resolve — simpan LID mapping sebagai fallback
                        lidChatMap.set(numericSender, msg.from)
                        console.warn(`[WA] LID tidak bisa di-resolve ke nomor telepon: ${msg.from} — pakai LID ID`)
                    }
                } catch (lidErr) {
                    lidChatMap.set(numericSender, msg.from)
                    console.warn(`[WA] Error resolve LID ${msg.from}: ${lidErr.message}`)
                }
            }

            console.log(`[WA] Pesan masuk dari ${numericSender} ${isLid ? '(via LID)' : ''}: ${message.substring(0, 50)}...`)

            // Forward ke FastAPI webhook
            await axios.post('http://app:5000/webhook', {
                sender: numericSender,
                message: message,
            }, {
                timeout: 30000, // 30 detik timeout
                headers: {
                    'Content-Type': 'application/json',
                },
            })

            console.log(`[WA] Pesan dari ${numericSender} berhasil diteruskan ke webhook`)
        } catch (error) {
            console.error('[WA] Error forwarding message to webhook:', error.message)
            // Jangan throw error agar bot tetap jalan meski webhook gagal
        }
    })
}

attachClientEvents(client)

// Mulai inisialisasi client
void bootstrapClient()
console.log('[WA] Initializing WhatsApp client...')


// Helper 

/**
 * Format nomor WA — pastikan pakai format internasional tanpa +
 * Contoh: 08123 → 628123, 628123 → 628123
 */
function formatNumber(number) {
    let num = number.replace(/\D/g, '') // hapus non-digit

    // Deteksi LID (Linked ID): biasanya 14+ digit dan BUKAN berawalan 62, 0, atau 8.
    // Jika formatnya cocok dengan LID, kita kembalikan dengan @lid agar whatsapp-web.js bisa kirim.
    if (num.length >= 14 && !num.startsWith('62') && !num.startsWith('0') && !num.startsWith('8')) {
        return `${num}@lid`
    }

    if (num.startsWith('0')) {
        num = '62' + num.slice(1)
    }
    return `${num}@c.us`
}

function resolveChatId(target) {
    const value = (target || '').trim()

    if (!value) {
        return ''
    }

    if (value.endsWith('@g.us') || value.endsWith('@c.us') || value.endsWith('@lid')) {
        return value
    }

    // Cek dulu apakah nomor ini adalah kontak LID — jika iya, pakai @lid chatId
    const numericOnly = value.replace(/\D/g, '')
    if (lidChatMap.has(numericOnly)) {
        const mappedId = lidChatMap.get(numericOnly)
        console.log(`[WA] resolveChatId: LID map hit ${numericOnly} → ${mappedId}`)
        return mappedId
    }

    return formatNumber(value)
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

/**
 * Simulasi mengetik sebelum mengirim pesan (typing indicator + dynamic delay)
 *
 * Menampilkan status "typing..." di WhatsApp penerima dan menunggu
 * selama durasi yang dihitung berdasarkan panjang pesan.
 *
 * @param {string}  chatId        - Chat ID tujuan (@c.us / @lid)
 * @param {string}  text          - Teks pesan (untuk hitung delay)
 * @param {object}  opts          - Opsi konfigurasi delay
 * @param {number}  opts.baseMin  - Delay dasar minimum (ms) — waktu "berpikir"
 * @param {number}  opts.baseMax  - Delay dasar maximum (ms)
 * @param {number}  opts.msPerChar - Delay per karakter (simulasi kecepatan ketik)
 * @param {number}  opts.minTotal - Total delay minimum (ms)
 * @param {number}  opts.maxTotal - Total delay maximum (ms)
 */
async function simulateTyping(chatId, text = '', opts = {}) {
    const {
        baseMin  = 1500,
        baseMax  = 2500,
        msPerChar = 25,
        minTotal = 2000,
        maxTotal = 7000,
    } = opts

    // 1. Hitung delay dinamis: waktu berpikir + kecepatan mengetik
    const baseDelay = Math.floor(Math.random() * (baseMax - baseMin)) + baseMin
    let delayMs = baseDelay + (text.length * msPerChar)

    // 2. Clamp agar tetap wajar
    delayMs = Math.min(maxTotal, Math.max(minTotal, delayMs))

    console.log(`[WA] Typing indicator aktif selama ${delayMs}ms ke ${chatId} (${text.length} chars)`)

    // 3. Aktifkan status "typing..." di WhatsApp penerima
    try {
        const chat = await client.getChatById(chatId)
        await chat.sendStateTyping()
    } catch (err) {
        // Jika gagal aktifkan typing (misal chat belum ada), tetap lanjut kirim
        console.warn(`[WA] Gagal aktifkan typing untuk ${chatId}: ${err.message}`)
    }

    // 4. Tunggu sesuai delay yang dihitung
    await delay(delayMs)
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
    void getCurrentWhatsAppStatus()
        .then((payload) => res.json(payload))
        .catch((error) => {
            res.status(500).json({
                status: 'disconnected',
                ready: false,
                has_qr: !!qrCodeData,
                connection_state: null,
            })
        })
})


/**
 * GET /messages
 * Ambil riwayat pesan dari chat tertentu di WhatsApp secara langsung (wwebjs).
 */
app.get('/messages', async (req, res) => {
    const { target, limit } = req.query
    if (!target) {
        return res.status(400).json({ status: 'error', message: 'target (phone number) wajib diisi' })
    }
    if (!isReady) {
        return res.status(503).json({ status: 'error', message: 'WhatsApp belum terkoneksi.' })
    }
    try {
        const chatId = resolveChatId(target)
        const chat = await client.getChatById(chatId)
        const wwebMsgs = await chat.fetchMessages({ limit: parseInt(limit) || 50 })
        
        const numericPhone = target.replace(/\D/g, '').replace('@c.us', '').replace('@lid', '')
        const mappedMsgs = wwebMsgs.map(msg => {
            return {
                id: msg.id._serialized,
                sender_number: numericPhone,
                message_text: msg.body || '',
                direction: msg.fromMe ? 'outbound' : 'inbound',
                source: msg.fromMe ? 'admin' : 'wwebjs',
                created_at: new Date(msg.timestamp * 1000).toISOString()
            }
        })
        res.json({ status: 'ok', data: mappedMsgs })
    } catch (err) {
        console.error(`[WA] Error fetch messages for ${target}:`, err.message)
        res.status(500).json({ status: 'error', message: err.message })
    }
})


/**
 * GET /qr
 * Ambil QR code dalam format base64 PNG.
 * Tampilkan di dashboard admin untuk proses scan pertama kali.
 */
app.get('/qr', async (req, res) => {
    const currentStatus = await getCurrentWhatsAppStatus()

    if (currentStatus.ready) {
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
    const chatId = resolveChatId(target)

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
        const chatId = resolveChatId(target)

        // Typing indicator + delay dinamis berdasarkan panjang pesan
        await simulateTyping(chatId, message)

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
        const chatId = resolveChatId(target)

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
        const chatId = resolveChatId(target)

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
