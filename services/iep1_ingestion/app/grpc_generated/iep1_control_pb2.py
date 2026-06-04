# AUTO-GENERATED EQUIVALENT — see proto/iep1_control.proto
# Descriptor is built at import time from google.protobuf.descriptor_pb2 so that
# no pre-compiled binary blob is needed.  Regenerate via: make proto
from google.protobuf import descriptor as _descriptor
from google.protobuf import descriptor_pool as _descriptor_pool
from google.protobuf import symbol_database as _symbol_database
from google.protobuf.internal import builder as _builder
from google.protobuf import descriptor_pb2 as _descriptor_pb2


_sym_db = _symbol_database.Default()


def _build_file_descriptor() -> bytes:
    fdp = _descriptor_pb2.FileDescriptorProto()
    fdp.name = "iep1_control.proto"
    fdp.package = "retailvision.iep1.v1"
    fdp.syntax = "proto3"

    TYPE_STRING = 9
    TYPE_FLOAT  = 2
    TYPE_BOOL   = 8
    TYPE_INT64  = 3
    TYPE_MSG    = 11
    OPT         = 1   # LABEL_OPTIONAL
    RPT         = 3   # LABEL_REPEATED

    def _f(msg, name, number, ftype, label=OPT, type_name=None):
        f = msg.field.add()
        f.name = name; f.number = number; f.label = label; f.type = ftype
        if type_name:
            f.type_name = type_name

    m = fdp.message_type.add(); m.name = "CameraConfig"
    _f(m, "camera_id",      1, TYPE_STRING)
    _f(m, "rtsp_url",       2, TYPE_STRING)
    _f(m, "target_fps",     3, TYPE_FLOAT)
    _f(m, "window_seconds", 4, TYPE_FLOAT)
    _f(m, "store_id",       5, TYPE_STRING)

    m = fdp.message_type.add(); m.name = "AddCameraResponse"
    _f(m, "success", 1, TYPE_BOOL)
    _f(m, "error",   2, TYPE_STRING)

    m = fdp.message_type.add(); m.name = "RemoveCameraRequest"
    _f(m, "camera_id", 1, TYPE_STRING)

    m = fdp.message_type.add(); m.name = "RemoveCameraResponse"
    _f(m, "success", 1, TYPE_BOOL)

    m = fdp.message_type.add(); m.name = "CameraStatus"
    _f(m, "camera_id",      1, TYPE_STRING)
    _f(m, "status",         2, TYPE_STRING)
    _f(m, "last_frame_ts",  3, TYPE_INT64)
    _f(m, "frames_dropped", 4, TYPE_INT64)

    m = fdp.message_type.add(); m.name = "Iep1StatusResponse"
    _f(m, "cameras", 1, TYPE_MSG, RPT, ".retailvision.iep1.v1.CameraStatus")

    fdp.message_type.add().name = "Empty"

    svc = fdp.service.add(); svc.name = "Iep1Control"
    for mname, inp, out in [
        ("AddCamera",
         ".retailvision.iep1.v1.CameraConfig",
         ".retailvision.iep1.v1.AddCameraResponse"),
        ("RemoveCamera",
         ".retailvision.iep1.v1.RemoveCameraRequest",
         ".retailvision.iep1.v1.RemoveCameraResponse"),
        ("GetStatus",
         ".retailvision.iep1.v1.Empty",
         ".retailvision.iep1.v1.Iep1StatusResponse"),
    ]:
        meth = svc.method.add()
        meth.name = mname; meth.input_type = inp; meth.output_type = out

    return fdp.SerializeToString()


DESCRIPTOR = _descriptor_pool.Default().AddSerializedFile(_build_file_descriptor())

_globals = globals()
_builder.BuildMessageAndEnumDescriptors(DESCRIPTOR, _globals)
_builder.BuildTopDescriptorsAndMessages(DESCRIPTOR, 'iep1_control_pb2', _globals)
# @@protoc_insertion_point(module_scope)
