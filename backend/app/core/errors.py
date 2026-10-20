import logging
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse


class DomainError(Exception):
    def __init__(self, code: str, status: int = 409, message: str = "Operation rejected"):
        self.code, self.status, self.message = code, status, message
        super().__init__(code)


def install_errors(app: FastAPI):
    def response(request, status, code, message):
        return JSONResponse(
            status_code=status,
            content={
                "error": {"code": code, "message": message, "details": []},
                "request_id": getattr(request.state, "request_id", str(uuid4())),
            },
        )

    @app.middleware("http")
    async def request_id(request: Request, call_next):
        request.state.request_id = str(uuid4())
        try:
            result = await call_next(request)
        except Exception:
            logging.getLogger("vietlaw").exception("Unhandled request %s", request.state.request_id)
            result = response(request, 500, "INTERNAL_ERROR", "Internal error")
        result.headers["X-Request-ID"] = request.state.request_id
        return result

    @app.exception_handler(DomainError)
    async def domain(request, exc):
        return response(request, exc.status, exc.code, exc.message)

    @app.exception_handler(RequestValidationError)
    async def invalid(request, exc):
        return response(request, 422, "INVALID_REQUEST", "Invalid request")

    @app.exception_handler(HTTPException)
    async def http(request, exc):
        return response(request, exc.status_code, f"HTTP_{exc.status_code}", "Request rejected")
