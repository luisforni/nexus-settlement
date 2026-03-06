from fastapi import APIRouter

from app.api.v1.endpoints.fraud import router as fraud_router

api_router = APIRouter()
api_router.include_router(fraud_router)
