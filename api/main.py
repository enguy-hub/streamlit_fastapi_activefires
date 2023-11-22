import logging
import typing
from contextlib import asynccontextmanager

import orjson
import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from api.routes import create

log = logging.getLogger("uvicorn")


class ORJSONResponse(JSONResponse):
    """
    Response class that can handle for example also nan values in response by using orjson.

    Source: https://github.com/tiangolo/fastapi/issues/459#issuecomment-536781105
    """

    media_type = "application/json"

    def render(self, content: typing.Any) -> bytes:
        return orjson.dumps(content)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan Events

    Startup
    ----------
        Register the database connection and create table list.

    Shutdown
    ----------
        De-register the database connection.
    """

    log.info("Starting up...")
    yield
    log.info("Shutting down...")


def create_application() -> FastAPI:
    """
    Create an instance of FastAPI.

    Returns FastAPI
    -------
        FastAPI
            An instance of class FastAPI
    """

    return FastAPI(
        default_response_class=ORJSONResponse,
        title="Welcome to Endpoints",
        lifespan=lifespan,
    )


def configure_app(app: FastAPI, dev_mode: bool):
    """
    Configure FastAPI app.
    Configure API Routes.

    Parameters
    ----------
        app: FastAPI
            The application that needs to be configured
        dev_mode: bool
            Defines whether the app runs in development mode.
            * Currently not used.
    """

    configure_api_routes(app)


def configure_api_routes(app: FastAPI):
    """
    Configure API routes to provide specific API endpoints.

    Parameters
    ----------
        app: FastAPI
            The application that needs to be configured
    """

    app.include_router(create.router, tags=["create"])


app = create_application()


@app.get("/")
async def root():
    return {"message: " "Welcome !!! "}


def main():
    """
    Main function called when file executed directly.
    """

    configure_app(app, dev_mode=True)  # when file is called directly, we are always in dev mode
    uvicorn.run(app, host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
else:
    # when app is called through the terminal with the uvicorn/gunicorn command, app is not in dev_mode
    configure_app(app, dev_mode=False)
