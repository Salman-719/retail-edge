# AUTO-GENERATED — see proto/iep1_control.proto. Regenerate via: make proto
import grpc

from app.grpc_generated import iep1_control_pb2 as _pb2


class Iep1ControlStub:
    def __init__(self, channel):
        self.AddCamera = channel.unary_unary(
            '/retailvision.iep1.v1.Iep1Control/AddCamera',
            request_serializer=_pb2.CameraConfig.SerializeToString,
            response_deserializer=_pb2.AddCameraResponse.FromString,
        )
        self.RemoveCamera = channel.unary_unary(
            '/retailvision.iep1.v1.Iep1Control/RemoveCamera',
            request_serializer=_pb2.RemoveCameraRequest.SerializeToString,
            response_deserializer=_pb2.RemoveCameraResponse.FromString,
        )
        self.GetStatus = channel.unary_unary(
            '/retailvision.iep1.v1.Iep1Control/GetStatus',
            request_serializer=_pb2.Empty.SerializeToString,
            response_deserializer=_pb2.Iep1StatusResponse.FromString,
        )


class Iep1ControlServicer:
    def AddCamera(self, request, context):
        context.set_code(grpc.StatusCode.UNIMPLEMENTED)
        raise NotImplementedError

    def RemoveCamera(self, request, context):
        context.set_code(grpc.StatusCode.UNIMPLEMENTED)
        raise NotImplementedError

    def GetStatus(self, request, context):
        context.set_code(grpc.StatusCode.UNIMPLEMENTED)
        raise NotImplementedError


def add_Iep1ControlServicer_to_server(servicer, server):
    rpc_method_handlers = {
        'AddCamera': grpc.unary_unary_rpc_method_handler(
            servicer.AddCamera,
            request_deserializer=_pb2.CameraConfig.FromString,
            response_serializer=_pb2.AddCameraResponse.SerializeToString,
        ),
        'RemoveCamera': grpc.unary_unary_rpc_method_handler(
            servicer.RemoveCamera,
            request_deserializer=_pb2.RemoveCameraRequest.FromString,
            response_serializer=_pb2.RemoveCameraResponse.SerializeToString,
        ),
        'GetStatus': grpc.unary_unary_rpc_method_handler(
            servicer.GetStatus,
            request_deserializer=_pb2.Empty.FromString,
            response_serializer=_pb2.Iep1StatusResponse.SerializeToString,
        ),
    }
    generic_handler = grpc.method_handlers_generic_handler(
        'retailvision.iep1.v1.Iep1Control', rpc_method_handlers)
    server.add_generic_rpc_handlers((generic_handler,))
    server.add_registered_method_handlers(
        'retailvision.iep1.v1.Iep1Control', rpc_method_handlers)
