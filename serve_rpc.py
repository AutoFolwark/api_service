import asyncio
import os
import signal
import sys

import grpc
from grpc_health.v1 import health_pb2, health_pb2_grpc
from grpc_reflection.v1alpha import reflection

sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "rpc_server", "gen", "python")
)

from auction.v1 import lot_pb2, lot_pb2_grpc

from config import Environment, settings
from core.logger import logger
from rpc_server.health import HealthCheckServicer
from rpc_server.lot_rpc import LotRpc


class GracefulServer:
    def __init__(self):
        self.server = None
        self.shutdown_event = asyncio.Event()

    async def setup_server(self):
        self.server = grpc.aio.server()

        listen_addr = f"[::]:{settings.GRPC_SERVER_PORT}"

        self.server.add_insecure_port(listen_addr)

        lot_pb2_grpc.add_LotServiceServicer_to_server(LotRpc(), self.server)
        health_pb2_grpc.add_HealthServicer_to_server(HealthCheckServicer(), self.server)

        if settings.ENVIRONMENT == Environment.DEVELOPMENT:
            try:
                service_names = [
                    lot_pb2.DESCRIPTOR.services_by_name["LotService"].full_name,
                    health_pb2.DESCRIPTOR.services_by_name["Health"].full_name,
                    reflection.SERVICE_NAME,
                ]
                reflection.enable_server_reflection(service_names, self.server)
                logger.info("🔍 gRPC Reflection enabled for development")
            except Exception as e:
                logger.warning(f"⚠️  Failed to enable reflection: {e}")

        logger.info(f"🚀 gRPC Server configured on {listen_addr}")

    def setup_signal_handlers(self):

        def signal_handler(signum, frame):
            logger.info(f"Received signal {signum}, initiating graceful shutdown...")
            asyncio.create_task(self.shutdown())

        signal.signal(signal.SIGTERM, signal_handler)
        signal.signal(signal.SIGINT, signal_handler)

    async def shutdown(self):
        if not self.shutdown_event.is_set():
            self.shutdown_event.set()

    async def serve(self):
        await self.setup_server()
        self.setup_signal_handlers()

        await self.server.start()
        logger.info("✅ gRPC Server started successfully")

        try:
            await self.shutdown_event.wait()
        except asyncio.CancelledError:
            logger.info("Server cancelled")
        finally:
            logger.info("Shutting down server...")
            await self.server.stop(grace=10.0)
            logger.info("Server stopped")


async def main():
    server = GracefulServer()
    try:
        await server.serve()
    except Exception as e:
        logger.error(f"Server error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
