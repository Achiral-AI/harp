"""Stub for ``google.protobuf.go_features_pb2``.

The pre-generated Python bindings shipped by ``warp-proto-apis`` reference
``go_features.proto`` for Go-specific feature flags. The Python ``protobuf``
distribution does not ship a ``go_features_pb2`` module, so a vanilla
``from google.protobuf import go_features_pb2`` raises ``ImportError``.

We register an empty ``FileDescriptorProto`` for ``google/protobuf/go_features.proto``
in the default descriptor pool, then expose this module under
``google.protobuf.go_features_pb2`` via ``sys.modules``. The stub is enough to
satisfy the import line and the dependency-resolution step in
``DescriptorPool.AddSerializedFile`` for the warp-proto-apis files, which never
read the Go-feature options at runtime.
"""

from __future__ import annotations

import sys

from google.protobuf import descriptor_pb2, descriptor_pool

_FILE_NAME = "google/protobuf/go_features.proto"


def _register_empty_descriptor() -> None:
    pool = descriptor_pool.Default()
    try:
        pool.FindFileByName(_FILE_NAME)
        return  # already registered
    except KeyError:
        pass

    proto = descriptor_pb2.FileDescriptorProto()
    proto.name = _FILE_NAME
    proto.package = "pb"
    proto.syntax = "proto2"
    pool.Add(proto)


def install() -> None:
    """Inject the stub module under ``google.protobuf.go_features_pb2``."""

    _register_empty_descriptor()

    module_name = "google.protobuf.go_features_pb2"
    if module_name not in sys.modules:
        # Re-export this stub module under the expected dotted path so that
        # ``from google.protobuf import go_features_pb2`` succeeds.
        sys.modules[module_name] = sys.modules[__name__]
