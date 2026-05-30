# ======================================================
# SmartClinic CRM AI — app.py
# FastAPI entry point — hanya inisialisasi app dan register router.
# Logic masing-masing endpoint ada di App/routers/.
#
# Last Change   :   31 May 2026
# Developer     :   Raja Zhafif Raditya Harahap
#                   MHD. Rafy Firdaus
#                   Wahyu Hardiyantara
# ======================================================

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from App.auth.router import router as auth_router
from App.routers.activity import router as activity_router
from App.routers.users import router as users_router
from App.routers import status, webhook, patients, messages, send, handoff, campaign, schedules, appointments, chatbot_settings, feedback
from App.campaign_scheduler import start_campaign_scheduler
from App.seed_bootstrap_users import seed_bootstrap_users

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


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ================= STARTUP =================
    print("[Lifespan] Running bootstrap user seeder...")
    try:
        seed_bootstrap_users() 
        print("[Lifespan] Bootstrap user seeder finished successfully.")
    except Exception as e:
        print(f"[Lifespan] Bootstrap user seeder failed: {e}")
        # Jika Anda ingin aplikasi tetap jalan walau seeder gagal, biarkan saja.
        # Jika ingin aplikasi crash sengaja saat gagal, biarkan error-nya raise.
        
    start_campaign_scheduler()
    yield
    # shutdown (if any cleanup is needed, add here)


# register lifespan with app
app.router.lifespan_context = lifespan


# ======================================================
#
#               APP SYSTEM ENTRYPOINT
#
# ======================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("App.app:app", host="0.0.0.0", port=5000, reload=False)
