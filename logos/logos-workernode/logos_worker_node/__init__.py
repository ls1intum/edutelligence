# Worker-node runtime package.
#
# Double-blind env alias: accept ANONTOOL_* environment variables as synonyms for
# the internal LOGOS_* names, so an anonymized deployment can configure the worker
# without any project name in its env. Runs on package import — before any
# submodule reads os.environ — and only fills a LOGOS_* value that is not already
# set, so it is purely additive.
import os as _os

for _k, _v in list(_os.environ.items()):
    if _k.startswith("ANONTOOL"):
        _os.environ.setdefault("LOGOS" + _k[len("ANONTOOL") :], _v)
