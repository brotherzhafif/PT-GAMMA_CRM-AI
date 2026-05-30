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

from App.auth.router import router as auth_router
from App.routers.activity import router as activity_router
from App.routers.users import router as users_router
from App.routers import status, webhook, patients, messages, send, handoff, campaign, schedules, appointments, chatbot_settings, feedback
from App.campaign_scheduler import start_campaign_scheduler
from .seed_bootstrap_users import seed_bootstrap_users_from_env

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
app.include_router(status.router)
app.include_router(schedules.router)
app.include_router(patients.router)
app.include_router(appointments.router)
app.include_router(chatbot_settings.router)
app.include_router(feedback.router)
app.include_router(auth_router)
app.include_router(users_router)
app.include_router(activity_router)


def _should_auto_seed_bootstrap_users() -> bool:
    import os

    return os.getenv("AUTO_SEED_BOOTSTRAP_USERS", os.getenv("AUTO_SEED_SUPER_ADMIN", "false")).lower() in {"1", "true", "yes", "on"}


@app.on_event("startup")
def _start_background_workers():
    start_campaign_scheduler()
    if _should_auto_seed_bootstrap_users():
        try:
            seed_bootstrap_users_from_env()
        except Exception as exc:
            print(f"[Seeder] Auto seed skipped or failed: {exc}")


# ======================================================
#
#               APP SYSTEM ENTRYPOINT
#
# ======================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("App.app:app", host="0.0.0.0", port=5000, reload=False)
