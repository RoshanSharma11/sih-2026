"""Start the FastAPI app. Routes land in slice 1b."""

import uvicorn


def main() -> None:
    uvicorn.run("skyguard.api.main:app", host="127.0.0.1", port=8000, reload=True)


if __name__ == "__main__":
    main()
