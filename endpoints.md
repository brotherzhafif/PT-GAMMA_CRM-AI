# SmartClinic CRM AI Endpoints

Daftar endpoint API yang tersedia di SmartClinic CRM AI:

## System
* `GET /` - Health check
* `POST /webhook` - Terima pesan WhatsApp masuk dari wa-service
* `GET /api/status/whatsapp-connection` - Stream koneksi WhatsApp (SSE)
* `GET /api/status/rme-connection` - Stream koneksi RME SmartClinic (SSE)
* `GET /api/chatbot-settings` - Ambil chatbot settings
* `PUT /api/chatbot-settings` - Update chatbot settings

## Send
* `POST /api/send` - Kirim pesan ke satu nomor
* `POST /api/send/media` - Kirim media via upload langsung
* `POST /api/send/interactive/booking` - Kirim menu booking ke nomor tertentu
* `POST /api/send/interactive/services` - Kirim menu layanan ke nomor tertentu
* `POST /api/send/interactive/poll-feedback` - Kirim polling feedback ke nomor tertentu
* `POST /api/send/broadcast` - Broadcast pesan ke semua nomor pasien

## Marketing Campaigns
* `GET /api/marketing/campaigns` - Ambil semua campaign
* `POST /api/marketing/campaigns` - Buat campaign baru
* `GET /api/marketing/campaigns/by-name/{campaign_name}` - Ambil campaign berdasarkan nama
* `PATCH /api/marketing/campaigns/by-name/{campaign_name}` - Edit campaign berdasarkan nama
* `POST /api/marketing/campaigns/upload` - Buat campaign baru dengan file upload

## Unified Chat
* `GET /api/messages/latest` - Stream latest messages via SSE
* `GET /api/messages/{phone_number}` - Stream pesan per nomor via SSE
* `GET /api/handoff` - Ambil semua sesi handoff aktif
* `POST /api/handoff/{phone_number}` - Mulai handoff manual oleh admin
* `DELETE /api/handoff/{phone_number}` - Akhiri handoff, kembalikan ke bot
* `POST /api/handoff/{phone_number}/reply` - Admin balas pesan ke pasien

## Schedules
* `GET /api/schedules` - Ambil semua jadwal dokter
* `GET /api/schedules/weekly` - Ambil jadwal mingguan
* `GET /api/schedules/slots` - Ambil slot jadwal tersedia

## Patients
* `GET /api/patients` - Ambil semua data pasien
* `POST /api/patients` - Buat data pasien baru
* `GET /api/patients/by-phone` - Cari pasien berdasarkan nomor telepon
* `GET /api/patients/{rme_patient_id}` - Ambil data pasien berdasarkan ID
* `PUT /api/patients/{rme_patient_id}` - Perbarui data pasien
* `DELETE /api/patients/{rme_patient_id}` - Hapus data pasien

## Appointments
* `GET /api/appointment` - Ambil daftar queues
* `GET /api/appointment/appointments/by-phone` - Ambil antrean berdasarkan nomor telepon
* `DELETE /api/appointment/appointments/{id}` - Batalkan janji temu pasien
* `POST /api/appointment/appointments` - Buat janji temu

## Feedback
* `GET /api/feedback` - Ambil semua feedback
* `POST /api/feedback` - Kirim feedback
* `GET /api/feedback/dashboard` - Dashboard feedback

## Auth
* `POST /api/auth/login` - Login admin
* `POST /api/auth/logout` - Logout
* `POST /api/auth/refresh` - Refresh token

## Users
* `GET /api/users` - Get Users
* `POST /api/users` - Create User
* `GET /api/users/{id}` - Get User By Id
* `PUT /api/users/{id}` - Update User
* `DELETE /api/users/{id}` - Deactivate User

## Activity
* `GET /api/activity` - Get Activity Logs
* `GET /api/activity/notifications` - Get Notifications
* `GET /api/activity/audit` - Get Audit Logs
* `GET /api/activity/logins` - Get Login Logs
* `PUT /api/activity/{id}/read` - Mark Activity Read
* `PUT /api/activity/read-all` - Mark All Notifications Read

## Analytics
* `GET /api/analytics/summary` - Ringkasan KPI dari messages
* `GET /api/analytics/timeseries` - Tren conversations dan handling per waktu
* `GET /api/analytics/insights` - AI chatbot insights berbasis messages
