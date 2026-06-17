# ======================================================
# SmartClinic CRM AI — app.py
# FastAPI entry point — hanya inisialisasi app dan register router.
# Logic masing-masing endpoint ada di App/routers/.
#
# Last Change   :   12 Jun 2026
# Developer     :   Raja Zhafif Raditya Harahap
#                   MHD. Rafy Firdaus
#                   Wahyu Hardiyantara
# ======================================================

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from App.auth.router import router as auth_router
from App.routers.activity import router as activity_router
from App.routers.analytics import router as analytics_router
from App.routers.users import router as users_router
from App.routers import status, webhook, patients, messages, send, handoff, campaign, schedules, appointments, chatbot_settings, feedback, reminder
from App.campaign_scheduler import start_campaign_scheduler
from App.appointment_reminder_scheduler import start_appointment_reminder_scheduler
from App.seed_bootstrap_users import seed_bootstrap_users
from App.smartclinic_auth import start_token_refresher


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ================= STARTUP =================
    print("[Lifespan] Running bootstrap user seeder...")
    try:
        seed_bootstrap_users() 
        print("[Lifespan] Bootstrap user seeder finished successfully.")
    except Exception as e:
        print(f"[Lifespan] Bootstrap user seeder failed: {e}")
        
    start_campaign_scheduler()
    start_appointment_reminder_scheduler()

    # Proactive token refresher — jaga token RME selalu fresh sebelum expired
    start_token_refresher()
    print("[Lifespan] SmartClinic proactive token refresher started.")

    yield
    # shutdown (if any cleanup is needed, add here)


app = FastAPI(
    title="SmartClinic CRM AI",
    description="Hybrid routing API untuk webhook Fonnte, Rasa, dan Groq LLM.",
    version="1.0.0",
    lifespan=lifespan
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
app.include_router(reminder.router)
app.include_router(chatbot_settings.router)
app.include_router(feedback.router)
app.include_router(auth_router)
app.include_router(users_router)
app.include_router(activity_router)
app.include_router(analytics_router)


# ======================================================
#
#               APP SYSTEM ENTRYPOINT
#
# ======================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("App.app:app", host="0.0.0.0", port=5000, reload=False)