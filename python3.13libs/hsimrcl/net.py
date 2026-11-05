# SPDX-FileCopyrightText: 2026 EOK
# SPDX-License-Identifier: Apache-2.0
"""Сертификаты TLS для urllib внутри Houdini.

Python Houdini на macOS собран с путём к сертификатам машины сборщика SideFX, поэтому любой https-запрос
ядра (urlopen без context) падает с CERTIFICATE_VERIFY_FAILED. Проверку не отключаем: если в контексте по
умолчанию нет ни одного корневого сертификата, ставим общий opener с набором certifi (лежит в Houdini) или
системным /etc/ssl/cert.pem. Opener глобальный для процесса, поэтому ставим его только когда без него
https не работает вовсе — тогда он ничего не может испортить другим плагинам.
"""
import os
import ssl
import urllib.request

SYSTEM_BUNDLE = "/etc/ssl/cert.pem"
_DONE = []


def ca_bundle():
    """Путь к набору корневых сертификатов: certifi, иначе системный; None если нет ни того, ни другого."""
    try:
        import certifi
        return certifi.where()
    except ImportError:
        return SYSTEM_BUNDLE if os.path.isfile(SYSTEM_BUNDLE) else None


def default_has_roots():
    """Есть ли в контексте по умолчанию хоть один корневой сертификат."""
    return ssl.create_default_context().cert_store_stats().get("x509_ca", 0) > 0


def ensure_tls():
    """Один раз за сессию: подставить набор сертификатов, если у Python Houdini своих нет. Возвращает путь или ''."""
    if _DONE:
        return _DONE[0]
    bundle = "" if default_has_roots() else (ca_bundle() or "")
    if bundle:
        context = ssl.create_default_context(cafile=bundle)
        urllib.request.install_opener(urllib.request.build_opener(urllib.request.HTTPSHandler(context=context)))
    _DONE.append(bundle)
    return bundle
