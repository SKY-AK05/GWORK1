from __future__ import annotations

from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, ConfigDict, Field


class ToolExtra(BaseModel):
    """Extra data for a tool response."""

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="allow")

    file_path: Optional[Union[str, List[str]]] = Field(default=None)
    data: Optional[Dict[str, Any]] = Field(default=None)
    parsed_model: Optional[BaseModel] = Field(default=None)


class ToolResponse(BaseModel):
    """Response for a tool call."""

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="allow")

    success: bool = Field(description="Whether the tool call was successful")
    message: str = Field(description="The message from the tool call")
    extra: Optional[ToolExtra] = Field(default=None)


class Tool(BaseModel):
    """Base class for tools exposed to the lightweight MVP flow."""

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="allow")

    name: str = Field(description="The name of the tool")
    description: str = Field(description="The description of the tool")
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict)
    require_grad: bool = Field(default=False)

    async def __call__(self, **kwargs) -> ToolResponse:
        raise NotImplementedError("All tools must implement __call__")


__all__ = ["Tool", "ToolExtra", "ToolResponse"]
