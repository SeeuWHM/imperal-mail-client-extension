"""Abstract base class for mail providers."""
from __future__ import annotations
from abc import ABC, abstractmethod
from imperal_sdk import Context

class BaseMailProvider(ABC):
    """Common interface every mail provider must implement.

    All methods return a dict with at minimum:
      - {"RESULT": "SUCCESS", ...}  on success
      - {"RESULT": "ERROR",   "error": "..."} on failure
    """

    @abstractmethod
    async def fetch_inbox(self, ctx: Context, acc: dict, max_results: int = 20) -> dict: ...

    @abstractmethod
    async def fetch_page(
        self, ctx: Context, acc: dict, folder: str, limit: int,
        cursor_data: dict | None,
    ) -> tuple[list[dict], dict | None, bool]:
        """Fetch one page of messages. Returns (messages, next_cursor_data, has_more)."""
        ...

    @abstractmethod
    async def get_unread_count(self, ctx: Context, acc: dict, folder: str = "inbox") -> int:
        """Get unread message count for a folder."""
        ...

    @abstractmethod
    async def read_email(self, ctx: Context, acc: dict, message_id: str) -> dict: ...

    @abstractmethod
    async def send(self, ctx: Context, acc: dict, to: str, subject: str, body: str,
                   cc: str = "", bcc: str = "") -> dict: ...

    @abstractmethod
    async def reply(self, ctx: Context, acc: dict, message_id: str, body: str,
                    to: str = "", cc: str = "", bcc: str = "") -> dict: ...

    @abstractmethod
    async def forward(self, ctx: Context, acc: dict, message_id: str,
                      to: str, comment: str = "") -> dict: ...

    @abstractmethod
    async def archive(self, ctx: Context, acc: dict, message_id: str) -> dict: ...

    @abstractmethod
    async def delete(self, ctx: Context, acc: dict, message_id: str) -> dict: ...

    @abstractmethod
    async def mark_read(self, ctx: Context, acc: dict, message_id: str,
                        read: bool = True) -> dict: ...

    @abstractmethod
    async def star(self, ctx: Context, acc: dict, message_id: str,
                   starred: bool = True) -> dict: ...

    @abstractmethod
    async def search(self, ctx: Context, acc: dict, query: str,
                     max_results: int = 10) -> dict: ...

    @abstractmethod
    async def folder(self, ctx: Context, acc: dict, folder_name: str,
                     max_results: int = 20) -> dict: ...

    @abstractmethod
    async def get_thread(self, ctx: Context, acc: dict, thread_id: str) -> dict: ...

    @abstractmethod
    async def move(self, ctx: Context, acc: dict, message_id: str,
                   from_folder: str = "INBOX", to_folder: str = "INBOX") -> dict: ...

    async def purge(self, ctx: Context, acc: dict, message_id: str,
                    from_folder: str = "Trash") -> dict:
        return self.err("Permanent deletion not implemented for this provider")

    @staticmethod
    def ok(**kwargs) -> dict:
        return {"RESULT": "SUCCESS", **kwargs}

    @staticmethod
    def err(error: str) -> dict:
        return {"RESULT": "ERROR", "error": error}
