"""Show Wine's Z: paths as the host paths they are.

Under Wine, Z: is the Linux root, so `Z:\\home\\v\\x.ex5` is `/home/v/x.ex5`
on the host. Callers in Docker pass host paths in (the wrapper turns them into
Z: paths) and must get host paths back. Other drives are left alone.
"""

from __future__ import annotations

import re

# A path ends at a character Windows forbids in paths, or at the line end.
_Z_PATH = re.compile(r'(?i)\bZ:\\[^:"<>|?*\r\n]*')


def host_paths(text: str) -> str:
    return _Z_PATH.sub(lambda m: "/" + m.group(0)[3:].replace("\\", "/"), text)
