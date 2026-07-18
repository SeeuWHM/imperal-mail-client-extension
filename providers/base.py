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
                   cc: str = "", bcc: str = "", is_html: bool = False) -> dict: ...

    @abstractmethod
    async def reply(self, ctx: Context, acc: dict, message_id: str, body: str,
                    to: str = "", cc: str = "", bcc: str = "", is_html: bool = False) -> dict: ...

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

    async def get_folder_stats(self, ctx: Context, acc: dict, folder: str = "inbox") -> dict:
        """Return {'total': int, 'unread': int} for the given folder.

        Default implementation returns unread from get_unread_count; total=0.
        Override in providers that have a cheap API for total count.
        """
        return {"total": 0, "unread": await self.get_unread_count(ctx, acc, folder)}

    async def get_counts(self, ctx: Context, acc: dict) -> dict:
        """Return normalized mailbox counts {total, unread, spam, archive}.

        Default derives from per-folder stats (total = INBOX total, unread = INBOX
        unread). Providers with a cheaper whole-mailbox total (Gmail profile,
        Graph $count) override `total`. Used by the skeleton classifier surface.
        """
        inbox = await self.get_folder_stats(ctx, acc, "inbox")
        spam  = await self.get_folder_stats(ctx, acc, "spam")
        arch  = await self.get_folder_stats(ctx, acc, "archive")
        return {
            "total":       int(inbox.get("total", 0) or 0),
            "inbox_total": int(inbox.get("total", 0) or 0),
            "unread":      int(inbox.get("unread", 0) or 0),
            "spam":        int(spam.get("total", 0) or 0),
            "archive":     int(arch.get("total", 0) or 0),
        }

    async def get_today_count(self, ctx: Context, acc: dict) -> int:
        """Count messages received during the current UTC day. Default 0 —
        override per provider (Gmail after:, Graph $filter, IMAP SINCE)."""
        return 0

    async def purge(self, ctx: Context, acc: dict, message_id: str,
                    from_folder: str = "Trash") -> dict:
        return self.err("Permanent deletion not implemented for this provider")

    async def get_list_unsubscribe(self, ctx: Context, acc: dict,
                                   message_id: str) -> tuple[str, str]:
        """Return (list_unsubscribe_header_value, list_unsubscribe_post_value).
        Empty strings if not found. Override per provider."""
        return "", ""

    async def download_attachment(self, ctx: Context, acc: dict, message_id: str,
                                  attachment_id: str) -> dict:
        """Download ONE attachment's raw bytes + filename + mime_type.

        Returns {"RESULT": "SUCCESS", "content": bytes, "filename": str,
        "mime_type": str} or an err() dict. Default: not implemented — a
        provider without real attachment-byte access (none currently) falls
        back to this honest error instead of silently returning nothing.
        """
        return self.err("Reading attachment content is not supported for this account type.")

    @staticmethod
    def ok(**kwargs) -> dict:
        return {"RESULT": "SUCCESS", **kwargs}

    @staticmethod
    def err(error: str) -> dict:
        return {"RESULT": "ERROR", "error": error}
