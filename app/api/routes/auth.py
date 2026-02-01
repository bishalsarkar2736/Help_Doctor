from fastapi import APIRouter,Depends,status
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi.security import OAuth2PasswordRequestForm

from app.db.postgres import get_db
from app.schemas.user import UserCreate,UserRead,Token
from app.services.auth_service import register_user,authentication_user
from app.security.jwt import get_current_user,create_access_token
from app.models.user import User
from app.services.auth_service import get_or_create_google_user,refresh_tokens, logout_user
from app.security.google_oauth import verify_google_token
from app.schemas.auth import RefreshTokenRequest

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)

router = APIRouter(prefix="/auth",tags=["Authentication"])

#Register

@router.post('/register',response_model=UserRead,status_code=status.HTTP_201_CREATED)
async def register(
    user_in:UserCreate,
    db:AsyncSession = Depends(get_db),
):
    return await register_user(db,user_in)


#Login

@router.post('/login',response_model=Token)
@limiter.limit("5/minute")
async def login(
    form_data:OAuth2PasswordRequestForm = Depends(),
    db:AsyncSession = Depends(get_db),
):
    access_token = await authentication_user(
        db = db,
        email=form_data.username,
        password=form_data.password
    )

    return {
        "access_token" : access_token,
        "token_type" : "bearer"
    }


@router.post('/logout')
async def logout(
    refresh_token : str,
    db: AsyncSession = Depends(get_db)
):
    return await logout_user(db, refresh_token)




@router.post("/google")
async def google_login(
    token : str,
    db : AsyncSession = Depends(get_db),
):
    user = await get_or_create_google_user(db,token)

    access_token = create_access_token(
        data = {"sub":user.id, "role":user.role}
    )

    return {
        "access_token":access_token,
        "token_type" : "bearer",
    }


@router.post('/refresh')
async def refresh_token_endpoint(
    body : RefreshTokenRequest,
    db:AsyncSession = Depends(get_db)
):
    return await refresh_tokens(db, body.refresh_token)

