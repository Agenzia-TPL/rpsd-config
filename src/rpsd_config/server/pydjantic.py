##################
# From: https://github.com/CourteousCoder/pydjantic/blob/main/pydjantic/pydjantic.py
##################

import inspect
from collections.abc import Mapping
from typing import Any

from pydantic import (
    BaseModel,
    SecretBytes,
    SecretStr,
)
from pydantic_settings import BaseSettings


def to_django(settings: BaseSettings):
    stack = inspect.stack()
    parent_frame = stack[1][0]

    def _get_actual_value(val: Any):
        if isinstance(val, BaseModel):
            # for DATABASES and other complicated objects
            return _get_actual_value(val.model_dump())
        elif isinstance(val, Mapping):
            return {k: _get_actual_value(v) for k, v in val.items()}
        elif isinstance(val, list):
            return [_get_actual_value(item) for item in val]
        elif isinstance(val, (SecretBytes, SecretStr)):
            return _get_actual_value(val.get_secret_value())
        else:
            return val

    for key, value in settings.model_dump().items():
        parent_frame.f_locals[key] = _get_actual_value(value)
