"""HoAux Source IR schema constants."""

SCHEMA_ID = "com.hotools.hoaux.source-ir"
SCHEMA_VERSION = 1

RESOURCE_KINDS = frozenset(
    {
        "BONE",
        "BONE_COLLECTION",
        "CONSTRAINT",
        "DRIVER",
        "DRIVER_VARIABLE",
        "EXPORT_ENDPOINT",
        "MODULE",
        "PIPELINE",
    }
)

RESOURCE_STATUSES = frozenset({"RESOLVED", "UNRESOLVED", "UNSUPPORTED"})
