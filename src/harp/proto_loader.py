"""Imports the vendored ``warp_multi_agent`` v1 protobuf bindings.

The bindings live under the ``harp.proto`` subpackage; they're
populated either by the Dockerfile (which copies ``vendor/warp-proto-apis/
.../gen/python``) or by the developer (who symlinks the same directory).

The generated ``*_pb2.py`` files use intra-package relative imports such as
``from . import response_pb2``, so they must be imported via their full dotted
path under ``harp.proto``.
"""

from __future__ import annotations

import importlib
import importlib.abc
import importlib.machinery
import sys
from pathlib import Path
from types import ModuleType

from . import _go_features_stub

# The pre-generated bindings reference ``google.protobuf.go_features_pb2``,
# which is not shipped in the Python ``protobuf`` package. Install our stub
# before any of the ``*_pb2`` modules are imported so the dependency lookup
# inside the descriptor pool succeeds.
_go_features_stub.install()

_PACKAGE = "harp.proto"


def _ensure_proto_present() -> Path:
    proto_dir = Path(__file__).resolve().parent / "proto"
    init_file = proto_dir / "__init__.py"
    if not proto_dir.is_dir() or not init_file.exists():
        raise RuntimeError(
            f"proto bindings missing at {proto_dir}; "
            "ensure the package was built with the proto vendoring step "
            "(see shim/Dockerfile and shim/README.md)."
        )
    return proto_dir


_proto_dir = _ensure_proto_present()


class _BareProtoFinder(importlib.abc.MetaPathFinder):
    """Resolve bare ``*_pb2`` imports to ``harp.proto.*_pb2``.

    The generated bindings are inconsistent: some files use
    ``from . import response_pb2`` (relative), others ``import response_pb2``
    (bare). The relative ones force a package-style import, while the bare
    ones expect to find the module on ``sys.path``. This finder bridges the
    gap by redirecting bare ``*_pb2`` imports to our subpackage so both styles
    resolve to the same loaded module.
    """

    def find_spec(self, fullname, path, target=None):  # type: ignore[override]
        if "." in fullname or not fullname.endswith("_pb2"):
            return None
        candidate = _proto_dir / f"{fullname}.py"
        if not candidate.is_file():
            return None
        # Defer to the package's own loader by aliasing through sys.modules.
        dotted = f"{_PACKAGE}.{fullname}"
        module = importlib.import_module(dotted)
        sys.modules[fullname] = module
        return importlib.machinery.ModuleSpec(fullname, loader=_AliasLoader(module))


class _AliasLoader(importlib.abc.Loader):
    def __init__(self, module: ModuleType) -> None:
        self._module = module

    def create_module(self, spec):  # type: ignore[override]
        return self._module

    def exec_module(self, module):  # type: ignore[override]
        # The aliased module is already executed; nothing to do.
        return None


if not any(isinstance(f, _BareProtoFinder) for f in sys.meta_path):
    sys.meta_path.append(_BareProtoFinder())


def _load(name: str) -> ModuleType:
    return importlib.import_module(f"{_PACKAGE}.{name}")


# Eagerly import everything so generated cross-references resolve.
attachment_pb2 = _load("attachment_pb2")
citations_pb2 = _load("citations_pb2")
conversation_data_pb2 = _load("conversation_data_pb2")
document_content_pb2 = _load("document_content_pb2")
file_content_pb2 = _load("file_content_pb2")
input_context_pb2 = _load("input_context_pb2")
lsp_pb2 = _load("lsp_pb2")
options_pb2 = _load("options_pb2")
request_pb2 = _load("request_pb2")
response_pb2 = _load("response_pb2")
skill_pb2 = _load("skill_pb2")
suggestions_pb2 = _load("suggestions_pb2")
task_pb2 = _load("task_pb2")
todo_pb2 = _load("todo_pb2")

# Convenience aliases for the most-used types.
Request = request_pb2.Request
ResponseEvent = response_pb2.ResponseEvent
ClientAction = response_pb2.ClientAction
LLMProvider = response_pb2.LLMProvider
Task = task_pb2.Task
Message = task_pb2.Message
AgentOutput = task_pb2.Message.AgentOutput
ToolType = task_pb2.ToolType
