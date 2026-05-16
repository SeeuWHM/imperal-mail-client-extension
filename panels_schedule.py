"""Mail Client · Background schedule (retired).

The inbox_warmup schedule was pre-warming InboxPage cache entries.
The panel never reads InboxPage — it reads InboxMessages (populated by
the skeleton). This schedule was dead code and is no longer registered.
"""
