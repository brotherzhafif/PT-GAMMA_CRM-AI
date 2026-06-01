# File ini berisikan logic untuk meminimalisir kemungkinan nomor whatsapp diblokir karena terlalu cepat mengirim pesan.
# Queue Manager akan mengatur antrian pengiriman pesan ke nomor whatsapp, dengan interval tertentu untuk setiap nomor HP. 

import time
import random
import threading
import queue

from App.wa_service_client import wa_service_request

class MessageQueueManager:
    def __init__(self):
        self.msg_queue = queue.Queue()
        worker_thread = threading.Thread(target=self._worker, name="WAServiceQueueWorker", daemon=True)
        worker_thread.start()
        print(f"[QUEUE] Worker thread '{worker_thread.name}' started for wa-service")

    def add_to_queue(self, target, message):
        """Masukkan pesan ke antrean"""
        self.msg_queue.put({"target": target, "message": message})
        print(f"[QUEUE] Pesan untuk {target} masuk antrean. Queue size: {self.msg_queue.qsize()}")

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

            # Kirim Pesan via wa-service
            self._send_now(target, message)
            
            self.msg_queue.task_done()

    def _send_now(self, target, message):
        """Kirim pesan via wa-service dengan retry logic"""
        max_retries = 3
        retry_delay = 5
        
        for attempt in range(1, max_retries + 1):
            if self._is_wa_connected():
                if self._send_via_wa_service(target, message):
                    return
                print(f"[QUEUE] wa-service gagal kirim ke {target} (percobaan {attempt}/{max_retries})")
            else:
                print(f"[QUEUE] wa-service tidak ready (percobaan {attempt}/{max_retries})")
            
            if attempt < max_retries:
                print(f"[QUEUE] Retry dalam {retry_delay} detik...")
                time.sleep(retry_delay)
        
        print(f"[QUEUE] GAGAL kirim ke {target} setelah {max_retries} percobaan. Pesan: {message[:50]}...")

    def _is_wa_connected(self):
        """Cek apakah wa-service ready"""
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
        """Kirim pesan via wa-service"""
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
            print(f"[QUEUE] ✓ Sent to {target} via wa-service. Status: {response.status_code}")
            return True
        except Exception as e:
            print(f"[QUEUE] Error sending via wa-service to {target}: {e}")
            return False


# Global instance
wa_queue = MessageQueueManager()

# Made with Bob
