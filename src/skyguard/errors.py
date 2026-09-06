"""Domain errors mapped to HTTP in the API layer."""


class SkyGuardError(Exception):
    pass


class StationNotFound(SkyGuardError):
    pass


class DuplicateObservation(SkyGuardError):
    pass


class CatalogNotLoaded(SkyGuardError):
    pass


class InvalidDemoRequest(SkyGuardError):
    pass
