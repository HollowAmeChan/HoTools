#include <Python.h>

#include "hotools_property_curve.hpp"

#include <algorithm>
#include <array>
#include <cmath>
#include <string>
#include <utility>
#include <vector>

namespace hotools {
namespace {

constexpr const char* kFloatCurveCapsuleName = "hotools_native.PropertyCurveFloatCurve";
constexpr const char* kColorCurveCapsuleName = "hotools_native.PropertyCurveColorCurve";

struct FloatCurvePoint {
    double x = 0.0;
    double y = 0.0;
    std::string interpolation = "LINEAR";
    std::string left_handle_type = "AUTO";
    std::string right_handle_type = "AUTO";
    double left_tangent = 0.0;
    double right_tangent = 0.0;
    double left_weight = 1.0;
    double right_weight = 1.0;
    double left_handle_x = 0.0;
    double left_handle_y = 0.0;
    double right_handle_x = 0.0;
    double right_handle_y = 0.0;
};

struct FloatCurveData {
    std::vector<FloatCurvePoint> points;
    double value = 0.0;
    std::string interpolation = "LINEAR";
    std::string extend = "CLAMP";
    bool is_constant = false;
    double constant_value = 0.0;
};

struct ColorCurvePoint {
    double x = 0.0;
    std::array<double, 4> color {1.0, 1.0, 1.0, 1.0};
    std::string interpolation = "LINEAR";
    std::string left_handle_type = "AUTO";
    std::string right_handle_type = "AUTO";
    std::array<double, 4> left_tangent {0.0, 0.0, 0.0, 0.0};
    std::array<double, 4> right_tangent {0.0, 0.0, 0.0, 0.0};
    double left_weight = 1.0;
    double right_weight = 1.0;
    double left_handle_x = 0.0;
    double right_handle_x = 0.0;
    std::array<double, 4> left_handle_y {0.0, 0.0, 0.0, 0.0};
    std::array<double, 4> right_handle_y {0.0, 0.0, 0.0, 0.0};
};

struct ColorCurveData {
    std::vector<ColorCurvePoint> points;
    std::string interpolation = "LINEAR";
    std::string extend = "CLAMP";
    bool is_constant = false;
    std::array<double, 4> constant_color {0.0, 0.0, 0.0, 0.0};
};

std::string uppercase_ascii(std::string value) {
    for (char& character : value) {
        if (character >= 'a' && character <= 'z') {
            character = static_cast<char>(character - 'a' + 'A');
        }
    }
    return value;
}

std::string object_text(PyObject* object) {
    if (object == nullptr || object == Py_None) {
        return {};
    }

    PyObject* text = PyObject_Str(object);
    if (text == nullptr) {
        PyErr_Clear();
        return {};
    }

    const char* value = PyUnicode_AsUTF8(text);
    if (value == nullptr) {
        Py_DECREF(text);
        PyErr_Clear();
        return {};
    }

    std::string result = value;
    Py_DECREF(text);
    return result;
}

double object_double(PyObject* object, double fallback = 0.0) {
    if (object == nullptr || object == Py_None) {
        return fallback;
    }

    PyErr_Clear();
    const double value = PyFloat_AsDouble(object);
    if (PyErr_Occurred()) {
        PyErr_Clear();
        return fallback;
    }
    return value;
}

std::string normalize_interpolation_text(const std::string& raw, const std::string& fallback) {
    const std::string fallback_key = [] (std::string value) {
        value = uppercase_ascii(std::move(value));
        if (value != "LINEAR" && value != "CONSTANT" && value != "BEZIER") {
            value = "LINEAR";
        }
        return value;
    }(fallback);

    const std::string key = uppercase_ascii(raw);
    if (key == "LINEAR" || key == "CONSTANT" || key == "BEZIER") {
        return key;
    }
    return fallback_key;
}

std::string normalize_handle_type_text(const std::string& raw, const std::string& fallback) {
    const std::string fallback_key = [] (std::string value) {
        value = uppercase_ascii(std::move(value));
        if (value != "AUTO" && value != "VECTOR" && value != "FREE" && value != "COORD") {
            value = "AUTO";
        }
        return value;
    }(fallback);

    const std::string key = uppercase_ascii(raw);
    if (key == "AUTO" || key == "VECTOR" || key == "FREE" || key == "COORD") {
        return key;
    }
    return fallback_key;
}

std::string normalize_extend_text(const std::string& raw, const std::string& fallback) {
    const std::string fallback_key = [] (std::string value) {
        value = uppercase_ascii(std::move(value));
        if (value != "CLAMP" && value != "REPEAT" && value != "MIRROR") {
            value = "CLAMP";
        }
        return value;
    }(fallback);

    const std::string key = uppercase_ascii(raw);
    if (key == "CLAMP" || key == "REPEAT" || key == "MIRROR") {
        return key;
    }
    return fallback_key;
}

bool is_curve_default_extend_text(const std::string& raw) {
    const std::string key = uppercase_ascii(raw);
    return raw.empty() || key == "CURVE" || key == "DEFAULT" || raw == u8"曲线" || raw == u8"默认";
}

std::string resolve_extend_mode(PyObject* extend_object, const std::string& curve_extend) {
    if (extend_object == nullptr || extend_object == Py_None) {
        return curve_extend;
    }

    const std::string raw = object_text(extend_object);
    if (is_curve_default_extend_text(raw)) {
        return curve_extend;
    }

    const std::string key = uppercase_ascii(raw);
    if (key == "CLAMP" || key == "REPEAT" || key == "MIRROR") {
        return key;
    }
    return curve_extend;
}

bool read_float_sequence(PyObject* object, std::array<double, 4>* values, const std::array<double, 4>& fallback) {
    if (object == nullptr || object == Py_None) {
        *values = fallback;
        return true;
    }

    if (PyFloat_Check(object) || PyLong_Check(object)) {
        const double scalar = object_double(object, fallback[0]);
        values->fill(scalar);
        return true;
    }

    PyObject* sequence = PySequence_Fast(object, nullptr);
    if (sequence == nullptr) {
        PyErr_Clear();
        *values = fallback;
        return true;
    }

    const Py_ssize_t size = PySequence_Fast_GET_SIZE(sequence);
    for (int index = 0; index < 4; ++index) {
        if (index < size) {
            values->at(index) = object_double(PySequence_Fast_GET_ITEM(sequence, index), fallback[index]);
        } else {
            values->at(index) = fallback[index];
        }
    }

    Py_DECREF(sequence);
    return true;
}

bool read_float_point(PyObject* point_object, FloatCurvePoint* point, const std::string& default_interpolation) {
    if (!PyDict_Check(point_object)) {
        return false;
    }

    point->x = object_double(PyDict_GetItemString(point_object, "x"), object_double(PyDict_GetItemString(point_object, "position"), 0.0));
    point->x = std::max(0.0, std::min(1.0, point->x));
    point->y = object_double(PyDict_GetItemString(point_object, "y"), object_double(PyDict_GetItemString(point_object, "value"), 0.0));
    point->interpolation = normalize_interpolation_text(object_text(PyDict_GetItemString(point_object, "interpolation")), default_interpolation);
    point->left_handle_type = normalize_handle_type_text(
        object_text(PyDict_GetItemString(point_object, "left_handle_type")), "AUTO");
    point->right_handle_type = normalize_handle_type_text(
        object_text(PyDict_GetItemString(point_object, "right_handle_type")), "AUTO");
    point->left_tangent = object_double(PyDict_GetItemString(point_object, "left_tangent"), 0.0);
    point->right_tangent = object_double(PyDict_GetItemString(point_object, "right_tangent"), 0.0);
    point->left_weight = std::max(0.0, object_double(PyDict_GetItemString(point_object, "left_weight"), 1.0));
    point->right_weight = std::max(0.0, object_double(PyDict_GetItemString(point_object, "right_weight"), 1.0));
    point->left_handle_x = object_double(PyDict_GetItemString(point_object, "left_handle_x"), 0.0);
    point->left_handle_y = object_double(PyDict_GetItemString(point_object, "left_handle_y"), 0.0);
    point->right_handle_x = object_double(PyDict_GetItemString(point_object, "right_handle_x"), 0.0);
    point->right_handle_y = object_double(PyDict_GetItemString(point_object, "right_handle_y"), 0.0);
    return true;
}

bool read_color_point(PyObject* point_object, ColorCurvePoint* point, const std::string& default_interpolation) {
    if (!PyDict_Check(point_object)) {
        return false;
    }

    point->x = object_double(PyDict_GetItemString(point_object, "x"), object_double(PyDict_GetItemString(point_object, "position"), 0.0));
    point->x = std::max(0.0, std::min(1.0, point->x));
    read_float_sequence(PyDict_GetItemString(point_object, "color"), &point->color, point->color);
    point->interpolation = normalize_interpolation_text(object_text(PyDict_GetItemString(point_object, "interpolation")), default_interpolation);
    point->left_handle_type = normalize_handle_type_text(
        object_text(PyDict_GetItemString(point_object, "left_handle_type")), "AUTO");
    point->right_handle_type = normalize_handle_type_text(
        object_text(PyDict_GetItemString(point_object, "right_handle_type")), "AUTO");
    read_float_sequence(PyDict_GetItemString(point_object, "left_tangent"), &point->left_tangent, point->left_tangent);
    read_float_sequence(PyDict_GetItemString(point_object, "right_tangent"), &point->right_tangent, point->right_tangent);
    point->left_weight = std::max(0.0, object_double(PyDict_GetItemString(point_object, "left_weight"), 1.0));
    point->right_weight = std::max(0.0, object_double(PyDict_GetItemString(point_object, "right_weight"), 1.0));
    point->left_handle_x = object_double(PyDict_GetItemString(point_object, "left_handle_x"), 0.0);
    point->right_handle_x = object_double(PyDict_GetItemString(point_object, "right_handle_x"), 0.0);
    read_float_sequence(PyDict_GetItemString(point_object, "left_handle_y"), &point->left_handle_y, point->left_handle_y);
    read_float_sequence(PyDict_GetItemString(point_object, "right_handle_y"), &point->right_handle_y, point->right_handle_y);
    return true;
}

PyObject* curve_payload_from_object(PyObject* object) {
    if (PyDict_Check(object)) {
        return Py_NewRef(object);
    }

    PyObject* method = PyObject_GetAttrString(object, "to_payload");
    if (method == nullptr) {
        PyErr_Clear();
        PyErr_SetString(PyExc_TypeError, "curve value must provide to_payload() or be a payload dict");
        return nullptr;
    }

    PyObject* payload = PyObject_CallNoArgs(method);
    Py_DECREF(method);
    if (payload == nullptr) {
        return nullptr;
    }
    if (!PyDict_Check(payload)) {
        Py_DECREF(payload);
        PyErr_SetString(PyExc_TypeError, "curve to_payload() must return a dict");
        return nullptr;
    }
    return payload;
}

void destroy_float_curve_capsule(PyObject* capsule) {
    delete static_cast<FloatCurveData*>(PyCapsule_GetPointer(capsule, kFloatCurveCapsuleName));
}

void destroy_color_curve_capsule(PyObject* capsule) {
    delete static_cast<ColorCurveData*>(PyCapsule_GetPointer(capsule, kColorCurveCapsuleName));
}

bool almost_equal(double left, double right) {
    return std::abs(left - right) <= 1.0e-12;
}

bool almost_zero(double value) {
    return std::abs(value) <= 1.0e-12;
}

std::string point_interpolation_text(const std::string& point_interpolation, const std::string& fallback) {
    return point_interpolation.empty() ? fallback : point_interpolation;
}

bool float_bezier_segment_is_constant(const FloatCurvePoint& left, const FloatCurvePoint& right) {
    if (left.right_handle_type == "COORD" || right.left_handle_type == "COORD") {
        return almost_zero(left.right_handle_y) && almost_zero(right.left_handle_y);
    }
    if (left.right_handle_type == "FREE" && !almost_zero(left.right_tangent * left.right_weight)) {
        return false;
    }
    if (right.left_handle_type == "FREE" && !almost_zero(right.left_tangent * right.left_weight)) {
        return false;
    }
    return true;
}

bool color_bezier_segment_is_constant(const ColorCurvePoint& left, const ColorCurvePoint& right) {
    if (left.right_handle_type == "COORD" || right.left_handle_type == "COORD") {
        for (int channel = 0; channel < 4; ++channel) {
            const std::size_t offset = static_cast<std::size_t>(channel);
            if (!almost_zero(left.right_handle_y[offset]) || !almost_zero(right.left_handle_y[offset])) {
                return false;
            }
        }
        return true;
    }
    if (left.right_handle_type == "FREE") {
        for (int channel = 0; channel < 4; ++channel) {
            if (!almost_zero(left.right_tangent[static_cast<std::size_t>(channel)] * left.right_weight)) {
                return false;
            }
        }
    }
    if (right.left_handle_type == "FREE") {
        for (int channel = 0; channel < 4; ++channel) {
            if (!almost_zero(right.left_tangent[static_cast<std::size_t>(channel)] * right.left_weight)) {
                return false;
            }
        }
    }
    return true;
}

bool detect_constant_float_curve(const FloatCurveData& curve, double* value) {
    if (curve.points.empty()) {
        *value = 0.0;
        return true;
    }

    const double constant = curve.points.front().y;
    for (const FloatCurvePoint& point : curve.points) {
        if (!almost_equal(point.y, constant)) {
            return false;
        }
    }

    for (std::size_t index = 0; index + 1 < curve.points.size(); ++index) {
        const FloatCurvePoint& left = curve.points[index];
        const FloatCurvePoint& right = curve.points[index + 1];
        if (point_interpolation_text(left.interpolation, curve.interpolation) == "BEZIER" &&
            !float_bezier_segment_is_constant(left, right)) {
            return false;
        }
    }

    *value = constant;
    return true;
}

bool detect_constant_color_curve(const ColorCurveData& curve, std::array<double, 4>* value) {
    if (curve.points.empty()) {
        *value = {0.0, 0.0, 0.0, 0.0};
        return true;
    }

    const std::array<double, 4> constant = curve.points.front().color;
    for (const ColorCurvePoint& point : curve.points) {
        for (int channel = 0; channel < 4; ++channel) {
            const std::size_t offset = static_cast<std::size_t>(channel);
            if (!almost_equal(point.color[offset], constant[offset])) {
                return false;
            }
        }
    }

    for (std::size_t index = 0; index + 1 < curve.points.size(); ++index) {
        const ColorCurvePoint& left = curve.points[index];
        const ColorCurvePoint& right = curve.points[index + 1];
        if (point_interpolation_text(left.interpolation, curve.interpolation) == "BEZIER" &&
            !color_bezier_segment_is_constant(left, right)) {
            return false;
        }
    }

    *value = constant;
    return true;
}

bool build_float_curve_from_payload(PyObject* payload, FloatCurveData* curve) {
    if (!PyDict_Check(payload)) {
        PyErr_SetString(PyExc_TypeError, "float curve payload must be a dict");
        return false;
    }

    curve->value = object_double(PyDict_GetItemString(payload, "value"), curve->value);
    curve->interpolation = normalize_interpolation_text(
        object_text(PyDict_GetItemString(payload, "interpolation")), curve->interpolation);
    curve->extend = normalize_extend_text(object_text(PyDict_GetItemString(payload, "extend")), curve->extend);

    std::vector<FloatCurvePoint> points;
    PyObject* points_object = PyDict_GetItemString(payload, "points");
    if (points_object != nullptr && points_object != Py_None) {
        PyObject* sequence = PySequence_Fast(points_object, nullptr);
        if (sequence != nullptr) {
            const Py_ssize_t size = PySequence_Fast_GET_SIZE(sequence);
            points.reserve(static_cast<std::size_t>(size));
            for (Py_ssize_t index = 0; index < size; ++index) {
                FloatCurvePoint point;
                if (read_float_point(PySequence_Fast_GET_ITEM(sequence, index), &point, curve->interpolation)) {
                    points.push_back(std::move(point));
                }
            }
            Py_DECREF(sequence);
        } else {
            PyErr_Clear();
        }
    }

    if (points.empty()) {
        points.push_back(FloatCurvePoint{});
        points.back().x = 0.0;
        points.back().y = 0.0;
        points.back().interpolation = curve->interpolation;
        points.back().left_handle_type = "AUTO";
        points.back().right_handle_type = "AUTO";
        points.back().left_tangent = 1.0;
        points.back().right_tangent = 1.0;
        points.back().left_weight = 1.0;
        points.back().right_weight = 1.0;
        points.back().left_handle_x = 0.0;
        points.back().left_handle_y = 0.0;
        points.back().right_handle_x = 0.0;
        points.back().right_handle_y = 0.0;

        points.push_back(FloatCurvePoint{});
        points.back().x = 1.0;
        points.back().y = 1.0;
        points.back().interpolation = curve->interpolation;
        points.back().left_handle_type = "AUTO";
        points.back().right_handle_type = "AUTO";
        points.back().left_tangent = 1.0;
        points.back().right_tangent = 1.0;
        points.back().left_weight = 1.0;
        points.back().right_weight = 1.0;
        points.back().left_handle_x = 0.0;
        points.back().left_handle_y = 0.0;
        points.back().right_handle_x = 0.0;
        points.back().right_handle_y = 0.0;
    } else if (points.size() == 1) {
        FloatCurvePoint duplicate = points.front();
        duplicate.x = duplicate.x <= 0.5 ? 1.0 : 0.0;
        points.push_back(std::move(duplicate));
    }

    std::sort(points.begin(), points.end(), [](const FloatCurvePoint& left, const FloatCurvePoint& right) {
        return left.x < right.x;
    });

    curve->points = std::move(points);
    curve->is_constant = detect_constant_float_curve(*curve, &curve->constant_value);
    return true;
}

bool build_color_curve_from_payload(PyObject* payload, ColorCurveData* curve) {
    if (!PyDict_Check(payload)) {
        PyErr_SetString(PyExc_TypeError, "color curve payload must be a dict");
        return false;
    }

    curve->interpolation = normalize_interpolation_text(
        object_text(PyDict_GetItemString(payload, "interpolation")), curve->interpolation);
    curve->extend = normalize_extend_text(object_text(PyDict_GetItemString(payload, "extend")), curve->extend);

    std::vector<ColorCurvePoint> points;
    PyObject* points_object = PyDict_GetItemString(payload, "points");
    if (points_object != nullptr && points_object != Py_None) {
        PyObject* sequence = PySequence_Fast(points_object, nullptr);
        if (sequence != nullptr) {
            const Py_ssize_t size = PySequence_Fast_GET_SIZE(sequence);
            points.reserve(static_cast<std::size_t>(size));
            for (Py_ssize_t index = 0; index < size; ++index) {
                ColorCurvePoint point;
                if (read_color_point(PySequence_Fast_GET_ITEM(sequence, index), &point, curve->interpolation)) {
                    points.push_back(std::move(point));
                }
            }
            Py_DECREF(sequence);
        } else {
            PyErr_Clear();
        }
    }

    if (points.empty()) {
        points.push_back(ColorCurvePoint{});
        points.back().x = 0.0;
        points.back().color = {0.0, 0.0, 0.0, 1.0};
        points.back().interpolation = curve->interpolation;
        points.back().left_handle_type = "AUTO";
        points.back().right_handle_type = "AUTO";
        points.back().left_tangent = {1.0, 1.0, 1.0, 1.0};
        points.back().right_tangent = {1.0, 1.0, 1.0, 1.0};
        points.back().left_weight = 1.0;
        points.back().right_weight = 1.0;
        points.back().left_handle_x = 0.0;
        points.back().right_handle_x = 0.0;
        points.back().left_handle_y = {0.0, 0.0, 0.0, 0.0};
        points.back().right_handle_y = {0.0, 0.0, 0.0, 0.0};

        points.push_back(ColorCurvePoint{});
        points.back().x = 1.0;
        points.back().color = {1.0, 1.0, 1.0, 1.0};
        points.back().interpolation = curve->interpolation;
        points.back().left_handle_type = "AUTO";
        points.back().right_handle_type = "AUTO";
        points.back().left_tangent = {1.0, 1.0, 1.0, 1.0};
        points.back().right_tangent = {1.0, 1.0, 1.0, 1.0};
        points.back().left_weight = 1.0;
        points.back().right_weight = 1.0;
        points.back().left_handle_x = 0.0;
        points.back().right_handle_x = 0.0;
        points.back().left_handle_y = {0.0, 0.0, 0.0, 0.0};
        points.back().right_handle_y = {0.0, 0.0, 0.0, 0.0};
    } else if (points.size() == 1) {
        ColorCurvePoint duplicate = points.front();
        duplicate.x = duplicate.x <= 0.5 ? 1.0 : 0.0;
        points.push_back(std::move(duplicate));
    }

    std::sort(points.begin(), points.end(), [](const ColorCurvePoint& left, const ColorCurvePoint& right) {
        return left.x < right.x;
    });

    curve->points = std::move(points);
    curve->is_constant = detect_constant_color_curve(*curve, &curve->constant_color);
    return true;
}

bool build_float_curve_from_object(PyObject* object, FloatCurveData* curve) {
    PyObject* payload = curve_payload_from_object(object);
    if (payload == nullptr) {
        return false;
    }
    const bool ok = build_float_curve_from_payload(payload, curve);
    Py_DECREF(payload);
    return ok;
}

bool build_color_curve_from_object(PyObject* object, ColorCurveData* curve) {
    PyObject* payload = curve_payload_from_object(object);
    if (payload == nullptr) {
        return false;
    }
    const bool ok = build_color_curve_from_payload(payload, curve);
    Py_DECREF(payload);
    return ok;
}

bool resolve_float_curve_object(PyObject* object, FloatCurveData* temp_curve, const FloatCurveData** curve) {
    if (PyCapsule_IsValid(object, kFloatCurveCapsuleName) == 1) {
        auto* native_curve = static_cast<FloatCurveData*>(PyCapsule_GetPointer(object, kFloatCurveCapsuleName));
        if (native_curve == nullptr) {
            return false;
        }
        *curve = native_curve;
        return true;
    }

    if (!build_float_curve_from_object(object, temp_curve)) {
        return false;
    }
    *curve = temp_curve;
    return true;
}

bool resolve_color_curve_object(PyObject* object, ColorCurveData* temp_curve, const ColorCurveData** curve) {
    if (PyCapsule_IsValid(object, kColorCurveCapsuleName) == 1) {
        auto* native_curve = static_cast<ColorCurveData*>(PyCapsule_GetPointer(object, kColorCurveCapsuleName));
        if (native_curve == nullptr) {
            return false;
        }
        *curve = native_curve;
        return true;
    }

    if (!build_color_curve_from_object(object, temp_curve)) {
        return false;
    }
    *curve = temp_curve;
    return true;
}

double safe_slope(double delta, double dx) {
    if (dx == 0.0) {
        return 0.0;
    }
    return delta / dx;
}

double hermite(double v0, double v1, double m0, double m1, double t) {
    const double t2 = t * t;
    const double t3 = t2 * t;
    return (2.0 * t3 - 3.0 * t2 + 1.0) * v0 +
           (t3 - 2.0 * t2 + t) * m0 +
           (-2.0 * t3 + 3.0 * t2) * v1 +
           (t3 - t2) * m1;
}

double cubic(double v0, double v1, double v2, double v3, double t) {
    const double u = 1.0 - t;
    return u * u * u * v0 +
           3.0 * u * u * t * v1 +
           3.0 * u * t * t * v2 +
           t * t * t * v3;
}

double cubic_derivative(double v0, double v1, double v2, double v3, double t) {
    const double u = 1.0 - t;
    return 3.0 * u * u * (v1 - v0) +
           6.0 * u * t * (v2 - v1) +
           3.0 * t * t * (v3 - v2);
}

double solve_cubic_x(double x0, double x1, double x2, double x3, double x) {
    if (std::abs(x3 - x0) < 0.000001) {
        return 0.0;
    }

    double t = std::max(0.0, std::min(1.0, (x - x0) / (x3 - x0)));
    for (int index = 0; index < 8; ++index) {
        const double value = cubic(x0, x1, x2, x3, t) - x;
        const double derivative = cubic_derivative(x0, x1, x2, x3, t);
        if (std::abs(derivative) < 0.000001) {
            break;
        }
        const double next_t = t - value / derivative;
        if (next_t < 0.0 || next_t > 1.0) {
            break;
        }
        t = next_t;
    }

    double low = 0.0;
    double high = 1.0;
    for (int index = 0; index < 24; ++index) {
        const double value = cubic(x0, x1, x2, x3, t);
        if (std::abs(value - x) < 0.000001) {
            return std::max(0.0, std::min(1.0, t));
        }
        if (value < x) {
            low = t;
        } else {
            high = t;
        }
        t = (low + high) * 0.5;
    }

    return std::max(0.0, std::min(1.0, t));
}

bool has_coord_handles(const FloatCurvePoint& left, const FloatCurvePoint& right) {
    return left.right_handle_type == "COORD" || right.left_handle_type == "COORD";
}

bool has_coord_handles(const ColorCurvePoint& left, const ColorCurvePoint& right) {
    return left.right_handle_type == "COORD" || right.left_handle_type == "COORD";
}

void float_coord_handles(const FloatCurvePoint& left, const FloatCurvePoint& right, double* left_x, double* left_y,
                         double* right_x, double* right_y) {
    *left_x = left.x + left.right_handle_x;
    *left_y = left.y + left.right_handle_y;
    *right_x = right.x + right.left_handle_x;
    *right_y = right.y + right.left_handle_y;
}

void color_coord_handles(const ColorCurvePoint& left, const ColorCurvePoint& right, int channel, double* left_x,
                         double* left_y, double* right_x, double* right_y) {
    *left_x = left.x + left.right_handle_x;
    *left_y = left.color[static_cast<std::size_t>(channel)] + left.right_handle_y[static_cast<std::size_t>(channel)];
    *right_x = right.x + right.left_handle_x;
    *right_y = right.color[static_cast<std::size_t>(channel)] + right.left_handle_y[static_cast<std::size_t>(channel)];
}

std::size_t find_segment_index(const std::vector<FloatCurvePoint>& points, double x) {
    std::size_t point_index = 0;
    while (point_index + 1 < points.size() && points[point_index + 1].x <= x) {
        ++point_index;
    }
    return point_index;
}

std::size_t find_segment_index(const std::vector<ColorCurvePoint>& points, double x) {
    std::size_t point_index = 0;
    while (point_index + 1 < points.size() && points[point_index + 1].x <= x) {
        ++point_index;
    }
    return point_index;
}

double float_auto_tangent(const std::vector<FloatCurvePoint>& points, std::size_t index) {
    const std::size_t left_index = index == 0 ? 0 : index - 1;
    const std::size_t right_index = std::min(points.size() - 1, index + 1);
    if (left_index == right_index) {
        return 0.0;
    }
    return safe_slope(points[right_index].y - points[left_index].y, points[right_index].x - points[left_index].x);
}

double float_out_tangent(const std::vector<FloatCurvePoint>& points, std::size_t index, const FloatCurvePoint& left,
                         const FloatCurvePoint& right) {
    if (left.right_handle_type == "FREE") {
        return left.right_tangent;
    }
    if (left.right_handle_type == "AUTO") {
        return float_auto_tangent(points, index);
    }
    return safe_slope(right.y - left.y, right.x - left.x);
}

double float_in_tangent(const std::vector<FloatCurvePoint>& points, std::size_t index, const FloatCurvePoint& left,
                        const FloatCurvePoint& right) {
    if (right.left_handle_type == "FREE") {
        return right.left_tangent;
    }
    if (right.left_handle_type == "AUTO") {
        return float_auto_tangent(points, index);
    }
    return safe_slope(right.y - left.y, right.x - left.x);
}

double color_auto_tangent(const std::vector<ColorCurvePoint>& points, std::size_t index, int channel) {
    const std::size_t left_index = index == 0 ? 0 : index - 1;
    const std::size_t right_index = std::min(points.size() - 1, index + 1);
    if (left_index == right_index) {
        return 0.0;
    }
    return safe_slope(points[right_index].color[static_cast<std::size_t>(channel)] -
                          points[left_index].color[static_cast<std::size_t>(channel)],
                      points[right_index].x - points[left_index].x);
}

double color_out_tangent(const std::vector<ColorCurvePoint>& points, std::size_t index, const ColorCurvePoint& left,
                         const ColorCurvePoint& right, int channel) {
    if (left.right_handle_type == "FREE") {
        return left.right_tangent[static_cast<std::size_t>(channel)];
    }
    if (left.right_handle_type == "AUTO") {
        return color_auto_tangent(points, index, channel);
    }
    return safe_slope(right.color[static_cast<std::size_t>(channel)] - left.color[static_cast<std::size_t>(channel)],
                      right.x - left.x);
}

double color_in_tangent(const std::vector<ColorCurvePoint>& points, std::size_t index, const ColorCurvePoint& left,
                        const ColorCurvePoint& right, int channel) {
    if (right.left_handle_type == "FREE") {
        return right.left_tangent[static_cast<std::size_t>(channel)];
    }
    if (right.left_handle_type == "AUTO") {
        return color_auto_tangent(points, index, channel);
    }
    return safe_slope(right.color[static_cast<std::size_t>(channel)] - left.color[static_cast<std::size_t>(channel)],
                      right.x - left.x);
}

double sample_float_curve_value(const FloatCurveData& curve, double position, PyObject* extend_object) {
    if (curve.is_constant) {
        return curve.constant_value;
    }

    const std::string extend_mode = resolve_extend_mode(extend_object, curve.extend);
    double x = position;
    if (extend_mode == "REPEAT") {
        if (0.0 <= x && x <= 1.0) {
            // keep
        } else {
            x = std::fmod(x, 1.0);
            if (x < 0.0) {
                x += 1.0;
            }
        }
    } else if (extend_mode == "MIRROR") {
        if (!(0.0 <= x && x <= 1.0)) {
            x = std::fmod(x, 2.0);
            if (x < 0.0) {
                x += 2.0;
            }
            if (x > 1.0) {
                x = 2.0 - x;
            }
        }
    } else {
        x = std::max(0.0, std::min(1.0, x));
    }

    const auto& points = curve.points;
    if (x <= points.front().x) {
        return points.front().y;
    }
    if (x >= points.back().x) {
        return points.back().y;
    }

    const std::size_t point_index = find_segment_index(points, x);
    const FloatCurvePoint& left = points[point_index];
    const FloatCurvePoint& right = points[std::min(point_index + 1, points.size() - 1)];
    const double dx = right.x - left.x;
    const std::string segment_interpolation = left.interpolation.empty() ? curve.interpolation : left.interpolation;
    if (segment_interpolation == "CONSTANT" || dx <= 0.0) {
        return left.y;
    }

    const double factor = (x - left.x) / dx;
    if (segment_interpolation == "BEZIER") {
        if (has_coord_handles(left, right)) {
            double left_x = 0.0;
            double left_y = 0.0;
            double right_x = 0.0;
            double right_y = 0.0;
            float_coord_handles(left, right, &left_x, &left_y, &right_x, &right_y);
            const double t = solve_cubic_x(left.x, left_x, right_x, right.x, x);
            return cubic(left.y, left_y, right_y, right.y, t);
        }

        const double out_tangent = float_out_tangent(points, point_index, left, right);
        const double in_tangent = float_in_tangent(points, point_index + 1, left, right);
        const double m0 = out_tangent * dx * left.right_weight;
        const double m1 = in_tangent * dx * right.left_weight;
        return hermite(left.y, right.y, m0, m1, factor);
    }

    return left.y * (1.0 - factor) + right.y * factor;
}

std::array<double, 4> sample_color_curve_value(const ColorCurveData& curve, double position, PyObject* extend_object) {
    if (curve.is_constant) {
        return curve.constant_color;
    }

    const std::string extend_mode = resolve_extend_mode(extend_object, curve.extend);
    double x = position;
    if (extend_mode == "REPEAT") {
        if (0.0 <= x && x <= 1.0) {
            // keep
        } else {
            x = std::fmod(x, 1.0);
            if (x < 0.0) {
                x += 1.0;
            }
        }
    } else if (extend_mode == "MIRROR") {
        if (!(0.0 <= x && x <= 1.0)) {
            x = std::fmod(x, 2.0);
            if (x < 0.0) {
                x += 2.0;
            }
            if (x > 1.0) {
                x = 2.0 - x;
            }
        }
    } else {
        x = std::max(0.0, std::min(1.0, x));
    }

    const auto& points = curve.points;
    if (x <= points.front().x) {
        return points.front().color;
    }
    if (x >= points.back().x) {
        return points.back().color;
    }

    const std::size_t point_index = find_segment_index(points, x);
    const ColorCurvePoint& left = points[point_index];
    const ColorCurvePoint& right = points[std::min(point_index + 1, points.size() - 1)];
    const double dx = right.x - left.x;
    const std::string segment_interpolation = left.interpolation.empty() ? curve.interpolation : left.interpolation;
    if (segment_interpolation == "CONSTANT" || dx <= 0.0) {
        return left.color;
    }

    const double factor = (x - left.x) / dx;
    std::array<double, 4> result {0.0, 0.0, 0.0, 0.0};
    if (segment_interpolation == "BEZIER") {
        if (has_coord_handles(left, right)) {
            for (int channel = 0; channel < 4; ++channel) {
                double left_x = 0.0;
                double left_y = 0.0;
                double right_x = 0.0;
                double right_y = 0.0;
                color_coord_handles(left, right, channel, &left_x, &left_y, &right_x, &right_y);
                const double t = solve_cubic_x(left.x, left_x, right_x, right.x, x);
                result[static_cast<std::size_t>(channel)] = cubic(left.color[static_cast<std::size_t>(channel)],
                                                                  left_y, right_y,
                                                                  right.color[static_cast<std::size_t>(channel)], t);
            }
            return result;
        }

        for (int channel = 0; channel < 4; ++channel) {
            const double out_tangent = color_out_tangent(points, point_index, left, right, channel);
            const double in_tangent = color_in_tangent(points, point_index + 1, left, right, channel);
            const double m0 = out_tangent * dx * left.right_weight;
            const double m1 = in_tangent * dx * right.left_weight;
            result[static_cast<std::size_t>(channel)] = hermite(left.color[static_cast<std::size_t>(channel)],
                                                                right.color[static_cast<std::size_t>(channel)], m0, m1,
                                                                factor);
        }
        return result;
    }

    for (int channel = 0; channel < 4; ++channel) {
        result[static_cast<std::size_t>(channel)] =
            left.color[static_cast<std::size_t>(channel)] * (1.0 - factor) +
            right.color[static_cast<std::size_t>(channel)] * factor;
    }
    return result;
}

}  // namespace

PyObject* compile_property_float_curve_object(PyObject* payload) {
    FloatCurveData* curve = new FloatCurveData();
    if (!build_float_curve_from_object(payload, curve)) {
        delete curve;
        return nullptr;
    }

    PyObject* capsule = PyCapsule_New(curve, kFloatCurveCapsuleName, destroy_float_curve_capsule);
    if (capsule == nullptr) {
        delete curve;
        return nullptr;
    }
    return capsule;
}

PyObject* compile_property_color_curve_object(PyObject* payload) {
    ColorCurveData* curve = new ColorCurveData();
    if (!build_color_curve_from_object(payload, curve)) {
        delete curve;
        return nullptr;
    }

    PyObject* capsule = PyCapsule_New(curve, kColorCurveCapsuleName, destroy_color_curve_capsule);
    if (capsule == nullptr) {
        delete curve;
        return nullptr;
    }
    return capsule;
}

PyObject* sample_property_float_curve_object(PyObject* curve_object, double position, PyObject* extend_object) {
    FloatCurveData temp_curve;
    const FloatCurveData* curve = nullptr;
    if (!resolve_float_curve_object(curve_object, &temp_curve, &curve)) {
        return nullptr;
    }

    const double value = sample_float_curve_value(*curve, position, extend_object);
    return PyFloat_FromDouble(value);
}

PyObject* sample_property_color_curve_object(PyObject* curve_object, double position, PyObject* extend_object) {
    ColorCurveData temp_curve;
    const ColorCurveData* curve = nullptr;
    if (!resolve_color_curve_object(curve_object, &temp_curve, &curve)) {
        return nullptr;
    }

    const std::array<double, 4> value = sample_color_curve_value(*curve, position, extend_object);
    return Py_BuildValue("(dddd)", value[0], value[1], value[2], value[3]);
}

PyObject* sample_property_float_curve_many_object(PyObject* curve_object, int sample_count, PyObject* extend_object) {
    FloatCurveData temp_curve;
    const FloatCurveData* curve = nullptr;
    if (!resolve_float_curve_object(curve_object, &temp_curve, &curve)) {
        return nullptr;
    }

    sample_count = std::max(1, sample_count);

    PyObject* list = PyList_New(sample_count);
    if (list == nullptr) {
        return nullptr;
    }

    if (curve->is_constant) {
        for (int index = 0; index < sample_count; ++index) {
            PyObject* value = PyFloat_FromDouble(curve->constant_value);
            if (value == nullptr) {
                Py_DECREF(list);
                return nullptr;
            }
            PyList_SET_ITEM(list, index, value);
        }
        return list;
    }

    if (sample_count == 1) {
        PyObject* value = PyFloat_FromDouble(sample_float_curve_value(*curve, 0.0, extend_object));
        if (value == nullptr) {
            Py_DECREF(list);
            return nullptr;
        }
        PyList_SET_ITEM(list, 0, value);
        return list;
    }

    for (int index = 0; index < sample_count; ++index) {
        const double position = static_cast<double>(index) / static_cast<double>(sample_count - 1);
        PyObject* value = PyFloat_FromDouble(sample_float_curve_value(*curve, position, extend_object));
        if (value == nullptr) {
            Py_DECREF(list);
            return nullptr;
        }
        PyList_SET_ITEM(list, index, value);
    }
    return list;
}

PyObject* sample_property_color_curve_many_object(PyObject* curve_object, int sample_count, PyObject* extend_object) {
    ColorCurveData temp_curve;
    const ColorCurveData* curve = nullptr;
    if (!resolve_color_curve_object(curve_object, &temp_curve, &curve)) {
        return nullptr;
    }

    sample_count = std::max(1, sample_count);

    PyObject* list = PyList_New(sample_count);
    if (list == nullptr) {
        return nullptr;
    }

    if (curve->is_constant) {
        for (int index = 0; index < sample_count; ++index) {
            PyObject* item = Py_BuildValue("(dddd)", curve->constant_color[0], curve->constant_color[1],
                                           curve->constant_color[2], curve->constant_color[3]);
            if (item == nullptr) {
                Py_DECREF(list);
                return nullptr;
            }
            PyList_SET_ITEM(list, index, item);
        }
        return list;
    }

    if (sample_count == 1) {
        const std::array<double, 4> value = sample_color_curve_value(*curve, 0.0, extend_object);
        PyObject* item = Py_BuildValue("(dddd)", value[0], value[1], value[2], value[3]);
        if (item == nullptr) {
            Py_DECREF(list);
            return nullptr;
        }
        PyList_SET_ITEM(list, 0, item);
        return list;
    }

    for (int index = 0; index < sample_count; ++index) {
        const double position = static_cast<double>(index) / static_cast<double>(sample_count - 1);
        const std::array<double, 4> value = sample_color_curve_value(*curve, position, extend_object);
        PyObject* item = Py_BuildValue("(dddd)", value[0], value[1], value[2], value[3]);
        if (item == nullptr) {
            Py_DECREF(list);
            return nullptr;
        }
        PyList_SET_ITEM(list, index, item);
    }
    return list;
}

PyObject* sample_property_float_curve_positions_object(PyObject* curve_object, PyObject* positions_object, PyObject* extend_object) {
    FloatCurveData temp_curve;
    const FloatCurveData* curve = nullptr;
    if (!resolve_float_curve_object(curve_object, &temp_curve, &curve)) {
        return nullptr;
    }

    PyObject* sequence = PySequence_Fast(positions_object, nullptr);
    if (sequence == nullptr) {
        PyErr_SetString(PyExc_TypeError, "positions must be a sequence");
        return nullptr;
    }

    const Py_ssize_t size = PySequence_Fast_GET_SIZE(sequence);
    PyObject* list = PyList_New(size);
    if (list == nullptr) {
        Py_DECREF(sequence);
        return nullptr;
    }

    if (curve->is_constant) {
        for (Py_ssize_t index = 0; index < size; ++index) {
            PyObject* value = PyFloat_FromDouble(curve->constant_value);
            if (value == nullptr) {
                Py_DECREF(sequence);
                Py_DECREF(list);
                return nullptr;
            }
            PyList_SET_ITEM(list, index, value);
        }
        Py_DECREF(sequence);
        return list;
    }

    for (Py_ssize_t index = 0; index < size; ++index) {
        const double position = object_double(PySequence_Fast_GET_ITEM(sequence, index), 0.0);
        PyObject* value = PyFloat_FromDouble(sample_float_curve_value(*curve, position, extend_object));
        if (value == nullptr) {
            Py_DECREF(sequence);
            Py_DECREF(list);
            return nullptr;
        }
        PyList_SET_ITEM(list, index, value);
    }

    Py_DECREF(sequence);
    return list;
}

PyObject* sample_property_color_curve_positions_object(PyObject* curve_object, PyObject* positions_object, PyObject* extend_object) {
    ColorCurveData temp_curve;
    const ColorCurveData* curve = nullptr;
    if (!resolve_color_curve_object(curve_object, &temp_curve, &curve)) {
        return nullptr;
    }

    PyObject* sequence = PySequence_Fast(positions_object, nullptr);
    if (sequence == nullptr) {
        PyErr_SetString(PyExc_TypeError, "positions must be a sequence");
        return nullptr;
    }

    const Py_ssize_t size = PySequence_Fast_GET_SIZE(sequence);
    PyObject* list = PyList_New(size);
    if (list == nullptr) {
        Py_DECREF(sequence);
        return nullptr;
    }

    if (curve->is_constant) {
        for (Py_ssize_t index = 0; index < size; ++index) {
            PyObject* item = Py_BuildValue("(dddd)", curve->constant_color[0], curve->constant_color[1],
                                           curve->constant_color[2], curve->constant_color[3]);
            if (item == nullptr) {
                Py_DECREF(sequence);
                Py_DECREF(list);
                return nullptr;
            }
            PyList_SET_ITEM(list, index, item);
        }
        Py_DECREF(sequence);
        return list;
    }

    for (Py_ssize_t index = 0; index < size; ++index) {
        const double position = object_double(PySequence_Fast_GET_ITEM(sequence, index), 0.0);
        const std::array<double, 4> value = sample_color_curve_value(*curve, position, extend_object);
        PyObject* item = Py_BuildValue("(dddd)", value[0], value[1], value[2], value[3]);
        if (item == nullptr) {
            Py_DECREF(sequence);
            Py_DECREF(list);
            return nullptr;
        }
        PyList_SET_ITEM(list, index, item);
    }

    Py_DECREF(sequence);
    return list;
}

}  // namespace hotools
