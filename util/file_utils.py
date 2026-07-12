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
    with open(path, 'rb') as file:
        r = file.read(size)
        f_charinfo = chardet.detect(r)
        encoding = f_charinfo['encoding']
    logger.debug("reading '%s' (detected: %s)", path.name, encoding)
    with open(path, 'r', encoding=encoding, errors="replace") as file:
        return file.read(size)


def xml_parser_factory(content: str) -> BeautifulSoup:

    soup = BeautifulSoup(content, "xml")
    return soup


def walk_dir(path: Path, exclude_patterns: Optional[List[str]] = None):
    patterns = [re.compile(p) for p in (exclude_patterns or [])]

    def is_excluded(name: str) -> bool:
        return any(p.fullmatch(name) for p in patterns)

    total = 0
    for root, dirs, files in os.walk(path, topdown=True):
        dirs[:] = [d for d in dirs if not is_excluded(d)]
        total += len([f for f in files if not is_excluded(f)])

    with tqdm(range(total), desc='walk progress') as tbar:
        for root, dirs, files in os.walk(path, topdown=True):
            dirs[:] = [d for d in dirs if not is_excluded(d)]
            for file in files:
                if not is_excluded(file):
                    yield Path(os.path.join(root, file))
                tbar.set_description_str(root.replace(str(path), ""))
                tbar.update()
