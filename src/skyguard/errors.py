"""Domain errors mapped to HTTP in the API layer."""


class SkyGuardError(Exception):
    pass


class StationNotFound(SkyGuardError):
    pass


class UnknownScaler(SkyGuardError):
    """Station is in the catalog but has no train scaler. Product HTTP is 400."""


class DuplicateObservation(SkyGuardError):
    pass


class CatalogNotLoaded(SkyGuardError):
    pass


class InvalidDemoRequest(SkyGuardError):
    pass
