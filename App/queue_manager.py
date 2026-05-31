# File ini beriskan logic untuk meminimalisir kemungkinan nomor whatsapp diblokir karena terlalu cepat mengirim pesan.
# Queue Manager akan mengatur antrian pengiriman pesan ke nomor whatsapp, dengan interval tertentu untuk setiap nomor HP. 

import time
import random
import threading
import queue
import os

from App.wa_service_client import wa_service_request

class MessageQueueManager:
    def __init__(self):
        self.msg_queue = queue.Queue()
        self.token = os.getenv('FONNTE_TOKEN', '').strip()
        worker_thread = threading.Thread(target=self._worker, name="FonnteQueueWorker", daemon=True)
        worker_thread.start()
        print(f"[QUEUE] Worker thread '{worker_thread.name}' started. Token loaded: {'yes' if self.token else 'NO - cek .env!'}")

    def add_to_queue(self, target, message):
        """Masukkan pesan ke antrean"""
        self.msg_queue.put({"target": target, "message": message})
        print(f"[QUEUE] Pesan dari {target} masuk antrean. Queue size: {self.msg_queue.qsize()}")

    def _worker(self):
        """Worker yang berjalan terus menerus memproses antrean"""
        while True:
            item = self.msg_queue.get()
            if item is None:
                break
            
            target = item['target']
            message = item['message']

            # ── Logic untuk simulasi perilaku balasan manusia (minimalisir blokir oleh WA) ──
            delay = random.uniform(3.0, 5.0) 
            print(f"[QUEUE] Menunggu {delay:.2f} detik sebelum kirim ke {target}...")
            time.sleep(delay)

            # 2. Kirim Pesan
            self._send_now(target, message)
            
            self.msg_queue.task_done()

    def _send_now(self, target, message):
        if self._is_wa_connected():
            if self._send_via_wa_service(target, message):
                return
            print(f"[QUEUE] wa-service gagal kirim ke {target}, fallback ke Fonnte...")

        self._send_via_fonnte(target, message)

    def _is_wa_connected(self):
        try:
            response = wa_service_request("GET", "/status", timeout=4)
            if response.status_code != 200:
                return False
            data = response.json() or {}
            return bool(data.get("ready"))
        except Exception as e:
            print(f"[QUEUE] Gagal cek status wa-service: {e}")
            return False

    def _send_via_wa_service(self, target, message):
        try:
            response = wa_service_request(
                "POST",
                "/send-message",
                json={"target": target, "message": message},
                timeout=20,
            )
            if response.status_code >= 400:
                print(f"[QUEUE] wa-service error {response.status_code}: {response.text}")
                return False
            print(f"[QUEUE] Sent to {target} via wa-service. Status: {response.status_code}")
            return True
        except Exception as e:
            print(f"[QUEUE] Error sending via wa-service to {target}: {e}")
            return False

    def _send_via_fonnte(self, target, message):
        url = "https://api.fonnte.com/send"
        payload = {
            'target': target,
            'message': message,
            'countryCode': '62'
        }
        headers = {'Authorization': self.token}

        try:
            response = requests.post(url, data=payload, headers=headers)
            print(f"[QUEUE] Sent to {target}. Status: {response.status_code} | Response: {response.text}")
        except Exception as e:
            print(f"[QUEUE] Error sending to {target}: {e}")


fonnte_queue = MessageQueueManager()