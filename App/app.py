# ======================================================
# SmartClinic CRM AI — app.py
# FastAPI entry point — hanya inisialisasi app dan register router.
# Logic masing-masing endpoint ada di App/routers/.
#
# Last Change   :   15 May 2026
# Developer     :   Raja Zhafif Raditya Harahap
#                   MHD. Rafy Firdaus
#                   Wahyu Hardiyantara
# ======================================================

from fastapi import FastAPI

from App.routers import webhook, patients, messages, send, handoff

app = FastAPI(
    title="SmartClinic CRM AI",
    description="Hybrid routing API untuk webhook Fonnte, Rasa, dan Groq LLM.",
    version="1.0.0",
)

#  Register Routers 
app.include_router(webhook.router)
app.include_router(patients.router)
app.include_router(messages.router)
app.include_router(send.router)
app.include_router(handoff.router)


# ======================================================
#
#               APP SYSTEM ENTRYPOINT
#
# ======================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("App.app:app", host="0.0.0.0", port=5000, reload=False)
