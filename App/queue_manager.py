# File ini beriskan logic untuk meminimalisir kemungkinan nomor whatsapp diblokir karena terlalu cepat mengirim pesan.
# Queue Manager akan mengatur antrian pengiriman pesan ke nomor whatsapp, dengan interval tertentu untuk setiap nomor HP. 

import time
import random
import threading
import queue
import requests
import os

class MessageQueueManager:
    def __init__(self):
        self.msg_queue = queue.Queue()
        self.token = os.getenv('FONNTE_TOKEN', '').strip()
        # Jalankan worker thread secara otomatis saat init
        threading.Thread(target=self._worker, daemon=True).name = "FonnteQueueWorker"
        threading.Thread(target=self._worker).start()

    def add_to_queue(self, target, message):
        """Masukkan pesan ke antrean"""
        self.msg_queue.put({"target": target, "message": message})

    def _worker(self):
        """Worker yang berjalan terus menerus memproses antrean"""
        while True:
            item = self.msg_queue.get()
            if item is None:
                break
            
            target = item['target']
            message = item['message']

            # ── Logic untuk simulasi perilaku balasan manusia (minimalisir blokir oleh WA) ─────────────────────────────────────────────────────────
            # 1. Simulasi Waktu Mengetik (Jeda Acak)
            delay = random.uniform(3.0, 5.0) 
            print(f"[QUEUE] Menunggu {delay:.2f} detik sebelum kirim ke {target}...")
            time.sleep(delay)

            # 2. Kirim Pesan
            self._send_now(target, message)
            
            self.msg_queue.task_done()

    def _send_now(self, target, message):
        url = "https://api.fonnte.com/send"
        payload = {
            'target': target,
            'message': message,
            'countryCode': '62'
        }
        headers = {'Authorization': self.token}

        try:
            response = requests.post(url, data=payload, headers=headers)
            print(f"[QUEUE] Sent to {target}. Response: {response.text}")
        except Exception as e:
            print(f"[QUEUE] Error sending to {target}: {e}")


fonnte_queue = MessageQueueManager()