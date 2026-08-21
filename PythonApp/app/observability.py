import json
import logging
import os
import sys

from datetime import (
    datetime,
    timezone,
)


STANDARD_LOG_RECORD_FIELDS = {
    "name",
    "msg",
    "args",
    "levelname",
    "levelno",
    "pathname",
    "filename",
    "module",
    "exc_info",
    "exc_text",
    "stack_info",
    "lineno",
    "funcName",
    "created",
    "msecs",
    "relativeCreated",
    "thread",
    "threadName",
    "processName",
    "process",
    "taskName",
}


class RailwayJSONFormatter(
    logging.Formatter
):
    def format(
        self,
        record: logging.LogRecord,
    ) -> str:
        payload = {
            "timestamp":
                datetime.now(
                    timezone.utc
                ).isoformat(),

            "level":
                record.levelname.lower(),

            "message":
                record.getMessage(),

            "logger":
                record.name,

            "environment":
                os.getenv(
                    "RAILWAY_ENVIRONMENT_NAME",
                    "local",
                ),

            "service":
                os.getenv(
                    "RAILWAY_SERVICE_NAME",
                    "techstep-backend",
                ),

            "deploymentId":
                os.getenv(
                    "RAILWAY_DEPLOYMENT_ID"
                ),
        }

        for key, value in (
            record.__dict__.items()
        ):
            if (
                key
                not in
                STANDARD_LOG_RECORD_FIELDS
                and key
                not in payload
            ):
                payload[key] = value

        if record.exc_info:
            payload["exception"] = (
                self.formatException(
                    record.exc_info
                )
            )

        return json.dumps(
            payload,
            ensure_ascii=False,
            default=str,
        )


def create_logger() -> logging.Logger:
    logger = logging.getLogger(
        "techstep"
    )

    logger.setLevel(
        os.getenv(
            "LOG_LEVEL",
            "INFO",
        ).upper()
    )

    logger.propagate = False

    if logger.handlers:
        return logger

    handler = logging.StreamHandler(
        sys.stdout
    )

    handler.setFormatter(
        RailwayJSONFormatter()
    )

    logger.addHandler(
        handler
    )

    return logger


logger = create_logger()