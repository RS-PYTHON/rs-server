"""HealthSchema schema implementation."""


from pydantic import BaseModel


class HealthSchema(BaseModel):
    """Health status flag."""

    healthy: bool
