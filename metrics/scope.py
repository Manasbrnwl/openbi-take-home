"""Access scope passed into every metric and list query. Built only by app/security.py."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Scope:
    user_id: str
    role: str
    # None = unrestricted (admin). Otherwise the req_keys this user may see.
    req_keys: frozenset[int] | None

    def sql_filter(self, column: str = "req_key") -> tuple[str, list]:
        """Return (sql_fragment, params) restricting `column` to this scope.

        Admin: real requisitions and orphans. Everyone else: exactly their req_keys.
        An empty scope matches nothing (never 'everything').
        """
        if self.req_keys is None:
            return "TRUE", []
        if not self.req_keys:
            return "FALSE", []
        keys = sorted(self.req_keys)
        return f"{column} IN ({','.join('?' * len(keys))})", keys
