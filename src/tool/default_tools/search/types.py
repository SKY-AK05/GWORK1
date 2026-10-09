from typing import Optional
from pydantic import BaseModel, Field

class SearchItem(BaseModel):
    """Represents a single search result item"""

    title: str = Field(description="The title of the search result")
    url: str = Field(description="The URL of the search result")
    date: Optional[str] = Field(default=None, description="The date of the search result")
    position: Optional[int] = Field(default=None, description="The position of the search result in the list")
    source: Optional[str] = Field(default=None, description="The source of the search result")
    description: Optional[str] = Field(default=None, description="A description or snippet of the search result")

    def __str__(self) -> str:
        """String representation of a search result item."""
        return f"{self.title} - {self.url} - {self.description or 'No description available'}"
