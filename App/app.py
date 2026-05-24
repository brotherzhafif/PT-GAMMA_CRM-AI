# ======================================================
# SmartClinic CRM AI — app.py
# FastAPI entry point — hanya inisialisasi app dan register router.
# Logic masing-masing endpoint ada di App/routers/.
#
# Last Change   :   22 May 2026
# Developer     :   Raja Zhafif Raditya Harahap
#                   MHD. Rafy Firdaus
#                   Wahyu Hardiyantara
# ======================================================

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from App.routers import webhook, patients, messages, send, handoff, wa, campaign, schedules
from App.campaign_scheduler import start_campaign_scheduler

app = FastAPI(
    title="SmartClinic CRM AI",
    description="Hybrid routing API untuk webhook Fonnte, Rasa, dan Groq LLM.",
    version="1.0.0",
)

# Allow CORS from any origin (use with caution in production)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

#  Register Routers 
app.include_router(webhook.router)
app.include_router(send.router)
app.include_router(campaign.router)
app.include_router(messages.router)
app.include_router(handoff.router)
app.include_router(wa.router)
app.include_router(schedules.router)
app.include_router(patients.router)


@app.on_event("startup")
def _start_background_workers():
    start_campaign_scheduler()


# ======================================================
#
#               APP SYSTEM ENTRYPOINT
#
# ======================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("App.app:app", host="0.0.0.0", port=5000, reload=False)
