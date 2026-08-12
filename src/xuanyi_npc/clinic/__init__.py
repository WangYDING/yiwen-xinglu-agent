"""Local clinic product entrypoint."""

from .server import ClinicHTTPServer, build_clinic_service, main

__all__ = ["ClinicHTTPServer", "build_clinic_service", "main"]
