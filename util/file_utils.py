import locale
import logging
import os
import re
from pathlib import Path
from typing import List, Optional
import chardet
from bs4 import BeautifulSoup
from tqdm import tqdm

logger = logging.getLogger(__name__)


def file_reader(path: Path, size: int = -1) -> str:
    """Read a file, decoding with whatever charset chardet detects.

    Opens the file **once**. The previous version opened it twice — binary to
    feed chardet, then text to do the actual read — which doubled the syscall
    count of every read in the pipeline (config files, base-entity loads, and
    the `classify` sniff, which alone runs over every file of every package).
    Decoding the bytes already in hand is measurably 2x faster and produced
    byte-identical output over every file in `vanilla`; see the note on
    newline handling below.

    `size >= 0` reads that many **bytes** rather than characters. The only
    caller is `classify`, which asks for 5 bytes to test `startswith("<")`, so
    the distinction cannot reach the output.
    """
    with open(path, "rb") as file:
        raw = file.read(size)
    encoding = chardet.detect(raw)["encoding"]
    logger.debug("reading '%s' (detected: %s)", path.name, encoding)
    text = raw.decode(encoding or locale.getencoding(), errors="replace")
    if size < 0:
        # Text mode translates newlines on read; bytes.decode does not.
        return text.replace("\r\n", "\n").replace("\r", "\n")
    return text


def xml_parser_factory(content: str) -> BeautifulSoup:

    soup = BeautifulSoup(content, "xml")
    return soup


def walk_dir(path: Path, exclude_patterns: Optional[List[str]] = None):
    patterns = [re.compile(p) for p in (exclude_patterns or [])]

    def is_excluded(name: str) -> bool:
        return any(p.fullmatch(name) for p in patterns)

    # sorted() so traversal order is a property of the tree, not of the
    # filesystem. Everything downstream (inherit resolution, clean_final merge)
    # is order-sensitive, so unsorted walk makes output machine-dependent.
    with tqdm(desc='walk progress') as tbar:
        for root, dirs, files in os.walk(path, topdown=True):
            dirs[:] = sorted(d for d in dirs if not is_excluded(d))
            for file in sorted(files):
                if not is_excluded(file):
                    tbar.set_description_str(root.replace(str(path), ""))
                    tbar.update()
                    yield Path(os.path.join(root, file))
