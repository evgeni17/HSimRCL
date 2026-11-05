# SPDX-FileCopyrightText: 2026 EOK
# SPDX-License-Identifier: Apache-2.0
"""Согласованность репозитория: версии, имена типов только через константы, SPDX, двуязычные README."""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PKG = os.path.join(ROOT, "python3.13libs", "hsimrcl")
FAILS = []


def check(label, ok, detail=""):
    print("%s %s%s" % ("ok " if ok else "BAD", label, "" if ok else ": " + str(detail)))
    if not ok:
        FAILS.append(label)


def init_value(key):
    src = open(os.path.join(PKG, "__init__.py"), encoding="utf-8").read()
    return re.search(r'^%s = "([^"]*)"' % key, src, re.M).group(1)


def own_py_files():
    for base, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in (".git", "__pycache__")]
        for f in files:
            if f.endswith(".py") and not (os.path.basename(base) == "core" and f.startswith("simready_")):
                yield os.path.join(base, f)


def main():
    version, hda = init_value("__version__"), init_value("HDA_VERSION")
    versions = json.load(open(os.path.join(ROOT, "VERSIONS.json"), encoding="utf-8"))["assets"]
    dev = [k for k, v in versions.items() if v["status"] == "development"]
    check("one development entry", dev == [hda], dev)
    check("VERSIONS plugin = __version__", versions.get(hda, {}).get("plugin") == version)
    check("VERSIONS upstream = SIMRCL_UPSTREAM",
          versions.get(hda, {}).get("simrcl_upstream") == init_value("SIMRCL_UPSTREAM"))
    literal = re.compile(r'["\']hsimrcl::[a-z_]+::')
    offenders = [p for p in own_py_files() if literal.search(open(p, encoding="utf-8").read())
                 and not p.endswith(os.path.join("hsimrcl", "__init__.py")) and "tests" not in p]
    check("type names only via constants", not offenders, offenders)
    no_spdx = [p for p in own_py_files() if "SPDX-License-Identifier" not in open(p, encoding="utf-8").read(400)]
    check("SPDX headers", not no_spdx, no_spdx)
    for name in ("README.md", "README.ru.md", "CHANGELOG.md", "CONTRIBUTING.md", "docs/PLAN.ru.md",
                 "LICENSE", "NOTICE", "third_party/SimRCL-LICENSE.txt"):
        check("exists " + name, os.path.isfile(os.path.join(ROOT, name)))
    changelog = open(os.path.join(ROOT, "CHANGELOG.md"), encoding="utf-8").read()
    pretty = re.sub(r"\.dev(\d+)$", r"-dev.\1", version)
    check("CHANGELOG has " + pretty, ("## " + pretty) in changelog)
    print("test_repo: %s" % ("OK" if not FAILS else "FAILED " + ", ".join(FAILS)))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
