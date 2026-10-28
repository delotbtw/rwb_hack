"""Импортирует все модули пакета, чтобы их @chart попали в реестр.

Новый файл app/charts/<тема>.py подхватывается сам, регистрировать его не нужно.
"""

import importlib
import pkgutil

for _m in pkgutil.iter_modules(__path__):
    if not _m.name.startswith("_"):
        importlib.import_module(f"{__name__}.{_m.name}")
