from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.responses import JSONResponse
from fastapi_paseto_auth import AuthPASETO
from fastapi_paseto_auth.exceptions import AuthPASETOException
from pydantic import BaseModel
from datetime import timedelta
from redis import Redis

app = FastAPI()


class User(BaseModel):
    username: str
    password: str


class Settings(BaseModel):
    authpaseto_secret_key: str = "secret"
    authpaseto_denylist_enabled: bool = True
    authpaseto_denylist_token_checks: set = {"access", "refresh"}
    access_expires: int = timedelta(minutes=15)
    refresh_expires: int = timedelta(days=30)


settings = Settings()


@AuthPASETO.load_config
def get_config():
    return settings


@app.exception_handler(AuthPASETOException)
def authpaseto_exception_handler(request: Request, exc: AuthPASETOException):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})


# Setup our redis connection for storing the denylist tokens
redis_conn = Redis(host="localhost", port=6379, db=0, decode_responses=True)

# Create our function to check if a token has been revoked. In this simple
# case, we will just store the tokens jti (unique identifier) in redis.
# This function will return the revoked status of a token. If a token exists
# in redis, token has been revoked
@AuthPASETO.token_in_denylist_loader
def check_if_token_in_denylist(decrypted_token):
    jti = decrypted_token["jti"]
    entry = redis_conn.get(jti)
    return entry


@app.post("/login")
def login(user: User, Authorize: AuthPASETO = Depends()):
    if user.username != "test" or user.password != "test":
        raise HTTPException(status_code=401, detail="Bad username or password")

    access_token = Authorize.create_access_token(subject=user.username)
    refresh_token = Authorize.create_refresh_token(subject=user.username)
    return {"access_token": access_token, "refresh_token": refresh_token}


# Standard refresh endpoint. Token in denylist will not
# be able to access this endpoint
@app.post("/refresh")
def refresh(Authorize: AuthPASETO = Depends()):
    Authorize.paseto_required(refresh_token=True)

    current_user = Authorize.get_subject()
    new_access_token = Authorize.create_access_token(subject=current_user)
    return {"access_token": new_access_token}


# Endpoint for revoking the current users access token
@app.delete("/access-revoke")
def access_revoke(Authorize: AuthPASETO = Depends()):
    Authorize.paseto_required()

    # Store the tokens in redis with the value true for revoked.
    # We can also set an expires time on these tokens in redis,
    # so they will get automatically removed after they expired.
    jti = Authorize.get_token_payload()["jti"]
    redis_conn.setex(jti, settings.access_expires, "true")
    return {"detail": "Access token has been revoke"}


# Endpoint for revoking the current users refresh token
@app.delete("/refresh-revoke")
def refresh_revoke(Authorize: AuthPASETO = Depends()):
    Authorize.paseto_required(refresh_token=True)

    jti = Authorize.get_token_payload()["jti"]
    redis_conn.setex(jti, settings.refresh_expires, "true")
    return {"detail": "Refresh token has been revoke"}


# A token in denylist will not be able to access this any more
@app.get("/protected")
def protected(Authorize: AuthPASETO = Depends()):
    Authorize.paseto_required()

    current_user = Authorize.get_subject()
    return {"user": current_user}
