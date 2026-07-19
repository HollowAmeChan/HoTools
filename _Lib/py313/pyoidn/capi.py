from cffi import FFI
import os
import sys

OIDN_TYPES = """
typedef struct CUstream_st* cudaStream_t;
typedef struct ihipStream_t* hipStream_t;

typedef enum
{
  OIDN_DEVICE_TYPE_DEFAULT = 0, // select device automatically

  OIDN_DEVICE_TYPE_CPU   = 1, // CPU device
  OIDN_DEVICE_TYPE_SYCL  = 2, // SYCL device
  OIDN_DEVICE_TYPE_CUDA  = 3, // CUDA device
  OIDN_DEVICE_TYPE_HIP   = 4, // HIP device
  OIDN_DEVICE_TYPE_METAL = 5, // Metal device
} OIDNDeviceType;

typedef enum
{
  OIDN_ERROR_NONE                 = 0, // no error occurred
  OIDN_ERROR_UNKNOWN              = 1, // an unknown error occurred
  OIDN_ERROR_INVALID_ARGUMENT     = 2, // an invalid argument was specified
  OIDN_ERROR_INVALID_OPERATION    = 3, // the operation is not allowed
  OIDN_ERROR_OUT_OF_MEMORY        = 4, // not enough memory to execute the operation
  OIDN_ERROR_UNSUPPORTED_HARDWARE = 5, // the hardware (e.g. CPU) is not supported
  OIDN_ERROR_CANCELLED            = 6, // the operation was cancelled by the user
} OIDNError;

typedef enum
{
  OIDN_QUALITY_DEFAULT  = 0, // default quality

  OIDN_QUALITY_FAST     = 4, // high performance (for interactive/real-time preview rendering)
  OIDN_QUALITY_BALANCED = 5, // balanced quality/performance (for interactive/real-time rendering)
  OIDN_QUALITY_HIGH     = 6, // high quality (for final-frame rendering)
} OIDNQuality;

typedef enum
{
  OIDN_FORMAT_UNDEFINED = 0,

  OIDN_FORMAT_FLOAT  = 1,
  OIDN_FORMAT_FLOAT2,
  OIDN_FORMAT_FLOAT3,
  OIDN_FORMAT_FLOAT4,

  OIDN_FORMAT_HALF  = 257,
  OIDN_FORMAT_HALF2,
  OIDN_FORMAT_HALF3,
  OIDN_FORMAT_HALF4,
} OIDNFormat;

typedef enum
{
  OIDN_STORAGE_UNDEFINED = 0,
  OIDN_STORAGE_HOST      = 1,
  OIDN_STORAGE_DEVICE    = 2,
  OIDN_STORAGE_MANAGED   = 3,
} OIDNStorage;

typedef void (*OIDNErrorFunction)(void* userPtr, OIDNError code, const char* message);

typedef struct OIDNDeviceImpl* OIDNDevice;

typedef bool (*OIDNProgressMonitorFunction)(void* userPtr, double n);

typedef struct OIDNFilterImpl* OIDNFilter;

typedef struct OIDNBufferImpl* OIDNBuffer;
"""

OIDN_CONSTANTS = """
#define OIDN_UUID_SIZE 16u
#define OIDN_LUID_SIZE 8u
"""

OIDN_FUNCTION_DEVICE = """
OIDNDevice oidnNewDevice(OIDNDeviceType type);
OIDNDevice oidnNewCUDADevice(const int* deviceIDs, const cudaStream_t* streams, int numPairs);
void oidnCommitDevice(OIDNDevice device);
void oidnSyncDevice(OIDNDevice device);
void oidnReleaseDevice(OIDNDevice device);
bool oidnIsCPUDeviceSupported();
bool oidnIsCUDADeviceSupported(int deviceID);

bool oidnGetDeviceBool(OIDNDevice device, const char* name);
void oidnSetDeviceBool(OIDNDevice device, const char* name, bool value);
int  oidnGetDeviceInt (OIDNDevice device, const char* name);
void oidnSetDeviceInt (OIDNDevice device, const char* name, int  value);
int  oidnGetDeviceUInt(OIDNDevice device, const char* name);
void oidnSetDeviceUInt(OIDNDevice device, const char* name, unsigned int value);
"""

OIDN_FUNCTION_BUFFER = """
OIDNBuffer oidnNewBuffer(OIDNDevice device, size_t byteSize);
OIDNBuffer oidnNewSharedBuffer(OIDNDevice device, void* devPtr, size_t byteSize);
OIDNBuffer oidnNewBufferWithStorage(OIDNDevice device, size_t byteSize, OIDNStorage storage);
size_t oidnGetBufferSize(OIDNBuffer buffer);
OIDNStorage oidnGetBufferStorage(OIDNBuffer buffer);
void* oidnGetBufferData(OIDNBuffer buffer);
void oidnReadBuffer(OIDNBuffer buffer, size_t byteOffset, size_t byteSize, void* dstHostPtr);
void oidnReadBufferAsync(OIDNBuffer buffer,
                                  size_t byteOffset, size_t byteSize, void* dstHostPtr);
void oidnWriteBuffer(OIDNBuffer buffer,
                              size_t byteOffset, size_t byteSize, const void* srcHostPtr);
void oidnWriteBufferAsync(OIDNBuffer buffer,
                                   size_t byteOffset, size_t byteSize, const void* srcHostPtr);
void oidnReleaseBuffer(OIDNBuffer buffer);
"""

OIDN_FUNCTION_FILTER = """
void oidnSetFilterImage(OIDNFilter filter, const char* name,
                                 OIDNBuffer buffer, OIDNFormat format,
                                 size_t width, size_t height,
                                 size_t byteOffset,
                                 size_t pixelByteStride, size_t rowByteStride);
void oidnSetSharedFilterImage(OIDNFilter filter, const char* name,
                                       void* devPtr, OIDNFormat format,
                                       size_t width, size_t height,
                                       size_t byteOffset,
                                       size_t pixelByteStride, size_t rowByteStride);
void oidnUnsetFilterImage(OIDNFilter filter, const char* name);

OIDNFilter oidnNewFilter(OIDNDevice device, const char* type);
void oidnCommitFilter(OIDNFilter filter);
void oidnExecuteFilter(OIDNFilter filter);
void oidnExecuteFilterAsync(OIDNFilter filter);
void oidnReleaseFilter(OIDNFilter filter);

void oidnSetFilterBool(OIDNFilter filter, const char* name, bool value);
bool oidnGetFilterBool(OIDNFilter filter, const char* name);
void oidnSetFilterInt(OIDNFilter filter, const char* name, int value);
int oidnGetFilterInt(OIDNFilter filter, const char* name);
void oidnSetFilterFloat(OIDNFilter filter, const char* name, float value);
float oidnGetFilterFloat(OIDNFilter filter, const char* name);

"""
OIDN_FUNCTION_ERROR = """
OIDNError oidnGetDeviceError(OIDNDevice device, const char** outMessage);
"""

OIDN_CAPI = (
    OIDN_TYPES
    + OIDN_CONSTANTS
    + OIDN_FUNCTION_DEVICE
    + OIDN_FUNCTION_BUFFER
    + OIDN_FUNCTION_FILTER
    + OIDN_FUNCTION_ERROR
)


def wrap_dylib(lib):
    prefix = "lib"
    if os.name == "nt":
        prefix = ""

    if os.name == "nt":
        suffix = ".dll"
    elif sys.platform == "darwin":
        suffix = ".dylib"
    else:
        suffix = ".so"

    return prefix + lib + suffix


def _load_oidn_library(ffi: FFI):
    is_win = os.name == "nt"
    dll_dir = os.path.join(os.path.dirname(__file__), "oidn", "bin" if is_win else "lib")
    dylibs = [wrap_dylib("OpenImageDenoise")]
    if is_win:
        # Windows requires device .dll loaded first
        dylibs = [wrap_dylib("OpenImageDenoise_device_cpu")] + dylibs

    entrypoint = None
    for dylib in dylibs:
        entrypoint = ffi.dlopen(os.path.join(dll_dir, dylib))
    return entrypoint


class _OidnCapiProxy:
    def __init__(self):
        self._entrypoint = None
        self._load_error = None

    def _ensure_loaded(self):
        if self._entrypoint is not None:
            return self._entrypoint
        if self._load_error is not None:
            raise self._load_error
        try:
            self._entrypoint = _load_oidn_library(oidn_ffi)
            return self._entrypoint
        except Exception as e:
            self._load_error = e
            raise

    def __getattr__(self, item):
        entrypoint = self._ensure_loaded()
        return getattr(entrypoint, item)


# Always define the FFI/types at import time so unit tests can mock the C API
oidn_ffi = FFI()
oidn_ffi.cdef(OIDN_CAPI)
oidn_Capi = _OidnCapiProxy()
